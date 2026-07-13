#!/usr/bin/env python3
"""vnstock_allocation.py — Phân bổ tài sản theo band vĩ mô B0-B4 (Phase 1).

Tại sao có module này
---------------------
Thiết kế "Báo cáo vĩ mô upload + Phân bổ tài sản" (user duyệt 2026-07-13) cần
một TẦNG SỐ ĐO deterministic làm gốc: gom các tín hiệu ĐÃ CÓ trong repo thành
một điểm rủi-ro-vĩ-mô rồi map sang band B0-B4 → bảng % phân bổ 5 lớp tài sản.
Phase 1 = đúng tầng này: **zero fetch, zero LLM** — chỉ đọc cache sẵn có; báo
cáo upload (P2+) về sau chỉ được TILT ±1 band, không bao giờ override tầng này.

Đầu vào (7 tín hiệu, thiếu cái nào bỏ cái đó — weight tự renormalize như
composite của vnstock_market_sentiment):

  • regime          — vnstock_regime.load_regime() (score -7..+7)
  • sentiment       — vnstock_market_sentiment (momentum -100..+100)
  • breadth         — % mã trên MA200 từ market_overview.json
  • macro_pressure  — vnstock_macro.macro_pressure_score (change-based, [-1,1])
  • liquidity       — gauge thanh khoản (ON − điều hành), LEVEL, dir −1/0/+1
  • term            — gauge kỳ hạn (10Y − điều hành, dốc 2-10), dir −1/0
  • intl            — gauge quốc tế (VN10Y − US10Y), dir −1/0

Band (convention VnBondLab: B0 = rủi ro vĩ mô THẤP nhất = tấn công):
  B0 thuận lợi · B1 tích cực · B2 trung tính · B3 thắt chặt · B4 căng thẳng

Hysteresis (user chốt): đổi band cần điểm vượt ranh giới ≥ margin trong
**2 phiên liên tiếp** (ngày khác nhau — recompute cùng ngày không đếm 2 lần);
lần chạy đầu tiên áp band thô ngay (chưa có gì để "giữ").

Bảng band → % là CONFIG user chỉnh được: ghi đè qua
``data_warehouse/_meta/allocation_config.json``::

    {"allocations": {"B2": {"Cổ phiếu": 50, "Trái phiếu": 20,
                            "Tiền gửi": 15, "Vàng": 10, "USD": 5}},
     "weights": {"regime": 0.3}}

Hàng ghi đè phải đủ 5 lớp và tổng ~100, sai thì bỏ qua (giữ mặc định) + cảnh báo.

State: ``data_warehouse/_meta/allocation_state.json`` — band hiện hành + điểm
+ lý do TỪNG input (nguồn + as_of) + pending hysteresis + **history log theo
ngày** (đủ để scorecard hồi tố P6 chấm lại: band + điểm + inputs mỗi phiên,
ghi từ ngày 1). Ghi atomic (tmp + os.replace) vì Streamlit/pipeline có thể đụng.

CLI::

    python vnstock_allocation.py --refresh    # thu inputs → tính → ghi state
    python vnstock_allocation.py --show       # xem band + bảng % + lý do
    python vnstock_allocation.py --history 10 # N dòng history gần nhất
    python vnstock_allocation.py --json       # state dạng JSON (máy đọc)

3 nguyên tắc thiết kế (KHÔNG nhượng bộ): LLM không bao giờ sinh số %/band;
số từ báo cáo upload không vào registry 13 chỉ số; guard brief mới (P4) chỉ
thêm vào apply_brief_guards dùng chung.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"
_STATE = _META / "allocation_state.json"
_CONFIG = _META / "allocation_config.json"

_ASSET_CLASSES = ("Cổ phiếu", "Trái phiếu", "Tiền gửi", "Vàng", "USD")

_BANDS = ("B0", "B1", "B2", "B3", "B4")
_BAND_LABELS = {
    "B0": "thuận lợi",
    "B1": "tích cực",
    "B2": "trung tính",
    "B3": "thắt chặt",
    "B4": "căng thẳng",
}

# Bảng % mặc định user duyệt 2026-07-13 (khẩu vị trung dung, có VÀNG từ đầu).
_DEFAULT_ALLOCATIONS: dict[str, dict[str, int]] = {
    "B0": {"Cổ phiếu": 70, "Trái phiếu": 10, "Tiền gửi": 10, "Vàng": 5,  "USD": 5},
    "B1": {"Cổ phiếu": 60, "Trái phiếu": 15, "Tiền gửi": 15, "Vàng": 5,  "USD": 5},
    "B2": {"Cổ phiếu": 45, "Trái phiếu": 20, "Tiền gửi": 20, "Vàng": 10, "USD": 5},
    "B3": {"Cổ phiếu": 30, "Trái phiếu": 25, "Tiền gửi": 30, "Vàng": 10, "USD": 5},
    "B4": {"Cổ phiếu": 15, "Trái phiếu": 25, "Tiền gửi": 40, "Vàng": 12, "USD": 8},
}

# Trọng số tín hiệu — renormalize trên tập inputs CÓ MẶT. Nhóm thị trường
# (regime/sentiment/breadth) nặng hơn vì cadence ngày; 3 gauge là LEVEL tuần.
_DEFAULT_WEIGHTS: dict[str, float] = {
    "regime":         0.25,
    "sentiment":      0.20,
    "breadth":        0.15,
    "macro_pressure": 0.15,
    "liquidity":      0.10,
    "term":           0.10,
    "intl":           0.05,
}

_INPUT_LABELS = {
    "regime":         "Regime thị trường",
    "sentiment":      "Tâm lý (momentum)",
    "breadth":        "Độ rộng (% trên MA200)",
    "macro_pressure": "Áp lực vĩ mô (thay đổi)",
    "liquidity":      "Thanh khoản hệ thống",
    "term":           "Kỳ hạn & đường cong",
    "intl":           "Chênh lệch quốc tế",
}

# Điểm tổng hợp [-1,1] → band: >= +0.50 B0 · >= +0.15 B1 · > −0.15 B2 ·
# > −0.50 B3 · còn lại B4. (Đối xứng quanh 0; biên ±0.15 khớp dải "Thận trọng"
# của mood sentiment, ±0.50 khớp dải Hưng phấn/Sợ hãi.)
_BAND_EDGES = (0.50, 0.15, -0.15, -0.50)

# Hysteresis: điểm phải vượt ranh giới thêm margin này, và giữ đề xuất trong
# _CONFIRM_SESSIONS phiên (ngày khác nhau) mới đổi band thật.
_HYSTERESIS_MARGIN = 0.05
_CONFIRM_SESSIONS = 2

_HISTORY_MAX = 500


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── Pure core: sub-scores → composite → band ────────────────────────────────


def _sub_score(key: str, raw: dict) -> "float | None":
    """Chuẩn hoá 1 input thô về [-1, +1], +1 = THUẬN LỢI cho tài sản rủi ro."""
    try:
        if key == "regime":
            # score nguyên -7..+7; ±5 bão hoà (±3 đã là "mạnh" theo bias floor)
            return _clamp(float(raw["score"]) / 5.0)
        if key == "sentiment":
            return _clamp(float(raw["momentum"]) / 100.0)
        if key == "breadth":
            # 45% là trung tính (cùng tâm với sentiment); /25 bão hoà chậm hơn
            # (70% → +1) vì allocation nhìn khung dài hơn mood ngày.
            return _clamp((float(raw["above_ma200_pct"]) - 45.0) / 25.0)
        if key == "macro_pressure":
            return _clamp(float(raw["score"]))
        if key == "term":
            # gộp cả dốc 2-10 khi có: trung bình 2 hướng (đều −1/0)
            dirs = [float(raw["dir"])]
            if raw.get("slope_dir") is not None:
                dirs.append(float(raw["slope_dir"]))
            return _clamp(sum(dirs) / len(dirs))
        if key in ("liquidity", "intl"):
            return _clamp(float(raw["dir"]))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def compute_score(inputs: dict, weights: "dict | None" = None) -> "dict | None":
    """Điểm tổng hợp từ các input thô có mặt.

    ``inputs`` = {key: {..raw reading.., "source"?, "as_of"?, "value"?,
    "detail"?}}; key ngoài ``_DEFAULT_WEIGHTS`` bị bỏ qua. Trả về
    ``{score, inputs: [rows]}`` — mỗi row đủ "lý do từng input" (nguồn +
    as_of + điểm + weight hiệu dụng); None khi không input nào dùng được.
    """
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})

    rows: list[dict] = []
    weighted = 0.0
    wsum = 0.0
    for key in _DEFAULT_WEIGHTS:            # thứ tự hiển thị ổn định
        raw = inputs.get(key)
        if not raw:
            continue
        s = _sub_score(key, raw)
        if s is None:
            continue
        weighted += s * w[key]
        wsum += w[key]
        rows.append({
            "key":    key,
            "label":  _INPUT_LABELS[key],
            "value":  raw.get("value") or "",
            "detail": raw.get("detail") or "",
            "score":  round(s, 2),
            "weight": w[key],
            "source": raw.get("source") or "",
            "as_of":  raw.get("as_of") or "",
        })
    if wsum == 0:
        return None
    for r in rows:                          # weight hiệu dụng sau renormalize
        r["weight"] = round(r["weight"] / wsum, 3)
    return {"score": round(weighted / wsum, 3), "inputs": rows}


def _band_idx(score: float) -> int:
    for i, edge in enumerate(_BAND_EDGES):
        if score >= edge:
            return i
    return len(_BAND_EDGES)


def band_from_score(score: float) -> str:
    """Band thô từ điểm tổng hợp (chưa hysteresis)."""
    return _BANDS[_band_idx(score)]


def apply_hysteresis(prev_state: "dict | None", score: float,
                     as_of: str) -> dict:
    """Band hiệu lực sau hysteresis: đổi band cần điểm vượt ranh giới ≥
    ``_HYSTERESIS_MARGIN`` trong ``_CONFIRM_SESSIONS`` phiên (ngày khác nhau).

    Trả ``{band, raw_band, pending}`` — pending = {band, dates} khi một đề
    xuất đổi band đang chờ xác nhận. Recompute CÙNG NGÀY không đếm thêm phiên
    (idempotent); lần chạy đầu (chưa có band cũ) áp band thô ngay.
    """
    raw_idx = _band_idx(score)
    prev = prev_state or {}
    cur_band = prev.get("band")
    if cur_band not in _BANDS:
        return {"band": _BANDS[raw_idx], "raw_band": _BANDS[raw_idx],
                "pending": None}
    cur_idx = _BANDS.index(cur_band)

    # Deadband: nghiêng điểm một margin NGƯỢC chiều đề xuất — vẫn ra band khác
    # current thì cú vượt là "thật", không phải dao động quanh ranh giới.
    if raw_idx > cur_idx:
        eff_idx = _band_idx(score + _HYSTERESIS_MARGIN)
        candidate = eff_idx if eff_idx > cur_idx else cur_idx
    elif raw_idx < cur_idx:
        eff_idx = _band_idx(score - _HYSTERESIS_MARGIN)
        candidate = eff_idx if eff_idx < cur_idx else cur_idx
    else:
        candidate = cur_idx

    if candidate == cur_idx:
        return {"band": cur_band, "raw_band": _BANDS[raw_idx], "pending": None}

    pending = prev.get("pending") or {}
    dates = list(pending.get("dates") or []) \
        if pending.get("band") == _BANDS[candidate] else []
    if as_of not in dates:
        dates.append(as_of)
    if len(dates) >= _CONFIRM_SESSIONS:
        return {"band": _BANDS[candidate], "raw_band": _BANDS[raw_idx],
                "pending": None}
    return {"band": cur_band, "raw_band": _BANDS[raw_idx],
            "pending": {"band": _BANDS[candidate], "dates": dates}}


def compute_allocation(inputs: dict, prev_state: "dict | None" = None,
                       config: "dict | None" = None,
                       as_of: "str | None" = None) -> "dict | None":
    """Pure core Phase 1: inputs thô → state mới (KHÔNG đọc/ghi file).

    Trả None khi không có input nào dùng được — caller GIỮ state cũ nguyên vẹn
    thay vì ghi đè bằng "không biết" (mirror triết lý giữ-cache-cũ của macro).
    """
    cfg = config or {}
    scored = compute_score(inputs, weights=cfg.get("weights"))
    if scored is None:
        return None
    as_of = as_of or date.today().isoformat()
    hyst = apply_hysteresis(prev_state, scored["score"], as_of)
    allocations = _allocations_table(cfg)
    return {
        "as_of":      as_of,
        "band":       hyst["band"],
        "band_label": _BAND_LABELS[hyst["band"]],
        "raw_band":   hyst["raw_band"],
        "pending":    hyst["pending"],
        "score":      scored["score"],
        "n_inputs":   len(scored["inputs"]),
        "inputs":     scored["inputs"],
        "allocation": dict(allocations[hyst["band"]]),
    }


def _allocations_table(config: "dict | None" = None) -> dict[str, dict[str, int]]:
    """Bảng band → % sau khi áp override hợp lệ từ config (đủ 5 lớp, tổng ~100)."""
    table = {b: dict(row) for b, row in _DEFAULT_ALLOCATIONS.items()}
    overrides = (config or {}).get("allocations") or {}
    for band, row in overrides.items():
        if band not in table or not isinstance(row, dict):
            continue
        if set(row) != set(_ASSET_CLASSES):
            print(f"[allocation] ⚠ config band {band} thiếu/thừa lớp tài sản — bỏ qua")
            continue
        try:
            total = sum(float(v) for v in row.values())
        except (TypeError, ValueError):
            continue
        if abs(total - 100.0) > 0.5:
            print(f"[allocation] ⚠ config band {band} tổng {total:g} ≠ 100 — bỏ qua")
            continue
        table[band] = {k: row[k] for k in _ASSET_CLASSES}
    return table


# ── Collect inputs (best-effort, zero fetch — chỉ đọc cache sẵn có) ─────────


def _load_overview() -> dict:
    try:
        p = _META / "market_overview.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def collect_inputs(effective_date: "str | None" = None) -> tuple[str, dict]:
    """Thu 7 input từ cache/loader sẵn có. Trả (as_of, inputs) — input lỗi/
    thiếu thì vắng mặt (weight renormalize), KHÔNG chặn các input còn lại."""
    overview = _load_overview()
    data_date = overview.get("data_date")
    as_of = effective_date or data_date or date.today().isoformat()
    inputs: dict[str, dict] = {}

    breadth = overview.get("breadth") or {}
    pct = breadth.get("above_ma200_pct")
    if pct is not None:
        inputs["breadth"] = {
            "above_ma200_pct": pct,
            "value": f"{float(pct):.0f}% mã trên MA200",
            "source": "market_overview.json", "as_of": data_date or as_of,
        }

    try:
        from vnstock_regime import load_regime
        r = load_regime()
        if r and r.get("n_signals"):
            inputs["regime"] = {
                "score": r["score"],
                "value": f"score {r['score']:+d} ({r['n_signals']} tín hiệu)",
                "detail": r.get("label", ""),
                "source": "vnstock_regime", "as_of": as_of,
            }
    except Exception:
        pass

    try:
        from vnstock_market_sentiment import load_market_sentiment
        ms = load_market_sentiment()
        if ms and ms.get("momentum") is not None:
            inputs["sentiment"] = {
                "momentum": ms["momentum"],
                "value": f"momentum {ms['momentum']:+d}/100",
                "detail": ms.get("mood", ""),
                "source": "vnstock_market_sentiment", "as_of": as_of,
            }
    except Exception:
        pass

    try:
        from vnstock_macro import (intl_spread, liquidity_spread, load_macro,
                                   macro_pressure_score, term_spread)
        macro = load_macro(as_of)
        rows = {m.get("key"): m for m in macro}

        def _row_as_of(*keys: str) -> str:
            # as_of CŨ nhất trong các chỉ số nền — trung thực về độ tươi
            avail = [rows[k]["as_of"] for k in keys if rows.get(k)]
            return min(avail) if avail else as_of

        mp = macro_pressure_score(macro)
        if mp:
            inputs["macro_pressure"] = {
                "score": mp["score"], "value": f"{mp['score']:+.2f}",
                "detail": mp.get("label", ""),
                "source": "vnstock_macro (pressure)", "as_of": as_of,
            }
        liq = liquidity_spread(macro)
        if liq:
            inputs["liquidity"] = {
                "dir": liq["dir"],
                "value": f"ON − điều hành {liq['spread']:+.2f} điểm %",
                "detail": liq.get("label", ""),
                "source": "vnstock_macro (gauge)",
                "as_of": _row_as_of("interbank_on", "sbv_policy_rate"),
            }
        term = term_spread(macro)
        if term:
            inputs["term"] = {
                "dir": term["dir"], "slope_dir": term.get("slope_dir"),
                "value": f"10Y − điều hành {term['spread']:+.2f} điểm %",
                "detail": term.get("label", ""),
                "source": "vnstock_macro (gauge)",
                "as_of": _row_as_of("govt_bond_yield_10y", "sbv_policy_rate"),
            }
        intl = intl_spread(macro)
        if intl:
            inputs["intl"] = {
                "dir": intl["dir"],
                "value": f"VN10Y − US10Y {intl['spread']:+.2f} điểm %",
                "detail": intl.get("label", ""),
                "source": "vnstock_macro (gauge)",
                "as_of": _row_as_of("govt_bond_yield_10y", "us10y"),
            }
    except Exception:
        pass

    return as_of, inputs


# ── State I/O (atomic) + history log ────────────────────────────────────────


def load_state() -> "dict | None":
    """State phân bổ hiện hành (band + inputs + history), None khi chưa có."""
    try:
        if _STATE.exists():
            return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_config() -> dict:
    try:
        if _CONFIG.exists():
            return json.loads(_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[allocation] ⚠ không đọc được config: {type(e).__name__}: {e}")
    return {}


def _write_state(state: dict) -> None:
    # atomic: Streamlit upload / pipeline recompute có thể đụng nhau
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _STATE)


def _history_entry(state: dict) -> dict:
    """1 dòng history/phiên — đủ cho scorecard hồi tố (P6) chấm lại band."""
    return {
        "date":     state["as_of"],
        "band":     state["band"],
        "raw_band": state["raw_band"],
        "score":    state["score"],
        "inputs":   {r["key"]: {"value": r["value"], "score": r["score"],
                                "as_of": r["as_of"]}
                     for r in state["inputs"]},
    }


def run_allocation(effective_date: "str | None" = None) -> "dict | None":
    """Thu inputs → tính band → persist state + history. Best-effort: không
    input nào dùng được → GIỮ state cũ, trả None (không bao giờ ghi đè bằng
    trạng thái rỗng)."""
    as_of, inputs = collect_inputs(effective_date)
    prev = load_state()
    state = compute_allocation(inputs, prev_state=prev, config=_load_config(),
                               as_of=as_of)
    if state is None:
        print("[allocation] ⚠ chưa đủ dữ liệu đầu vào — giữ state cũ nguyên vẹn")
        return None
    history = [h for h in (prev or {}).get("history", [])
               if h.get("date") != state["as_of"]]
    history.append(_history_entry(state))
    history.sort(key=lambda h: h.get("date") or "")
    state["history"] = history[-_HISTORY_MAX:]
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_state(state)
    return state


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_state(state: dict) -> None:
    band = state["band"]
    print(f"🧭 Phân bổ tài sản — band {band} ({state['band_label']}) · "
          f"điểm {state['score']:+.3f} · phiên {state['as_of']}")
    if state.get("raw_band") != band:
        print(f"   (điểm thô đề xuất {state['raw_band']} — hysteresis đang giữ {band})")
    if state.get("pending"):
        p = state["pending"]
        print(f"   ⏳ chờ xác nhận đổi sang {p['band']} "
              f"({len(p['dates'])}/{_CONFIRM_SESSIONS} phiên: {', '.join(p['dates'])})")
    print("\n  Lớp tài sản   | %")
    print("  " + "-" * 22)
    for cls in _ASSET_CLASSES:
        print(f"  {cls:<13} | {state['allocation'][cls]:>3}%")
    print(f"\n  Lý do ({state['n_inputs']} tín hiệu, weight sau renormalize):")
    for r in state["inputs"]:
        detail = f" — {r['detail']}" if r.get("detail") else ""
        print(f"  • {r['label']:<24} {r['score']:+.2f} × {r['weight']:.3f}"
              f"  [{r['value']}]{detail}")
        print(f"    nguồn: {r['source']} · as_of {r['as_of']}")
    if state.get("updated_at"):
        print(f"\n  cập nhật: {state['updated_at']}")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Phân bổ tài sản theo band vĩ mô B0-B4")
    ap.add_argument("--refresh", action="store_true",
                    help="thu inputs từ cache → tính band → ghi state + history")
    ap.add_argument("--show", action="store_true", help="in state hiện hành")
    ap.add_argument("--history", type=int, nargs="?", const=10, default=None,
                    metavar="N", help="in N dòng history gần nhất (mặc định 10)")
    ap.add_argument("--json", action="store_true", help="in state dạng JSON")
    ap.add_argument("--as-of", default=None,
                    help="ép ngày phiên (YYYY-MM-DD) khi --refresh")
    args = ap.parse_args(argv)

    if args.refresh:
        state = run_allocation(args.as_of)
        if state is None:
            return 1
        _print_state(state)
        return 0

    state = load_state()
    if state is None:
        print("[allocation] chưa có state — chạy: python vnstock_allocation.py --refresh")
        return 1
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.history is not None:
        for h in state.get("history", [])[-args.history:]:
            print(f"  {h['date']}  band {h['band']} (thô {h['raw_band']}) "
                  f"điểm {h['score']:+.3f}  [{len(h.get('inputs', {}))} tín hiệu]")
        return 0
    _print_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

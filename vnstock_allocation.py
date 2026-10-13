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

    if candidate != cur_idx and _one_step_enabled():
        # Vá 1 (P1b-2, #20): lề 0.05 × 2 phiên vẫn để ứng viên cách 2 bậc — mỗi
        # lần đổi chỉ 1 bậc, bậc kế tiếp phải được xác nhận lại từ đầu.
        candidate = cur_idx + (1 if candidate > cur_idx else -1)

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
            # as_of CŨ nhất trong các chỉ số nền THỊ TRƯỜNG — trung thực về độ
            # tươi. sbv_policy_rate bị loại khỏi phép min: as_of của nó là ngày
            # SBV ra quyết định (có thể nhiều năm trước), không phải độ cũ data
            # — cùng lý do doctor coi chỉ số này "không bao giờ cũ". (Bắt được
            # khi verify 2026-07-14: gauge hiện as_of 2023-06-19 gây hiểu nhầm.)
            avail = [rows[k]["as_of"] for k in keys
                     if rows.get(k) and k != "sbv_policy_rate"]
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


# ── Tilt từ báo cáo (P3 — đọc consensus đã cache, vẫn zero LLM tại đây) ─────


def _tilt_enabled() -> bool:
    return os.environ.get("VNSTOCK_ALLOCATION_TILT", "1") != "0"


def _load_report_tilt(as_of: "str | None") -> "dict | None":
    """Consensus digest báo cáo (vnstock_report_digest) — best-effort, chỉ ĐỌC
    digest đã cache trong reports_index (không gọi LLM). None khi chưa có
    digest / module lỗi / tilt = 0."""
    if not _tilt_enabled():
        return None
    try:
        from vnstock_report_digest import consensus
        c = consensus(as_of=as_of)
        if c and c.get("tilt"):
            return c
    except Exception:
        pass
    return None


def tilt_label(rt: "dict | None") -> str:
    """"+1 band" hoặc "+1 band × 60% (B2→B3, báo cáo cũ dần)" — state cũ chưa
    có `label` vẫn in được."""
    rt = rt or {}
    return rt.get("label") or f"{rt.get('tilt', 0):+d} band"


def blend_allocation(a: dict, b: dict, f: float) -> dict:
    """Tỷ trọng đi từ ``a`` tới ``b`` một đoạn ``f`` (0..1), số NGUYÊN, tổng
    giữ nguyên (chia phần dư theo phần lẻ lớn nhất). f=1 ⇒ đúng ``b``."""
    f = max(0.0, min(1.0, f))
    raw = {cls: a[cls] + (b.get(cls, a[cls]) - a[cls]) * f for cls in a}
    out = {cls: int(v // 1) for cls, v in raw.items()}
    left = int(round(sum(raw.values()))) - sum(out.values())
    for cls in sorted(raw, key=lambda c: raw[c] - out[c], reverse=True)[:max(0, left)]:
        out[cls] += 1
    return out


def apply_tilt(state: dict, tilt_info: "dict | None",
               config: "dict | None" = None) -> dict:
    """Áp tilt ±1 band từ consensus báo cáo LÊN TRÊN band data (nguyên tắc
    thiết kế: báo cáo chỉ tilt ±1, KHÔNG override data sống).

    ``state["band_data"]`` luôn = band từ data (hysteresis P1 neo vào đây);
    ``state["band"]`` = band hiệu lực sau tilt. Không tilt → 2 field bằng nhau.
    Mức áp = ``strength`` của consensus (05/10): báo cáo cũ dần ⇒ tỷ trọng
    TRƯỢT từ bảng band đã tilt về bảng band data; ``band`` hiệu lực là band
    GẦN hơn (strength ≥ 0,5 ⇒ band đã tilt). Thiếu strength (bản cũ) = 1.
    """
    state["band_data"] = state["band"]
    tilt = (tilt_info or {}).get("tilt") or 0
    if not tilt:
        state["report_tilt"] = None
        return state
    raw_s = tilt_info.get("strength", 1.0)
    strength = max(0.0, min(1.0, float(1.0 if raw_s is None else raw_s)))
    table = _allocations_table(config)
    idx = max(0, min(len(_BANDS) - 1, _BANDS.index(state["band"]) + tilt))
    tilted = _BANDS[idx]
    state["allocation"] = blend_allocation(table[state["band_data"]], table[tilted],
                                           strength)
    if strength >= 0.5:
        state["band"] = tilted
    state["band_label"] = _BAND_LABELS[state["band"]]
    label = f"{tilt:+d} band"
    if strength < 1 and tilted != state["band_data"]:
        label += (f" × {strength:.0%} ({state['band_data']}→{tilted}, "
                  f"báo cáo cũ dần)")
    state["report_tilt"] = {
        "tilt": tilt,
        "strength": round(strength, 2),
        "label": label,
        "stance_cp": (tilt_info.get("stance") or {}).get("Cổ phiếu"),
        "n_reports": tilt_info.get("n_reports"),
        "sources": [d.get("source") for d in tilt_info.get("drivers", [])],
    }
    return state


# ── Kẹp theo trung hạn (P1b-2, #20 — `docs/THIET-KE-BRIEF-3-KHUNG.md` §3.8) ──
#
# Câu 14 = B (user chốt 06/10): % cổ phiếu CHỈ được tăng khi trung hạn TĂNG và
# 🚨 tắt; ĐI NGANG/GIẢM/🚨 chỉ giữ hoặc giảm (kể cả phần trôi do tilt phai).
# Hết kẹp: tăng ≤1 bậc/tuần, báo trước ⏳ 1 tuần. Giảm rủi ro luôn đi qua.

_UP_STEP_DAYS = 7
_MEDIUM_NAME = {1: "TĂNG", 0: "ĐI NGANG", -1: "GIẢM"}


_OFF_VALUES = {"0", "false", "off", "no"}      # cùng tập với doctor check_kill_switches


def _horizon_cap_enabled() -> bool:
    return os.environ.get("VNSTOCK_ALLOC_HORIZON_CAP", "1").strip().lower() not in _OFF_VALUES


def _one_step_enabled() -> bool:
    return os.environ.get("VNSTOCK_ALLOC_ONE_STEP", "1").strip().lower() not in _OFF_VALUES


def _load_horizon() -> "tuple[dict | None, str | None]":
    """(trung hạn + 🚨 của bản published 3 khung mới nhất, None) hoặc (None, lý
    do) khi state chưa có / cũ / có conflicted copy — khi đó KHÔNG kẹp."""
    try:
        import vnstock_horizons_state as hs
        lp = hs.latest_published(_META.parent)
    except Exception as e:
        return None, f"không đọc được state 3 khung ({type(e).__name__}: {e})"
    if not lp.usable:
        return None, lp.reason
    snap = lp.snap
    return {"as_of": snap.get("as_of"), "medium": snap.get("medium"),
            "alert_tier": (snap.get("alert") or {}).get("tier") or 0}, None


def _cap_reason(horizon: dict) -> "str | None":
    """Lý do CẤM tăng % cổ phiếu, None khi trung hạn TĂNG và 🚨 tắt."""
    why = []
    if horizon.get("medium") != 1:
        why.append(f"trung hạn {_MEDIUM_NAME.get(horizon.get('medium'), '?')}")
    if horizon.get("alert_tier"):
        why.append("🚨 bật")
    return " · ".join(why) or None


def _equity_pct(state: dict) -> float:
    return float((state.get("allocation") or {}).get("Cổ phiếu") or 0)


def _hold(state: dict, prev: dict) -> None:
    """Giữ band + bảng % HIỆU LỰC hôm trước (band_data vẫn đi tiếp)."""
    state["band"] = prev["band"]
    state["band_label"] = _BAND_LABELS[prev["band"]]
    state["allocation"] = dict(prev["allocation"])


def apply_horizon_cap(state: dict, prev: "dict | None", horizon: "dict | None",
                      as_of: str, *, note: "str | None" = None,
                      config: "dict | None" = None) -> dict:
    """Áp kẹp lên state đã tilt (sửa tại chỗ, trả lại state).

    - trung hạn ≠ TĂNG hoặc 🚨 bật mà % cổ phiếu mới > % hiệu lực hôm trước ⇒
      giữ band + bảng % cũ, ghi ``capped_by`` (band/% dữ liệu đề xuất);
    - trung hạn TĂNG và 🚨 tắt mà band hiệu lực lên bậc ⇒ ⏳ ``ramp`` 1 tuần
      rồi mới lên, mỗi tuần ≤1 bậc;
    - giảm rủi ro luôn đi qua; ``horizon`` None (state 3 khung chưa có / cũ /
      hỏng) ⇒ không kẹp, ghi ``horizon_note``; lần chạy đầu không có gì để giữ.
    """
    if (not _horizon_cap_enabled() or not prev or not prev.get("allocation")
            or prev.get("band") not in _BANDS):
        return state
    if horizon is None:
        state["horizon_note"] = note or "không đọc được state 3 khung"
        return state
    if why := _cap_reason(horizon):
        new_pct = _equity_pct(state)
        if new_pct > _equity_pct(prev):
            proposed = state["band"]
            _hold(state, prev)
            state["capped_by"] = {"by": "horizons", "why": why,
                                  "proposed_band": proposed, "proposed_pct": new_pct}
        return state
    cur_idx, new_idx = _BANDS.index(prev["band"]), _BANDS.index(state["band"])
    if new_idx >= cur_idx:
        return state
    target = state["band"]
    since = (prev.get("ramp") or {}).get("since") or as_of
    if (date.fromisoformat(as_of) - date.fromisoformat(since)).days < _UP_STEP_DAYS:
        _hold(state, prev)
        state["ramp"] = {"band": target, "since": since}
        return state
    if new_idx < cur_idx - 1:
        step = _BANDS[cur_idx - 1]
        state["band"] = step
        state["band_label"] = _BAND_LABELS[step]
        state["allocation"] = dict(_allocations_table(config)[step])
        state["ramp"] = {"band": target, "since": as_of}
    return state


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
        "date":      state["as_of"],
        "band":      state["band"],
        "band_data": state.get("band_data", state["band"]),
        "tilt":      (state.get("report_tilt") or {}).get("tilt", 0) or 0,
        "tilt_strength": (state.get("report_tilt") or {}).get("strength"),
        # % THẬT đã khuyến nghị — tilt trộn dở (05/10) không còn khớp bảng band
        "allocation": dict(state.get("allocation") or {}),
        "raw_band":  state["raw_band"],
        # Vá 3 (P1b-2, #20): đề xuất đang chờ + kẹp theo trung hạn + ⏳ tăng
        "pending":   state.get("pending"),
        "capped_by": state.get("capped_by"),
        "ramp":      state.get("ramp"),
        "score":     state["score"],
        "inputs":    {r["key"]: {"value": r["value"], "score": r["score"],
                                 "as_of": r["as_of"]}
                      for r in state["inputs"]},
    }


def run_allocation(effective_date: "str | None" = None, *,
                   persist: bool = True) -> "dict | None":
    """Thu inputs → tính band → kẹp theo trung hạn → persist state + history.
    Best-effort: không input nào dùng được → GIỮ state cũ, trả None (không
    bao giờ ghi đè bằng trạng thái rỗng). ``persist=False`` = chỉ tính để hiện
    (nút dashboard lúc overview còn giữa phiên — Vá 2), không ghi file."""
    as_of, inputs = collect_inputs(effective_date)
    prev = load_state()
    cfg = _load_config()
    # Hysteresis neo vào band DATA (band_data) — band hiệu lực có thể đã bị
    # tilt bởi báo cáo, không được để tilt làm trôi mốc so sánh của data.
    prev_for_hyst = None
    if prev:
        prev_for_hyst = {**prev, "band": prev.get("band_data") or prev.get("band")}
    state = compute_allocation(inputs, prev_state=prev_for_hyst, config=cfg,
                               as_of=as_of)
    if state is None:
        print("[allocation] ⚠ chưa đủ dữ liệu đầu vào — giữ state cũ nguyên vẹn")
        return None
    apply_tilt(state, _load_report_tilt(as_of), config=cfg)
    horizon, note = _load_horizon() if _horizon_cap_enabled() else (None, None)
    apply_horizon_cap(state, prev, horizon, state["as_of"], note=note, config=cfg)
    history = [h for h in (prev or {}).get("history", [])
               if h.get("date") != state["as_of"]]
    history.append(_history_entry(state))
    history.sort(key=lambda h: h.get("date") or "")
    state["history"] = history[-_HISTORY_MAX:]
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if persist:
        _write_state(state)
    return state


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_state(state: dict) -> None:
    band = state["band"]
    print(f"🧭 Phân bổ tài sản — band {band} ({state['band_label']}) · "
          f"điểm {state['score']:+.3f} · phiên {state['as_of']}")
    rt = state.get("report_tilt")
    if rt:
        arrow = "tấn công hơn" if rt["tilt"] < 0 else "phòng thủ hơn"
        print(f"   📚 tilt {tilt_label(rt)} ({arrow}) từ {rt['n_reports']} "
              f"báo cáo (stance CP {rt['stance_cp']:+.2f}) — band data: "
              f"{state['band_data']}")
    band_data = state.get("band_data", band)
    if state.get("raw_band") != band_data:
        print(f"   (điểm thô đề xuất {state['raw_band']} — hysteresis đang giữ "
              f"{band_data})")
    if state.get("pending"):
        p = state["pending"]
        print(f"   ⏳ chờ xác nhận đổi sang {p['band']} "
              f"({len(p['dates'])}/{_CONFIRM_SESSIONS} phiên: {', '.join(p['dates'])})")
    if cap := state.get("capped_by"):
        print(f"   🔒 kẹp theo trung hạn: band dữ liệu đề xuất {cap['proposed_band']} "
              f"({cap['proposed_pct']:g}% cổ phiếu) — giữ vì {cap['why']}")
    if ramp := state.get("ramp"):
        print(f"   ⏳ tăng tỷ trọng về {ramp['band']}: ≤1 bậc/tuần, tính từ {ramp['since']}")
    if note := state.get("horizon_note"):
        print(f"   (kẹp theo trung hạn không áp: {note})")
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

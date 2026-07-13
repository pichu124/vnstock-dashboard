#!/usr/bin/env python3
"""vnstock_scorecard.py — Scorecard hồi tố cho band phân bổ (Phase 6).

Đối soát band phân bổ (vnstock_allocation, kỳ THÁNG) với return THỰC của
từng lớp tài sản kỳ đó — mirror tinh thần vnstock_reconciler (khuyến nghị
mở → chấm khi đóng), nhưng cho tầng phân bổ. Đồng thời LOG chất lượng nguồn
báo cáo (stance CP của mỗi digest vs return VNINDEX 30 ngày sau) — xếp hạng
nguồn chỉ LOG từ bây giờ, UI xếp hạng để dành khi đủ mẫu (tham số duyệt).

Proxy return từng lớp (đều dán nhãn THÔ — zero fetch, chỉ đọc cache sẵn có):
  * Cổ phiếu   — %Δ VNINDEX (kho parquet)
  * Trái phiếu — −Δ lợi suất 10Y (điểm %) × duration ~7 (proxy giá TPCP,
                 KHÔNG phải return quỹ trái phiếu thật)
  * Tiền gửi   — lãi suất điều hành theo ngày nắm giữ (carry, %/năm × d/365)
  * Vàng       — %Δ spot quốc tế (vnstock_gold; chưa gồm premium SJC)
  * USD        — %Δ USD/VND (registry)

Kỳ = THÁNG LỊCH: entry ĐẦU TIÊN của mỗi tháng trong history của
allocation_state là band "chốt" cho tháng đó; kỳ hoàn tất khi tháng sau có
entry. Cần ≥ 2 kỳ (≥ 2 tháng history) mới có dòng scorecard — trước đó lệnh
--show ghi rõ "chưa đủ kỳ" (đúng thiết kế "sau ≥2 kỳ"; log nguồn báo cáo thì
chạy NGAY từ bây giờ).

Cache: ``data_warehouse/_meta/allocation_scorecard.json`` (atomic write).
CLI: ``--refresh`` / ``--show``. Bước ``run.py allocation`` tự refresh
scorecard best-effort sau khi tính band.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"
_SCORECARD = _META / "allocation_scorecard.json"

# Duration proxy cho lớp Trái phiếu: −Δyield × duration ≈ %Δ giá. TPCP VN kỳ
# hạn phổ biến 5-10Y → chọn 7 (proxy thô, dán nhãn ở mọi nơi hiển thị).
_BOND_DURATION = 7.0

# Return VNINDEX bao nhiêu ngày sau report_date dùng để log chất lượng nguồn.
_SOURCE_HORIZON_DAYS = 30

_CLASS_PROXY_LABELS = {
    "Cổ phiếu":   "%Δ VNINDEX",
    "Trái phiếu": f"−Δ lợi suất 10Y × duration {_BOND_DURATION:g} (proxy thô)",
    "Tiền gửi":   "lãi suất điều hành × ngày nắm giữ (carry)",
    "Vàng":       "%Δ vàng spot quốc tế (chưa gồm premium SJC)",
    "USD":        "%Δ USD/VND",
}


# ── History loaders (best-effort, zero fetch) ────────────────────────────────


def _vnindex_closes() -> dict[str, float]:
    """{date_iso: close} từ kho parquet VNINDEX — {} khi kho trống."""
    out: dict[str, float] = {}
    vn_dir = _META.parent / "prices" / "ticker=VNINDEX"
    if not vn_dir.exists():
        return out
    try:
        import pandas as pd
        for f in sorted(vn_dir.glob("year=*/*.parquet")):
            df = pd.read_parquet(f, columns=["time", "close"])
            for t, c in zip(pd.to_datetime(df["time"]), df["close"]):
                out[t.date().isoformat()] = float(c)
    except Exception:
        return {}
    return out


def _macro_history(key: str) -> dict[str, float]:
    """{date: value} một chỉ số registry — đọc thẳng cache macro (state thuần)."""
    try:
        from vnstock_macro import _load_cache
        hist = ((_load_cache().get("indicators") or {}).get(key) or {}) \
            .get("history") or {}
        return {d: float(v) for d, v in hist.items()}
    except Exception:
        return {}


def _gold_history() -> dict[str, float]:
    try:
        from vnstock_gold import _load_cache
        return {d: float(v) for d, v in
                (_load_cache().get("history") or {}).items()}
    except Exception:
        return {}


def _value_on(hist: dict[str, float], date_iso: str) -> "float | None":
    """Reading gần nhất ≤ date — kỳ THÁNG nên lệch vài ngày chấp nhận được."""
    ok = [d for d in hist if d <= date_iso]
    return hist[max(ok)] if ok else None


def _pct(a: "float | None", b: "float | None") -> "float | None":
    if a is None or b is None or not a:
        return None
    return round((b - a) / a * 100, 2)


def class_returns(start: str, end: str,
                  hists: "dict | None" = None) -> dict[str, dict]:
    """Return proxy từng lớp trong [start, end] — {cls: {ret_pct, proxy}};
    ret_pct=None khi thiếu data (KHÔNG bịa). ``hists`` inject được cho test."""
    h = hists or {
        "vnindex": _vnindex_closes(),
        "y10": _macro_history("govt_bond_yield_10y"),
        "policy": _macro_history("sbv_policy_rate"),
        "gold": _gold_history(),
        "usdvnd": _macro_history("usdvnd"),
    }
    days = max((date.fromisoformat(end) - date.fromisoformat(start)).days, 0)

    y0, y1 = _value_on(h["y10"], start), _value_on(h["y10"], end)
    bond = round(-(y1 - y0) * _BOND_DURATION, 2) \
        if (y0 is not None and y1 is not None) else None
    pol = _value_on(h["policy"], start)
    deposit = round(pol * days / 365.0, 2) if pol is not None else None

    rets = {
        "Cổ phiếu":   _pct(_value_on(h["vnindex"], start), _value_on(h["vnindex"], end)),
        "Trái phiếu": bond,
        "Tiền gửi":   deposit,
        "Vàng":       _pct(_value_on(h["gold"], start), _value_on(h["gold"], end)),
        "USD":        _pct(_value_on(h["usdvnd"], start), _value_on(h["usdvnd"], end)),
    }
    return {cls: {"ret_pct": r, "proxy": _CLASS_PROXY_LABELS[cls]}
            for cls, r in rets.items()}


# ── Pure core: kỳ tháng + chấm điểm ─────────────────────────────────────────


def monthly_periods(history: list[dict]) -> list[tuple[dict, str]]:
    """(entry đầu tháng, ngày-đầu-tháng-sau) cho mỗi kỳ THÁNG HOÀN TẤT.

    Entry ĐẦU TIÊN mỗi tháng = band chốt cho tháng đó; kỳ khép lại tại entry
    đầu của tháng kế tiếp. Tháng cuối (đang chạy) không tạo kỳ.
    """
    firsts: dict[str, dict] = {}
    for hrow in sorted(history or [], key=lambda x: x.get("date") or ""):
        month = (hrow.get("date") or "")[:7]
        if month and month not in firsts:
            firsts[month] = hrow
    months = sorted(firsts)
    return [(firsts[m], firsts[months[i + 1]]["date"])
            for i, m in enumerate(months[:-1])]


def compute_scorecard(history: list[dict], table: dict[str, dict[str, int]],
                      returns_fn=None) -> list[dict]:
    """Chấm từng kỳ tháng: return danh mục theo bảng % của band kỳ đó vs
    baseline B2 (trung tính). Pure trừ ``returns_fn`` (inject được; mặc định
    ``class_returns`` — resolve lúc GỌI để test monkeypatch được).

    Return danh mục = Σ w_cls × r_cls trên các lớp CÓ data; ``coverage_pct``
    ghi tổng trọng số có data — thiếu data là nói thiếu, không độn 0.
    """
    if returns_fn is None:
        returns_fn = class_returns
    rows: list[dict] = []
    for entry, end in monthly_periods(history):
        band = entry.get("band")
        if band not in table:
            continue
        start = entry["date"]
        rets = returns_fn(start, end)

        def _port(weights: dict[str, int]) -> tuple["float | None", float]:
            got = [(w / 100.0, rets[cls]["ret_pct"])
                   for cls, w in weights.items()
                   if rets.get(cls, {}).get("ret_pct") is not None]
            cov = round(sum(w for w, _ in got) * 100, 0)
            if not got:
                return None, 0.0
            return round(sum(w * r for w, r in got), 2), cov

        port, cov = _port(table[band])
        base, _ = _port(table["B2"])
        rows.append({
            "period_start": start, "period_end": end,
            "band": band, "band_data": entry.get("band_data", band),
            "tilt": entry.get("tilt", 0),
            "class_returns": {cls: v["ret_pct"] for cls, v in rets.items()},
            "port_ret_pct": port,
            "baseline_b2_ret_pct": base,
            "delta_vs_b2": (round(port - base, 2)
                            if port is not None and base is not None else None),
            "coverage_pct": cov,
        })
    return rows


def source_log(reports: list[dict], vnindex: "dict[str, float] | None" = None,
               today: "str | None" = None) -> list[dict]:
    """LOG chất lượng nguồn: stance CP mỗi digest vs %Δ VNINDEX 30 ngày sau
    report_date. Chỉ log báo cáo đã đủ chân trời 30 ngày; return None khi
    thiếu giá (không bịa). Xếp hạng/UI để dành khi đủ mẫu."""
    vnindex = vnindex if vnindex is not None else _vnindex_closes()
    anchor = today or date.today().isoformat()
    rows: list[dict] = []
    for rec in reports or []:
        d = rec.get("digest") or {}
        rd = rec.get("report_date")
        if not rd or not d.get("stance"):
            continue
        end = (date.fromisoformat(rd)
               + timedelta(days=_SOURCE_HORIZON_DAYS)).isoformat()
        if end > anchor:
            continue                       # chưa đủ chân trời — kỳ sau log
        rows.append({
            "id": rec.get("id"), "source": rec.get("source"),
            "report_date": rd,
            "stance_cp": d["stance"].get("Cổ phiếu", 0),
            "vnindex_ret_30d": _pct(_value_on(vnindex, rd),
                                    _value_on(vnindex, end)),
            "has_mismatch": bool(d.get("has_mismatch")),
        })
    return rows


# ── Refresh + I/O ────────────────────────────────────────────────────────────


def load_scorecard() -> "dict | None":
    try:
        if _SCORECARD.exists():
            return json.loads(_SCORECARD.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def refresh_scorecard() -> "dict | None":
    """Đọc allocation history + reports → chấm → ghi atomic. None khi chưa có
    allocation state (không có gì để chấm)."""
    try:
        from vnstock_allocation import _allocations_table, _load_config, load_state
    except Exception:
        return None
    state = load_state()
    if not state:
        print("[scorecard] chưa có allocation state — chạy run.py allocation trước")
        return None
    periods = compute_scorecard(state.get("history") or [],
                                _allocations_table(_load_config()))
    try:
        from vnstock_reports import load_for_analysis
        reports = load_for_analysis(max_age_days=365)
    except Exception:
        reports = []
    sources = source_log(reports)
    from datetime import datetime
    out = {"updated_at": datetime.now().isoformat(timespec="seconds"),
           "n_periods": len(periods), "periods": periods, "sources": sources}
    _SCORECARD.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SCORECARD.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _SCORECARD)
    print(f"[scorecard] {len(periods)} kỳ tháng hoàn tất, "
          f"{len(sources)} dòng log nguồn báo cáo")
    if not periods:
        print("[scorecard] chưa đủ kỳ (cần history ≥ 2 tháng) — log nguồn vẫn chạy")
    return out


def _print(sc: dict) -> None:
    print(f"🗂 Scorecard phân bổ (cập nhật {sc.get('updated_at', '?')})")
    periods = sc.get("periods") or []
    if not periods:
        print("  Chưa đủ kỳ tháng hoàn tất (cần history ≥ 2 tháng).")
    for p in periods:
        port = p["port_ret_pct"]
        base = p["baseline_b2_ret_pct"]
        delta = p["delta_vs_b2"]
        print(f"  {p['period_start']} → {p['period_end']}  band {p['band']}"
              f"  danh mục {port if port is not None else '?'}%"
              f"  vs B2 {base if base is not None else '?'}%"
              f"  (Δ {f'{delta:+.2f}' if delta is not None else '?'}pp,"
              f" phủ {p['coverage_pct']:.0f}%)")
    srcs = sc.get("sources") or []
    if srcs:
        print(f"  Log nguồn báo cáo ({len(srcs)} — xếp hạng để dành khi đủ mẫu):")
        for s in srcs:
            r = s["vnindex_ret_30d"]
            print(f"    • {s['report_date']} {s['source']}: stance CP "
                  f"{s['stance_cp']:+d} → VNINDEX 30d "
                  f"{f'{r:+.2f}%' if r is not None else '?'}")
    print("  (Proxy return THÔ: " + "; ".join(
        f"{c} = {l}" for c, l in _CLASS_PROXY_LABELS.items()) + ")")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Scorecard hồi tố band phân bổ")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)
    if args.refresh:
        return 0 if refresh_scorecard() is not None else 1
    sc = load_scorecard()
    if not sc:
        print("[scorecard] chưa có — chạy --refresh (cần allocation state)")
        return 1
    _print(sc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

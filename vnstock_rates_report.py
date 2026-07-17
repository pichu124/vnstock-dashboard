"""
vnstock_rates_report.py — Báo cáo tuần lãi suất & tiền tệ (render từ cache)
===========================================================================
Mượn Ý TƯỞNG trình bày từ skill Thanhtran-165/baocaolaisuatvatiente (báo cáo
tuần data-driven, 0 speculation — KHÔNG copy code, no LICENSE), NHƯNG lật
ngược: skill dành ~80% code ĐI LẤY dữ liệu, còn dashboard ĐÃ có sẵn toàn bộ
(registry vĩ mô + HNX 8 kỳ hạn + 3 gauge + OMO/SBV) → đây chỉ là tầng RENDER.

Thuần, deterministic, ZERO fetch/LLM: đọc cache qua `vnstock_macro.load_macro`
+ `vnstock_hnx.load_yields` + gauge functions + `vnstock_sbv.load_weekly`.
3 output:
  * `build_report_data(as_of)`  → dict cấu trúc (dùng chung A + B)
  * `render_html(data)`         → HTML tự chứa (bảng + đường cong SVG + gauge
                                  + narrative) cho tab dashboard / tải / Artifact
  * `render_telegram(data)`     → text gọn cho Telegram (không chart)

Narrative = câu SUY TỪ SỐ (nhãn gauge + đổi lãi suất + OMO), KHÔNG dự đoán
tương lai (mirror "banned speculation" của skill) → không cần guard/LLM.

CLI:  python vnstock_rates_report.py --html out.html | --text
"""

from __future__ import annotations

import argparse
import html as _html
from datetime import date, datetime
from typing import Optional

# Kỳ hạn đường cong hiển thị (khớp key HNX)
_CURVE_TENORS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y")
# Chỉ số lãi suất/tỷ giá nêu trong bảng (theo key registry macro)
_RATE_KEYS = ("sbv_policy_rate", "interbank_on", "interbank_1w",
              "govt_bond_yield_2y", "govt_bond_yield_10y",
              "us10y", "fed_funds", "usdvnd")


def _iso_week_label(as_of: str) -> str:
    try:
        d = date.fromisoformat(as_of)
        y, w, _ = d.isocalendar()
        return f"Tuần {w}/{y}"
    except Exception:
        return as_of or ""


def build_report_data(as_of: Optional[str] = None) -> dict:
    """Gom dữ liệu báo cáo từ cache sẵn có. Zero fetch. Trường thiếu → bỏ
    khỏi output (best-effort), KHÔNG bịa."""
    import vnstock_macro as mac

    macro = mac.load_macro(as_of) or []
    by_key = {m["key"]: m for m in macro}

    rates = []
    for k in _RATE_KEYS:
        m = by_key.get(k)
        if not m:
            continue
        ch = mac.fmt_change(m)
        rates.append({
            "key": k,
            "label": m.get("label") or k,
            "value": mac.fmt_value(m),
            "as_of": m.get("as_of"),
            "source": m.get("source"),
            "change": (f"{ch[0]} {ch[1]}" if ch else ""),
            "dir": (m.get("change") or {}).get("dir", 0),
        })

    gauges = []
    for fn, nm in ((mac.liquidity_spread, "Thanh khoản hệ thống"),
                   (mac.term_spread, "Kỳ hạn & đường cong"),
                   (mac.intl_spread, "Chênh lệch quốc tế VN−US")):
        try:
            g = fn(macro)
        except Exception:
            g = None
        if g:
            gauges.append({"name": nm, "spread": g.get("spread"),
                           "label": g.get("label"), "dir": g.get("dir", 0),
                           "slope": g.get("slope_2_10") or g.get("slope_10y_on")})

    curve = None
    try:
        import vnstock_hnx
        got = vnstock_hnx.load_yields(as_of)
        if got:
            pts = [(t, got[1][t]) for t in _CURVE_TENORS if t in got[1]]
            if len(pts) >= 2:
                curve = {"as_of": got[0], "points": pts}
    except Exception:
        pass

    omo = fx_central = None
    try:
        import vnstock_sbv
        w = vnstock_sbv.load_weekly()
        omo = w.get("omo_net")
        fx_central = w.get("fx_central")
    except Exception:
        pass

    eff = as_of or (rates[0]["as_of"] if rates else None) \
        or datetime.now().date().isoformat()
    data = {
        "as_of": eff,
        "week_label": _iso_week_label(eff),
        "rates": rates,
        "gauges": gauges,
        "curve": curve,
        "omo_net": omo,
        "fx_central": fx_central,
    }
    data["narrative"] = _narrative(data, by_key, mac)
    return data


def _narrative(data: dict, by_key: dict, mac) -> list:
    """Câu SUY TỪ SỐ (không dự đoán tương lai). Mỗi câu best-effort."""
    out: list[str] = []
    for g in data["gauges"]:
        if g.get("label"):
            sp = g.get("spread")
            sp_s = f" ({sp:+.2f} điểm %)" if isinstance(sp, (int, float)) else ""
            out.append(f"{g['name']}: {g['label']}{sp_s}.")
    on = by_key.get("interbank_on")
    if on and (on.get("change") or {}).get("delta") is not None:
        d = on["change"]["delta"]
        if abs(d) >= 0.10:
            verb = "tăng" if d > 0 else "giảm"
            out.append(f"Lãi suất liên ngân hàng qua đêm {verb} "
                       f"{abs(d):.2f} điểm % so với kỳ trước.")
    omo = data.get("omo_net")
    if isinstance(omo, (int, float)) and abs(omo) >= 1:
        side = "hút ròng" if omo > 0 else "bơm ròng"
        out.append(f"NHNN {side} {abs(omo):,.0f} tỷ đồng qua kênh OMO trong tuần.")
    return out


# ── Render HTML tự chứa (inline CSS + SVG, zero external dep) ────────────────

def _svg_yield_curve(curve: dict, width: int = 620, height: int = 240) -> str:
    """Đường cong lợi suất bằng inline SVG (polyline scaled). '' khi thiếu."""
    pts = curve.get("points") or []
    if len(pts) < 2:
        return ""
    ys = [v for _, v in pts]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 30
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(pts)
    coords = []
    for i, (t, v) in enumerate(pts):
        x = pad_l + (iw * i / (n - 1))
        y = pad_t + ih * (1 - (v - lo) / span)
        coords.append((x, y, t, v))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#2563eb"/>'
        f'<text x="{x:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#374151">{v:.2f}</text>'
        f'<text x="{x:.1f}" y="{height - 10}" text-anchor="middle" '
        f'font-size="10" fill="#6b7280">{_html.escape(t)}</text>'
        for x, y, t, v in coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'style="max-width:{width}px" role="img" aria-label="Đường cong lợi suất TPCP">'
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" '
        f'y2="{height - pad_b}" stroke="#d1d5db"/>'
        f'<polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="2"/>'
        f'{dots}</svg>')


_DIR_MARK = {1: "▲", -1: "▼", 0: ""}
_DIR_COLOR = {1: "#dc2626", -1: "#16a34a", 0: "#6b7280"}   # lãi suất tăng = đỏ (thắt)


def render_html(data: dict) -> str:
    """HTML tự chứa (1 chuỗi). Không phụ thuộc mạng — nhúng inline CSS/SVG."""
    esc = _html.escape
    rows = "".join(
        f'<tr><td>{esc(r["label"])}</td><td class="num">{esc(r["value"])}</td>'
        f'<td class="num" style="color:{_DIR_COLOR.get(r["dir"], "#6b7280")}">'
        f'{esc(r["change"])}</td>'
        f'<td class="dim">{esc(str(r.get("as_of") or ""))}'
        f'{" · " + esc(r["source"]) if r.get("source") else ""}</td></tr>'
        for r in data["rates"])
    gauge_cards = "".join(
        f'<div class="gauge"><div class="gname">{esc(g["name"])}</div>'
        f'<div class="glabel" style="color:{_DIR_COLOR.get(g["dir"], "#6b7280")}">'
        f'{esc(g.get("label") or "")}</div></div>'
        for g in data["gauges"])
    narr = "".join(f"<li>{esc(s)}</li>" for s in data.get("narrative", []))
    svg = _svg_yield_curve(data["curve"]) if data.get("curve") else ""
    curve_block = (
        f'<h2>Đường cong lợi suất TPCP (HNX, phiên {esc(str(data["curve"]["as_of"]))})</h2>{svg}'
        if svg else "")
    omo = data.get("omo_net")
    omo_line = ""
    if isinstance(omo, (int, float)):
        side = "hút ròng" if omo > 0 else "bơm ròng"
        omo_line = f'<p class="dim">OMO tuần: {side} {abs(omo):,.0f} tỷ VND.</p>'

    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo tuần lãi suất & tiền tệ — {esc(data["week_label"])}</title>
<style>
 html{{background:#ffffff}}
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111827;
  background:#ffffff;max-width:760px;margin:0 auto;padding:20px;line-height:1.5}}
 /* background TƯỜNG MINH: nhúng qua components.html iframe trong dashboard
    nền TỐI thì iframe transparent → chữ #111827 tàng hình (bug thật 17/07) */
 h1{{font-size:20px;margin:0 0 2px}} h2{{font-size:15px;margin:22px 0 8px}}
 .sub{{color:#6b7280;font-size:13px;margin:0 0 8px}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 td.dim,.dim{{color:#6b7280;font-size:12px}}
 .gauges{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}}
 .gauge{{flex:1;min-width:200px;border:1px solid #e5e7eb;border-radius:8px;padding:10px}}
 .gname{{font-weight:600;font-size:12px;color:#374151}}
 .glabel{{font-size:13px;margin-top:3px}}
 ul{{margin:6px 0;padding-left:18px}} li{{font-size:13px;margin:3px 0}}
 .foot{{color:#9ca3af;font-size:11px;margin-top:24px}}
</style></head><body>
<h1>Báo cáo tuần lãi suất & tiền tệ</h1>
<p class="sub">{esc(data["week_label"])} · dữ liệu đến {esc(str(data["as_of"]))}</p>
<h2>Nhận định (suy từ số liệu)</h2><ul>{narr or "<li>Chưa đủ dữ liệu.</li>"}</ul>
<h2>Lãi suất & tỷ giá</h2>
<table><thead><tr><th>Chỉ số</th><th class="num">Giá trị</th>
<th class="num">Đổi</th><th>Nguồn</th></tr></thead><tbody>{rows}</tbody></table>
{omo_line}
{curve_block}
<h2>Gauge phái sinh</h2><div class="gauges">{gauge_cards or "<span class=dim>—</span>"}</div>
<p class="foot">Tự sinh từ cache dashboard (macro registry + HNX + SBV) — zero fetch,
không dự đoán tương lai. Lãi suất/lợi suất tăng hiển thị màu đỏ (thắt chặt).</p>
</body></html>"""


# ── Render Telegram (text gọn, không chart) ─────────────────────────────────

def render_telegram(data: dict) -> str:
    lines = [f"🏦 <b>Báo cáo tuần lãi suất & tiền tệ</b> — {data['week_label']}",
             f"<i>dữ liệu đến {data['as_of']}</i>", ""]
    for r in data["rates"]:
        ch = f"  {r['change']}" if r["change"] else ""
        lines.append(f"• {r['label']}: <b>{r['value']}</b>{ch}")
    if data.get("curve"):
        pts = data["curve"]["points"]
        key = {t: v for t, v in pts}
        seg = " · ".join(f"{t} {key[t]:.2f}" for t in ("2Y", "5Y", "10Y") if t in key)
        if seg:
            lines.append(f"• TPCP (HNX): {seg}")
    omo = data.get("omo_net")
    if isinstance(omo, (int, float)) and abs(omo) >= 1:
        side = "hút ròng" if omo > 0 else "bơm ròng"
        lines.append(f"• OMO tuần: {side} {abs(omo):,.0f} tỷ")
    if data.get("narrative"):
        lines.append("")
        lines.append("📝 " + " ".join(data["narrative"]))
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Báo cáo tuần lãi suất & tiền tệ (render từ cache)")
    ap.add_argument("--html", metavar="PATH", help="ghi HTML ra file")
    ap.add_argument("--text", action="store_true", help="in bản Telegram")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args(argv)
    data = build_report_data(args.as_of)
    if not data["rates"] and not data["curve"]:
        print("Cache vĩ mô/HNX rỗng — chạy `python run.py macro` trước.")
        return 1
    if args.html:
        from pathlib import Path
        Path(args.html).write_text(render_html(data), encoding="utf-8")
        print(f"✅ Đã ghi {args.html}")
    if args.text or not args.html:
        print(render_telegram(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

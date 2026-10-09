#!/usr/bin/env python3
"""vnstock_assets_brief.py — P5 đa tài sản: mục "🪙 Hàng hoá & Tiền tệ" trong brief (U86).

CODE dựng mọi số (luật repo: LLM hay phớt chỉ thị ⇒ số do code chốt). `brief_lines()` trả các dòng
"- …" cùng kiểu mục 🌐 Vĩ mô; brief đưa chúng vào prompt làm DỮ KIỆN và guard
`enforce_assets_section` thay nguyên thân mục bằng chính các dòng này (model không sửa được số).

Chỉ in chuỗi CÒN TƯƠI (cũ theo lịch thị trường ⇒ bỏ dòng, không in số cũ) — chuẩn user 09/10: số
quốc tế phải có trong ngày. Không còn dòng nào ⇒ trả rỗng ⇒ brief không có mục 🪙.
Kill-switch: `VNSTOCK_BRIEF_ASSETS=0`.
"""
from __future__ import annotations

import os
from datetime import date

import vnstock_assets as va
import vnstock_assets_view as av
from vnstock_brief_canon import _ASSETS_SECTION_TITLE as SECTION_TITLE   # dùng chung với guard

ENV_SWITCH = "VNSTOCK_BRIEF_ASSETS"
MAX_LINK_ITEMS = 3


def enabled() -> bool:
    return (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in ("0", "false", "off", "no")


def _fresh(key: str, today: date) -> "dict | None":
    c = av.card(key, today=today)
    return c if c and not c["stale"] else None


def _d1(c: dict) -> str:
    v = (c.get("chg") or {}).get("1 phiên")
    return f"{v:+.2f}% 1 phiên" if v is not None else "chưa có phiên trước"


def _ddmm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def snapshot(today: "date | None" = None) -> dict:
    """Số cho mục 🪙 (chỉ chuỗi còn tươi) — dùng cho cả dòng brief lẫn kiểm thử."""
    today = today or date.today()
    snap = {k: _fresh(k, today) for k in ("XAU", "GOLD_SJC_BAR", "BRENT", "WTI", "DXY",
                                          "USDVND_VCB", "USD_CENTRAL")}
    prem = av.premium_frame(start=None)
    if len(prem) and snap["GOLD_SJC_BAR"] and prem.index[-1].date().isoformat() == snap["GOLD_SJC_BAR"]["date"]:
        snap["premium_pct"] = float(prem["pct"].iloc[-1])
    snap["room"] = va.usd_ceiling_room_pct() if snap["USDVND_VCB"] and snap["USD_CENTRAL"] else None
    snap["curve"] = va.curve_spreads("CURVE_BRENT") if snap["BRENT"] else None
    est = (va.read_status().get("estimates") or {}).get("USD_BROAD_EST") or {}
    fresh_est = est.get("value") and est.get("date") and \
        (today - date.fromisoformat(est["date"])).days <= av.STALE_DAYS
    snap["usd_broad_est"] = est if fresh_est else None
    try:
        import vnstock_assets_links as al
        rows = al.load().get("rows") or []
        found = [r for r in rows if r["verdict"].startswith("có") and r["w60"]["t"] is not None]
        snap["links"] = sorted(found, key=lambda r: -abs(r["w60"]["t"]))[:MAX_LINK_ITEMS]
    except Exception:                                              # noqa: BLE001
        snap["links"] = []
    return snap


def brief_lines(today: "date | None" = None, snap: "dict | None" = None) -> "list[str]":
    """Các dòng thân mục 🪙 (KHÔNG có tiêu đề). Rỗng khi tắt hoặc không còn chuỗi tươi."""
    if not enabled():
        return []
    s = snap if snap is not None else snapshot(today)
    lines = []
    xau, sjc = s.get("XAU"), s.get("GOLD_SJC_BAR")
    if xau or sjc:
        parts = []
        if xau:
            parts.append(f"vàng TG {xau['value']:,.2f} USD/oz ({_d1(xau)}, {_ddmm(xau['date'])})")
        if sjc:
            part = f"SJC miếng bán {sjc['value'] / 1e6:,.2f} triệu đ/lượng ({_d1(sjc)})"
            if s.get("premium_pct") is not None:
                part += f", đắt hơn vàng TG quy đổi {s['premium_pct']:+.2f}%"
            parts.append(part)
        lines.append("- Vàng: " + " · ".join(parts))
    br, wt = s.get("BRENT"), s.get("WTI")
    if br or wt:
        parts = [f"{name} {c['value']:,.2f} USD/thùng ({_d1(c)}, {_ddmm(c['date'])})"
                 for name, c in (("Brent", br), ("WTI", wt)) if c]
        cv = s.get("curve")
        if cv:
            parts.append(f"đường cong Brent {cv['shape']} (tháng gần − tháng kế {cv['m1_m2']['usd']:+.2f} USD)")
        lines.append("- Dầu (hợp đồng tháng gần): " + " · ".join(parts))
    dxy, vcb, room = s.get("DXY"), s.get("USDVND_VCB"), s.get("room")
    if dxy or vcb or s.get("usd_broad_est"):
        parts = []
        if dxy:
            parts.append(f"DXY {dxy['value']:,.2f} ({_d1(dxy)})")
        est = s.get("usd_broad_est")
        if est:
            parts.append(f"chỉ số USD rộng ước tính {est['value']:,.2f} ±{est['band_pct']}%")
        if vcb:
            part = f"VCB bán {vcb['value']:,.0f} ({_d1(vcb)})"
            if room:
                part += f", còn cách trần {room['pct']:.2f}% (trần {room['ceiling']:,})"
            parts.append(part)
        lines.append("- USD: " + " · ".join(parts))
    if lines and s.get("links"):
        lines.append("- Độ nhạy 60 phiên (đã trừ nhịp chung thị trường): " + " · ".join(
            f"{r['ticker']} {r['w60']['beta']:+.2f}% khi {r['driver_label']} đổi 1%" for r in s["links"]))
    return lines


def prompt_block(lines: "list[str]") -> str:
    """Khối DỮ KIỆN cho prompt (tiêu đề + dòng + chỉ thị) — guard thay thân mục bằng đúng `lines`."""
    if not lines:
        return ""
    return "\n".join([f"\n{SECTION_TITLE}"] + lines + [
        "→ Mục 🪙 do HỆ THỐNG dựng từ dữ liệu: chỉ in tiêu đề mục, KHÔNG tự viết số vàng/dầu/USD. "
        "Muốn nhắc hàm ý ở mục khác thì chỉ dùng đúng số trong khối này."])


def main() -> int:
    lines = brief_lines()
    print("\n".join([SECTION_TITLE] + lines) if lines else "(không có dòng nào — tắt hoặc chuỗi đều cũ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

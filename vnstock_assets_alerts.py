#!/usr/bin/env python3
"""vnstock_assets_alerts.py — P5 đa tài sản: cảnh báo Telegram khi vàng · dầu · USD biến động mạnh (U86).

Chạy trong lượt MỖI GIỜ (`vnstock_assets.hourly`, sau lượt Python) — không gọi mạng ngoài Telegram,
chỉ đọc kho. Gửi qua KÊNH TIN (`TELEGRAM_NEWS_*`, cùng group cảnh báo tin mỗi giờ).

Luật (đổi so với PHIÊN TRƯỚC của chính chuỗi, chỉ chuỗi còn tươi):
- XAU ≥ 2% · Brent/WTI ≥ 3% · DXY ≥ 1% · SJC miếng ≥ 2% · VCB bán ≥ 0,5%;
- VCB bán còn ≤ 1% tới trần biên độ (mức), ≤ 0,5% là bậc 2.
Bậc = phần nguyên |Δ| / ngưỡng (1, 2, 3…): mỗi (chuỗi, NGÀY DỮ LIỆU, bậc) chỉ gửi MỘT lần ⇒ cú đi của
hôm qua không bị gửi lại sáng nay, còn cú đi lớn dần trong ngày thì báo thêm khi lên bậc. Sổ
`_meta/assets_alerts.json` (giữ 10 ngày). Không có gì vượt ngưỡng ⇒ im lặng.
Kill-switch: `VNSTOCK_ASSETS_ALERTS=0`. Thử: `python vnstock_assets_alerts.py --dry-run`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import vnstock_assets as va
import vnstock_assets_view as av

ENV_SWITCH = "VNSTOCK_ASSETS_ALERTS"
LEDGER_NAME = "assets_alerts.json"
KEEP_DAYS = 10

# (khoá, ngưỡng % đổi so phiên trước, nhãn, đơn vị in)
MOVE_RULES = (
    ("XAU", 2.0, "Vàng TG", "USD/oz"),
    ("BRENT", 3.0, "Dầu Brent (HĐTL tháng gần)", "USD/thùng"),
    ("WTI", 3.0, "Dầu WTI (HĐTL tháng gần)", "USD/thùng"),
    ("DXY", 1.0, "DXY", "điểm"),
    ("GOLD_SJC_BAR", 2.0, "SJC miếng (bán)", "đ/lượng"),
    ("USDVND_VCB", 0.5, "USD/VND Vietcombank (bán)", "đ"),
)
CEILING_ROOM_LEVELS = (1.0, 0.5)          # % còn tới trần: bậc 1, bậc 2


def enabled() -> bool:
    return (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in ("0", "false", "off", "no")


def _ddmm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def detect(today: "date | None" = None) -> "list[dict]":
    """Mọi tín hiệu đang vượt ngưỡng (chưa xét sổ đã gửi): [{id, text, …}]."""
    today = today or date.today()
    out = []
    for key, thr, label, unit in MOVE_RULES:
        c = av.card(key, today=today)
        if not c or c["stale"]:
            continue
        d1 = (c.get("chg") or {}).get("1 phiên")
        if d1 is None or abs(d1) < thr:
            continue
        level = int(abs(d1) // thr)
        val = av.fmt_value(c["value"], c["unit"])
        out.append({"id": f"{key}:{c['date']}:L{level}", "key": key, "level": level, "pct": d1,
                    "text": f"• {label} {val} {unit} {'▲' if d1 > 0 else '▼'} {d1:+.2f}% so phiên trước "
                            f"(dữ liệu {_ddmm(c['date'])}, ngưỡng {thr:g}%)"})
    room = va.usd_ceiling_room_pct()
    vcb = av.card("USDVND_VCB", today=today)
    if room and vcb and not vcb["stale"]:
        level = sum(1 for lim in CEILING_ROOM_LEVELS if room["pct"] <= lim)
        if level:
            out.append({"id": f"USD_CEILING:{vcb['date']}:L{level}", "key": "USD_CEILING", "level": level,
                        "pct": room["pct"],
                        "text": f"• VCB bán {room['vcb_sell']:,.0f} đ chỉ còn {room['pct']:.2f}% tới trần biên độ "
                                f"{room['ceiling']:,} (trung tâm {room['central']:,.0f} × 1,05)"})
    return out


def _ledger(meta=None) -> dict:
    with contextlib.suppress(Exception):
        return json.loads((Path(meta or va.META_DIR) / LEDGER_NAME).read_text(encoding="utf-8"))
    return {}


def _save(led: dict, now: datetime, meta=None) -> None:
    from vnstock_parquet_io import write_json_atomic
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    led["sent"] = {k: v for k, v in (led.get("sent") or {}).items() if v >= cutoff}
    write_json_atomic(led, Path(meta or va.META_DIR) / LEDGER_NAME)


def compose(items: "list[dict]", now: datetime) -> str:
    return "\n".join([f"🪙 Biến động mạnh — vàng · dầu · USD ({now:%H:%M %d/%m})"]
                     + [i["text"] for i in items]
                     + ["Nguồn: kho tài sản (Finhay/Yahoo/VCB/SJC) · chi tiết ở tab Hàng hoá & Tiền tệ trên dashboard."])


def _default_send(text: str) -> bool:
    """Kênh tin (TELEGRAM_NEWS_*, thiếu thì bot/chat mặc định); `send_message` gửi HTML (tự thử lại
    bằng chữ trơn khi 400) và NÉM lỗi khi thiếu token/chat hay Telegram từ chối."""
    import html
    import vnstock_telegram as tg
    resp = tg.send_message(html.escape(text, quote=False), channel="news")
    return bool((resp or {}).get("ok", True))


def run(now: "datetime | None" = None, *, send=None, dry_run: bool = False, meta=None) -> dict:
    """Một lượt: dò tín hiệu → bỏ cái đã gửi (cùng chuỗi, ngày dữ liệu, bậc ≤ đã gửi) → gửi gộp một tin."""
    if not enabled():
        return {"status": "disabled"}
    now = now or datetime.now()
    led = _ledger(meta)
    sent = led.get("sent") or {}
    fresh = []
    for it in detect(now.date()):
        base = it["id"].rsplit(":L", 1)[0]
        done = [int(k.rsplit(":L", 1)[1]) for k in sent if k.rsplit(":L", 1)[0] == base]
        if not done or it["level"] > max(done):
            fresh.append(it)
    if not fresh:
        return {"status": "quiet"}
    text = compose(fresh, now)
    if dry_run:
        return {"status": "dry-run", "text": text, "n": len(fresh)}
    try:
        ok = (send or _default_send)(text)
    except Exception as e:                                         # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "n": len(fresh)}
    if not ok:
        return {"status": "error", "error": "Telegram không nhận tin", "n": len(fresh)}
    at = now.isoformat(timespec="seconds")
    led["sent"] = {**sent, **{it["id"]: at for it in fresh}}
    led["last"] = {"at": at, "n": len(fresh), "ids": [it["id"] for it in fresh]}
    _save(led, now, meta)
    return {"status": "sent", "n": len(fresh), "ids": [it["id"] for it in fresh]}


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Cảnh báo biến động vàng · dầu · USD (P5, U86)")
    ap.add_argument("--dry-run", action="store_true", help="in tin sẽ gửi, không gửi, không ghi sổ")
    a = ap.parse_args(argv)
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    res = run(dry_run=a.dry_run)
    print(res.get("text") or res)
    return 0 if res.get("status") != "error" else 1


if __name__ == "__main__":
    sys.exit(main())

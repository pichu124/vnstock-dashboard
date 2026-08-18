"""Soi "giá có liên tục không" cho các mã guard đơn vị VỪA quy đổi — bằng SỐ.

Vì sao có file này (18/08): badge doctor "Quy đổi đơn vị giá (rollup)" tự sửa
xong rồi giao lại cho NGƯỜI một việc mắt: "soi chart các mã này xem giá có liên
tục không". Việc mắt thì không lặp lại được, không ghi sổ được, và người soi
phải nhớ ngưỡng nào là bất thường. Ở đây làm đúng doctrine của repo: đổi phán
đoán bằng mắt thành ngưỡng deterministic + test.

Hai câu hỏi công cụ trả lời, tách bạch vì CHỮA KHÁC NHAU:

1. **Chuỗi kho có vách đứt không** — hai bar liền nhau lệch quá biên độ sàn
   (±15%) cộng biên an toàn. Vách ~1000× (hoặc ~1/1000) là VẾT QUY ĐỔI SÓT;
   vách cỡ 2× là nghi CHIA TÁCH chưa back-adjust; vách khác là dữ liệu lỗi.
   → chữa ở kho: `python run.py fix-units` / soi nguồn sync.
2. **Kho có lệch giá LIVE không** — bar cuối của kho so với `_live/quote_*.json`.
   Lệch lớn KHÔNG phải lỗi đơn vị mà thường là KHO LỠ PHIÊN (mã kém thanh
   khoản, nguồn phủ mỏng) hoặc mã vừa có sự kiện quyền.
   → chữa ở sync/nguồn, không phải ở guard đơn vị.

Mặc định đọc đúng nguồn mà badge doctor đọc (`_meta/unit_normalizations.json`)
nên hai bên không bao giờ nói về hai tập mã khác nhau.

Dùng
----
    python scripts/check_unit_continuity.py                 # mã trong 7 ngày
    python scripts/check_unit_continuity.py --days 30       # nới cửa sổ
    python scripts/check_unit_continuity.py --ticker XPH    # chỉ định mã
    python scripts/check_unit_continuity.py --bars 20       # in nhiều bar hơn

Exit code: 0 sạch · 1 có mã cần soi tay · 2 không đọc được kho.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# Biên độ sàn VN rộng nhất là UPCOM ±15%; 30% cho biên an toàn (bar thiếu
# phiên, giá tham chiếu sau nghỉ lễ) — vượt ngưỡng này là chuyện phải giải
# thích được, không phải dao động thường ngày.
JUMP_PCT = 30.0
# Vách quanh 1000× là chữ ký của lệch đơn vị VND ↔ nghìn VND.
UNIT_LO, UNIT_HI = 500.0, 2000.0
# Chữ ký chia tách/thưởng: 2:1 hoặc 3:1 (±biên). CỐ Ý KHÔNG nới xuống 1.5×—
# thưởng tỉ lệ nhỏ trùng vùng dao động thường, đoán bừa nguyên nhân còn tệ
# hơn nói "không rõ" (ca 65% trong test là ví dụ).
SPLIT_LO, SPLIT_HI = 1.8, 3.3
# Kho vs live: một phiên trần/sàn rộng nhất là ±15% (UPCOM), cộng biên cho
# kho trễ một phiên → 1.3×. Quá mức đó là kho lỡ NHIỀU phiên, phải soi.
LIVE_TOLERANCE = 1.3


def _load_events(meta_dir: Path, days: int) -> list[dict]:
    path = meta_dir / "unit_normalizations.json"
    if not path.exists():
        return []
    try:
        events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except Exception:
        return []
    cutoff = datetime.now() - timedelta(days=days)
    fresh = []
    for ev in events:
        try:
            if datetime.fromisoformat(str(ev.get("at", ""))) >= cutoff:
                fresh.append(ev)
        except ValueError:
            fresh.append(ev)          # timestamp hỏng → soi thừa còn hơn bỏ sót
    return fresh


def load_bars(prices_dir: Path, ticker: str) -> pd.DataFrame:
    tdir = prices_dir / f"ticker={ticker.upper()}"
    if not tdir.exists():
        return pd.DataFrame()
    frames = []
    for pq_file in sorted(tdir.glob("year=*/*.parquet")):
        try:
            frames.append(pd.read_parquet(
                pq_file, columns=["time", "open", "high", "low", "close", "volume"]))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)


def find_jumps(df: pd.DataFrame, jump_pct: float = JUMP_PCT) -> list[dict]:
    """Vách đứt giữa hai bar liền nhau, kèm CHẨN ĐOÁN theo tỉ lệ."""
    if df.empty or "close" not in df.columns or len(df) < 2:
        return []
    close = pd.to_numeric(df["close"], errors="coerce")
    out = []
    for i in range(1, len(close)):
        prev, cur = close.iloc[i - 1], close.iloc[i]
        if not (prev > 0 and cur > 0):
            continue
        pct = (cur / prev - 1) * 100
        if abs(pct) < jump_pct:
            continue
        ratio = cur / prev
        inv = 1 / ratio
        if UNIT_LO <= ratio <= UNIT_HI or UNIT_LO <= inv <= UNIT_HI:
            why = "VẾT QUY ĐỔI SÓT (~1000× — VND lẫn nghìn VND)"
        elif SPLIT_LO <= ratio <= SPLIT_HI or SPLIT_LO <= inv <= SPLIT_HI:
            why = "nghi CHIA TÁCH/THƯỞNG chưa back-adjust (~2×)"
        else:
            why = "vượt biên độ sàn — dữ liệu lỗi hoặc thiếu phiên"
        out.append({"time": str(df['time'].iloc[i].date()),
                    "prev": float(prev), "cur": float(cur),
                    "pct": float(pct), "why": why})
    return out


def live_gap(live_dir: Path, ticker: str, last_close: float) -> dict | None:
    """So bar cuối của kho với giá live. None = không có quote để so."""
    path = live_dir / f"quote_{ticker.upper()}.json"
    if not path.exists() or last_close <= 0:
        return None
    try:
        price = float(json.loads(path.read_text(encoding="utf-8")).get("price", 0))
    except Exception:
        return None
    if price <= 0:
        return None
    # Kho ở NGHÌN VND, quote live ở VND — đưa về cùng đơn vị trước khi so.
    live_k = price / 1000 if price > 500 else price
    ratio = live_k / last_close
    return {"live_vnd": price, "live_k": live_k, "ratio": ratio,
            "ok": (1 / LIVE_TOLERANCE) <= ratio <= LIVE_TOLERANCE}


def check_ticker(ticker: str, prices_dir: Path, live_dir: Path,
                 n_bars: int, jump_pct: float) -> dict:
    df = load_bars(prices_dir, ticker)
    if df.empty:
        return {"ticker": ticker, "status": "no_data"}
    jumps = find_jumps(df, jump_pct)
    last_close = float(pd.to_numeric(df["close"], errors="coerce").iloc[-1])
    gap = live_gap(live_dir, ticker, last_close)
    return {
        "ticker": ticker,
        "status": "suspect" if (jumps or (gap and not gap["ok"])) else "clean",
        "bars": len(df),
        "last_time": str(df["time"].iloc[-1].date()),
        "last_close": last_close,
        "jumps": jumps,
        "live": gap,
        "tail": df.tail(n_bars),
    }


def render(res: dict, n_bars: int) -> None:
    tk = res["ticker"]
    if res["status"] == "no_data":
        print(f"\n⬜ {tk}: không có dữ liệu trong kho")
        return
    icon = "✅" if res["status"] == "clean" else "⚠️"
    print(f"\n{icon} {tk}: {res['bars']:,} bar · bar cuối {res['last_time']} "
          f"· close {res['last_close']:,.2f} nghìn VND")
    for j in res["jumps"]:
        print(f"   ⚠ {j['time']}: {j['prev']:,.2f} → {j['cur']:,.2f} "
              f"({j['pct']:+,.1f}%) — {j['why']}")
    if not res["jumps"]:
        print(f"   ↳ chuỗi LIÊN TỤC (không bar nào lệch > {JUMP_PCT:.0f}% so với bar trước)")
    gap = res["live"]
    if gap:
        if gap["ok"]:
            print(f"   ↳ khớp giá live {gap['live_vnd']:,.0f} VND "
                  f"(lệch {gap['ratio']:.2f}×)")
        else:
            print(f"   ⚠ live {gap['live_vnd']:,.0f} VND vs kho "
                  f"{res['last_close']:,.2f} nghìn — lệch {gap['ratio']:.2f}×. "
                  f"KHÔNG phải lỗi đơn vị: nghi kho lỡ phiên (mã kém thanh "
                  f"khoản) hoặc vừa có sự kiện quyền → soi nguồn sync.")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(res["tail"].to_string(index=False))


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warehouse", default="data_warehouse")
    ap.add_argument("--ticker", action="append", default=None,
                    help="chỉ định mã (lặp lại được); mặc định lấy từ vết quy đổi")
    ap.add_argument("--days", type=int, default=7,
                    help="cửa sổ vết quy đổi (mặc định 7 — giống doctor)")
    ap.add_argument("--bars", type=int, default=10, help="số bar cuối in ra")
    ap.add_argument("--jump-pct", type=float, default=JUMP_PCT)
    args = ap.parse_args(argv)

    wh = Path(args.warehouse)
    if not wh.is_absolute():
        wh = REPO_ROOT / wh
    prices_dir, meta_dir, live_dir = wh / "prices", wh / "_meta", wh / "_live"
    if not prices_dir.exists():
        print(f"[unit-continuity] ✗ không thấy kho giá tại {prices_dir}")
        return 2

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
        print(f"[unit-continuity] soi {len(tickers)} mã chỉ định")
    else:
        events = _load_events(meta_dir, args.days)
        tickers = list(dict.fromkeys(str(e.get("ticker", "")).upper()
                                     for e in events if e.get("ticker")))
        print(f"[unit-continuity] {len(events)} vết quy đổi trong {args.days} "
              f"ngày → {len(tickers)} mã: {', '.join(tickers) or '(không có)'}")
    if not tickers:
        print("[unit-continuity] ✅ không có mã nào cần soi")
        return 0

    results = [check_ticker(t, prices_dir, live_dir, args.bars, args.jump_pct)
               for t in tickers]
    for res in results:
        render(res, args.bars)

    suspect = [r["ticker"] for r in results if r["status"] == "suspect"]
    print()
    if suspect:
        print(f"[unit-continuity] ⚠️ {len(suspect)}/{len(results)} mã cần soi tay: "
              f"{', '.join(suspect)}")
        return 1
    print(f"[unit-continuity] ✅ {len(results)} mã đều liên tục — quy đổi ĐÚNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

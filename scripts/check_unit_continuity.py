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
# Hai bar cách quá số ngày này thì KHÔNG còn là hai phiên kề nhau (thứ Sáu →
# thứ Hai đã là 3 ngày; nghỉ lễ dài hơn). Mã kém thanh khoản có bar cách nhau
# hàng tháng — chấm biên độ sàn lên quãng đó là báo động giả.
MAX_ADJACENT_DAYS = 4
# Vách CŨ HƠN mọi lookback thực tế thì không quyết định nào chạm tới nó nữa:
# backtest dài nhất là tầng vị thế 730 ngày (vnstock_strategy.TIER_CONFIGS).
# Vẫn IN ra để đọc, nhưng KHÔNG tính là "cần soi tay" — nếu không, một vách
# năm 2006 làm mã bị gắn cờ ngang với vách tháng trước. Ca thật 19/08: 11/50
# mã bị gắn cờ, mà 10 trong đó là vết 2006-2025 của penny; mã DUY NHẤT đáng
# chữa (VVS, vách 2026-06-15, GTGD ~13 tỷ/phiên) chìm nghỉm giữa đám đó.
LOOKBACK_DAYS = 730
# Lệch CƠ SỞ điều chỉnh là một BẬC THANG GIỮ NGUYÊN — nguồn rebase cả chuỗi thì
# mức giá mới không quay lại mức cũ. Vách rồi ĐẢO CHIỀU về gần chỗ cũ trong vài
# phiên là dao động thật của mã kém thanh khoản (khớp lác đác, giá nhảy cóc).
# Ca XDH 19/08: 15.41 → 10.40 → 13.97, probe xác nhận kho khớp nguồn 1.0000×
# TỪNG BAR — tức công cụ đã hô "nghi KHO LỆCH CƠ SỞ" cho dữ liệu nguồn đúng.
REVERT_BARS = 5
REVERT_TOL = 0.12
# Ngày GDKHQ trong cache có thể lệch 1-2 phiên so với bar rơi giá (nguồn ghi
# ngày chốt quyền vs ngày giao dịch không hưởng quyền) → cửa sổ đối chiếu.
EVENT_WINDOW_DAYS = 3


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


def _is_equity(ticker: str) -> bool:
    """Chỉ CỔ PHIẾU mới chịu biên độ ±15% — dùng lại bộ lọc của anomaly.

    Bài học 18/08: lần quét toàn kho đầu tiên gắn cờ 1.902/3.125 mã, mà phần
    lớn là CHỨNG QUYỀN (CFPT2528…), TRÁI PHIẾU (CTG121030…), phái sinh
    (41I1G4000) và cả VNINDEX — những thứ KHÔNG có biên độ nên nhảy 30-50%
    một phiên là bình thường. Chấm chúng bằng thước cổ phiếu là báo động giả
    hàng loạt, đúng thứ làm người ta bỏ qua cả báo động thật.
    Import hỏng → tự lọc thô, thà sót còn hơn kêu oan 1.900 dòng.
    """
    try:
        import sys
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from vnstock_anomaly import _is_stock
        return bool(_is_stock(ticker))
    except Exception:
        import re as _re
        t = ticker.strip().upper()
        return bool(t) and t[0].isalpha() and not _re.match(r"^[A-Z]{2,6}\d{4,6}$", t)


def load_bars(prices_dir: Path, ticker: str,
              since_days: int = 0) -> pd.DataFrame:
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
    if since_days > 0:
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=since_days)
        df = df[df["time"] >= cutoff]
    return df.sort_values("time").reset_index(drop=True)


def find_jumps(df: pd.DataFrame, jump_pct: float = JUMP_PCT) -> list[dict]:
    """Vách đứt giữa hai bar liền nhau, kèm CHẨN ĐOÁN theo tỉ lệ VÀ khoảng cách.

    KHOẢNG CÁCH NGÀY là điều kiện thứ hai, thêm sau lần chạy thật đầu tiên
    (18/08, 50 mã): mã kém thanh khoản có bar cách nhau HÀNG THÁNG (VTS: 2026-03-10
    → 2026-08-07), nên "hai bar liền nhau" không có nghĩa "hai phiên liền nhau".
    Chấm biên độ sàn lên một quãng 5 tháng là báo động giả — 8/50 mã bị gắn cờ
    oan đúng kiểu đó. Nay chỉ KẾT TỘI khi hai bar thật sự kề phiên; cách xa thì
    ghi nhận để đọc chứ không tính là nghi vấn.

    Ngoại lệ: vách ~1000× luôn là nghi vấn bất kể cách nhau bao lâu — không
    quãng thời gian nào biến giá thành sai đơn vị.
    """
    if df.empty or "close" not in df.columns or len(df) < 2:
        return []
    close = pd.to_numeric(df["close"], errors="coerce")
    times = pd.to_datetime(df["time"])
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
        gap = int((times.iloc[i] - times.iloc[i - 1]).days)
        age_days = int((pd.Timestamp.now().normalize() - times.iloc[i]).days)
        is_unit = UNIT_LO <= ratio <= UNIT_HI or UNIT_LO <= inv <= UNIT_HI
        if is_unit:
            why, suspect = "VẾT QUY ĐỔI SÓT (~1000× — VND lẫn nghìn VND)", True
        elif gap > MAX_ADJACENT_DAYS:
            why = (f"cách {gap} ngày (mã nghỉ giao dịch) — biến động tích luỹ "
                   f"nhiều phiên, KHÔNG kết luận được")
            suspect = False
        elif SPLIT_LO <= ratio <= SPLIT_HI or SPLIT_LO <= inv <= SPLIT_HI:
            why, suspect = "nghi CHIA TÁCH/THƯỞNG chưa back-adjust (~2×)", True
        else:
            # Ca VVS (18/08) chốt bằng `probe_price_basis`: chữ ký này thường
            # KHÔNG phải "dữ liệu lỗi" mà là KHO LỆCH CƠ SỞ ĐIỀU CHỈNH —
            # nguồn rebase cả chuỗi sau sự kiện quyền, sync chỉ nối bar mới
            # lên lịch sử cũ (updater luôn fetch từ bar cuối). Trỏ thẳng sang
            # bước phân định thay vì bỏ lửng người đọc ở chữ "lỗi".
            why = ("kề phiên mà vượt biên độ sàn — nghi KHO LỆCH CƠ SỞ "
                   "điều chỉnh (nguồn rebase sau sự kiện quyền)")
            suspect = True
        # Vách có ĐẢO CHIỀU không? Soi CẢ HAI PHÍA vì chữ V có hai chân, và
        # chân thứ hai (cú hồi) tự nó cũng vượt ngưỡng: nhìn xuôi bắt được
        # chân đi xuống, nhìn ngược bắt được chân đi lên của cùng một cú.
        # NGOẠI LỆ ~1000×: không quãng thời gian hay cú hồi nào biến giá thành
        # sai đơn vị — giữ nguyên luật cũ, nếu không lưới này nuốt mất chính
        # ca mà công cụ sinh ra để bắt.
        reverted_in = 0
        if suspect and not is_unit:
            lo, hi = prev * (1 - REVERT_TOL), prev * (1 + REVERT_TOL)
            for k in range(i + 1, min(i + 1 + REVERT_BARS, len(close))):
                nxt = close.iloc[k]
                if nxt > 0 and lo <= nxt <= hi:
                    reverted_in = k - i
                    break
            if not reverted_in:
                blo, bhi = cur * (1 - REVERT_TOL), cur * (1 + REVERT_TOL)
                for k in range(i - 2, max(i - 2 - REVERT_BARS, -1), -1):
                    prv = close.iloc[k]
                    if prv > 0 and blo <= prv <= bhi:
                        reverted_in = i - k
                        break
        if reverted_in:
            why = (f"vách ĐẢO CHIỀU trong {reverted_in} phiên — dao động thật "
                   f"của mã kém thanh khoản, KHÔNG phải lệch cơ sở (lệch cơ sở "
                   f"thì bậc thang GIỮ NGUYÊN, giá không quay lại mức cũ)")
            suspect = False
        stale = suspect and age_days > LOOKBACK_DAYS
        if stale:
            why = (f"{why} · NGOÀI lookback {LOOKBACK_DAYS} ngày "
                   f"({age_days:,} ngày trước) — không quyết định nào chạm tới")
        out.append({"time": str(df['time'].iloc[i].date()),
                    "prev": float(prev), "cur": float(cur), "pct": float(pct),
                    "gap_days": gap, "age_days": age_days, "why": why,
                    "reverted_in": reverted_in,
                    "suspect": suspect and not stale, "stale_history": stale})
    return out


def match_corp_action(ticker: str, warehouse: Path, jump_date: str,
                      window_days: int = EVENT_WINDOW_DAYS) -> dict | None:
    """Vách này có trùng một SỰ KIỆN QUYỀN đã biết không?

    Thêm 18/08 sau ca VVS (kề phiên mà rơi 36.7% — bất khả với biên ±15%):
    biết "có vách" mới xong nửa việc, người đọc vẫn phải tự đi tra vì sao.
    Kho sự kiện đã có sẵn (`vnstock_adjust.load_events`, gộp 3 nguồn từ 14/08)
    nên tool tự đối chiếu được: trùng ngày GDKHQ ⇒ nguyên nhân là back-adjust
    chưa áp, chữa ở tầng điều chỉnh — KHÁC HẲN "dữ liệu lỗi" (chữa ở nguồn).
    Không có cache sự kiện → trả None, im lặng như `live_gap`.
    """
    try:
        import sys
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from vnstock_adjust import load_events
        ev = load_events(ticker, warehouse)
    except Exception:
        return None
    if ev is None or ev.empty or "ex_date" not in ev.columns:
        return None
    try:
        target = pd.to_datetime(jump_date).date()
        ex = pd.to_datetime(ev["ex_date"]).dt.date
        dist = ex.map(lambda d: abs((d - target).days))
        near = ev[dist <= window_days]
        if near.empty:
            return None
        row = near.iloc[int(dist[dist <= window_days].argmin())]
    except Exception:
        return None
    return {"ex_date": str(row.get("ex_date", "?")),
            "type": str(row.get("type", "?")),
            "ratio": row.get("ratio"),
            "cash_amount": row.get("cash_amount"),
            "raw": str(row.get("raw", ""))[:90]}


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
                 n_bars: int, jump_pct: float,
                 warehouse: "Path | None" = None,
                 since_days: int = 0) -> dict:
    df = load_bars(prices_dir, ticker, since_days)
    if df.empty:
        return {"ticker": ticker, "status": "no_data"}
    jumps = find_jumps(df, jump_pct)
    if warehouse is not None:
        for j in jumps:
            if not j["suspect"]:
                continue        # vách qua quãng nghỉ: không cần truy nguyên nhân
            ev = match_corp_action(ticker, warehouse, j["time"])
            if ev:
                j["event"] = ev
                j["why"] = (f"TRÙNG SỰ KIỆN QUYỀN ({ev['type']}, GDKHQ "
                            f"{ev['ex_date']}) → kho CHƯA back-adjust")
    last_close = float(pd.to_numeric(df["close"], errors="coerce").iloc[-1])
    gap = live_gap(live_dir, ticker, last_close)
    hot = [j for j in jumps if j["suspect"]]
    # GTGD TB 20 phiên (tỷ VND): kho ở NGHÌN VND, volume ở cổ phiếu →
    # close*1000*vol/1e9 = close*vol/1e6. Dùng để XẾP ƯU TIÊN: 149 mã nghi vấn
    # mà đa số là penny không ai giao dịch thì danh sách tên vô dụng — thứ cần
    # biết là mã nào đủ thanh khoản để lọt vào universe chiến lược.
    gtgd = 0.0
    try:
        tail = df.tail(20)
        gtgd = float((pd.to_numeric(tail["close"], errors="coerce")
                      * pd.to_numeric(tail["volume"], errors="coerce")
                      / 1e6).median())
    except Exception:
        gtgd = 0.0
    worst = max(hot, key=lambda j: abs(j["pct"]), default=None)
    return {
        "gtgd20": gtgd,
        "worst": worst,
        "ticker": ticker,
        "status": "suspect" if (hot or (gap and not gap["ok"])) else "clean",
        "bars": len(df),
        "last_time": str(df["time"].iloc[-1].date()),
        "last_close": last_close,
        "jumps": jumps,
        "live": gap,
        "tail": df.tail(n_bars),
    }


def render_compact(res: dict) -> None:
    """Một dòng/mã cho chế độ quét rộng — tên không kèm số thì không xếp được
    ưu tiên, mà 149 dòng chi tiết thì không ai đọc."""
    w = res.get("worst")
    tk = res["ticker"]
    gt = res.get("gtgd20") or 0.0
    if not w:
        print(f"⚠️ {tk:<10} · lệch giá live · GTGD20 ~{gt:,.2f} tỷ")
        return
    factor = w["prev"] / w["cur"] if w["cur"] else float("nan")
    print(f"⚠️ {tk:<10} · {w['time']} {w['prev']:,.2f}→{w['cur']:,.2f} "
          f"({factor:,.3f}×) · GTGD20 ~{gt:,.2f} tỷ"
          + ("  ← có sự kiện quyền" if w.get("event") else ""))


def render(res: dict, n_bars: int) -> None:
    tk = res["ticker"]
    if res["status"] == "no_data":
        print(f"\n⬜ {tk}: không có dữ liệu trong kho")
        return
    icon = "✅" if res["status"] == "clean" else "⚠️"
    print(f"\n{icon} {tk}: {res['bars']:,} bar · bar cuối {res['last_time']} "
          f"· close {res['last_close']:,.2f} nghìn VND")
    for j in res["jumps"]:
        print(f"   {'⚠' if j['suspect'] else 'ℹ'} {j['time']}: "
              f"{j['prev']:,.2f} → {j['cur']:,.2f} "
              f"({j['pct']:+,.1f}%) — {j['why']}")
        ev = j.get("event")
        if ev:
            _r = ev.get("ratio")
            _c = ev.get("cash_amount")
            print(f"      ↳ hệ số giá quan sát {j['prev'] / j['cur']:.3f}× "
                  + (f"· ratio sự kiện {float(_r):,.3f} "
                     if _r is not None and pd.notna(_r) else "")
                  + (f"· tiền mặt {float(_c):,.0f} " if _c is not None
                     and pd.notna(_c) else "")
                  + (f"· \"{ev['raw']}\"" if ev.get("raw") else ""))
    if not any(j["suspect"] for j in res["jumps"]):
        print(f"   ↳ không vách đứt đáng ngờ giữa hai phiên KỀ NHAU "
              f"(ngưỡng {JUMP_PCT:.0f}%)")
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
    ap.add_argument("--since", type=int, default=None, metavar="N",
                    help="chỉ soi N ngày gần nhất (0 = toàn lịch sử). Mặc định: "
                         "365 khi --all, 0 khi soi mã lẻ — lịch sử 20 năm có sẵn "
                         "nhiễu cũ, quét rộng mà không cắt cửa sổ thì tín hiệu "
                         "mới chìm nghỉm")
    ap.add_argument("--full", action="store_true",
                    help="in đầy đủ cả mã sạch (mặc định chỉ in mã cần soi) — "
                         "dùng khi đối chiếu sau lúc chữa")
    ap.add_argument("--all", action="store_true",
                    help="quét TOÀN KHO (chỉ in mã nghi vấn) — tìm mã lệch cơ "
                         "sở điều chỉnh sau ca VVS 18/08")
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

    since = args.since if args.since is not None else (365 if args.all else 0)
    if args.all:
        every = sorted(p.name.removeprefix("ticker=")
                       for p in prices_dir.glob("ticker=*") if p.is_dir())
        tickers = [t for t in every if _is_equity(t)]
        print(f"[unit-continuity] quét TOÀN KHO: {len(tickers):,} mã cổ phiếu "
              f"(bỏ {len(every) - len(tickers):,} CW/trái phiếu/phái sinh/chỉ số "
              f"— không có biên độ nên không chấm bằng thước cổ phiếu) · "
              f"{since} ngày gần nhất · chỉ in mã nghi vấn")
    elif args.ticker:
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

    results = [check_ticker(t, prices_dir, live_dir, args.bars, args.jump_pct,
                            warehouse=wh, since_days=since)
               for t in tickers]
    if args.all:
        hot = [r for r in results if r["status"] == "suspect"]
        hot.sort(key=lambda r: -(r.get("gtgd20") or 0.0))
        print(f"\n── {len(hot)} mã nghi vấn, xếp theo THANH KHOẢN giảm dần "
              f"(mã dưới cùng gần như không ảnh hưởng quyết định nào) ──")
        for res in hot:
            render_compact(res)
    else:
        # Mặc định: mã SẠCH gói vào một dòng, chỉ mã cần soi mới in đầy đủ.
        # Ca thật 19/08: 50 mã × (6 dòng chú thích + bảng 10 bar) = phải cuộn
        # qua ~600 dòng để tìm đúng 1 mã đáng đọc. Danh sách mà phải cuộn thì
        # người ta bỏ qua — cùng lý do đã hạ vách ngoài lookback xuống ℹ.
        # `--full` giữ hành vi cũ (dùng khi ĐỐI CHIẾU sau lúc chữa).
        clean = [r for r in results if r["status"] == "clean"]
        if clean and not args.full:
            print(f"\n✅ {len(clean)} mã liên tục, không cần đọc: "
                  f"{', '.join(r['ticker'] for r in clean)}")
        for res in results:
            if res["status"] == "clean" and not args.full:
                continue
            render(res, args.bars)

    suspect = [r["ticker"] for r in results if r["status"] == "suspect"]
    n_data = sum(1 for r in results if r["status"] != "no_data")
    print()
    if suspect:
        _head = ", ".join(suspect[:40])
        _more = f" … (+{len(suspect) - 40} mã)" if len(suspect) > 40 else ""
        print(f"[unit-continuity] ⚠️ {len(suspect)}/{n_data} mã cần soi tay: "
              f"{_head}{_more}")
        print("        Vách 'nghi KHO LỆCH CƠ SỞ' → phân định từng mã bằng:")
        print("        python scripts/probe_price_basis.py --ticker <MÃ> "
              "--break-date <ngày vách>")
        return 1
    print(f"[unit-continuity] ✅ {n_data} mã đều liên tục — quy đổi ĐÚNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Kiểm tính nhất quán điều chỉnh cổ tức của kho giá — mục 4d (chốt 13/08).

Vì sao tồn tại: tầng vị thế giữ lệnh 20-40 phiên đã chạy thật. Kho lấy giá
vnstock (THƯỜNG đã điều chỉnh) nhưng build tăng dần từng ngày — nếu nguồn
điều chỉnh hồi tố mà kho không refetch lịch sử, hoặc một đợt cổ tức không
được nguồn điều chỉnh, chuỗi giá SỤT một bậc đúng ngày GDKHQ. Backtest giữ
lệnh xuyên ngày đó thấy "lỗ" đúng bằng cổ tức — lỗ GIẢ (người giữ thật nhận
tiền/cổ phiếu về tài khoản). `vnstock_adjust` xác nhận: tầng back-adjust
CHƯA TỪNG được nối vào production, kho tin 100% vào nguồn.

Cách đo — mỗi sự kiện là một phép thử giữa hai giả thuyết trên gap qua đêm
tại ex-date (close hôm trước → open hôm GDKHQ):
  * H_adjusted: chuỗi đã điều chỉnh  → gap ≈ 0 (chỉ còn nhiễu thị trường)
  * H_raw:      chuỗi thô            → gap ≈ −drop kỳ vọng (cổ tức/giá)
Chọn giả thuyết GẦN quan sát hơn. Sự kiện chỉ được chấm khi drop kỳ vọng
đủ lớn so với nhiễu ngày thường; gap sâu hơn hẳn kỳ vọng (ngày sập sàn
trùng ex-date) cũng bị loại — "không kết luận được" là một kết quả hợp lệ,
KHÔNG được tính là đạt, cũng không được tính là hỏng.

Exit code: 0 = có bằng chứng chuỗi điều chỉnh, không gap thô nào ·
1 = CHƯA KẾT LUẬN ĐƯỢC (thiếu events cache / mẫu chấm được quá mỏng) ·
2 = BẮT ĐƯỢC gap thô — backtest giữ lệnh dài đang ăn lỗ giả, báo Claude.

CHẠY TRÊN MÁY THẬT (container CI không có kho giá):
    python vnstock_div_check.py                      # VN30 · 750 ngày
    python vnstock_div_check.py --tickers VCB,FPT --days 1000
    python vnstock_div_check.py --refresh            # fetch events thiếu (mạng)
    python vnstock_div_check.py --json               # in JSON thay bảng

Thiếu events cache hàng loạt → chạy `python run.py refresh-metadata --events`
(chậm, gọi API từng mã) rồi kiểm lại. Kết quả ghi
`data_warehouse/_meta/div_check.json` (nguyên tử) cho lần đọc sau.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

# Kho giá đã được pipeline chuẩn hoá về NGHÌN ĐỒNG (doctor "Quy đổi đơn vị
# giá" canh); cash_amount trong corp_actions là VND/cp. Đổi về cùng đơn vị
# tại một chỗ duy nhất này.
_PRICE_UNIT_VND = 1_000.0

# Sự kiện chỉ chấm được khi drop kỳ vọng ≥ max(sàn cứng, hệ số × nhiễu ngày
# thường) — cổ tức ~0.5% chìm nghỉm trong biên độ ±7%/phiên của HOSE.
_MIN_EXPECTED_DROP_PCT = 1.0
_NOISE_MULT = 2.0
# Gap sâu hơn (kỳ vọng + đệm nhiễu) coi như nhiễu thị trường trội (sập sàn
# trùng ex-date) — không dám kết luận thô hay điều chỉnh.
_CRASH_BUFFER_NOISE_MULT = 6.0
# Yield một đợt vượt mức này ở VN gần như chắc là sai đơn vị/tỷ lệ nguồn.
_MAX_PLAUSIBLE_YIELD_PCT = 40.0
# prev-bar → ex-bar cách quá số ngày lịch này = đứt chuỗi quanh sự kiện.
_MAX_CALENDAR_GAP_DAYS = 7
_MIN_BARS_FOR_NOISE = 30

VERDICT_ADJUSTED = "adjusted_ok"
VERDICT_RAW = "raw_gap"
VERDICT_UNSURE = "inconclusive"


# ─────────────────────────────────────────────────────────────────────────────
# Phần thuần — test được không cần kho
# ─────────────────────────────────────────────────────────────────────────────


def expected_drop_pct(event: dict, close_prev: float) -> "tuple[float | None, str]":
    """Drop giá kỳ vọng (%) tại ex-date cho một sự kiện corp-action.

    cash: cash_amount (VND/cp) trên giá đóng cửa hôm trước (nghìn đồng).
    split ratio r > 1  (10:1 → r=10): giá chia r        → drop (1 − 1/r).
    bonus/stock 0 < r ≤ 1 (thưởng 10% → r=0.1): giá × 1/(1+r) → drop r/(1+r).
    Trả (None, lý do) khi thiếu tham số — sự kiện thành "không kết luận được".
    """
    etype = str(event.get("type") or "").lower()
    cash = event.get("cash_amount")
    ratio = event.get("ratio")
    if etype == "cash":
        try:
            cash_f = float(cash)
        except (TypeError, ValueError):
            return None, "cash_amount thiếu/hỏng"
        if not cash_f > 0 or not close_prev > 0:
            return None, "cash_amount/giá không dương"
        return cash_f / _PRICE_UNIT_VND / close_prev * 100.0, ""
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return None, "ratio thiếu/hỏng"
    if r > 1:
        return (1.0 - 1.0 / r) * 100.0, ""
    if r > 0:
        return r / (1.0 + r) * 100.0, ""
    return None, "ratio không dương"


def _daily_noise_pct(close: "pd.Series") -> float:
    """Nhiễu ngày thường = median |%đổi/phiên| — thước để biết cổ tức có đủ
    lớn để nhìn thấy giữa dao động bình thường không."""
    rets = close.astype(float).pct_change().abs().dropna()
    return float(rets.median()) * 100.0 if len(rets) else 0.0


def classify_event(df: "pd.DataFrame", ex_date, expected_pct: float) -> dict:
    """Chấm MỘT sự kiện trên chuỗi giá kho: adjusted_ok / raw_gap / inconclusive.

    df cần cột time (datetime) + open/close, sort sẵn hay chưa đều được.
    Trả dict {verdict, observed_pct, expected_pct, reason}.
    """
    out = {"verdict": VERDICT_UNSURE, "observed_pct": None,
           "expected_pct": round(float(expected_pct), 2), "reason": ""}
    if df is None or df.empty or len(df) < _MIN_BARS_FOR_NOISE:
        out["reason"] = "chuỗi giá quá ngắn"
        return out

    d = df.sort_values("time")
    times = pd.to_datetime(d["time"])
    ex_ts = pd.Timestamp(ex_date)
    prev_mask = times < ex_ts
    post_mask = times >= ex_ts
    if not prev_mask.any() or not post_mask.any():
        out["reason"] = "thiếu bar quanh ex-date"
        return out
    prev = d[prev_mask].iloc[-1]
    ex = d[post_mask].iloc[0]
    if (pd.to_datetime(ex["time"]) - pd.to_datetime(prev["time"])).days \
            > _MAX_CALENDAR_GAP_DAYS:
        out["reason"] = "đứt chuỗi quanh ex-date"
        return out

    base = float(prev["close"])
    open_v = ex.get("open")
    ref = (float(open_v) if open_v is not None and pd.notna(open_v)
           and float(open_v) > 0 else float(ex["close"]))    # open hỏng → close
    if not base > 0 or not ref > 0:
        out["reason"] = "giá không dương quanh ex-date"
        return out
    observed = (ref / base - 1.0) * 100.0
    out["observed_pct"] = round(observed, 2)

    noise = _daily_noise_pct(d["close"])
    floor = max(_MIN_EXPECTED_DROP_PCT, _NOISE_MULT * noise)
    if expected_pct < floor:
        out["reason"] = (f"cổ tức nhỏ chìm trong nhiễu "
                         f"(kỳ vọng {expected_pct:.2f}% < sàn {floor:.2f}%)")
        return out
    if expected_pct > _MAX_PLAUSIBLE_YIELD_PCT:
        out["reason"] = (f"yield {expected_pct:.1f}% bất thường — "
                         f"nghi sai đơn vị/tỷ lệ nguồn")
        return out
    if observed < -(expected_pct + _CRASH_BUFFER_NOISE_MULT * noise):
        out["reason"] = "gap sâu hơn hẳn cổ tức — nhiễu thị trường trội"
        return out

    d_adjusted = abs(observed)
    d_raw = abs(observed + expected_pct)
    if d_raw < d_adjusted and observed < 0:
        out["verdict"] = VERDICT_RAW
        out["reason"] = "gap khớp kịch bản chuỗi THÔ (chưa điều chỉnh)"
    elif d_adjusted < d_raw:
        out["verdict"] = VERDICT_ADJUSTED
        out["reason"] = "gap khớp kịch bản đã điều chỉnh"
    else:
        out["reason"] = "nằm giữa hai kịch bản — không dám kết luận"
    return out


def grade_report(per_ticker: "list[dict]") -> dict:
    """Gộp kết quả các mã thành verdict cuối + exit code.

    Luật (họ bug quen "không đo được ≠ đạt"):
      * ≥1 raw_gap        → exit 2 (backtest dài hạn đang ăn lỗ giả)
      * 0 adjusted_ok chấm được (toàn inconclusive / thiếu events) → exit 1
      * còn lại           → exit 0
    """
    flagged, ok_events = [], []
    n_unsure = 0
    no_events = [t["ticker"] for t in per_ticker if not t["events"]]
    for t in per_ticker:
        for ev in t["events"]:
            if ev["verdict"] == VERDICT_RAW:
                flagged.append(ev)
            elif ev["verdict"] == VERDICT_ADJUSTED:
                ok_events.append(ev)
            else:
                n_unsure += 1
    if flagged:
        code = 2
    elif not ok_events:
        code = 1
    else:
        code = 0
    return {"exit_code": code, "flagged": flagged, "n_adjusted": len(ok_events),
            "n_inconclusive": n_unsure, "tickers_no_events": no_events,
            "n_tickers": len(per_ticker)}


# ─────────────────────────────────────────────────────────────────────────────
# Phần chạy thật — cần kho giá + cache corp_actions
# ─────────────────────────────────────────────────────────────────────────────


def check_ticker(ticker: str, days: int = 750) -> dict:
    """Chấm mọi sự kiện của một mã trong cửa sổ `days` gần nhất."""
    from vnstock_adjust import load_events
    from vnstock_strategy import _load_history

    hist = _load_history(ticker, days=days)
    events = load_events(ticker)
    out = {"ticker": ticker.upper(), "events": [], "has_cache": not events.empty,
           "has_prices": hist is not None and not hist.empty}
    if not out["has_cache"] or not out["has_prices"]:
        return out

    # Sort MỘT lần ở đây: close_prev bên dưới lấy "bar cuối trước ex-date"
    # bằng vị trí index — kho chưa chắc trả chuỗi đã sort.
    hist = hist.sort_values("time").reset_index(drop=True)
    times = pd.to_datetime(hist["time"])
    lo, hi = times.min(), times.max()
    for _, row in events.iterrows():
        ex = pd.Timestamp(row["ex_date"])
        if not (lo < ex <= hi):
            continue                       # sự kiện ngoài cửa sổ giá đang có
        prev_mask = times < ex
        if not prev_mask.any():
            continue
        close_prev = float(hist.loc[prev_mask[prev_mask].index[-1], "close"])
        exp, why = expected_drop_pct(row.to_dict(), close_prev)
        if exp is None:
            out["events"].append({
                "ticker": out["ticker"], "ex_date": str(row["ex_date"]),
                "type": row.get("type"), "verdict": VERDICT_UNSURE,
                "observed_pct": None, "expected_pct": None, "reason": why})
            continue
        res = classify_event(hist, ex, exp)
        out["events"].append({
            "ticker": out["ticker"], "ex_date": str(row["ex_date"]),
            "type": row.get("type"), **res})
    return out


def run_check(tickers: "list[str]", days: int = 750,
              refresh: bool = False) -> dict:
    """Chạy checker trên một rổ mã; trả report đầy đủ (kèm exit_code)."""
    if refresh:
        from vnstock_adjust import load_events, refresh_events
        for tk in tickers:
            try:
                if load_events(tk).empty:
                    refresh_events(tk)
            except Exception:
                continue                    # best-effort — thiếu thì báo ở dưới
    per_ticker = [check_ticker(tk, days=days) for tk in tickers]
    report = grade_report(per_ticker)
    report["days"] = days
    report["per_ticker"] = per_ticker
    return report


def _print_report(report: dict, verbose: bool = False) -> None:
    print("🧾 Kiểm điều chỉnh cổ tức kho giá — "
          f"{report['n_tickers']} mã · {report['days']} ngày")
    print("=" * 64)
    for t in report["per_ticker"]:
        if not t["has_prices"]:
            print(f"  ⬜ {t['ticker']:<5} không có kho giá")
            continue
        if not t["has_cache"]:
            print(f"  ⬜ {t['ticker']:<5} thiếu events cache")
            continue
        n_adj = sum(e["verdict"] == VERDICT_ADJUSTED for e in t["events"])
        n_raw = sum(e["verdict"] == VERDICT_RAW for e in t["events"])
        n_un = sum(e["verdict"] == VERDICT_UNSURE for e in t["events"])
        icon = "❌" if n_raw else ("✅" if n_adj else "⚠️")
        print(f"  {icon} {t['ticker']:<5} {len(t['events'])} sự kiện trong cửa sổ: "
              f"{n_adj} điều chỉnh · {n_raw} GAP THÔ · {n_un} chưa kết luận")
        for ev in t["events"]:
            if ev["verdict"] == VERDICT_RAW:
                print(f"       ↳ ❌ {ev['ex_date']} [{ev['type']}] kỳ vọng "
                      f"−{ev['expected_pct']:.2f}% — quan sát "
                      f"{ev['observed_pct']:+.2f}% → {ev['reason']}")
            elif verbose and ev["verdict"] == VERDICT_UNSURE:
                exp = (f"−{ev['expected_pct']:.2f}%"
                       if ev.get("expected_pct") is not None else "?")
                obs = (f"{ev['observed_pct']:+.2f}%"
                       if ev.get("observed_pct") is not None else "?")
                print(f"       ↳ ⚠️ {ev['ex_date']} [{ev['type']}] kỳ vọng "
                      f"{exp} — quan sát {obs} → {ev['reason']}")

    print("-" * 64)
    print(f"Tổng: {report['n_adjusted']} sự kiện khớp ĐÃ điều chỉnh · "
          f"{len(report['flagged'])} GAP THÔ · "
          f"{report['n_inconclusive']} chưa kết luận")
    no_prices = [t["ticker"] for t in report["per_ticker"] if not t["has_prices"]]
    no_cache = [t["ticker"] for t in report["per_ticker"]
                if t["has_prices"] and not t["has_cache"]]
    for label, names, hint in (
        ("không có kho giá", no_prices, "chạy trên máy có data_warehouse"),
        ("thiếu events cache", no_cache,
         "chạy `python run.py refresh-metadata --events` hoặc thêm --refresh"),
    ):
        if names:
            shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
            print(f"⬜ {len(names)} mã {label} ({shown}) — {hint}")

    code = report["exit_code"]
    if code == 0:
        print("\n✅ KHÔNG thấy gap thô nào — chuỗi giá nhất quán điều chỉnh "
              "trong phạm vi chấm được; backtest giữ lệnh dài dùng được.")
    elif code == 1:
        print("\n⚠️ CHƯA KẾT LUẬN ĐƯỢC — không có sự kiện nào chấm được "
              "(thiếu events cache hoặc cổ tức đều quá nhỏ). Bù cache rồi "
              "chạy lại; đây KHÔNG phải bằng chứng kho sạch.")
    else:
        print("\n❌ CÓ GAP THÔ — backtest giữ lệnh dài đang ăn lỗ giả tại các "
              "sự kiện trên. Dán NGUYÊN output này cho Claude.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tickers", default="",
                    help="mặc định VN30; truyền 'VCB,FPT,…' để kiểm bộ khác")
    ap.add_argument("--days", type=int, default=750,
                    help="cửa sổ giá gần nhất (mặc định 750 ≈ lookback tầng vị thế)")
    ap.add_argument("--refresh", action="store_true",
                    help="fetch events cho mã thiếu cache (gọi API, cần mạng)")
    ap.add_argument("--json", action="store_true", help="in JSON thay bảng")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="in cả lý do của sự kiện 'chưa kết luận' (soi VIC…)")
    args = ap.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        from vnstock_brief_canon import VN30_TICKERS
        tickers = sorted(VN30_TICKERS)

    report = run_check(tickers, days=args.days, refresh=args.refresh)

    if args.json:
        slim = {k: v for k, v in report.items() if k != "per_ticker"}
        print(json.dumps(slim, ensure_ascii=False, indent=2))
    else:
        _print_report(report, verbose=args.verbose)

    try:
        from datetime import datetime
        from vnstock_parquet_io import write_json_atomic
        write_json_atomic(
            {"generated_at": datetime.now().isoformat(timespec="seconds"),
             **{k: v for k, v in report.items() if k != "per_ticker"}},
            "data_warehouse/_meta/div_check.json")
    except Exception:
        pass                                # best-effort — report đã in ra rồi
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

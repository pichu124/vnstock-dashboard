"""Đo TẦM VỚI của chốt lời theo horizon — chọn tham số bằng số đo, không đoán.

Vì sao tồn tại (13/08): chiến lược auto-train đặt TP 2.5–4×ATR với horizon
5 phiên → **0/49 khuyến nghị live chạm chốt lời** (14 dính SL, 35 hết hạn).
Giả thuyết: trong 5 phiên giá không đi nổi 2.5×ATR theo MỘT chiều, còn SL
1.5–2.5×ATR thì nằm gọn trong nhiễu. Module này biến giả thuyết thành SỐ:

Với mỗi ngày vào lệnh giả định, đo trong N phiên kế tiếp:
* **MFE** (max favorable excursion) — mức lãi TỐI ĐA giá từng cho, theo % và
  theo bội ATR14 tại ngày vào (so thẳng được với `tp_atr_mult`);
* **MAE** — mức lỗ sâu nhất phải chịu (so với `sl_atr_mult`).

Đầu ra trả lời ba câu hỏi cấu hình:
1. TP hiện tại (2.5–4×ATR) với tới được BAO NHIÊU % số lần, ở từng horizon?
2. Muốn TP với tới ~60% số lần thì đặt ở đâu (p60 của MFE)?
3. Tầng "vị thế" mới nên lấy horizon nào (20 hay 40 phiên)?

CHẠY TRÊN MÁY THẬT (container CI không có kho giá):
    python vnstock_reachability.py                     # VN30, 500 phiên
    python vnstock_reachability.py --horizons 5,20,40 --days 750

Kết quả in bảng + ghi `data_warehouse/_meta/reachability.json` (nguyên tử) để
lần cấu hình tầng dài hạn đọc lại được.

Lưu ý đã biết: kho giá CHƯA được kiểm tính nhất quán điều chỉnh cổ tức qua
các đợt ex-div (mục chờ trong CLAUDE-NOTES) — gap cổ tức chưa điều chỉnh làm
MAE âm sâu giả ở một ít mẫu; percentile chịu được nhiễu lẻ nhưng đọc p90 MAE
thì nhớ điều này.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

DEFAULT_HORIZONS = (5, 10, 20, 40)
_ATR_N = 14
# Bước nhảy giữa các ngày vào lệnh giả định — mẫu sát nhau chồng lấn gần như
# hoàn toàn (cùng một cú sóng đếm nhiều lần); 3 phiên là đủ thưa cho chẩn đoán.
_STRIDE = 3
# Các mốc bội ATR để báo "với tới được bao nhiêu % số lần" — 2.5 và 4.0 đúng
# biên dải `tp_atr_mult` mà prompt sinh chiến lược đang hướng dẫn.
_TP_MULTIPLES = (1.5, 2.5, 4.0)


def _atr(df: pd.DataFrame, n: int = _ATR_N) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def measure_ticker(df: pd.DataFrame, horizons=DEFAULT_HORIZONS,
                   stride: int = _STRIDE) -> dict:
    """MFE/MAE của MỘT mã. Trả {horizon: {"mfe_pct": [...], "mae_pct": [...],
    "mfe_atr": [...]}}; mã quá ngắn trả list rỗng (bỏ qua, không ném)."""
    out = {int(h): {"mfe_pct": [], "mae_pct": [], "mfe_atr": []} for h in horizons}
    if df is None or df.empty or len(df) < _ATR_N + max(horizons) + 2:
        return out
    atr = _atr(df).to_numpy()
    c = df["close"].astype(float).to_numpy()
    hi = df["high"].astype(float).to_numpy()
    lo = df["low"].astype(float).to_numpy()
    last_entry = len(df) - max(horizons) - 1
    for i in range(_ATR_N, last_entry, stride):
        entry, a = c[i], atr[i]
        if not (entry > 0) or not (a > 0):
            continue
        for n in horizons:
            win_hi = hi[i + 1:i + 1 + n]
            win_lo = lo[i + 1:i + 1 + n]
            mfe_abs = float(win_hi.max()) - entry
            out[int(n)]["mfe_pct"].append(mfe_abs / entry * 100)
            out[int(n)]["mae_pct"].append((float(win_lo.min()) - entry) / entry * 100)
            out[int(n)]["mfe_atr"].append(mfe_abs / a)
    return out


def merge_measures(per_ticker: "list[dict]") -> dict:
    """Gộp mẫu của nhiều mã về một bảng chung theo horizon."""
    merged: dict = {}
    for m in per_ticker:
        for h, cols in m.items():
            slot = merged.setdefault(int(h), {"mfe_pct": [], "mae_pct": [], "mfe_atr": []})
            for k in slot:
                slot[k].extend(cols.get(k, []))
    return merged


def summarize(merged: dict) -> dict:
    """Percentile + tỷ lệ với-tới theo mốc ATR, cho từng horizon.

    Trả {} khi không có mẫu — không đo được thì nói không đo được, tuyệt đối
    không trả bảng số 0 trông như "đo ra thị trường đứng yên".
    """
    out: dict = {}
    for h in sorted(merged):
        mfe = np.asarray(merged[h]["mfe_pct"], dtype=float)
        mae = np.asarray(merged[h]["mae_pct"], dtype=float)
        mfa = np.asarray(merged[h]["mfe_atr"], dtype=float)
        if mfe.size == 0:
            continue
        out[str(h)] = {
            "n_samples": int(mfe.size),
            "mfe_pct": {p: round(float(np.percentile(mfe, q)), 2)
                        for p, q in (("p50", 50), ("p60", 60), ("p75", 75), ("p90", 90))},
            "mae_pct_p50": round(float(np.percentile(mae, 50)), 2),
            "mfe_atr": {p: round(float(np.percentile(mfa, q)), 2)
                        for p, q in (("p50", 50), ("p60", 60), ("p75", 75))},
            # "TP đặt ở k×ATR thì với tới bao nhiêu % số lần?"
            "tp_reach_share": {str(k): round(float((mfa >= k).mean()), 3)
                               for k in _TP_MULTIPLES},
        }
    return out


def _load_universe(tickers: "list[str]", days: int) -> "list[pd.DataFrame]":
    from vnstock_strategy import _load_history
    out = []
    for tk in tickers:
        try:
            hist = _load_history(tk, days=days)
            if hist is not None and not hist.empty:
                out.append(hist)
        except Exception:
            continue                    # mã thiếu kho — bỏ qua, đo phần còn lại
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=500)
    ap.add_argument("--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS))
    ap.add_argument("--tickers", default="",
                    help="mặc định VN30; truyền 'VCB,FPT,…' để đo bộ khác")
    args = ap.parse_args()

    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        from vnstock_brief_canon import VN30_TICKERS
        tickers = sorted(VN30_TICKERS)

    frames = _load_universe(tickers, days=args.days + max(horizons) + 40)
    if not frames:
        print("⚠️ Không đọc được kho giá — chạy trên máy có data_warehouse.")
        return 2

    summary = summarize(merge_measures(
        [measure_ticker(f, horizons) for f in frames]))
    if not summary:
        print("⚠️ Kho có mã nhưng chuỗi quá ngắn cho horizon yêu cầu.")
        return 2

    print(f"Đo trên {len(frames)}/{len(tickers)} mã · {args.days} phiên gần nhất\n")
    print(f"{'Horizon':>8} {'n':>7} {'MFE p50':>9} {'MFE p60':>9} {'MFE p75':>9} "
          f"{'MAE p50':>9} {'MFE p60 (×ATR)':>15}  với tới TP 2.5×ATR")
    for h, s in summary.items():
        print(f"{h:>7}d {s['n_samples']:>7,} {s['mfe_pct']['p50']:>8.1f}% "
              f"{s['mfe_pct']['p60']:>8.1f}% {s['mfe_pct']['p75']:>8.1f}% "
              f"{s['mae_pct_p50']:>8.1f}% {s['mfe_atr']['p60']:>14.2f}  "
              f"{s['tp_reach_share']['2.5']:>6.0%}")
    print("\nĐọc kết quả: `tp_atr_mult` hiện 2.5–4.0 — horizon nào cột cuối"
          " dưới ~40% thì TP ở horizon đó phần lớn KHÔNG với tới.")

    from datetime import datetime
    from vnstock_parquet_io import write_json_atomic
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "days": args.days, "tickers_measured": len(frames),
               "horizons": list(horizons), "summary": summary}
    write_json_atomic(payload, "data_warehouse/_meta/reachability.json")
    print("→ đã ghi data_warehouse/_meta/reachability.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

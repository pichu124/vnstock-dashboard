"""Thẻ kỹ thuật 3 khung — BẢN MẪU để duyệt (PTKT P2a, `vnstock_ta_card`).

Chỉ ĐỌC kho giá (`data_warehouse/prices`), không gọi mạng/LLM, không ghi gì. Kho đồng bộ qua
Dropbox ⇒ ○ máy nào cũng được (tránh khung pipeline 18:00 → `⏱ TỔNG`):

    python scripts/sample_ta_card.py                    # phiên cuối trong kho
    python scripts/sample_ta_card.py --date 2026-10-30  # cắt kho tới phiên đó (không nhìn trước)
    python scripts/sample_ta_card.py --top 15           # số mã VN30 thanh khoản lớn nhất

In thẻ VN-Index nhiều dòng + một dòng nén cho từng mã VN30 (rổ hằng số canon) có GTGD TB20 lớn
nhất. S/R ở bản mẫu là TẠM: pivot 60 phiên hiện hành của brief (`_select_sr_levels`), dựng trên
bar TỚI PHIÊN TRƯỚC (đúng mức brief hôm trước đã công bố). P2b (§17) đo: không cách nào hơn giá ± ATR ⇒ giữ pivot60 làm mốc tham chiếu (§18).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import vnstock_ta_card as tc  # noqa: E402  (sau sys.path)

HISTORY_DAYS = 800            # đủ SMA200 + 52 tuần + MA40 tuần
SR_WINDOW, SR_SKIP, SR_MIN_BARS = 60, 2, 12   # như `vnstock_brief.ticker_sr_levels`


def prior_sr(daily: pd.DataFrame) -> dict | None:
    """S1/S2/R1/R2 pivot 60 phiên tính trên bar TỚI PHIÊN TRƯỚC phiên đánh giá."""
    import vnstock_brief as vb
    prev = daily.iloc[:-1]
    if len(prev) < SR_MIN_BARS:
        return None
    last = float(prev["close"].iloc[-1])
    win = prev.iloc[-(SR_WINDOW + SR_SKIP):-SR_SKIP]
    above = sorted({round(float(v), 2) for v in win["high"] if v > last})
    below = sorted({round(float(v), 2) for v in win["low"] if v < last}, reverse=True)
    res, sup = vb._select_sr_levels(above, last), vb._select_sr_levels(below, last)
    keys = (("support_1", sup, 0), ("support_2", sup, 1),
            ("resistance_1", res, 0), ("resistance_2", res, 1))
    sr = {k: (lv[i] if len(lv) > i else None) for k, lv, i in keys}
    return sr if any(v is not None for v in sr.values()) else None


def _cut(df: pd.DataFrame, until: date | None) -> pd.DataFrame:
    if df is None or df.empty or "time" not in df.columns:
        return pd.DataFrame()
    df = df.assign(time=pd.to_datetime(df["time"]))
    if until is not None:
        df = df[df["time"].dt.date <= until]
    return df.reset_index(drop=True)


def _gtgd20(df: pd.DataFrame) -> float:
    if df.empty or "volume" not in df.columns:
        return 0.0
    tail = df.tail(20)
    return float((tail["close"] * tail["volume"]).mean())


def build(prices: Path, until: date | None, top: int) -> list[str]:
    import vnstock_brief as vb
    from vnstock_brief_canon import VN30_TICKERS
    from vnstock_strategy import _load_history_from_parquet

    days = HISTORY_DAYS + ((date.today() - until).days if until else 0)
    saved, vb._VNINDEX_PRICES_DIR = vb._VNINDEX_PRICES_DIR, prices
    try:
        idx = _cut(vb._load_vnindex_df(augment=False), until)
    finally:
        vb._VNINDEX_PRICES_DIR = saved
    idx_card = tc.ta_card(idx, sr=prior_sr(idx) if len(idx) else None, label="VN-Index")
    out = tc.card_lines(idx_card)
    tickers = {tk: _cut(_load_history_from_parquet(tk, days, prices_dir=prices), until)
               for tk in sorted(VN30_TICKERS)}
    ranked = sorted((tk for tk, df in tickers.items() if not df.empty),
                    key=lambda tk: -_gtgd20(tickers[tk]))[:top]
    out += ["", f"Từng mã (VN30, {len(ranked)} mã GTGD TB20 lớn nhất):"]
    for tk in ranked:
        df = tickers[tk]
        card = tc.ta_card(df, sr=prior_sr(df), label=tk)
        out.append(f"- {tc.card_line(card, market_as_of=idx_card['as_of'])}")
    missing = sorted(tk for tk, df in tickers.items() if df.empty)
    if missing:
        out.append(f"(không có dữ liệu trong kho: {', '.join(missing)})")
    out += ["", "S/R = pivot 60 phiên tính tới phiên trước — MỐC THAM CHIẾU, không phải lợi thế (đo §17: không cách nào hơn giá ± ATR)."]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="phiên đánh giá YYYY-MM-DD (mặc định: phiên cuối trong kho)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--prices", type=Path, default=_REPO / "data_warehouse" / "prices")
    args = ap.parse_args(argv)
    print("\n".join(build(args.prices, args.date, args.top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

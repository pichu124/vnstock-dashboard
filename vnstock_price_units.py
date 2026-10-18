"""Chuẩn hoá ĐƠN VỊ GIÁ — nguồn của vnstock trộn hai đơn vị trong cùng một kho.

Tách khỏi `vnstock_dashboard.py` (12/08) vì hai lý do:

1. Đây là logic thuần pandas/số học, nhưng nằm sau `st.set_page_config()` nên
   test không import nổi → suốt thời gian dài chỉ có REPLICA trong
   `tests/test_dashboard.py` (bản chép tay, trôi lúc nào không hay).
2. Nó là **bất biến dữ liệu** của cả pipeline, không riêng UI: `vnstock_brief`
   cũng nhắc tới ngưỡng >500 (dòng ~1820) như "cùng quy ước".

Bối cảnh: vnstock (free VCI) trả giá ở NGHÌN VND (FPT = 77.7), còn
vnstock_data (sponsor) trả giá ở VND (FPT = 77700). Kho + bars parquet vì thế
pha trộn cả hai — thậm chí trong CÙNG 1 row (open=77.8 nghìn, close=77700 VND).

Không đụng tới Streamlit ở đây: cache (`@st.cache_data`) là chuyện của lớp UI.
"""
from __future__ import annotations

import pandas as pd

# Ô OHLC > 500 là ỨNG VIÊN đơn vị VND. Tiền đề cũ "không mã nào > 500 nghìn" đã SAI
# (18/10: HLB 660, VNZ 579 nghìn — chia 1000 từng ô làm HLB 20D −99,85%), nên ô chỉ bị
# chia khi CÒN lệch ~1000 lần so với trung vị các ô ≤ 500 của CHÍNH chuỗi đó.
PRICE_UNIT_THRESHOLD = 500.0

# Giá live so với close historical: lệch ~1000 lần thì hai bên khác đơn vị.
# Dùng biên rộng (100x / 0.01x) để trần/sàn ±7% hay gap không bao giờ chạm.
_LIVE_RATIO_HIGH = 100.0
_LIVE_RATIO_LOW = 0.01

_OHLC_COLUMNS = ("open", "high", "low", "close")


def normalize_price_units(df: pd.DataFrame) -> pd.DataFrame:
    """Đưa mọi cột OHLC của MỘT mã về nghìn VND. Trả DataFrame MỚI, không sửa bản gốc.

    Chuẩn hoá theo TỪNG Ô chứ không theo cột: một row có thể trộn hai đơn vị. Ô > 500 chỉ bị
    chia 1000 khi gấp ≥ 100 lần trung vị các ô ≤ 500 (mốc nghìn VND của chính chuỗi) — giá
    thật trên 500 nghìn (HLB, VNZ) và mã penny lưu VND quanh 500 giữ nguyên một thang.
    """
    if df.empty:
        return df

    df = df.copy()
    cols = [c for c in _OHLC_COLUMNS if c in df.columns]
    if not cols:
        return df
    vals = df[cols].astype(float)
    small = vals[(vals > 0) & (vals <= PRICE_UNIT_THRESHOLD)].stack()
    # ponytail: chuỗi KHÔNG có ô nào ≤ 500 thì không có mốc ⇒ giữ luật cũ (chia hết), vì
    # mơ hồ giữa penny VND 500–999đ và giá nghìn > 500. Chỗ gọi nên đưa chuỗi DÀI (cả năm)
    # vào trước khi cắt cửa sổ — VNZ có 30 phiên cuối đều > 500.
    ref = float(small.median()) if len(small) else None
    for col in cols:
        v = vals[col]
        mask = v > PRICE_UNIT_THRESHOLD
        if ref is not None:
            mask &= v >= ref * _LIVE_RATIO_HIGH
        if mask.any():
            df.loc[mask, col] = v[mask] / 1000

    return df


def normalize_live_price(historical_last_close: float, live_price: float) -> float:
    """Chuẩn hoá giá live cho khớp scale của chart historical.

    vnstock thường trả intraday dạng nghìn (25.55 = 25,550đ) trong khi
    `Market.price_board()` trả giá VND thật (25550). Merge thẳng sẽ phá scale
    chart (triệu chứng "chart 1D trắng bóc").

    Giá trị <= 0 (không đo được / thiếu data) được trả NGUYÊN — không suy đoán
    đơn vị từ số vô nghĩa.
    """
    if historical_last_close <= 0 or live_price <= 0:
        return live_price
    ratio = live_price / historical_last_close
    if ratio > _LIVE_RATIO_HIGH:
        # Live cao gấp ~1000x → historical đang ở dạng nghìn
        return live_price / 1000.0
    if ratio < _LIVE_RATIO_LOW:
        # Live thấp hơn ~1000x → historical đang ở VND
        return live_price * 1000.0
    return live_price

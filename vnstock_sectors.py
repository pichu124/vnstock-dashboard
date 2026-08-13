"""Canonical sector taxonomy — dùng chung dashboard, brief và screener.

Hai tầng, độc lập nhau:

* **Nhóm ngành chuẩn** (`SECTOR_GROUPS`): gom 31 ngành gốc của nguồn dữ liệu
  về 15 nhóm hiển thị, tra bằng TÊN NGÀNH.
* **Nhóm tuỳ biến** (`_CUSTOM_GROUPS`): "Họ VIN", "Họ M"… tra bằng MÃ, được
  kiểm TRƯỚC nhóm ngành chuẩn ở những tab có bật.

Pure / dependency-free on purpose — importable from both the Streamlit-bound
dashboard module and the headless screener/runner without pulling heavy deps.
(Chuyển `SECTOR_*` từ `vnstock_dashboard.py` sang đây 12/08: nằm sau
`st.set_page_config()` nên test không import nổi, chỉ có replica chép tay.)

To add a new family: append one (label, {tickers}) entry to _CUSTOM_GROUPS.
The order here is the display order when these groups are pinned to the front
of the sector tables. A ticker may belong to at most one group (enforced).
"""
from __future__ import annotations

# ── Nhóm ngành chuẩn: 31 ngành gốc → 15 nhóm ────────────────────────────────
SECTOR_GROUPS = {
    "Ngân hàng":            "Ngân hàng",
    "Chứng khoán & Đầu tư tài chính": "Chứng khoán",
    "Bảo hiểm":            "Bảo hiểm",
    "Bất động sản":         "Bất động sản",
    "Xây dựng & Hạ tầng":  "Xây dựng & Hạ tầng",
    "Thép & Kim loại":     "Thép & Kim loại",
    "Vật liệu xây dựng":  "Hoá chất & Vật liệu",
    "Hóa chất & Phân bón": "Hoá chất & Vật liệu",
    "Nhựa & Bao bì":      "Hoá chất & Vật liệu",
    "Cơ khí & Thiết bị công nghiệp": "Hoá chất & Vật liệu",
    "Dầu khí":             "Năng lượng",
    "Điện & Năng lượng tái tạo": "Năng lượng",
    "Khai khoáng & Tài nguyên":  "Năng lượng",
    "Công nghệ thông tin & Phần mềm": "Công nghệ",
    "Viễn thông":          "Công nghệ",
    "Truyền thông & Quảng cáo": "Công nghệ",
    "Bán lẻ & Thương mại": "Tiêu dùng",
    "Thực phẩm & Đồ uống": "Tiêu dùng",
    "Dệt may & May mặc":  "Tiêu dùng",
    "Thể thao & Hàng tiêu dùng": "Tiêu dùng",
    "Nông nghiệp & Thủy sản": "Nông & Thuỷ sản",
    "Y tế & Dược phẩm":   "Y tế & Dược",
    "Vận tải & Logistics": "Vận tải & Cảng",
    "Cảng & Hạ tầng logistics": "Vận tải & Cảng",
    "Du lịch & Khách sạn": "Dịch vụ & Du lịch",
    "Giáo dục":            "Dịch vụ & Du lịch",
    "Dịch vụ công ích & Môi trường": "Dịch vụ & Du lịch",
    "Dịch vụ tư vấn & Kiểm định": "Dịch vụ & Du lịch",
    "Đa ngành":            "Khác",
    "In ấn & Xuất bản":   "Khác",
    "Gỗ & Nội thất":      "Khác",
    "Khác":                "Khác",
}

# Thứ tự hiển thị của 15 nhóm (bảng ngành, biểu đồ dòng tiền…).
SECTOR_ORDER = [
    "Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản",
    "Xây dựng & Hạ tầng", "Thép & Kim loại", "Hoá chất & Vật liệu",
    "Năng lượng", "Công nghệ", "Tiêu dùng", "Nông & Thuỷ sản",
    "Y tế & Dược", "Vận tải & Cảng", "Dịch vụ & Du lịch", "Khác",
]

SECTOR_ICONS = {
    "Ngân hàng": "🏦", "Chứng khoán": "📈", "Bảo hiểm": "🛡",
    "Bất động sản": "🏠", "Xây dựng & Hạ tầng": "🏗", "Thép & Kim loại": "⚙️",
    "Hoá chất & Vật liệu": "🧪", "Năng lượng": "⚡", "Công nghệ": "💻",
    "Tiêu dùng": "🛒", "Nông & Thuỷ sản": "🌾", "Y tế & Dược": "💊",
    "Vận tải & Cảng": "🚢", "Dịch vụ & Du lịch": "✈️", "Khác": "📦",
}


def get_sector(primary_industry: str) -> str:
    """Map ngành gốc → nhóm 15. Ngành lạ/rỗng → "Khác"."""
    return SECTOR_GROUPS.get(primary_industry, "Khác")


# ── Nhóm tuỳ biến theo mã ───────────────────────────────────────────────────

# Ticker-based sector groups, checked BEFORE the normal industry mapping.
_CUSTOM_GROUPS: "tuple[tuple[str, frozenset[str]], ...]" = (
    # Vingroup ecosystem (VPL = Vinpearl, listed 2025).
    ("Họ VIN", frozenset({"VIC", "VHM", "VRE", "VPL"})),
    # "Họ M" — Gelex ecosystem & affiliates.
    ("Họ M", frozenset({"GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"})),
)


def _build_lookup(groups) -> "dict[str, str]":
    """Flatten groups → {ticker: label}, rejecting a ticker in two groups."""
    lut: "dict[str, str]" = {}
    for label, family in groups:
        for tk in family:
            if tk in lut:
                raise ValueError(
                    f"ticker {tk} is in two custom sector groups "
                    f"({lut[tk]} and {label})")
            lut[tk] = label
    return lut


_TICKER_TO_GROUP = _build_lookup(_CUSTOM_GROUPS)

# Display order of the custom groups (pinned to the front of sector tables).
CUSTOM_SECTOR_ORDER = [label for label, _ in _CUSTOM_GROUPS]
# Every ticker that belongs to any custom group.
CUSTOM_FAMILY = frozenset(_TICKER_TO_GROUP)


def custom_sector_for(symbol: str) -> "str | None":
    """Return the custom sector label for a ticker, else None."""
    return _TICKER_TO_GROUP.get(symbol)


def tickers_in_group(label: str) -> "frozenset[str] | None":
    """Mã thuộc một nhóm tuỳ biến; None nếu `label` là ngành chuẩn."""
    for name, family in _CUSTOM_GROUPS:
        if name == label:
            return family
    return None


def rows_for_sector(df, label: str, *, ticker_col: str = "Mã",
                    sector_col: str = "Ngành"):
    """Lọc bảng MÃ theo một nhãn ngành — hiểu CẢ nhóm tuỳ biến.

    Vì sao cần hàm này thay vì `df[df["Ngành"] == label]`:

    Bảng cấp NGÀNH gom theo nhóm tuỳ biến (nên "Họ VIN" hiện ra như một ngành),
    nhưng bảng cấp MÃ cố ý giữ `Ngành` = ngành GỐC — `vnstock_runner` ghi rõ lý
    do: brief dựa vào ngành gốc để nhận diện bất động sản / tài chính, đổi đi là
    hỏng chỗ khác. Hệ quả: lọc `Ngành == "Họ VIN"` LUÔN ra rỗng, dù bảng ngành
    vẫn hiện đủ 4 mã (user báo 13/08: bấm vào Họ VIN / Họ M → "Không có dữ liệu
    ticker").

    Nhóm tuỳ biến vì thế phải lọc theo DANH SÁCH MÃ, ngành chuẩn thì lọc theo
    cột ngành. Gom vào đây để hai chỗ dùng (drill-down bảng ngành và khối "mã
    dẫn dắt" trong nhận định) không mỗi nơi tự chế một bản.

    Không import pandas: chỉ dùng giao diện của `df` truyền vào.
    """
    family = tickers_in_group(label)
    if family:
        return df[df[ticker_col].isin(family)]
    return df[df[sector_col] == label]

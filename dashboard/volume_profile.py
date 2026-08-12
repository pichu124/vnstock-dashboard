"""dashboard/volume_profile.py — tính Value Area / POC (thuần, không Streamlit).

Tách khỏi vnstock_dashboard 12/08 để tests/ import ĐỒ THẬT thay vì chép tay:
file dashboard chính gọi `st.set_page_config()` lúc import nên test không
import nổi → sinh ra replica, replica trôi, test hoá vô nghĩa.

Chỉ stdlib — không pandas/numpy/streamlit. Phần vẽ (`render_volume_profile`)
ở lại vnstock_dashboard vì nó st.markdown/st.caption.
"""
from __future__ import annotations


def calc_value_area(profile: list, pct: float = 0.70) -> tuple:
    """
    Tính Value Area — vùng giá chứa `pct` (mặc định 70%) tổng volume.

    Thuật toán:
    1. Tìm POC (price level có total_vol cao nhất)
    2. Từ POC, mở rộng ra 2 bên (trên + dưới) — mỗi bước chọn bên nào
       có volume cao hơn
    3. Dừng khi tổng volume trong vùng đạt ≥ pct × total_all_vol

    Returns: (poc_idx, vah_idx, val_idx, poc_price, vah_price, val_price)
      trong đó idx là index trong list profile (đã sort theo price giảm dần).
    """
    if not profile:
        return (0, 0, 0, 0, 0, 0)

    # Profile đã sort theo price giảm dần
    volumes = [float(r.get("total_vol", 0)) for r in profile]
    prices = [float(r.get("price", 0)) for r in profile]
    total_all = sum(volumes)
    if total_all <= 0:
        return (0, 0, len(profile) - 1, prices[0], prices[0],
                prices[-1] if prices else 0)

    # POC = index có volume cao nhất
    poc_idx = max(range(len(volumes)), key=lambda i: volumes[i])

    # Mở rộng từ POC ra 2 bên
    va_vol = volumes[poc_idx]
    target = total_all * pct
    upper = poc_idx - 1   # index nhỏ hơn = price cao hơn (sort giảm dần)
    lower = poc_idx + 1   # index lớn hơn = price thấp hơn

    while va_vol < target and (upper >= 0 or lower < len(volumes)):
        up_vol = volumes[upper] if upper >= 0 else -1
        lo_vol = volumes[lower] if lower < len(volumes) else -1

        if up_vol >= lo_vol and upper >= 0:
            va_vol += up_vol
            upper -= 1
        elif lower < len(volumes):
            va_vol += lo_vol
            lower += 1
        else:
            break

    vah_idx = max(upper + 1, 0)
    val_idx = min(lower - 1, len(volumes) - 1)

    return (poc_idx, vah_idx, val_idx,
            prices[poc_idx], prices[vah_idx], prices[val_idx])

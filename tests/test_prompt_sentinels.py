"""Khối prompt thiếu dữ liệu phải NÓI LÀ THIẾU, không được biến mất âm thầm.

Bất biến này đã có sẵn trong code từ lâu — `build_prompt` ghi rõ:

    "CRITICAL anti-hallucination invariant: if the loader returned {}, we STILL
     emit the section header with an explicit 'no data' sentinel — otherwise the
     prompt downstream tells the LLM to extract from the VNINDEX block, and a
     missing block leaves a vacuum the LLM fills from imagination."

Nhưng nó chỉ được áp cho 5 khối, bằng tay, không có lưới. Quét 12/08 (AST, 17
khối prompt có điều kiện) thấy **11 khối biến mất âm thầm** khi thiếu data.
Không phải cả 11 đều sai — và đó chính là lý do lưới này phải là DANH SÁCH
KHAI BÁO chứ không phải luật quét mù:

* Khối **cảnh báo** (độ tươi dữ liệu, ràng buộc bias) chỉ xuất hiện KHI CÓ vấn
  đề → vắng mặt là đúng, không cần sentinel.
* Khối **dữ liệu** mà template lại ra lệnh "dùng đúng block ở trên" → vắng mặt
  là để lại khoảng trống, và model được lệnh phải nộp mục đó → nó bịa.

Ba khối bổ sung sentinel ngày 12/08 và LÝ DO chọn đúng ba khối đó:

* **Top Gainers/Losers** — nặng nhất. Template nói "CHỈ chọn mã trong block
  Top Gainers/Losers CÓ DẤU ⭐" và còn nói block đó "BÌNH THƯỜNG có sẵn vài mã",
  trong khi vẫn đòi tối đa 3 setup. Không có block = bịa mã + bịa giá.
* **🎯 Dẫn dắt/Tụt hậu** — template có mục BẮT BUỘC "## 🏆 Dẫn dắt & Tụt hậu"
  trỏ thẳng vào block này.
* **Quant Market Regime** — template ràng buộc stance/hướng setup theo regime.

Các khối con của "Phân loại ngành" (rotation/stealth/distribution) KHÔNG cần
sentinel riêng: khối cha đã có, vắng khối con không tạo khoảng trống mới.
"""
import pytest

import vnstock_brief as vb

_MIN_CTX = {"date": "2026-08-12", "time": "08:30"}

# Khối BẮT BUỘC có sentinel khi thiếu data. Thêm khối prompt mới mà template
# ra lệnh "dùng đúng block ở trên" → thêm vào đây; lưới chỉ soi thứ ĐƯỢC KHAI BÁO.
_MUST_WARN_WHEN_EMPTY = [
    ("VNINDEX kỹ thuật",      "KHÔNG CÓ DỮ LIỆU VNINDEX"),
    ("Market Breadth",        "KHÔNG CÓ breadth data"),
    ("Session Timing",        "KHÔNG CÓ session stats"),
    ("Phân loại ngành",       "KHÔNG CÓ quant scores"),
    ("Top Gainers/Losers",    "KHÔNG CÓ dữ liệu movers"),
    ("Dẫn dắt/Tụt hậu",       "KHÔNG CÓ DỮ LIỆU"),
    ("Quant Market Regime",   "KHÔNG CÓ quant regime"),
]

# Khối chỉ hiện KHI CÓ vấn đề — vắng mặt là ĐÚNG, không được đòi sentinel.
_CONDITIONAL_BY_DESIGN = ["Độ tươi dữ liệu", "RÀNG BUỘC BIAS"]


@pytest.fixture(scope="module")
def empty_prompt():
    """Prompt dựng từ ctx TRỐNG — mô phỏng đêm mọi loader đều thất bại."""
    return vb.build_prompt(dict(_MIN_CTX), brief_type="morning")


@pytest.fixture(scope="module")
def empty_prompt_close():
    return vb.build_prompt(dict(_MIN_CTX), brief_type="close")


@pytest.mark.parametrize("section,sentinel", _MUST_WARN_WHEN_EMPTY)
def test_section_says_it_is_empty(section, sentinel, empty_prompt):
    """Thiếu data thì phải NÓI LÀ THIẾU. Im lặng = khoảng trống cho model bịa."""
    assert sentinel in empty_prompt, (
        f"Khối '{section}' biến mất âm thầm khi không có data — "
        f"không thấy cảnh báo {sentinel!r} trong prompt")


@pytest.mark.parametrize("section,sentinel", _MUST_WARN_WHEN_EMPTY)
def test_parity_close_brief_gets_the_same_sentinels(section, sentinel, empty_prompt_close):
    """Parity sáng/chiều: brief chiều cũng phải được cảnh báo y hệt."""
    assert sentinel in empty_prompt_close


@pytest.mark.parametrize("section", _CONDITIONAL_BY_DESIGN)
def test_conditional_blocks_stay_absent(section, empty_prompt):
    """Chốt lại rằng đây là chủ đích: khối cảnh báo KHÔNG được hiện khi không
    có gì để cảnh báo — nếu không thì mọi brief đều mở đầu bằng cảnh báo giả."""
    assert section not in empty_prompt


def test_sentinels_forbid_inventing_instead_of_just_noting_absence(empty_prompt):
    """Sentinel chỉ ghi "không có data" là chưa đủ — model vẫn có thể lấp bằng
    trí nhớ. Mỗi cảnh báo phải kèm lệnh CẤM rõ ràng."""
    for marker in ("TUYỆT ĐỐI KHÔNG", "KHÔNG được"):
        if marker in empty_prompt:
            break
    else:
        pytest.fail("Sentinel không kèm lệnh cấm bịa")
    # Đủ số lệnh cấm cho các khối đã khai báo
    bans = empty_prompt.count("TUYỆT ĐỐI KHÔNG") + empty_prompt.count("KHÔNG được")
    assert bans >= len(_MUST_WARN_WHEN_EMPTY)


def test_movers_sentinel_blocks_the_setup_section(empty_prompt):
    """Ca nặng nhất: không có movers thì mục 'Đề xuất giao dịch' phải bị chặn
    TẠI CHỖ, vì template vẫn đang đòi tối đa 3 setup."""
    assert "không đề xuất setup" in empty_prompt
    assert "KHÔNG nêu tên mã" in empty_prompt


def test_full_data_prompt_has_no_false_alarms():
    """Chiều ngược lại: có data đầy đủ thì KHÔNG được xuất hiện cảnh báo —
    sentinel bật nhầm còn tệ hơn không có, vì nó dạy model im lặng."""
    ctx = dict(_MIN_CTX)
    ctx["quant_regime"] = {"regime": "RISK-ON", "conviction": 0.5, "detail": "test"}
    ctx["lead_sector"] = {"name": "Ngân hàng", "contrib": 0.30}
    ctx["lag_sector"] = {"name": "Thép & Kim loại", "contrib": -0.30}
    ctx["vn30_gainers"] = [{"Mã": "VCB", "Giá 1T %": 2.5, "Ngành": "Ngân hàng", "last": 90.0}]

    prompt = vb.build_prompt(ctx, brief_type="morning")
    assert "KHÔNG CÓ quant regime" not in prompt
    assert "KHÔNG CÓ dữ liệu movers" not in prompt
    assert "Dẫn dắt/Tụt hậu — KHÔNG CÓ DỮ LIỆU" not in prompt
    assert "RISK-ON" in prompt and "VCB" in prompt


def test_losers_only_still_counts_as_having_movers():
    """Phiên đỏ toàn tập: có losers mà không có gainers vẫn là CÓ data —
    bật cảnh báo lúc này là báo động giả."""
    ctx = dict(_MIN_CTX)
    ctx["vn30_losers"] = [{"Mã": "HPG", "Giá 1T %": -3.1, "Ngành": "Thép & Kim loại",
                           "last": 25.0}]
    prompt = vb.build_prompt(ctx, brief_type="morning")
    assert "KHÔNG CÓ dữ liệu movers" not in prompt
    assert "HPG" in prompt

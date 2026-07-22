"""conftest.py — lưới hermetic DÙNG CHUNG cho toàn bộ tests/.

BÀI HỌC 2 NGÀY LIỀN (17-18/07): sandbox bị chặn mạng nên test gọi
`vnstock_macro.refresh()` mà fetcher lọt fixture vẫn "vô tình pass"; chạy
trên MÁY CÓ MẠNG (desktop user) là fetch THẬT đè fixture → fail hàng loạt
(17/07: 3 fail trong fast list → vá autouse test_macro; 18/07: thêm 6 fail
trong FULL suite ở test_vbma/test_nso/test_fred — autouse cục bộ mỗi file
chỉ chặn fetcher CŨ, fetcher mới thêm sau lọt lưới).

Fix tận gốc: autouse Ở ĐÂY chặn TOÀN BỘ fetcher ngoài của vnstock_macro
cho MỌI test — file test mới/fetcher mới tự động được chặn, khỏi nhớ cập
nhật từng autouse cục bộ. Test nào cần fetcher nào thì tự re-patch (các
test hiện có đều đã làm vậy). FX chặn qua `_FX_ENDPOINTS=()` chứ KHÔNG
patch hàm — test parser fetch_usdvnd cần hàm thật (tự dựng endpoint fake).

Autouse cục bộ trong test_macro/test_vbma/test_fred GIỮ NGUYÊN (defense
in depth + tài liệu bài học tại chỗ); trùng với đây là vô hại.
"""
from __future__ import annotations

import pytest

import vnstock_macro as _mac
import vnstock_price_fallback as _fb


@pytest.fixture(autouse=True)
def _no_macro_network_anywhere(monkeypatch):
    monkeypatch.setattr(_mac, "_fetch_nso", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_fred", lambda: None)
    monkeypatch.setattr(_mac, "_pmi_from_news", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_vbma", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_hnx", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_sbv", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_sbv_daily", lambda: None)
    monkeypatch.setattr(_mac, "_fetch_sbv_policy", lambda: None)
    monkeypatch.setattr(_mac, "_FX_ENDPOINTS", ())


@pytest.fixture(autouse=True)
def _reset_price_fallback_breaker():
    """BREAKER là singleton (dùng chung 8 worker của updater) → RÒ TRẠNG THÁI
    giữa các test (lộ 20/07 trên desktop: test cố ý MỞ mạch chạy trước →
    test_ratelimit/test_updater_partial_bar chạy sau bị bỏ qua _fetch_prices
    fake, đi thẳng fallback KBS thật → 'error'; sandbox không thấy vì các
    test đó skip thiếu vnstock). Reset trước VÀ sau mỗi test."""
    _fb.BREAKER.reset()
    yield
    _fb.BREAKER.reset()


@pytest.fixture(autouse=True)
def _no_llm_alert_anywhere(monkeypatch):
    """Alert "LLM ladder DOWN" (22/07) gửi Telegram THẬT nếu máy có token —
    test đi qua đường cạn-toàn-bộ-nấc (digest (None,''), chat_complete None)
    mà không tắt là spam điện thoại user mỗi lần chạy suite. Tắt cứng ở đây;
    test nào test CHÍNH alert thì tự setenv VNSTOCK_LLM_ALERT=1 đè lại."""
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "0")

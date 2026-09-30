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


@pytest.fixture(autouse=True)
def _rollup_meta_to_tmp_anywhere(tmp_path, monkeypatch):
    """Cùng họ bài học ledger 30/07: `_normalize_units` (11/08) nay ghi vết
    vào `_meta/unit_normalizations.json` — test nào đi qua đường quy đổi mà
    không redirect là ghi VẾT GIẢ vào kho thật, sáng hôm sau badge doctor
    trên máy user warn OAN "có quy đổi đơn vị". Redirect cho MỌI test; test
    soi vết thật thì tự setattr đè (vô hại, cùng tmp_path)."""
    import vnstock_rollup as _vr
    monkeypatch.setattr(_vr, "META_DIR", tmp_path)


@pytest.fixture(autouse=True)
def _ledger_to_tmp_anywhere(tmp_path, monkeypatch):
    """Cùng họ bài học với alert ở trên, lộ 30/07 trên máy user: test fake
    HTTP nhưng agent/digest vẫn gọi vnstock_llm_ledger.record THẬT → suite
    chạy sau nửa đêm ghi rác vào data_warehouse/_meta/llm_ledger.json
    (--show sáng ra hiện "4 call Anthropic Haiku" dù máy không có key —
    toàn usage giả 10/5 token từ fixture _Resp, cost tính tiền như thật).
    Redirect _META về tmp cho MỌI test; test soi ledger (_tmp_meta cục bộ)
    setattr đè tiếp cũng vẫn về tmp — vô hại."""
    import vnstock_llm_ledger as _ledger
    monkeypatch.setattr(_ledger, "_META", tmp_path)


@pytest.fixture(autouse=True)
def _no_claude_cli_anywhere(monkeypatch):
    """Engine Claude Code (30/09, U62): `.env` máy user có thể đặt
    VNSTOCK_LLM_ENGINE=claude và có `claude` trên PATH ⇒ test đi qua
    digest/sentiment/news/train sẽ SPAWN OPUS THẬT rồi đỏ hàng loạt (thẩm
    định ngược: 14 test whitelist đỏ ở cấu hình desktop giả). Lưới ở đây cho
    MỌI test: không đọc .env, xoá mọi công tắc engine, ghim exe về đường dẫn
    không tồn tại (`cli_executable()` → None, KHÔNG rơi về PATH), xoá memo
    "CLI chết". Test cần engine thì tự setenv; test cần exe thì tự patch
    `cli_executable`/truyền `exe=` (tests/test_claude_cli.py đã làm vậy)."""
    import vnstock_claude_cli as _vcc
    monkeypatch.setattr(_vcc, "_ENV_LOADED", True)
    for k in ("VNSTOCK_LLM_ENGINE", *_vcc.STEP_ENGINE_ENV.values(),
              "VNSTOCK_CLAUDE_CLI_MODEL", "VNSTOCK_BRIEF_CLI_MODEL",
              "VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_EXE", "/nonexistent/claude-hermetic")
    monkeypatch.delenv("VNSTOCK_BRIEF_CLI_EXE", raising=False)
    _vcc.reset_dead_memo()
    yield
    _vcc.reset_dead_memo()


@pytest.fixture(autouse=True)
def _events_meta_to_tmp_anywhere(tmp_path, monkeypatch):
    """`vnstock_events.refresh_upcoming` (30/09) ghi/xoá marker backoff ở
    `_META/upcoming_events.backoff.json` — test đi qua đường trắng tay mà
    không redirect là ghi VẾT GIẢ vào kho thật (cùng họ bài học ledger). Test
    nào set `ev._META` riêng thì đè tiếp, vô hại."""
    import vnstock_events as _ev
    monkeypatch.setattr(_ev, "_META", tmp_path)

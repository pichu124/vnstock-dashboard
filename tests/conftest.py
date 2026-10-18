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

from importlib.machinery import PathFinder
from importlib.util import find_spec

import pytest

import vnstock_macro as _mac
import vnstock_price_fallback as _fb

# CI (.github/workflows/tests.yml) chỉ cài gói tối thiểu. Test kéo thư viện
# ngoài đó thì SKIP kèm tên thư viện — xét bằng import được thật, không bằng env.
# updater/classifier/warehouse import được khi có vnstock_data HOẶC vnstock.
HAS_VNSTOCK_SDK = find_spec("vnstock_data") is not None or find_spec("vnstock") is not None
VNSTOCK_SKIP_REASON = "cần vnstock hoặc vnstock_data — CI tối thiểu không cài"
needs_vnstock = pytest.mark.skipif(not HAS_VNSTOCK_SDK, reason=VNSTOCK_SKIP_REASON)


def _installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except ValueError:
        # sys.modules giữ bản GIẢ không __spec__ (test_dashboard gắn MagicMock vào
        # "streamlit" lúc thu thập) ⇒ tìm thẳng trên sys.path.
        return PathFinder.find_spec(module) is not None


def needs(module: str):
    return pytest.mark.skipif(not _installed(module),
                              reason=f"cần {module} — CI tối thiểu không cài")


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


@pytest.fixture(autouse=True)
def _fundamentals_writers_to_tmp_anywhere(tmp_path, monkeypatch):
    """U17 (06/10): test cũ ghi ảnh chụp cơ bản AAA/BBB/CCC vào kho THẬT ba
    tháng liền (08·09·10) vì chỉ chuyển FUND_PATH mà quên FUND_HISTORY_DIR —
    "bản đầu tháng thắng" nên ảnh thật không lần nào ghi được. Lưới cho MỌI
    test: fundamentals.parquet, ảnh chụp tháng, sổ kỳ BCTC (đi theo FUND_PATH)
    và sổ đã báo của brief (`vnstock_fund_periods.META_DIR`) đều về tmp. Test
    nào tự setattr thì đè tiếp, vô hại."""
    import vnstock_fund_periods as _fp
    import vnstock_fundamental_updater as _fu
    monkeypatch.setattr(_fu, "FUND_PATH", tmp_path / "fundamentals.parquet")
    monkeypatch.setattr(_fu, "FUND_HISTORY_DIR", tmp_path / "fundamentals_history")
    monkeypatch.setattr(_fp, "META_DIR", tmp_path)


@pytest.fixture(autouse=True)
def _rec_display_reads_no_real_warehouse(tmp_path, monkeypatch):
    """08/10: brief 💡 + footer Telegram gọi `vnstock_train.rec_display_levels`
    (mốc lệnh mở đã quy đổi qua GDKHQ) — đọc lịch sử giá + neo trong SQLite.
    Test rec giả mang `id` (strategy_tiers…) không được đọc kho THẬT của máy
    chạy test: lịch sử rỗng ⇒ mốc gốc. Test cần thì tự đè `_display_history`."""
    import pandas as _pd
    import vnstock_train as _vt
    monkeypatch.setattr(_vt, "_display_history", lambda *a, **k: _pd.DataFrame())
    # Neo từ bản sao lưu rebase (08/10): không được đọc `_meta/backup_rebase` THẬT.
    monkeypatch.setattr(_vt, "_REBASE_BACKUP_ROOT", tmp_path / "_backup_rebase_none")


@pytest.fixture(autouse=True)
def _mcp_enrich_to_tmp_anywhere(tmp_path, monkeypatch):
    """U79 (08/10): `_meta/mcp_enrich.json` nằm trong KHO (Dropbox) — test quên
    `meta_dir` không được ghi đè bản chạy bóng thật (cùng bài học U17)."""
    import vnstock_mcp_enrich as _me
    monkeypatch.setattr(_me, "META_DIR", tmp_path / "_meta_mcp")


@pytest.fixture(autouse=True)
def _assets_hermetic_anywhere(tmp_path, monkeypatch):
    """U82 (09/10): kho đa tài sản nằm trong KHO (Dropbox) ⇒ mọi test ghi/đọc ở tmp; mạng của
    nguồn Python bị chặn (một chỗ `vnstock_assets_sources.HTTP`); khoá theo máy về tmp (không
    giẫm lượt chạy thật trên desktop); móc mỗi giờ của `run.py news-alert` TẮT — test nào cần
    thì tự bật + giả subprocess."""
    import vnstock_assets as _va
    import vnstock_assets_sources as _vas

    def _blocked(*a, **k):
        raise ConnectionError("test hermetic: nguồn tài sản không được ra mạng")
    monkeypatch.setattr(_va, "ASSETS_DIR", tmp_path / "_assets")
    monkeypatch.setattr(_va, "META_DIR", tmp_path / "_meta_assets")
    monkeypatch.setattr(_va, "LOCK_DIR", tmp_path / "_lock_assets")
    monkeypatch.setattr(_vas, "HTTP", _blocked)
    monkeypatch.setattr(_vas, "fetch_mbk_central", lambda *a, **k: [])
    monkeypatch.setenv("VNSTOCK_ASSETS_HOURLY", "0")
    monkeypatch.setenv("VNSTOCK_ASSETS_ALERTS", "0")    # P5: không test nào được gửi Telegram thật


@pytest.fixture(autouse=True)
def _futures_foreign_hermetic(tmp_path, monkeypatch):
    """U88 (15/10): kho phái sinh khối ngoại nằm trong KHO (Dropbox) ⇒ mọi test đọc/ghi ở tmp
    (RỖNG — brief không có mục 📑 trừ khi test tự nạp seed, nên test brief cũ không đổi theo kho
    máy thật); tiền tố tool MCP cố định, không đọc `.env`/connector máy thật."""
    import vnstock_futures_foreign as _ff
    monkeypatch.setattr(_ff, "FUT_DIR", tmp_path / "_futures")
    monkeypatch.setattr(_ff, "META_DIR", tmp_path / "_meta_futures")
    monkeypatch.setattr(_ff, "ssi_prefix", lambda: "mcp__test_SSI__")
    monkeypatch.delenv("VNSTOCK_FUTURES_FOREIGN", raising=False)
    monkeypatch.delenv("VNSTOCK_BRIEF_FUTURES_FOREIGN", raising=False)


@pytest.fixture(autouse=True)
def _no_horizons_switch_from_dotenv(monkeypatch):
    """Brief 3 khung (P1b, #24/#26): `.env` máy thật lọt vào pytest (vnstock_auth
    load_dotenv lúc import) — bật VNSTOCK_HORIZONS ở `.env` không được làm đổi nhãn
    regime / prompt / guard trong các test viết cho hành vi mặc định (pipeline đêm
    chạy test trước brief: đỏ là MẤT brief, U65). Test cần công tắc thì tự setenv.

    Từ 14/10 công tắc mặc định BẬT ⇒ nền chung ghim TẮT ("0"): test cũ canh đường
    khung cũ — chính là đường kill-switch `VNSTOCK_HORIZONS=0` (đo 14/10: bỏ ghim thì
    36 test cũ đỏ, toàn vì nhãn/prompt/stub, 0 lỗi code). Test 3 khung tự đặt "1";
    test mặc định tự delenv (`test_horizons_rollout`)."""
    import os
    for k in list(os.environ):
        if k.startswith(("VNSTOCK_HORIZON", "VNSTOCK_REGIME_NN", "VNSTOCK_ALLOC_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")

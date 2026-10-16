"""Render thử tab Thị trường + 5 panel brief bằng Streamlit GIẢ.

Vì sao cần: đợt tách 12/08 kéo ~2.400 dòng UI ra khỏi hai hàm khổng lồ. Suite
cũ chỉ soi được phần THUẦN (định dạng, nhận định, sparkline) — phần render thì
không test nào chạm tới, nên lỗi kiểu "cắt khối ra mà quên truyền một biến"
chỉ lộ khi mở dashboard bằng mắt.

Test này chạy THẲNG `render_market_tab()` / `render_brief_panel()` với một
Streamlit giả. Nó KHÔNG kiểm giao diện đẹp hay số đúng — chỉ trả lời đúng một
câu: **code có chạy hết không, hay nổ giữa chừng**. Đó lại chính là rủi ro của
một đợt refactor.

Giới hạn (nói rõ để không tưởng bở):
* Streamlit giả luôn trả về "không bấm" cho mọi nút → nhánh sau khi bấm không
  chạy (train, scan, sinh brief — những thứ tốn tiền/thời gian thật).
* `vnstock_dashboard` bị thay bằng stub, vì module thật dựng UI ngay khi
  import nên không import nổi trong pytest.
* Chạy được KHÔNG có nghĩa là hiển thị đúng — vẫn cần liếc mắt một lần sau
  khi merge.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from tests.conftest import needs

ROOT = Path(__file__).resolve().parent.parent
_SECTORS = ["Ngân hàng", "Thép & Kim loại", "Công nghệ"]


class _Ctx(MagicMock):
    """Widget vừa là giá trị vừa là context manager (`with st.expander(...)`)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_streamlit():
    st = MagicMock()
    st.columns = lambda spec=2, **k: [
        _Ctx() for _ in (range(spec) if isinstance(spec, int) else spec)]
    st.tabs = lambda labels, **k: [_Ctx() for _ in labels]
    for name in ("expander", "container", "form", "spinner", "status", "empty", "popover"):
        setattr(st, name, lambda *a, **k: _Ctx())
    st.sidebar = _Ctx()
    st.session_state = {}
    st.cache_data = lambda *a, **k: (lambda f: f)
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.fragment = lambda *a, **k: (lambda f: f)
    # Không bấm gì cả — nhánh "sau khi bấm" là việc thật (train/scan/gọi LLM).
    st.button = lambda *a, **k: False
    st.checkbox = lambda *a, **k: False
    st.toggle = lambda *a, **k: False
    st.radio = lambda label, options=(), **k: (list(options)[0] if len(options) else None)
    st.selectbox = lambda label, options=(), **k: (list(options)[0] if len(options) else None)
    st.multiselect = lambda *a, **k: []
    st.text_input = lambda *a, **k: ""
    st.text_area = lambda *a, **k: ""
    st.slider = lambda label, *a, **k: (a[0] if a else 0)
    # Widget nào QUÊN khai ở đây sẽ trả về MagicMock, và dòng `if giá_trị > 0`
    # ngay sau đó ném TypeError → panel rơi vào `except` rồi tự tắt. Test vẫn
    # XANH mà không soi gì cả (đúng ca `select_slider` bị sót, phát hiện 13/08).
    # `test_no_panel_silently_disables_itself` bên dưới là lưới chặn ca đó.
    st.select_slider = lambda label, options=(), value=None, **k: (
        value if value is not None else (list(options)[0] if len(options) else 0))
    st.number_input = lambda label, min_value=0, max_value=None, value=0, **k: value
    st.date_input = lambda *a, **k: __import__("datetime").date(2026, 8, 12)
    st.color_picker = lambda *a, **k: "#000000"
    st.file_uploader = lambda *a, **k: None
    st.feedback = lambda *a, **k: None
    st.data_editor = lambda df=None, *a, **k: df
    return st


def _sector_df():
    n = len(_SECTORS)
    cols = {"Ngành": _SECTORS, "Số mã": [10, 5, 3]}
    for c, base in (("Vốn hoá (tỷ)", 1e6), ("Freefloat (tỷ)", 3e5), ("GTGD TB (tỷ)", 500),
                    ("Vol Avg 5", 10.0), ("Vol Avg 10", 9.0), ("Vol Avg 20", 8.0),
                    ("AVG 5-10 %", 5.0), ("AVG 10-20 %", 2.0),
                    ("Vol 5/Free %", 0.5), ("Vol 10/Free %", 0.4), ("Vol 20/Free %", 0.6),
                    ("Vol 5/20 %", 120.0),
                    ("Net BS 1T", 10.0), ("Net BS 1M", 20.0),
                    ("Net BS 3M", 30.0), ("Net BS 6M", 40.0),
                    ("NN 1T (tỷ)", 100.0), ("NN 1M (tỷ)", 200.0), ("NN 3M (tỷ)", 300.0),
                    ("Biên 1T (%)", 2.0), ("Biên 1M (%)", 3.0), ("Biên 3M (%)", 4.0),
                    ("Giá 1T %", 1.5), ("Giá 1M %", 3.0), ("Giá 3M %", 5.0)):
        # dấu xen kẽ để chạm cả nhánh xanh lẫn đỏ của bảng màu
        cols[c] = [base * s for s in (1, -0.5, 0.2)][:n]
    return pd.DataFrame(cols)


def _ticker_df():
    df = _sector_df().rename(columns={"Ngành": "_x"})
    df.insert(0, "Mã", ["VCB", "HPG", "FPT"])
    df.insert(1, "Ngành", _SECTORS)
    return df.drop(columns=["_x", "Số mã"])


def _index_df():
    return pd.DataFrame({
        "time": pd.bdate_range(end="2026-08-12", periods=90),
        "VNINDEX": np.linspace(1200, 1300, 90),
        "VNINDEX_chg": np.linspace(-1, 1, 90),
    })


def _stub_dashboard(sector_df=None, index_df=None):
    """`vnstock_dashboard` thật dựng UI ngay khi import → phải stub."""
    m = types.ModuleType("vnstock_dashboard")
    m.INDEX_SYMBOLS = ["VNINDEX"]
    m.VN30_SYMBOLS = ["VCB"]
    m.WSS_AVAILABLE = False
    m.load_market_overview = lambda *a, **k: (
        sector_df if sector_df is not None else pd.DataFrame())
    m.load_index_overview = lambda days=90: (
        index_df if index_df is not None else pd.DataFrame())
    m.load_live_quote = lambda *a, **k: {}
    m.load_price_history = lambda *a, **k: pd.DataFrame()
    m.load_screener_results = lambda *a, **k: None
    m.PRICES_DIR = ROOT / "data_warehouse" / "prices"
    return m


def _fake_analyzer():
    """Lớp chấm điểm quant — thay bằng bản giả.

    KHÔNG phải để test chạy được (bản thật chạy được), mà để test chạy NHANH và
    ỔN ĐỊNH: bản thật đọc quarantine, ex-div, session stats, foreign flow từ đĩa.
    Đo trên máy user 13/08: ba test render này ngốn 20.5s = 19% cả vòng lặp
    `--fast`, gần hết là I/O của lớp này. Test ở đây soi CODE RENDER của mình,
    không soi thuật toán chấm điểm (đã có test riêng).
    """
    m = types.ModuleType("vnstock_market_analyzer")
    m.compute_scores = lambda df, presets=None, index_returns=None, exdiv_map=None: {"n": len(df)}
    m.market_regime = lambda scores, breadth: {
        "regime": "RISK-ON", "conviction": 0.42, "detail": "smoke"}
    m.format_row = lambda row, name_col="Ngành": [
        f"{row[name_col]} `{row['composite']:+.2f}`", "  dòng phụ"]
    m.build_preset_sets = lambda x: None
    m.compute_index_returns = lambda df, index_col="VNINDEX": {"1T": 1.2, "1M": -0.4, "3M": 5.6}
    m.load_quarantine_tickers = lambda: set()
    m.load_recent_exdiv = lambda days_back=7: {}
    m.session_timing_signal = lambda t, h, index_name="VNINDEX": {"signal": "N/A", "detail": ""}

    def _rank(df, scores, n_top=5, n_bot=5, name_col="Ngành", quarantined=None):
        names = list(df[name_col])
        rows = [{name_col: n, "composite": round(1.5 - i, 2)} for i, n in enumerate(names)]
        return {"top": rows[:n_top], "avoid": list(reversed(rows))[:n_bot],
                "stealth": rows[1:2], "distribution": rows[:1], "rotation": rows[:2]}
    m.rank = _rank
    return m


def _fake_memory():
    """Bộ nhớ brief (SQLite) — bản giả TRẢ RỖNG, không phải MagicMock.

    Cố ý: MagicMock sẽ làm panel rơi vào nhánh `except` rồi in "panel disabled",
    tức test không còn soi thân panel nữa — nhanh hơn mà mất tác dụng. Trả rỗng
    thì panel chạy hết nhánh "chưa có dữ liệu", đúng cảnh máy vừa dựng lại.
    """
    m = types.ModuleType("vnstock_memory")
    m.init_db = lambda *a, **k: None
    m.get_active_family = lambda *a, **k: None
    m.best_strategies = lambda *a, **k: []
    m.open_recommendations = lambda *a, **k: []
    m.recommendation_performance = lambda *a, **k: {}
    m.recent_closed_recommendations = lambda *a, **k: []
    m.outcome_distribution = lambda *a, **k: {}
    m.family_history = lambda *a, **k: []
    m.latest_backtest = lambda *a, **k: None
    m.update_rating = lambda *a, **k: None
    m.top_rated_briefs = lambda *a, **k: []
    m.recent_briefs = lambda *a, **k: []
    m._conn = lambda *a, **k: None
    return m


@pytest.fixture
def render_env(monkeypatch):
    """Cài Streamlit giả + stub các module ĐỌC ĐĨA, rồi nạp lại module tab."""
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setitem(sys.modules, "streamlit.components", MagicMock())
    monkeypatch.setitem(sys.modules, "streamlit.components.v1", MagicMock())

    monkeypatch.setitem(sys.modules, "vnstock_market_analyzer", _fake_analyzer())
    monkeypatch.setitem(sys.modules, "vnstock_memory", _fake_memory())
    sess = types.ModuleType("vnstock_session_stats")
    sess.load_session_stats_history = lambda *a, **k: {}
    sess.load_session_stats = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "vnstock_session_stats", sess)
    return st


def _load(name):
    import importlib
    mod = importlib.import_module(name)
    return importlib.reload(mod)


def test_market_tab_renders_with_no_data(render_env, monkeypatch):
    """Kho trống / loader chết — đường đi hay gặp nhất khi máy vừa dựng lại."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_dashboard())
    _load("dashboard.market_tab").render_market_tab()


def test_market_tab_renders_with_data(render_env, monkeypatch):
    """Có data thì bảng ngành, thang màu, sparkline, treemap, nhận định đều
    chạy — đúng những chỗ vừa bị kéo ra module khác."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(_sector_df(), _index_df()))
    render_env.session_state["_mkt_ticker_data"] = _ticker_df()
    _load("dashboard.market_tab").render_market_tab()


def test_market_tab_renders_when_drilldown_sector_selected(render_env, monkeypatch):
    """Drill-down dùng THANG MÀU RIÊNG (`_dd_amp_color`) — chính chỗ trước đây
    là bản chép của thang bảng tổng."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(_sector_df(), _index_df()))
    st = render_env
    st.session_state["_mkt_ticker_data"] = _ticker_df()
    st.selectbox = lambda label, options=(), **k: (
        "Ngân hàng" if "ngành" in str(label).lower() and "Ngân hàng" in list(options)
        else (list(options)[0] if len(options) else None))
    _load("dashboard.market_tab").render_market_tab()


def test_custom_sector_drilldown_is_not_empty(render_env, monkeypatch):
    """Ca user báo 13/08: bấm vào "Họ VIN" ra "Không có dữ liệu ticker".

    Bảng MÃ giữ `Ngành` = ngành GỐC (VIC/VHM = Bất động sản), nên lọc theo nhãn
    nhóm luôn rỗng. Đây là test đi ĐÚNG đường user bấm, khác với test đơn vị ở
    `test_custom_sector_drilldown.py` chỉ soi hàm lọc."""
    sectors = _sector_df()
    sectors.loc[0, "Ngành"] = "Họ VIN"          # nhóm tuỳ biến xuất hiện ở bảng ngành
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(sectors, _index_df()))

    ticks = _ticker_df()
    ticks["Mã"] = ["VIC", "VHM", "FPT"]
    ticks["Ngành"] = ["Bất động sản", "Bất động sản", "Công nghệ"]  # KHÔNG mã nào là "Họ VIN"

    st = render_env
    st.session_state["_mkt_ticker_data"] = ticks
    st.selectbox = lambda label, options=(), **k: (
        "Họ VIN" if "Họ VIN" in list(options)
        else (list(options)[0] if len(options) else None))
    said = []
    st.info = lambda *a, **k: said.append(str(a[0]) if a else "")

    _load("dashboard.market_tab").render_market_tab()

    assert not [s for s in said if "Không có dữ liệu ticker" in s], (
        "Drill-down nhóm tuỳ biến vẫn rỗng — dùng vnstock_sectors.rows_for_sector")


def test_brief_panel_renders(render_env):
    """5 panel con vừa tách — nổ ở đây nghĩa là cắt khối mà rơi mất biến."""
    _load("dashboard.market_brief_panel").render_brief_panel()


@pytest.mark.parametrize("mod,fn", [
    ("dashboard.brief_agent_settings", "render_agent_settings"),
    ("dashboard.brief_run_panel", "render_brief_runner"),
    ("dashboard.brief_accuracy_panel", "render_accuracy_widget"),
    ("dashboard.brief_history_panel", "render_brief_history"),
    ("dashboard.brief_strategy_panel", "render_strategy_panel"),
])
def test_each_brief_subpanel_renders_on_its_own(render_env, mod, fn):
    """Gọi lẻ từng panel: panel phải tự đứng được, không dựa vào biến mà panel
    trước tình cờ để lại."""
    getattr(_load(mod), fn)()


def test_no_panel_silently_disables_itself(render_env):
    """Panel nào cũng bọc `try/except` rộng để một panel hỏng không kéo sập cả
    tab — rất đúng cho production, nhưng nó cũng NUỐT luôn giá trị của smoke
    test: panel rơi vào `except` thì test vẫn xanh mà chẳng soi gì.

    Đã dính thật (13/08): Streamlit giả sót `select_slider` → panel Lịch sử
    tự tắt, mà test vẫn báo PASS. Lưới này bắt đúng ca đó."""
    st = render_env
    said = []
    for name in ("caption", "warning", "error", "info"):
        setattr(st, name, lambda *a, _s=said, **k: _s.append(str(a[0]) if a else ""))

    _load("dashboard.market_brief_panel").render_brief_panel()

    disabled = [s for s in said
                if "disabled" in s.lower() or "Không tìm thấy" in s]
    assert not disabled, "Panel tự tắt thay vì chạy thân:\n  " + "\n  ".join(disabled)


class TestAllocationBriefButtonBranch:
    """Nhánh SAU KHI BẤM nút "📝 Tạo brief phân bổ" — chỗ smoke thường né.

    Bug user bắt 13/08, ngay lần bấm nút THẬT đầu tiên: generate_brief trả
    kèm metadata `_brief_ids` (list N id) / `_warnings` (dict); vòng for cũ
    mổ `(text, err)` NGAY TRONG câu for — trước cả dòng lọc key "_" — nên
    brief càng THÀNH CÔNG (4 agent → _brief_ids 4 phần tử) càng chắc nổ
    "too many values to unpack (expected 2)". Panel bọc try/except nên chỉ
    hiện hộp đỏ "Không render được sub tab Phân bổ" SAU khi đã vẽ đủ brief.
    """

    def _st_pressed(self):
        st = _fake_streamlit()
        st.button = lambda label, *a, key=None, **k: key == "_al_brief"
        return st

    def test_brief_button_survives_metadata_keys(self, monkeypatch):
        import vnstock_brief as vb
        import vnstock_memory as mem
        from dashboard.allocation_tab import _render_brief

        realistic = {
            "Gemini 3.5 Flash": ("brief A", None),
            "Mistral Small": ("brief B", None),
            "Cerebras GPT-OSS-120B": ("", "429 rate limit"),
            "_brief_ids": [101, 102, 103, 104],   # thủ phạm: 4 phần tử ≠ 2
            "_warnings": {"Gemini 3.5 Flash": ["1 câu bị guard sửa"]},
        }
        monkeypatch.setattr(vb, "generate_brief", lambda *a, **k: dict(realistic))
        monkeypatch.setattr(mem, "recent_briefs", lambda *a, **k: [])

        st = self._st_pressed()
        _render_brief(st)          # trước fix: ValueError ngay dòng for

        rendered = " | ".join(str(c.args[0]) if c.args else ""
                              for c in st.markdown.call_args_list)
        assert "brief A" in rendered and "brief B" in rendered
        assert "_brief_ids" not in rendered   # metadata không hiện như agent

    def test_all_agents_failed_shows_error_not_crash(self, monkeypatch):
        import vnstock_brief as vb
        import vnstock_memory as mem
        from dashboard.allocation_tab import _render_brief

        monkeypatch.setattr(vb, "generate_brief", lambda *a, **k: {
            "Gemini 3.5 Flash": ("", "hết quota"),
            "_no_available": ("", "3 key đều thiếu"),
            "_brief_ids": [],                  # list rỗng: unpack cũng nổ
        })
        monkeypatch.setattr(mem, "recent_briefs", lambda *a, **k: [])

        st = self._st_pressed()
        _render_brief(st)
        assert st.error.called                # báo lỗi tử tế, không crash


def test_agent_settings_two_rows_same_type_have_unique_keys(render_env, monkeypatch):
    """Nút "➕ Thêm agent" luôn tạo type TRÙNG (defaults đã đủ mọi type). Key
    widget đặt theo type ⇒ lượt rerun kế nổ StreamlitDuplicateElementKey, mất
    cả khối brief — và lỗi dính mãi vì file cấu hình nằm trong kho dùng chung."""
    import vnstock_brief as vb
    monkeypatch.setattr(vb, "load_agent_configs", lambda: [
        {"type": "gemini", "name": "Gemini A", "model": "m-a", "enabled": True},
        {"type": "gemini", "name": "Gemini B", "model": "m-b", "enabled": False},
    ])
    st = render_env
    seen: set = set()

    def _unique(fn):
        def wrapped(*a, key=None, **k):
            if key is not None:
                if key in seen:
                    raise RuntimeError(f"StreamlitDuplicateElementKey: {key}")
                seen.add(key)
            return fn(*a, key=key, **k)
        return wrapped

    for name in ("checkbox", "text_input", "button", "selectbox"):
        setattr(st, name, _unique(getattr(st, name)))

    _load("dashboard.brief_agent_settings").render_agent_settings()


def test_accuracy_widget_does_not_rank_tiny_sample_first(render_env, monkeypatch):
    """Lỗi họ 13/08 ("0/2 hiện 0%"): widget in thẳng accuracy thô và trao 🥇
    cho agent mới chấm 1 brief. Agent 1/1 không được hiện "100%" và không được
    đứng trên agent đã chấm 12/20."""
    import vnstock_brief as vb
    monkeypatch.setattr(sys.modules["vnstock_memory"], "recent_briefs",
                        lambda *a, **k: [{"agent_name": "x"}])

    def _slot(n_match, n_eval):
        return {"n_total": n_eval, "n_evaluated": n_eval, "n_match": n_match,
                "accuracy": n_match / n_eval, "stance_dist": {},
                "reliable": n_eval >= vb._ACCURACY_MIN_SAMPLE}
    monkeypatch.setattr(vb, "agent_accuracy_summary", lambda *a, **k: {
        "Lucky": _slot(1, 1), "Steady": _slot(12, 20)})

    st = render_env
    _load("dashboard.brief_accuracy_panel").render_accuracy_widget()

    cards = [str(c.args[0]) for c in st.markdown.call_args_list
             if c.args and "<div" in str(c.args[0])]
    assert len(cards) == 2, cards
    assert "Steady" in cards[0] and "🥇" in cards[0]
    assert "100%" not in cards[1] and "🥇" not in cards[1]


def _fake_brief_db(rows_by_id):
    """`vnstock_memory._conn()` giả: chỉ trả hàng khi truy vấn ĐÚNG id."""
    from contextlib import contextmanager

    class _Cur:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _Conn:
        def execute(self, sql, params=()):
            return _Cur(next((rows_by_id[p] for p in params if p in rows_by_id), None))

    @contextmanager
    def _conn():
        yield _Conn()
    return _conn


def test_brief_runner_rating_uses_returned_brief_id(render_env, monkeypatch):
    """Brief lưu theo ngày PHIÊN, ô ⭐ cũ dò theo `now().date()` ⇒ T7/CN (hay
    sau nửa đêm) ô chấm sao im lặng biến mất. Id đã có sẵn ở `_brief_ids`."""
    import vnstock_stance_track
    monkeypatch.setattr(vnstock_stance_track, "summary_line", lambda *a, **k: None)
    monkeypatch.setattr(sys.modules["vnstock_memory"], "_conn",
                        _fake_brief_db({7: {"id": 7, "user_rating": None}}))
    st = render_env
    st.session_state["_brief_results"] = {"A": ("brief text", None),
                                          "_brief_ids": {"A": 7}}
    st.session_state["_brief_type"] = "afternoon"
    keys = []
    st.select_slider = lambda label, options=(), value=None, key=None, **k: (
        keys.append(key) or value)

    _load("dashboard.brief_run_panel").render_brief_runner()

    assert "_rate_7_v" in keys


def _said_captions(st):
    said = []
    st.caption = lambda *a, **k: said.append(str(a[0]) if a else "")
    return said


def test_strategy_panel_reports_broken_block_instead_of_hiding(render_env, monkeypatch):
    """Khối con lỗi từng `except: pass` ⇒ kiểm định / tầng vị thế biến mất
    không dấu vết. Phải hạ xuống caption "disabled" kèm lỗi."""
    import vnstock_strategy
    monkeypatch.setattr(vnstock_strategy, "strategy_health",
                        lambda *a, **k: {"state": "insufficient"})
    mem = sys.modules["vnstock_memory"]
    monkeypatch.setattr(mem, "get_active_family", lambda *a, **k: {
        "id": 1, "name": "S1", "family_id": "f1", "params_json": "{}"})

    def _boom(*a, **k):
        raise RuntimeError("db hỏng")
    monkeypatch.setattr(mem, "latest_backtest", _boom)
    said = _said_captions(render_env)

    _load("dashboard.brief_strategy_panel").render_strategy_panel()

    assert [s for s in said if "disabled" in s and "db hỏng" in s], said


def test_brief_runner_reports_broken_stance_track(render_env, monkeypatch):
    import vnstock_stance_track

    def _boom(*a, **k):
        raise RuntimeError("sổ stance hỏng")
    monkeypatch.setattr(vnstock_stance_track, "summary_line", _boom)
    st = render_env
    st.session_state["_brief_results"] = {"A": ("brief text", None)}
    said = _said_captions(st)

    _load("dashboard.brief_run_panel").render_brief_runner()

    assert [s for s in said if "disabled" in s and "sổ stance hỏng" in s], said


def _markdowns(st):
    return [str(c.args[0]) for c in st.markdown.call_args_list if c.args]


def test_top_volume_card_picks_the_highest_vol20_sector(render_env, monkeypatch):
    """Bảng ngành sắp theo VỐN HOÁ, nên `iloc[0]` là ngành vốn hoá lớn nhất chứ
    không phải ngành KLGD cao nhất. Thẻ phải chọn theo "Vol Avg 20"."""
    sectors = _sector_df()
    sectors["Vol Avg 20"] = [1.0, 50.0, 3.0]          # max ở dòng 2, không phải dòng đầu
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(sectors, _index_df()))
    st = render_env
    _load("dashboard.market_tab").render_market_tab()

    card = [m for m in _markdowns(st) if "Ngành KLGD cao nhất" in m]
    assert card and "Thép & Kim" in card[0] and "Vol 20: 50M cp" in card[0], card


@needs("plotly")  # chart ngành chỉ vẽ khi có plotly (market_tab ~1182)
def test_sector_price_chart_does_not_clip_large_moves(render_env, monkeypatch):
    """Trục x cố định [-30, 30] cắt mất ngành chạy ±42% khỏi khung."""
    sectors = _sector_df()
    sectors["Giá 1M %"] = [42.0, -5.0, 3.0]
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(sectors, _index_df()))
    st = render_env
    _load("dashboard.market_tab").render_market_tab()

    bars = [c.args[0] for c in st.plotly_chart.call_args_list
            if c.args and any(getattr(t, "orientation", None) == "h" for t in c.args[0].data)]
    assert bars, "Không thấy chart biến động giá theo ngành"
    lo, hi = bars[0].layout.xaxis.range
    assert lo <= -42 and hi >= 42


def test_index_table_title_matches_rows_shown(render_env, monkeypatch):
    """Tiêu đề ghi "(30 phiên)" trong khi bảng chỉ in 20 dòng."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_dashboard(None, _index_df()))
    st = render_env
    _load("dashboard.market_tab").render_market_tab()

    title = [m for m in _markdowns(st) if "Diễn biến chỉ số thị trường" in m]
    assert title == ["#### 📈 Diễn biến chỉ số thị trường (20 phiên)"]


def test_regime_failure_is_visible_not_silent(render_env, monkeypatch):
    """`except Exception: pass` làm khối regime biến mất im lặng — user không
    phân biệt được "không có regime" với "regime hỏng"."""
    reg = types.ModuleType("vnstock_regime")

    def _boom():
        raise RuntimeError("boom")
    reg.load_regime = _boom
    monkeypatch.setitem(sys.modules, "vnstock_regime", reg)
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_dashboard())
    st = render_env
    said = []
    st.caption = lambda *a, **k: said.append(str(a[0]) if a else "")
    _load("dashboard.market_tab").render_market_tab()

    assert "⚠️ Market regime lỗi: RuntimeError: boom" in said, said


@pytest.mark.parametrize("fresh,expect", [
    ({"reason": "intraday", "overview_time": "11:02", "overview_date": "2026-10-16"},
     "chốt giữa phiên 11:02"),
    ({"reason": "prev_session", "overview_time": "15:30", "overview_date": "2026-10-15"},
     "phiên trước (2026-10-15)"),
])
def test_freshness_badge_flags_intraday_and_previous_session(render_env, monkeypatch,
                                                             fresh, expect):
    """Bất biến CLAUDE.md: overview cùng phiên mà chốt trước 15:05 là GIỮA PHIÊN
    ⇒ stale. Badge cũ chỉ so mtime với 24h nên file ghi lúc 11:00 trông "tươi"."""
    import vnstock_brief as vb
    monkeypatch.setattr(vb, "market_data_freshness", lambda *a, **k: {
        "stale": True, "data_date": "2026-10-16", "stale_blocks": [], **fresh})
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_dashboard())
    st = render_env
    said = []
    st.caption = lambda *a, **k: said.append(str(a[0]) if a else "")
    _load("dashboard.market_tab").render_market_tab()

    assert [s for s in said if expect in s], said


def test_custom_group_row_gets_a_sparkline(render_env, monkeypatch):
    """Sparkline gom mã theo cột `Ngành` GỐC nên dòng nhóm tuỳ biến ("Họ VIN")
    luôn hiện "—" dù có đủ giá VIC/VHM."""
    sectors = _sector_df()
    sectors.loc[0, "Ngành"] = "Họ VIN"
    idx = _index_df()
    stub = _stub_dashboard(sectors, idx)
    stub.load_price_history = lambda tk, days=0: pd.DataFrame(
        {"time": idx["time"], "close": np.linspace(100, 130, len(idx))})
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", stub)

    ticks = _ticker_df()
    ticks["Mã"] = ["VIC", "VHM", "FPT"]
    ticks["Ngành"] = ["Bất động sản", "Bất động sản", "Công nghệ"]
    ticks["Vốn hoá (tỷ)"] = [400_000.0, 300_000.0, 200_000.0]
    st = render_env
    st.session_state["_mkt_ticker_data"] = ticks
    _load("dashboard.market_tab").render_market_tab()

    tbl = [m for m in _markdowns(st) if "α 30d vs VNINDEX" in m]
    assert tbl, "Bảng ngành không có cột sparkline"
    row = [r for r in tbl[0].split("<tr") if "Họ VIN" in r]
    assert row and "<svg" in row[0], "Dòng Họ VIN không có sparkline"


def test_quant_filters_load_once_per_render_with_drilldown_open(render_env, monkeypatch):
    """Drill-down + nhận định từng đọc sổ cách ly / sổ cổ tức MỖI BÊN một lần
    (2 lượt đọc đĩa mỗi rerun). Nạp một lần trong render rồi truyền xuống."""
    from collections import Counter
    calls = Counter()
    ma = sys.modules["vnstock_market_analyzer"]
    monkeypatch.setattr(ma, "load_quarantine_tickers",
                        lambda: calls.update(["quarantine"]) or set(), raising=False)
    monkeypatch.setattr(ma, "load_recent_exdiv",
                        lambda days_back=7: calls.update(["exdiv"]) or {}, raising=False)
    monkeypatch.setattr(sys.modules["vnstock_session_stats"], "load_session_stats_history",
                        lambda *a, **k: calls.update(["session"]) or {}, raising=False)
    # Fake analyzer thiếu hàm này + trả dict ⇒ drill-down ném TRƯỚC khi tới loader.
    monkeypatch.setattr(ma, "_sector_technical_summary", lambda df, presets: "", raising=False)
    monkeypatch.setattr(ma, "compute_scores", lambda df, **k: pd.DataFrame(
        {"composite": np.linspace(1, -1, len(df))}, index=df.index))
    import vnstock_brief as vb   # badge độ tươi đọc session stats khi kho trống — tách ra
    monkeypatch.setattr(vb, "market_data_freshness", lambda *a, **k: {"stale": False})
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(_sector_df(), _index_df()))
    st = render_env
    st.session_state["_mkt_ticker_data"] = _ticker_df()
    st.selectbox = lambda label, options=(), **k: (
        "Ngân hàng" if "ngành" in str(label).lower() and "Ngân hàng" in list(options)
        else (list(options)[0] if len(options) else None))
    _load("dashboard.market_tab").render_market_tab()

    assert calls == {"quarantine": 1, "exdiv": 1, "session": 1}, calls

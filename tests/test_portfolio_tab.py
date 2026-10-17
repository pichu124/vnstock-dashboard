"""Smoke tests for dashboard.portfolio_tab — the Streamlit UI is tested
manually; this file covers the non-UI helpers, the import path, and the write
guard when portfolio.json is corrupt or cannot be written (fake Streamlit)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.conftest import needs


def test_module_imports_without_streamlit():
    """The tab module must be importable even when Streamlit is not
    available — Streamlit is only imported inside render_portfolio_tab."""
    import importlib
    mod = importlib.import_module("dashboard.portfolio_tab")
    assert hasattr(mod, "render_portfolio_tab")
    assert callable(mod.render_portfolio_tab)


def test_load_portfolio_returns_empty_when_file_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio
    assert _load_portfolio(tmp_path) == []


def test_load_portfolio_raises_on_corrupt_file(tmp_path: Path):
    """File hỏng KHÔNG được đọc thành [] — nút Thêm/Xoá sẽ ghi đè cả danh mục."""
    from dashboard.portfolio_tab import _load_portfolio
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "portfolio.json").write_text("{not valid json")
    with pytest.raises(ValueError):
        _load_portfolio(tmp_path)


def test_save_load_round_trip(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    positions = [
        {"ticker": "VCB", "quantity": 100, "buy_price": 90000,
         "buy_date": "2026-01-15"},
        {"ticker": "FPT", "quantity": 50, "buy_price": 120000,
         "buy_date": "2026-02-01"},
    ]
    _save_portfolio(tmp_path, positions)
    assert _load_portfolio(tmp_path) == positions


def test_save_is_atomic_and_raises_on_failure(tmp_path: Path, monkeypatch):
    """Ghi lỗi phải RAISE (tab báo st.error) — không nuốt im lặng; file cũ giữ nguyên."""
    from dashboard.portfolio_tab import _save_portfolio, _portfolio_path
    import os as _os
    import vnstock_parquet_io as pio

    _save_portfolio(tmp_path, [{"ticker": "FPT"}])
    before = _portfolio_path(tmp_path).read_bytes()

    def _fail(_a, _b):
        raise OSError("disk full")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(_os, "replace", _fail)
    with pytest.raises(OSError):
        _save_portfolio(tmp_path, [{"ticker": "VCB"}])
    monkeypatch.undo()

    assert _portfolio_path(tmp_path).read_bytes() == before
    assert not any(p.name.startswith("portfolio") and p.suffix.endswith(".tmp")
                   for p in (tmp_path / "_meta").glob("*"))


def test_live_quote_returns_none_when_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    assert _live_quote("XYZ", tmp_path) is None


def test_live_quote_parses_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text(json.dumps({
        "ticker": "VCB", "price": 91000, "ts": "2026-04-22T10:00:00",
    }))
    q = _live_quote("VCB", tmp_path)
    assert q is not None
    assert q["price"] == 91000


def test_live_quote_handles_corrupt_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text("not-json")
    assert _live_quote("VCB", tmp_path) is None


# ── tripwire ⚠ sai đơn vị giá (review 21/07: tách hàm thuần + nới ngưỡng) ──

def test_unit_suspect_same_day_thousandfold_loss():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", -99.7) is True


def test_unit_suspect_same_day_thousandfold_gain():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", 99_900.0) is True


def test_unit_suspect_legit_bands_not_flagged():
    """HOSE ±7% · HNX ±10% · UPCoM ±15% · chào sàn ±40% · mua đáy −N% đóng
    trần +N% — tất cả là %L/L cùng-ngày HỢP LỆ, không được dán nhãn 'gần như
    chắc chắn sai' như ngưỡng ±7.5% cũ."""
    from dashboard.portfolio_tab import _unit_suspect
    for pct in (6.9, -9.8, 14.9, -15.0, 39.9, -40.0, 42.0, 133.0):
        assert _unit_suspect("2026-07-21", "2026-07-21", pct) is False, pct


def test_unit_suspect_only_fires_on_buy_day():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-18", "2026-07-21", -99.7) is False
    assert _unit_suspect("", "2026-07-21", -99.7) is False
    assert _unit_suspect("2026-07-21", "", -99.7) is False


# ── trục X chart NAV (review 21/07: tách hàm thuần cho nhánh dtick) ────────

def test_nav_xaxis_short_series_forces_daily_dtick():
    from dashboard.portfolio_tab import _nav_xaxis
    x = _nav_xaxis(5)
    assert x["dtick"] == 86_400_000
    assert x["tickformat"] == "%d/%m"
    assert x["rangebreaks"] == [{"bounds": ["sat", "mon"]}]


def test_nav_xaxis_long_series_keeps_auto_ticks():
    from dashboard.portfolio_tab import _nav_xaxis
    assert "dtick" not in _nav_xaxis(11)
    assert _nav_xaxis(11)["tickformat"] == "%d/%m"


# ── File hỏng / ghi lỗi không được làm mất danh mục (Dropbox đẩy sang máy kia) ──

class _Rerun(Exception):
    """st.rerun thật dừng script bằng exception — giả lập đúng như vậy."""


def _render_clicking(monkeypatch, warehouse: Path, click: str = "pf_add",
                     confirm_clear: bool = False):
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.button = lambda label, key=None, **k: key == click and not k.get("disabled")
    st.checkbox = lambda label, key=None, **k: confirm_clear and key == "pf_clear_confirm"
    st.text_input = lambda label, **k: "VCB" if k.get("key") == "pf_ticker" else ""
    st.number_input = lambda label, min_value=0, max_value=None, value=0, **k: (
        25_000.0 if k.get("key") == "pf_price" else value)

    def _rerun():
        raise _Rerun

    st.rerun = _rerun
    monkeypatch.setitem(sys.modules, "streamlit", st)
    from dashboard.portfolio_tab import render_portfolio_tab
    try:
        render_portfolio_tab(warehouse)
    except _Rerun:
        pass
    return st


def test_corrupt_portfolio_blocks_writes_and_keeps_bytes(tmp_path: Path, monkeypatch):
    from dashboard.portfolio_tab import _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    truncated = b'[\n  {\n    "ticker": "HPG",\n    "quantity": 1000,\n    "buy_pr'
    path.write_bytes(truncated)

    st = _render_clicking(monkeypatch, tmp_path)

    assert path.read_bytes() == truncated                    # không ghi đè bằng [] + 1 vị thế
    assert sorted(p.name for p in path.parent.iterdir()) == ["portfolio.json"]   # không đổi tên/xoá
    assert str(path) in st.error.call_args.args[0]


def test_portfolio_save_failure_is_reported(tmp_path: Path, monkeypatch):
    from dashboard.portfolio_tab import _portfolio_path
    import os as _os
    import vnstock_parquet_io as pio

    def _fail(_a, _b):
        raise OSError("file đang bị khoá")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(_os, "replace", _fail)
    st = _render_clicking(monkeypatch, tmp_path)

    assert not _portfolio_path(tmp_path).exists()
    msg = st.error.call_args.args[0]
    assert str(_portfolio_path(tmp_path)) in msg and "file đang bị khoá" in msg


@pytest.mark.parametrize("confirm", [False, True])
def test_clear_all_requires_confirmation(tmp_path: Path, monkeypatch, confirm: bool):
    """"🗑 Xoá tất cả" từng xoá sạch ngay cú bấm đầu: chưa tick xác nhận thì không ghi."""
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    _save_portfolio(tmp_path, [_LOT_A, _LOT_B])

    _render_clicking(monkeypatch, tmp_path, click="pf_clear", confirm_clear=confirm)

    assert _load_portfolio(tmp_path) == ([] if confirm else [_LOT_A, _LOT_B])


# ── Xoá vị thế: theo VỊ TRÍ dòng, không theo nhãn ───────────────────────────

class _WidgetState(dict):
    """session_state giả: như Streamlit, ghi key của widget ĐÃ VẼ trong lượt này thì ném."""

    def __init__(self):
        super().__init__()
        self.drawn: set = set()

    def __setitem__(self, key, value):
        if key in self.drawn:
            raise RuntimeError(f"StreamlitAPIException: `{key}` đã vẽ trong lượt này")
        super().__setitem__(key, value)


class _DeleteFlow:
    """Chạy tab nhiều lượt với đủ ngữ nghĩa Streamlit cho selectbox + nút Xoá:
    selectbox giữ lựa chọn trong state theo key; callback `on_click` chạy ĐẦU lượt
    kế (trước script) và nút trả True đúng lượt đó; chỉ bấm trúng nút ĐANG HIỆN;
    st.rerun mở lượt mới không bấm gì."""

    def __init__(self, monkeypatch, warehouse: Path):
        from tests.test_tab_render_smoke import _fake_streamlit
        self.st = st = _fake_streamlit()
        st.session_state = _WidgetState()
        st.selectbox, st.button, st.rerun = self._selectbox, self._button, self._rerun
        self.labels: list = []
        self.shown: dict = {}
        self._warehouse, self._clicked = warehouse, None
        monkeypatch.setitem(sys.modules, "streamlit", st)

    def _selectbox(self, label, options=(), format_func=str, key=None, **k):
        options = list(options)
        if key != "pf_del_select":
            return options[0] if options else None
        self.labels = [format_func(o) for o in options]
        state = self.st.session_state
        value = state.get(key, options[0])
        dict.__setitem__(state, key, value if value in options else options[0])
        state.drawn.add(key)
        return state[key]

    def _button(self, label, key=None, on_click=None, args=(), kwargs=None, **k):
        self.shown[key] = (on_click, args, kwargs or {})
        return key == self._clicked

    @staticmethod
    def _rerun():
        raise _Rerun

    def pick(self, index):
        """User chọn dòng `index` trong selectbox (lượt chạy kế tiếp sẽ thấy)."""
        dict.__setitem__(self.st.session_state, "pf_del_select", index)

    def run(self, click=None):
        from dashboard.portfolio_tab import render_portfolio_tab
        while True:
            shown, self.shown = self.shown, {}
            self._clicked = click if click in shown else None    # nút đã ẩn ⇒ bấm hụt
            self.st.session_state.drawn.clear()
            if self._clicked and shown[self._clicked][0] is not None:
                cb, args, kwargs = shown[self._clicked]
                cb(*args, **kwargs)
            try:
                return render_portfolio_tab(self._warehouse)
            except _Rerun:
                click = None


def test_delete_second_of_two_identical_labels_keeps_first(tmp_path: Path, monkeypatch):
    """Hai lô cùng mã/số lượng/giá (khác ngày mua) có CÙNG nhãn trong selectbox;
    `_options.index(nhãn)` trả lô ĐẦU ⇒ chọn xoá lô thứ hai lại xoá lô đầu."""
    from dashboard.portfolio_tab import _portfolio_path, _save_portfolio, _load_portfolio
    lot1 = {"ticker": "VCB", "quantity": 100, "buy_price": 90000, "buy_date": "2026-01-15"}
    lot2 = {"ticker": "VCB", "quantity": 100, "buy_price": 90000, "buy_date": "2026-03-02"}
    lot3 = {"ticker": "FPT", "quantity": 50, "buy_price": 120000, "buy_date": "2026-02-01"}
    _save_portfolio(tmp_path, [lot1, lot2, lot3])

    flow = _DeleteFlow(monkeypatch, tmp_path)
    flow.run()
    shown = flow.labels
    flow.pick(1)                                                # [—, lô 1, LÔ 2, lô 3]
    flow.run()
    flow.run(click="pf_del_btn")

    assert _portfolio_path(tmp_path).exists()
    assert _load_portfolio(tmp_path) == [lot1, lot3]
    # Fake selectbox giữ thẳng option, bỏ qua serde; Streamlit thật lưu lựa chọn bằng
    # NHÃN ⇒ nhãn trùng thì không xoá được lô đầu (test serde thật ngay dưới).
    assert shown == ["—", "VCB (100 cp @ 90,000) · mua 2026-01-15 · #1",
                     "VCB (100 cp @ 90,000) · mua 2026-03-02 · #2",
                     "FPT (50 cp @ 120,000) · mua 2026-02-01 · #3"]
    assert len(set(shown)) == len(shown)


_LOT_A = {"ticker": "AAA", "quantity": 100, "buy_price": 10000, "buy_date": "2026-01-02"}
_LOT_B = {"ticker": "BBB", "quantity": 200, "buy_price": 20000, "buy_date": "2026-01-03"}
_LOT_C = {"ticker": "CCC", "quantity": 300, "buy_price": 30000, "buy_date": "2026-01-04"}
_LOT_D = {"ticker": "DDD", "quantity": 400, "buy_price": 40000, "buy_date": "2026-01-05"}


def _flow_with_b_selected(monkeypatch, warehouse: Path) -> _DeleteFlow:
    from dashboard.portfolio_tab import _save_portfolio
    _save_portfolio(warehouse, [_LOT_A, _LOT_B, _LOT_C])
    flow = _DeleteFlow(monkeypatch, warehouse)
    flow.run()
    flow.pick(1)                                                # B (#2)
    flow.run()
    assert "pf_del_btn" in flow.shown
    return flow


def test_delete_double_click_does_not_drop_next_lot(tmp_path: Path, monkeypatch):
    """[A, B, C], chọn B, bấm Xoá. Trước đây selectbox vẫn giữ chỉ số 1 — giờ là C —
    và nút Xoá vẫn hiện ⇒ cú bấm thứ hai của bấm đúp xoá luôn C."""
    from dashboard.portfolio_tab import _load_portfolio, _portfolio_path
    flow = _flow_with_b_selected(monkeypatch, tmp_path)

    flow.run(click="pf_del_btn")
    assert _load_portfolio(tmp_path) == [_LOT_A, _LOT_C]
    flow.run(click="pf_del_btn")

    assert _load_portfolio(tmp_path) == [_LOT_A, _LOT_C]
    assert flow.st.session_state["pf_del_select"] is None
    assert "pf_del_btn" not in flow.shown
    msgs = [c.args[0] for c in flow.st.error.call_args_list]
    assert not [m for m in msgs if str(_portfolio_path(tmp_path)) in m], msgs


def test_delete_keeps_lot_added_on_disk_after_render(tmp_path: Path, monkeypatch):
    """Lúc bấm Xoá phải đọc LẠI file: lô D máy kia vừa thêm (Dropbox) sau lượt vẽ
    vẫn còn, không bị bản chụp lúc vẽ ghi đè."""
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    flow = _flow_with_b_selected(monkeypatch, tmp_path)
    _save_portfolio(tmp_path, [_LOT_A, _LOT_B, _LOT_C, _LOT_D])

    flow.run(click="pf_del_btn")

    assert _load_portfolio(tmp_path) == [_LOT_A, _LOT_C, _LOT_D]


@pytest.mark.parametrize("failure", ["ghi", "đọc lại"])
def test_delete_failure_keeps_portfolio_and_selection(tmp_path: Path, monkeypatch, failure):
    """Ghi lỗi (Dropbox giữ file) hoặc đọc lại lỗi ⇒ báo st.error kèm đường dẫn, đĩa
    giữ nguyên, selectbox GIỮ lựa chọn để bấm lại."""
    import os as _os
    import vnstock_parquet_io as pio
    from dashboard.portfolio_tab import _portfolio_path
    flow = _flow_with_b_selected(monkeypatch, tmp_path)
    path = _portfolio_path(tmp_path)
    before = path.read_bytes()

    def _locked(*_a, **_k):
        raise OSError("file đang bị khoá")

    if failure == "ghi":
        monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
        monkeypatch.setattr(_os, "replace", _locked)
    else:                                       # lần đọc ĐẦU (lúc bấm) lỗi, lượt vẽ đọc được
        real_read_text, calls = Path.read_text, []

        def _read_once_locked(self, *a, **k):
            if self == path and not calls:
                calls.append(self)
                _locked()
            return real_read_text(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", _read_once_locked)

    flow.run(click="pf_del_btn")

    assert path.read_bytes() == before
    assert flow.st.session_state["pf_del_select"] == 1
    assert "pf_del_btn" in flow.shown
    msgs = [c.args[0] for c in flow.st.error.call_args_list]
    assert any(str(path) in m and "file đang bị khoá" in m for m in msgs), msgs


def _assert_refused(flow: _DeleteFlow) -> None:
    msgs = [c.args[0] for c in flow.st.error.call_args_list]
    assert any("vừa thay đổi" in m and "chưa xoá gì" in m for m in msgs), msgs
    assert flow.st.session_state["pf_del_select"] is None


def test_delete_refuses_when_lot_shifted_on_disk(tmp_path: Path, monkeypatch):
    """Vẽ [A, B, C], chọn B (#2). Trước khi bấm, máy kia/tab khác xoá A ⇒ file [B, C].
    Chỉ số 1 chốt lúc vẽ giờ là C: bấm Xoá KHÔNG được xoá C, phải báo và bỏ chọn."""
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    flow = _flow_with_b_selected(monkeypatch, tmp_path)
    _save_portfolio(tmp_path, [_LOT_B, _LOT_C])

    flow.run(click="pf_del_btn")

    assert _load_portfolio(tmp_path) == [_LOT_B, _LOT_C]
    _assert_refused(flow)


def test_delete_callback_replayed_does_not_drop_next_lot(tmp_path: Path, monkeypatch):
    """Bấm đúp khi lượt chạy chưa xong: Streamlit bỏ bước dọn widget (`premature_stop`)
    nên gọi LẠI callback cũ với cùng args trên file đã thành [A, C] ⇒ không được xoá C."""
    from dashboard.portfolio_tab import _load_portfolio
    flow = _flow_with_b_selected(monkeypatch, tmp_path)
    callback, args, kwargs = flow.shown["pf_del_btn"]
    flow.st.session_state.drawn.clear()                         # callback chạy trước script

    callback(*args, **kwargs)
    assert _load_portfolio(tmp_path) == [_LOT_A, _LOT_C]
    callback(*args, **kwargs)

    assert _load_portfolio(tmp_path) == [_LOT_A, _LOT_C]
    _assert_refused(flow)


def test_delete_refuses_without_rewrite_when_file_shrank(tmp_path: Path, monkeypatch):
    """Chọn B (chỉ số 1) rồi file co còn [A] ⇒ chỉ số vượt độ dài: từ chối, KHÔNG ghi lại
    file (ghi lại [A] cùng nội dung vẫn đè bản Dropbox đang tới)."""
    import os as _os
    from dashboard.portfolio_tab import _portfolio_path, _save_portfolio
    flow = _flow_with_b_selected(monkeypatch, tmp_path)
    _save_portfolio(tmp_path, [_LOT_A])
    path = _portfolio_path(tmp_path)
    _os.utime(path, (1_000_000_000, 1_000_000_000))
    before = path.read_bytes()

    flow.run(click="pf_del_btn")

    assert path.read_bytes() == before
    assert path.stat().st_mtime == 1_000_000_000
    _assert_refused(flow)


# Chạy trong process RIÊNG: `tests/test_dashboard.py` gắn MagicMock vào sys.modules["streamlit"]
# ngay lúc pytest thu thập ⇒ chạy cả suite thì không import được `streamlit.elements…` thật,
# còn gỡ mock ngay trong process pytest thì module thật lọt sang test khác.
_SERDE_ROUND_TRIP = """
import json, sys
from streamlit.elements.lib.options_selector_utils import create_mappings
from streamlit.elements.widgets.selectbox import SelectboxSerde
pairs = json.loads(sys.argv[1])
opts = [o for o, _ in pairs]
label_of = {json.dumps(o): lbl for o, lbl in pairs}
fmt = lambda o: label_of[json.dumps(o)]
labels, label_to_index = create_mappings(opts, fmt)
serde = SelectboxSerde(opts, formatted_options=labels,
                       formatted_option_to_option_index=label_to_index,
                       default_option_index=0, format_func=fmt)
print(json.dumps([serde.deserialize(serde.serialize(o)) for o in opts]))
"""


@needs("streamlit")
def test_delete_options_round_trip_through_real_streamlit_serde(tmp_path: Path, monkeypatch):
    """Streamlit 1.56 serialize selectbox bằng NHÃN đã format (`create_mappings`: nhãn
    trùng thì cái sau thắng). Hai lô cùng nhãn ⇒ chọn lô 1 deserialize ra lô 2, lô 1
    không bao giờ xoá được. Lấy đúng options + nhãn tab đưa vào selectbox rồi đi qua
    serde THẬT: mọi lựa chọn phải về đúng nó."""
    import subprocess
    from tests.test_tab_render_smoke import _fake_streamlit
    from dashboard.portfolio_tab import _save_portfolio
    lot = {"ticker": "VCB", "quantity": 100, "buy_price": 90000, "buy_date": "2026-01-15"}
    _save_portfolio(tmp_path, [lot, dict(lot), {**lot, "buy_date": ""}, dict(lot, buy_date="")])

    st = _fake_streamlit()
    seen: dict = {}

    def _selectbox(label, options=(), format_func=str, **k):
        options = list(options)
        if k.get("key") == "pf_del_select":
            seen["pairs"] = [[o, format_func(o)] for o in options]
        return options[0] if options else None

    st.selectbox = _selectbox
    monkeypatch.setitem(sys.modules, "streamlit", st)
    from dashboard.portfolio_tab import render_portfolio_tab
    render_portfolio_tab(tmp_path)

    opts = [o for o, _ in seen["pairs"]]
    assert opts == [None, 0, 1, 2, 3]
    run = subprocess.run([sys.executable, "-I", "-c", _SERDE_ROUND_TRIP,
                          json.dumps(seen["pairs"])],
                         capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.strip().splitlines()[-1]) == opts


# ── Vị thế chưa có giá (gõ sai mã, mã chưa có bar): không phải lỗ −100% ─────

def test_position_without_price_is_left_out_of_totals(tmp_path: Path, monkeypatch):
    """Danh mục 500 triệu: AAA 450 triệu có giá (+10%), ZZZ 50 triệu không nguồn giá nào.
    Trước đây ZZZ tính giá trị 0 ⇒ dòng −100% và tổng Lãi/Lỗ −5 triệu thay vì +45 triệu."""
    import re
    from tests.test_tab_render_smoke import _fake_streamlit
    from dashboard.portfolio_tab import _save_portfolio, render_portfolio_tab
    _save_portfolio(tmp_path, [
        {"ticker": "AAA", "quantity": 45_000, "buy_price": 10_000, "buy_date": "2026-01-02"},
        {"ticker": "ZZZ", "quantity": 5_000, "buy_price": 10_000, "buy_date": "2026-01-02"}])
    (tmp_path / "_live").mkdir()
    (tmp_path / "_live" / "quote_AAA.json").write_text(
        json.dumps({"price": 11_000, "time": "2026-10-16T14:45:00"}))
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)

    render_portfolio_tab(tmp_path)

    html = " ".join(str(c.args[0]) for c in st.markdown.call_args_list)
    cards = dict(re.findall(r'<div class="label">(.*?)</div><div class="value"[^>]*>(.*?)</div>',
                            html))
    assert cards == {"Vốn đầu tư": "450,000,000", "Giá trị hiện tại": "495,000,000",
                     "Lãi/Lỗ": "+45,000,000", "% Lãi/Lỗ": "+10.00%"}
    zzz = next(r for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html) if ">ZZZ<" in r)
    assert re.findall(r"<td[^>]*>(.*?)</td>", zzz) == [
        "ZZZ", "5,000", "10,000", "—", "50,000,000", "—", "—", "—", "2026-01-02"]
    captions = [c.args[0] for c in st.caption.call_args_list]
    assert any("1 vị thế chưa có giá" in c and "ZZZ" in c for c in captions), captions


# ── JSON hợp lệ nhưng SAI DẠNG: cũng là file hỏng, không phải danh mục ──────

_WRONG_SHAPE = ["null",                                          # gốc không phải list
                '[{"ticker": "VCB", "quantity": 100}, 1]',       # phần tử không phải dict
                '{"ticker": "VCB", "quantity": 100}']            # dict thay vì list


@pytest.mark.parametrize("payload", _WRONG_SHAPE)
def test_load_portfolio_rejects_wrong_shape(tmp_path: Path, payload: str):
    from dashboard.portfolio_tab import _load_portfolio, _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="sai định dạng"):
        _load_portfolio(tmp_path)


@pytest.mark.parametrize("payload", _WRONG_SHAPE)
def test_wrong_shape_portfolio_blocks_writes(tmp_path: Path, monkeypatch, payload: str):
    """Trước đây lọt qua `_load_portfolio` rồi chết TypeError giữa render
    (`None + [...]`, `1["ticker"]`) thay vì báo file hỏng."""
    from dashboard.portfolio_tab import _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()

    st = _render_clicking(monkeypatch, tmp_path)

    assert path.read_bytes() == before
    assert str(path) in st.error.call_args.args[0]

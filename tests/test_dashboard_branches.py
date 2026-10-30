"""Các nhánh LỘ RA sau khi gỡ replica (đợt 2, 12/08).

Replica trong `tests/test_dashboard.py` là bản chép tay ĐÃ TRÔI, nên có nguyên
một mảng nhánh chưa từng ai kiểm:

* `compute_indicators`: nhánh `rsi.where(loss != 0, 100.0)` — chính là bản vá
  cho bất biến "4 panel cùng số bar"; và cả khối VWAP intraday (reset theo
  phiên) mà replica không có lấy một dòng.
* `cell_color`: nhánh `Trend` / `Ticker` / `Ngành` và hai bậc RSI mềm 40/60.
* `cell_weight`: nhánh MACD BUY/SELL.
* `normalize_price_units`: nhánh thiếu cột OHLC.
* `watchlist_io`: ghi nguyên tử — file cũ phải sống sót khi ghi hỏng.

Đây mới là phần trả lại giá trị thật của việc gỡ replica: không phải "test
xanh", mà là "test cuối cùng cũng SOI đúng đồ đang chạy".
"""
import ast
import copy
import json
import logging
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashboard.chart_indicators import compute_indicators
from dashboard.table_style import cell_color, cell_weight
from dashboard.theme import TOKENS as T, font_face_css, lwc_palette
from dashboard.watchlist_io import load_watchlist, save_watchlist
from vnstock_console_launch import build_ps_command
from vnstock_parquet_io import write_json_atomic
from vnstock_price_units import normalize_live_price, normalize_price_units
from vnstock_sectors import SECTOR_GROUPS, SECTOR_ORDER, get_sector
from vnstock_wss import INDEX_SYMBOLS


# ── compute_indicators: RSI khi loss = 0 ────────────────────────────────────

def _rising(n: int = 40) -> pd.DataFrame:
    """Chuỗi TOÀN TĂNG — loss rolling = 0 ở mọi bar sau warmup."""
    close = np.arange(n, dtype=float) + 10
    return pd.DataFrame({
        "time": pd.bdate_range(end="2026-04-10", periods=n),
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1_000] * n,
    })


class TestRsiAllUpStreak:
    """Bất biến docs/CLAUDE-NOTES.md: panel RSI phải CÙNG SỐ BAR với panel nến.
    `loss.replace(0, NaN)` ngây thơ để lỗ hổng ở ĐUÔI chuỗi → panel auto-fit
    ngắn hơn → 4 chart lệch trục. Replica cũ giữ đúng công thức ngây thơ đó."""

    def test_rsi_is_100_not_nan_when_no_loss(self):
        rsi = compute_indicators(_rising())["rsi"]
        assert rsi.iloc[-1] == 100.0

    def test_no_nan_at_the_tail(self):
        """NaN chỉ được phép ở warmup 14 bar ĐẦU, tuyệt đối không ở đuôi."""
        rsi = compute_indicators(_rising())["rsi"]
        assert rsi.iloc[:14].isna().all()
        assert not rsi.iloc[14:].isna().any()

    def test_naive_formula_would_have_left_gaps(self):
        """Chốt lại vì sao nhánh này tồn tại: công thức cũ để NaN ở đuôi."""
        c = _rising()["close"]
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        naive = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        assert naive.iloc[-1] != naive.iloc[-1]      # NaN — bản cũ hỏng ở đây

    def test_mixed_series_keeps_normal_rsi(self):
        """Có cả tăng lẫn giảm → RSI bình thường, KHÔNG bị ép về 100."""
        rng = np.random.default_rng(7)
        n = 60
        close = 50 + np.cumsum(rng.normal(0, 0.8, n))
        df = pd.DataFrame({
            "time": pd.bdate_range(end="2026-04-10", periods=n),
            "open": close, "high": close + 0.3, "low": close - 0.3,
            "close": close, "volume": [1_000] * n,
        })
        rsi = compute_indicators(df)["rsi"].dropna()
        assert (rsi < 100).any()
        assert ((rsi >= 0) & (rsi <= 100)).all()


# ── compute_indicators: EMA chưa hội tụ ─────────────────────────────────────

class TestEmaWarmup:

    def test_long_ema_is_nan_when_series_too_short(self):
        """40 bar < span 200 → ema200 để NaN thay vì số vô nghĩa."""
        out = compute_indicators(_rising(40))
        assert out["ema200"].isna().all()
        assert out["ema50"].isna().all()
        assert not out["ema9"].isna().all()

    def test_ema_computed_when_long_enough(self):
        out = compute_indicators(_rising(250))
        assert not out["ema200"].isna().all()


# ── compute_indicators: VWAP intraday ───────────────────────────────────────

def _intraday(day_prices: dict, bars_per_day: int = 60) -> pd.DataFrame:
    """Bar 1 phút, nhiều phiên; mỗi phiên một mức giá phẳng cho dễ kiểm."""
    times, closes = [], []
    for day, price in day_prices.items():
        times.append(pd.date_range(f"{day} 09:15", periods=bars_per_day, freq="1min"))
        closes.extend([float(price)] * bars_per_day)
    t = pd.DatetimeIndex(np.concatenate([x.values for x in times]))
    c = np.array(closes)
    return pd.DataFrame({
        "time": t, "open": c, "high": c, "low": c, "close": c,
        "volume": [100] * len(c),
    })


class TestVwap:

    def test_daily_data_has_no_vwap(self):
        """VWAP vô nghĩa với bar ngày → không thêm cột (chart khỏi vẽ nhầm)."""
        assert "vwap" not in compute_indicators(_rising(100)).columns

    def test_intraday_adds_vwap_and_bands(self):
        out = compute_indicators(_intraday({"2026-04-10": 20}))
        for col in ("vwap", "vwap_upper1", "vwap_lower1",
                    "vwap_upper2", "vwap_lower2"):
            assert col in out.columns

    def test_vwap_resets_each_session(self):
        """Phiên trước giá 20, phiên sau giá 30: bar ĐẦU phiên sau phải VWAP=30.
        Nếu cumsum không reset theo ngày thì nó sẽ dính ~20 của hôm trước."""
        out = compute_indicators(_intraday({"2026-04-09": 20, "2026-04-10": 30}))
        first_bar_day2 = out["vwap"].iloc[60]
        assert first_bar_day2 == pytest.approx(30.0)

    def test_vwap_bands_ordered(self):
        out = compute_indicators(_intraday({"2026-04-10": 20}))
        valid = out.dropna(subset=["vwap_upper2", "vwap_lower2"])
        assert (valid["vwap_upper2"] >= valid["vwap_upper1"]).all()
        assert (valid["vwap_lower2"] <= valid["vwap_lower1"]).all()

    def test_row_count_unchanged(self):
        """4 panel phải CÙNG SỐ BAR — khối VWAP không được làm rơi dòng nào."""
        df = _intraday({"2026-04-09": 20, "2026-04-10": 30})
        assert len(compute_indicators(df)) == len(df)


# ── normalize_price_units: nhánh thiếu cột ──────────────────────────────────

class TestNormalizeMissingColumns:

    def test_skips_absent_ohlc_column(self):
        """Bảng chỉ có close (vd tổng hợp từ screener) không được ném KeyError."""
        df = pd.DataFrame({"close": [77_700.0], "volume": [1_000]})
        out = normalize_price_units(df)
        assert out["close"].iloc[0] == pytest.approx(77.7)
        assert list(out.columns) == ["close", "volume"]

    def test_leaves_non_price_columns_alone(self):
        """Volume thừa sức > 500 — không được đụng vào."""
        df = pd.DataFrame({"close": [77.7], "volume": [1_234_567]})
        assert normalize_price_units(df)["volume"].iloc[0] == 1_234_567


# ── cell_color: các nhánh replica không có ──────────────────────────────────

class TestCellColorUncoveredBranches:

    def test_trend_up_is_green(self):
        assert cell_color("Trend", "UP") == T["up"]

    @pytest.mark.parametrize("val", ["DOWN", "DN", "down", "dn"])
    def test_trend_down_variants_are_red(self, val):
        assert cell_color("Trend", val) == T["down"]

    def test_trend_unknown_is_neutral(self):
        assert cell_color("Trend", "SIDEWAY") == T["text_muted"]

    def test_ticker_and_industry_have_own_colors(self):
        assert cell_color("Ticker", "VCB") == T["link"]
        assert cell_color("Ngành", "Ngân hàng") == T["category"]

    def test_rsi_soft_bands(self):
        """Bậc 40/60 (cảnh báo mềm) — replica cũ nhảy thẳng từ 30 sang 70."""
        assert cell_color("RSI", "35") == T["up_soft"]
        assert cell_color("RSI", "65") == T["down_soft"]
        assert cell_color("RSI", "50") == T["text"]

    @pytest.mark.parametrize("val,expected", [
        ("BUY", T["up"]), ("BULL", T["up_soft"]),
        ("SELL", T["down"]), ("BEAR", T["down_soft"]),
        ("buy", T["up"]),
    ])
    def test_macd_palette(self, val, expected):
        assert cell_color("MACD", val) == expected

    def test_macd_unknown_is_neutral(self):
        assert cell_color("MACD", "???") == T["text_muted"]

    def test_unknown_column_gets_default(self):
        assert cell_color("Vốn hoá", "12,345") == T["text"]

    def test_empty_string_is_empty_gray(self):
        assert cell_color("Ticker", "") == T["text_faint"]


class TestCellWeightUncoveredBranches:

    def test_macd_signal_is_heavy(self):
        assert cell_weight("MACD", "BUY") == "700"
        assert cell_weight("MACD", "sell") == "700"

    def test_macd_soft_signal_is_normal(self):
        """BULL/BEAR là tín hiệu yếu hơn → không in đậm."""
        assert cell_weight("MACD", "BULL") == "400"

    def test_unknown_column_is_normal(self):
        assert cell_weight("Trend", "UP") == "400"


# ── watchlist_io: ghi nguyên tử ─────────────────────────────────────────────

class TestWatchlistAtomicity:

    def test_creates_parent_directory(self, tmp_path):
        p = tmp_path / "_meta" / "watchlist.json"
        save_watchlist(p, ["VCB"])
        assert load_watchlist(p) == ["VCB"]

    def test_crash_mid_write_keeps_old_file(self, tmp_path, monkeypatch):
        """Lỗi CỐT LÕI của `open(w)` cũ: cắt file về 0 RỒI mới ghi. Giả lập chết
        ĐÚNG lúc tráo file → watchlist cũ phải còn NGUYÊN, và không để lại rác."""
        import vnstock_parquet_io as pio

        p = tmp_path / "watchlist.json"
        save_watchlist(p, ["VCB", "FPT"])

        def _die(src, dst):
            raise RuntimeError("máy tắt giữa lúc ghi")

        monkeypatch.setattr(pio.os, "replace", _die)
        with pytest.raises(RuntimeError):
            save_watchlist(p, ["HPG"])
        monkeypatch.undo()

        assert load_watchlist(p) == ["FPT", "VCB"]
        assert not list(p.parent.glob("*.tmp"))

    def test_bad_payload_fails_before_touching_disk(self, tmp_path):
        """Payload không hợp lệ phải vỡ TRƯỚC khi đụng đĩa, không để lại nửa vời."""
        p = tmp_path / "watchlist.json"
        save_watchlist(p, ["VCB", "FPT"])

        with pytest.raises(TypeError):
            save_watchlist(p, [{"khong": "hashable"}])

        assert load_watchlist(p) == ["FPT", "VCB"]
        assert not list(p.parent.glob("*.tmp"))

    def test_stores_updated_at(self, tmp_path):
        p = tmp_path / "watchlist.json"
        save_watchlist(p, ["VCB"])
        assert "updated_at" in json.loads(p.read_text(encoding="utf-8"))

    def test_accepts_str_path(self, tmp_path):
        p = tmp_path / "watchlist.json"
        save_watchlist(str(p), ["HPG"])
        assert load_watchlist(str(p)) == ["HPG"]

    def test_missing_tickers_key_returns_empty(self, tmp_path):
        """File JSON hợp lệ nhưng sai schema → `[]`, không ném."""
        p = tmp_path / "watchlist.json"
        p.write_text('{"khac": 1}', encoding="utf-8")
        assert load_watchlist(p) == []


# ── build_ps_command: nhánh biên ────────────────────────────────────────────

class TestBuildPsCommandEdges:

    def test_empty_command_list_still_closes_window(self):
        cmd = build_ps_command([], "/usr/bin/python")
        assert "Read-Host 'Hoan tat" in cmd
        assert "if ($LASTEXITCODE -ne 0)" not in cmd

    def test_last_step_never_gets_the_guard(self):
        """Guard sau step cuối là vô nghĩa (không còn gì để dừng)."""
        cmd = build_ps_command([{"label": "A", "args": ["a.py"]}], "py")
        assert "if ($LASTEXITCODE -ne 0)" not in cmd

    def test_guard_count_matches_stop_on_error_steps(self):
        cmds = [
            {"label": "A", "args": ["a.py"]},
            {"label": "B", "args": ["b.py"], "stop_on_error": False},
            {"label": "C", "args": ["c.py"]},
            {"label": "D", "args": ["d.py"]},
        ]
        # A và C có guard; B tắt; D là cuối → 2
        assert build_ps_command(cmds, "py").count("if ($LASTEXITCODE -ne 0)") == 2

    def test_each_arg_is_quoted_separately(self):
        cmd = build_ps_command(
            [{"label": "X", "args": ["vnstock_updater.py", "--force", "--all"]}], "py")
        assert "'vnstock_updater.py' '--force' '--all'" in cmd


# ── vnstock_sectors: bất biến của bảng ngành ────────────────────────────────

class TestSectorTaxonomy:

    def test_every_group_target_is_in_display_order(self):
        """Ngành map ra một nhóm KHÔNG có trong SECTOR_ORDER = nhóm tàng hình:
        bảng ngành và biểu đồ dòng tiền sẽ lặng lẽ bỏ qua nó."""
        missing = sorted(set(SECTOR_GROUPS.values()) - set(SECTOR_ORDER))
        assert not missing, f"Nhóm không nằm trong thứ tự hiển thị: {missing}"

    def test_display_order_has_no_orphan(self):
        """Chiều ngược lại: nhóm trong SECTOR_ORDER mà không ngành nào map tới
        sẽ hiện ra rỗng mãi mãi."""
        orphan = sorted(set(SECTOR_ORDER) - set(SECTOR_GROUPS.values()))
        assert not orphan, f"Nhóm không ngành nào map tới: {orphan}"

    def test_unknown_and_empty_fall_back_to_khac(self):
        assert get_sector("Ngành trên trời") == "Khác"
        assert get_sector("") == "Khác"
        assert get_sector(None) == "Khác"


# ── vnstock_dashboard: chạy ĐÚNG hàm trong source, không import module ──────
# `vnstock_dashboard` gọi st.set_page_config + nạp .env + dựng UI ngay khi
# import nên pytest không import nổi. Trích hàm từ AST (bỏ decorator cache)
# rồi exec với globals tiêm vào: vẫn là code đang chạy, không phải bản chép tay.

_ROOT = Path(__file__).resolve().parent.parent


def load_source_fns(relpath: str, *names: str, **globs) -> dict:
    """Namespace chứa các hàm (kể cả hàm lồng) / hằng cấp module `names`.
    Tên được xin phải là DUY NHẤT trong file — trùng thì raise, không đoán bản nào."""
    tree = ast.parse((_ROOT / relpath).read_text(encoding="utf-8"))
    nodes: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            nodes.setdefault(n.name, []).append(n)
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            nodes.setdefault(n.targets[0].id, []).append(n)
    ns = dict(globs)
    for name in names:
        found = nodes[name]
        if len(found) > 1:
            raise ValueError(f"{relpath}: '{name}' được định nghĩa {len(found)} lần "
                             f"(dòng {[n.lineno for n in found]}) — không biết exec bản nào")
        node = found[0]
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
        exec(compile(ast.Module([node], []), str(_ROOT / relpath), "exec"), ns)
    return ns


def test_load_source_fns_rejects_ambiguous_name(tmp_path):
    """Hai hàm lồng CÙNG TÊN ⇒ helper phải từ chối, không im lặng exec bản đầu."""
    src = tmp_path / "fake.py"
    src.write_text('''
def outer():
    def helper():
        return 1


def other():
    def helper():
        return 2
''', encoding="utf-8")
    with pytest.raises(ValueError, match="'helper'.*2 lần"):
        load_source_fns(str(src), "helper")
    assert load_source_fns(str(src), "outer")["outer"]() is None


# ── Price alert: bắn MỘT lần, không lặp mỗi 10s ─────────────────────────────

@pytest.fixture()
def alert_env(tmp_path):
    sent: list = []

    def _send(token, chat, msg):
        sent.append(msg)
        return True

    ns = load_source_fns(
        "vnstock_dashboard.py",
        "load_alerts", "save_alerts", "check_and_fire_alerts",
        json=json, log=logging.getLogger("vnstock_dashboard"),
        ALERTS_PATH=tmp_path / "_meta" / "price_alerts.json",
        load_live_quote=lambda t: {"price": 25.5, "chg_pct": 1.0, "volume": 1e6},
        send_telegram_alert=_send, write_json_atomic=write_json_atomic,
        _normalize_live_price=normalize_live_price,
        load_price_history=lambda t, days=0: pd.DataFrame(),   # kho trống
        INDEX_SYMBOLS=INDEX_SYMBOLS,
    )
    ns["sent"] = sent
    return ns


def test_check_and_fire_alerts_returns_copies_and_leaves_input_alone(alert_env):
    alerts = [{"ticker": "VCB", "condition": "above", "target": 25.0, "fired": False}]
    before = copy.deepcopy(alerts)
    out = alert_env["check_and_fire_alerts"](alerts, "tok", "chat")
    assert alerts == before
    assert out[0]["fired"] is True
    assert out[0]["fired_price"] == 25.5


def test_alert_checker_fragment_sends_telegram_once_across_runs(alert_env):
    """Fragment chạy mỗi 10s: lượt 1 bắn + LƯU, lượt 2 đọc lại thấy đã bắn."""
    alert_env["save_alerts"](
        [{"ticker": "VCB", "condition": "above", "target": 25.0, "fired": False}])
    toasts: list = []
    st = types.SimpleNamespace(
        session_state={"_tg_token": "tok", "_tg_chat": "chat"}, toast=toasts.append)
    frag = load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
    )["_alert_checker"]
    frag()
    frag()
    assert len(alert_env["sent"]) == 1
    assert len(toasts) == 1
    assert alert_env["load_alerts"]()[0]["fired"] is True


def test_alerts_roundtrip_utf8_message(alert_env):
    """Máy cp1252: không ghi utf-8 thì 🔔/tiếng Việt ném UnicodeEncodeError."""
    al = [{"ticker": "VCB", "fired": True, "message": "🔔 <b>ALERT</b>\nĐiều kiện: giá >= 25"}]
    alert_env["save_alerts"](al)
    assert alert_env["load_alerts"]() == al


def test_save_alerts_retries_when_dropbox_holds_the_file(alert_env, monkeypatch):
    """Dropbox giữ handle price_alerts.json ⇒ os.replace ném PermissionError lần
    đầu. Không thử lại thì alert vừa bắn không được lưu ⇒ 10s sau Telegram lặp."""
    import os

    import vnstock_parquet_io as pio
    real_replace, calls = os.replace, []

    def _flaky(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(13, "Dropbox đang giữ file")
        return real_replace(src, dst)

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(os, "replace", _flaky)
    al = [{"ticker": "VCB", "fired": True, "message": "🔔 Điều kiện: giá >= 25"}]
    alert_env["save_alerts"](al)
    monkeypatch.undo()

    path = alert_env["ALERTS_PATH"]
    assert len(calls) == 2
    assert "🔔 Điều kiện" in path.read_text(encoding="utf-8")   # utf-8, không \u-escape
    assert json.loads(path.read_text(encoding="utf-8")) == al
    assert [p.name for p in path.parent.iterdir()] == ["price_alerts.json"]


# File alert hỏng (Dropbox cắt cụt) KHÔNG được đọc thành [] — "✅ Tạo alert" sẽ
# ghi đè mọi alert cũ bằng [1 alert] rồi Dropbox đẩy sang máy kia.

_TRUNCATED_ALERTS = b'[\n  {\n    "ticker": "HPG",\n    "targ'


def test_load_alerts_missing_is_empty_but_corrupt_raises(alert_env):
    assert alert_env["load_alerts"]() == []
    path = alert_env["ALERTS_PATH"]
    path.parent.mkdir(parents=True)
    path.write_bytes(_TRUNCATED_ALERTS)
    with pytest.raises(ValueError):
        alert_env["load_alerts"]()


class _Rerun(Exception):
    """st.rerun thật dừng script bằng exception — giả lập đúng như vậy."""


def _run_alert_sidebar(alert_env, **session):
    """Chạy ĐÚNG khối 🔔 Price Alerts ở sidebar analysis_tab, bấm "✅ Tạo alert"
    (nút giả tôn trọng `disabled` như Streamlit thật)."""
    from dashboard.analysis_tab import _ALERT_SAVE_FAIL_MAX
    from tests.test_tab_render_smoke import _fake_streamlit

    tree = ast.parse((_ROOT / "dashboard" / "analysis_tab.py").read_text(encoding="utf-8"))
    side = next(n for n in ast.walk(tree)
                if isinstance(n, ast.With) and "🔔 Price Alerts" in ast.unparse(n))
    start = next(i for i, n in enumerate(side.body) if "🔔 Price Alerts" in ast.unparse(n))
    st = _fake_streamlit()
    st.button = lambda label, key=None, **k: key == "alert_create" and not k.get("disabled")
    st.text_input = lambda label, **k: "VCB" if k.get("key") == "alert_ticker" else ""
    st.number_input = lambda label, **k: 25.0 if k.get("key") == "alert_target" else 0

    def _rerun():
        raise _Rerun

    st.rerun = _rerun
    st.session_state.update(session)
    ns = {"st": st, "ALERTS_PATH": alert_env["ALERTS_PATH"],
          "_ALERT_SAVE_FAIL_MAX": _ALERT_SAVE_FAIL_MAX,
          "load_alerts": alert_env["load_alerts"], "save_alerts": alert_env["save_alerts"]}
    try:
        exec(compile(ast.Module(side.body[start:], []), "analysis_tab.py", "exec"), ns)
    except _Rerun:
        pass
    return st


def test_create_alert_appends_to_existing_alerts(alert_env):
    """Đối chứng: file lành ⇒ bấm Tạo thì GIỮ alert cũ + thêm alert mới."""
    old = {"ticker": "HPG", "condition": "above", "target": 30.0, "fired": False}
    alert_env["save_alerts"]([old])
    _run_alert_sidebar(alert_env)
    al = alert_env["load_alerts"]()
    assert [a["ticker"] for a in al] == ["HPG", "VCB"]


def test_corrupt_alerts_file_blocks_create_and_keeps_bytes(alert_env):
    path = alert_env["ALERTS_PATH"]
    path.parent.mkdir(parents=True)
    path.write_bytes(_TRUNCATED_ALERTS)

    st = _run_alert_sidebar(alert_env)

    assert path.read_bytes() == _TRUNCATED_ALERTS                 # không đè bằng [1 alert]
    assert [p.name for p in path.parent.iterdir()] == ["price_alerts.json"]  # không đổi tên/xoá
    assert str(path) in st.error.call_args.args[0]


def test_alert_checker_on_corrupt_file_sends_nothing_and_writes_nothing(alert_env, caplog):
    path = alert_env["ALERTS_PATH"]
    path.parent.mkdir(parents=True)
    path.write_bytes(_TRUNCATED_ALERTS)
    st = types.SimpleNamespace(
        session_state={"_tg_token": "tok", "_tg_chat": "chat"}, toast=lambda m: None)
    frag = load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=path,
    )["_alert_checker"]

    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        frag()

    assert alert_env["sent"] == []
    assert path.read_bytes() == _TRUNCATED_ALERTS
    assert str(path) in caplog.text


# Gửi Telegram mất vài giây: file có thể đổi giữa lần đọc đầu fragment và lúc lưu.

_ALERT_A = {"ticker": "VCB", "condition": "above", "target": 25.0, "fired": False,
            "created_at": "2026-10-16T09:00:00"}
_ALERT_B = {"ticker": "HPG", "condition": "below", "target": 20.0, "fired": False,
            "created_at": "2026-10-16T09:00:05"}


def _alert_checker_sending(alert_env, while_sending):
    """`_alert_checker` thật; Telegram giả chạy `while_sending()` trước khi trả OK."""
    def _send(token, chat, msg):
        alert_env["sent"].append(msg)
        while_sending()
        return True

    alert_env["send_telegram_alert"] = _send
    st = types.SimpleNamespace(
        session_state={"_tg_token": "tok", "_tg_chat": "chat"}, toast=lambda m: None)
    return load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=alert_env["ALERTS_PATH"],
    )["_alert_checker"]


def test_alert_checker_keeps_alert_created_while_sending(alert_env):
    """User bấm "✅ Tạo alert" (B) trong lúc fragment đang gửi Telegram cho A. Lưu bản
    đọc TRƯỚC khi gửi là nuốt B không báo gì."""
    alert_env["save_alerts"]([_ALERT_A])
    frag = _alert_checker_sending(alert_env, lambda: alert_env["save_alerts"](
        [*alert_env["load_alerts"](), _ALERT_B]))

    frag()

    on_disk = alert_env["load_alerts"]()
    assert [a["ticker"] for a in on_disk] == ["VCB", "HPG"]
    fired_a, kept_b = on_disk
    assert fired_a["fired"] is True and fired_a["fired_price"] == 25.5
    assert fired_a["fired_at"] and "ALERT: VCB" in fired_a["message"]
    assert kept_b == _ALERT_B
    frag()                                                   # lượt 10s sau: A đã bắn, B chưa chạm
    assert len(alert_env["sent"]) == 1
    assert alert_env["load_alerts"]() == on_disk


def test_alert_checker_does_not_save_when_reread_fails(alert_env, caplog):
    """File hỏng (Dropbox cắt cụt) trong lúc gửi ⇒ không ghi đè; Telegram đã đi thì thôi."""
    path = alert_env["ALERTS_PATH"]
    alert_env["save_alerts"]([_ALERT_A])
    frag = _alert_checker_sending(alert_env, lambda: path.write_bytes(_TRUNCATED_ALERTS))

    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        frag()

    assert len(alert_env["sent"]) == 1
    assert path.read_bytes() == _TRUNCATED_ALERTS
    assert [p.name for p in path.parent.iterdir()] == ["price_alerts.json"]
    assert str(path) in caplog.text


def test_alert_checker_stops_telegram_while_save_keeps_failing(alert_env):
    """`write_json_atomic` hết lượt thử (Dropbox giữ file lâu) ⇒ alert không được đánh dấu
    đã bắn ⇒ cứ 10s fragment gửi lại Telegram. Từ lần lưu lỗi thứ 3 liên tiếp: ngừng gửi,
    báo đỏ; lưu lại được thì gửi tiếp."""
    alert_env["save_alerts"]([_ALERT_A])
    real_write, broken = alert_env["write_json_atomic"], [True]

    def _flaky_write(data, path):
        if broken[0]:
            raise PermissionError(13, "Dropbox đang giữ file")
        return real_write(data, path)

    alert_env["write_json_atomic"] = _flaky_write
    errors: list = []
    st = types.SimpleNamespace(session_state={"_tg_token": "tok", "_tg_chat": "chat"},
                               toast=lambda m: None, error=errors.append)
    frag = load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=alert_env["ALERTS_PATH"],
    )["_alert_checker"]

    for _ in range(8):
        frag()
    assert 2 <= len(alert_env["sent"]) <= 3
    assert errors and str(alert_env["ALERTS_PATH"]) in errors[-1]
    stopped_at = len(alert_env["sent"])

    broken[0] = False                                       # Dropbox nhả file
    frag()
    assert len(alert_env["sent"]) == stopped_at + 1
    assert alert_env["load_alerts"]()[0]["fired"] is True
    frag()                                                  # đã lưu ⇒ không gửi lặp
    assert len(alert_env["sent"]) == stopped_at + 1


def test_alert_checker_probe_save_ok_then_fire_save_fails_sends_no_more(alert_env):
    """Dropbox lúc khoá lúc nhả: lượt dò ghi được, lượt lưu sau khi bắn lại lỗi. Dò
    được mà reset bộ đếm về 0 là mỗi lần dò kéo theo tối đa 3 tin trùng."""
    alert_env["save_alerts"]([_ALERT_A])
    real_write, free_writes = alert_env["write_json_atomic"], [0]

    def _flaky_write(data, path):
        if free_writes[0] <= 0:
            raise PermissionError(13, "Dropbox đang giữ file")
        free_writes[0] -= 1
        return real_write(data, path)

    alert_env["write_json_atomic"] = _flaky_write
    st = types.SimpleNamespace(session_state={"_tg_token": "tok", "_tg_chat": "chat"},
                               toast=lambda m: None, error=lambda m: None)
    frag = load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=alert_env["ALERTS_PATH"],
    )["_alert_checker"]
    for _ in range(5):
        frag()
    stopped_at = len(alert_env["sent"])

    free_writes[0] = 1                                      # chỉ lượt dò ghi được
    frag()
    assert len(alert_env["sent"]) == stopped_at + 1
    for _ in range(5):
        frag()
    assert len(alert_env["sent"]) == stopped_at + 1


def test_alert_checker_stops_telegram_while_reread_after_fire_keeps_failing(alert_env):
    """Đọc đầu lượt được, đọc LẠI sau khi bắn thì lỗi (Dropbox đang ghi dở) ⇒ dấu "đã
    bắn" không được lưu. Không tính là lưu lỗi thì cứ 10s gửi lại Telegram."""
    from dashboard.analysis_tab import _ALERT_SAVE_FAIL_MAX

    alert_env["save_alerts"]([_ALERT_A])
    real_load, calls, flaky = alert_env["load_alerts"], [0], [True]

    def _load():                                            # lần đọc chẵn lỗi
        calls[0] += 1
        if flaky[0] and calls[0] % 2 == 0:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return real_load()

    errors: list = []
    st = types.SimpleNamespace(session_state={"_tg_token": "tok", "_tg_chat": "chat"},
                               toast=lambda m: None, error=errors.append)
    frag = load_source_fns(
        "dashboard/analysis_tab.py", "_alert_checker", "_ALERT_SAVE_FAIL_MAX", st=st,
        load_alerts=_load, save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=alert_env["ALERTS_PATH"],
    )["_alert_checker"]

    for _ in range(8):
        frag()
    assert len(alert_env["sent"]) == _ALERT_SAVE_FAIL_MAX
    assert errors and str(alert_env["ALERTS_PATH"]) in errors[-1]

    flaky[0] = False                                        # đọc lại được
    frag()
    frag()
    assert len(alert_env["sent"]) == _ALERT_SAVE_FAIL_MAX + 1
    assert real_load()[0]["fired"] is True


def test_sidebar_hides_stopped_error_when_no_alert_is_active(alert_env):
    """Không còn alert active (máy kia đã bắn + lưu, hoặc đã xoá) thì không có gì bị
    chặn gửi — báo đỏ "đã NGỪNG gửi" không được kẹt mãi."""
    alert_env["save_alerts"]([{**_ALERT_A, "fired": True}])
    st = _run_alert_sidebar(alert_env, _alert_save_fails=3)
    st.error.assert_not_called()


def test_sidebar_shows_red_error_while_alert_saves_keep_failing(alert_env):
    st = _run_alert_sidebar(alert_env)
    st.error.assert_not_called()
    st = _run_alert_sidebar(alert_env, _alert_save_fails=3)
    msg = st.error.call_args_list[0].args[0]
    assert str(alert_env["ALERTS_PATH"]) in msg and "Telegram" in msg


def test_save_alerts_reports_success(alert_env):
    assert alert_env["save_alerts"]([_ALERT_A]) is True

    def _locked(data, path):
        raise PermissionError(13, "Dropbox đang giữ file")

    alert_env["write_json_atomic"] = _locked
    assert alert_env["save_alerts"]([_ALERT_A]) is False


def test_failed_telegram_send_is_logged(alert_env, caplog):
    alert_env["send_telegram_alert"] = lambda *a: False
    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        alert_env["check_and_fire_alerts"](
            [{"ticker": "VCB", "condition": "above", "target": 25.0}], "tok", "chat")
    assert "VCB" in caplog.text


def test_vnd_target_fires_on_live_price_in_thousands(alert_env):
    """Ô nhập ghi "Giá (VND)"; bảng giá (price_board) trả VND, nhưng nhánh dự phòng
    `_http_fetch_quote` (nến 1m vnstock) ghi quote ở NGHÌN đồng. So thẳng 90.5 với
    90000 thì "above" không bao giờ bắn còn "below" bắn ngay — Telegram báo sai."""
    alert_env["load_live_quote"] = lambda t: {"price": 90.5, "chg_pct": 0.5, "volume": 1e6}
    out = alert_env["check_and_fire_alerts"]([
        {"ticker": "FPT", "condition": "above", "target": 90000.0, "fired": False},
        {"ticker": "FPT", "condition": "below", "target": 90000.0, "fired": False},
    ], "tok", "chat")
    assert [a["fired"] for a in out] == [True, False]
    assert out[0]["fired_price"] == 90500.0
    assert "90,500.00" in out[0]["message"]


def test_penny_price_in_vnd_is_not_rescaled(alert_env):
    """Bảng giá trả AVF = 400 (VND thật — mã/chứng quyền dưới 500 đ là có thật):
    quy đổi theo ngưỡng 500 sẽ biến nó thành 400,000 đ."""
    alert_env["load_live_quote"] = lambda t: {"price": 400.0}
    out = alert_env["check_and_fire_alerts"](
        [{"ticker": "AVF", "condition": "below", "target": 500.0, "fired": False}], "tok", "chat")
    assert out[0]["fired"] is True and out[0]["fired_price"] == 400.0


def _alerts_vs_warehouse(alert_env, kho_close, live, alerts):
    """Kho có close gần nhất `kho_close` (nghìn đồng, như `load_price_history`)."""
    alert_env["load_price_history"] = lambda t, days=0: pd.DataFrame(
        {"time": pd.to_datetime(["2026-10-16"]), "close": [kho_close]})
    alert_env["load_live_quote"] = lambda t: {"price": live}
    return alert_env["check_and_fire_alerts"](
        [{"fired": False, **a} for a in alerts], "tok", "chat")


def test_warrant_10_vnd_does_not_fire_far_above_target(alert_env):
    """Chứng quyền 10 đ, "above 1.500": lấy MỤC TIÊU làm mốc đơn vị thì 10/1500 < 0,01
    ⇒ giá bị nhân 1000 thành 10.000 đ và bắn ngay."""
    out = _alerts_vs_warehouse(alert_env, 0.01, 10.0, [
        {"ticker": "CVHM2601", "condition": "above", "target": 1500.0}])
    assert out[0]["fired"] is False
    assert alert_env["sent"] == []


def test_live_in_thousands_is_scaled_by_warehouse_close(alert_env):
    out = _alerts_vs_warehouse(alert_env, 90.2, 90.5, [
        {"ticker": "FPT", "condition": "above", "target": 90000.0}])
    assert out[0]["fired"] is True and out[0]["fired_price"] == 90500.0


def test_penny_vnd_live_far_below_target_is_not_rescaled(alert_env):
    """AVF 400 đ (VND), kho 0.4 nghìn, "below 50.000": mốc mục tiêu thì 400/50000 < 0,01
    ⇒ thành 400.000 đ, alert không bao giờ bắn."""
    out = _alerts_vs_warehouse(alert_env, 0.4, 400.0, [
        {"ticker": "AVF", "condition": "below", "target": 50000.0},
        {"ticker": "AVF", "condition": "above", "target": 1000.0}])
    assert [a["fired"] for a in out] == [True, False]
    assert out[0]["fired_price"] == 400.0


def test_penny_vnd_kept_raw_in_warehouse_is_not_rescaled(alert_env):
    """AVF 400 đ, kho lưu THÔ 400 (`normalize_price_units` chỉ chia khi > 500), quote 400
    VND. Quote cùng thang kho mà ×1000 ⇒ 400.000 đ: "above 1.000" bắn ngay, "below
    50.000" không bao giờ bắn."""
    out = _alerts_vs_warehouse(alert_env, 400.0, 400.0, [
        {"ticker": "AVF", "condition": "above", "target": 1000.0},
        {"ticker": "AVF", "condition": "below", "target": 50000.0}])
    assert [a["fired"] for a in out] == [False, True]
    assert out[1]["fired_price"] == 400.0


def test_index_below_500_points_is_not_rescaled(alert_env):
    """HNXINDEX ~230 điểm: kho 230, quote 230 — chỉ số tính bằng điểm, không có thang VND."""
    out = _alerts_vs_warehouse(alert_env, 230.0, 230.0, [
        {"ticker": "HNXINDEX", "condition": "above", "target": 250.0},
        {"ticker": "HNXINDEX", "condition": "below", "target": 240.0}])
    assert [a["fired"] for a in out] == [False, True]
    assert out[1]["fired_price"] == 230.0


# ── render_chart: thư viện chart + live bar ──────────────────────────────────

def _render_chart_html(lwc_path: Path, df=None, **chart_kw) -> tuple[list, list]:
    """Chạy render_chart THẬT với st/_stc giả; trả (html đã vẽ, lời báo st.error/warning)."""
    html, said = [], []
    st = types.SimpleNamespace(warning=said.append, error=said.append)
    stc = types.SimpleNamespace(html=lambda h, **k: html.append(h))
    ns = load_source_fns("vnstock_dashboard.py", "_lwc_js", "render_chart",
                         st=st, _stc=stc, pd=pd, compute_indicators=compute_indicators,
                         LWC_JS_PATH=lwc_path, _lwc_palette=lwc_palette,
                         _font_face_css=font_face_css)
    ns["render_chart"](_rising() if df is None else df, "VCB", **chart_kw)
    return html, said


def test_render_chart_without_lwc_file_reports_instead_of_blank_chart(tmp_path):
    """Clone mới không có lwc.min.js ⇒ `<script></script>` rỗng, chart trắng không báo gì."""
    html, said = _render_chart_html(tmp_path / "lwc.min.js")
    assert html == []
    assert "Thiếu lwc.min.js" in said[0] and str(tmp_path / "lwc.min.js") in said[0]


def test_render_chart_inlines_lwc_library(tmp_path):
    lib = tmp_path / "lwc.min.js"
    lib.write_text("/* LWC giả */", encoding="utf-8")
    html, said = _render_chart_html(lib)
    assert said == []
    assert "<script>/* LWC giả */</script>" in html[0]


# JS chart chạy trong node với LightweightCharts giả: series ghi lại mọi điểm (setData/update
# theo đúng luật LWC: time cũ hơn ⇒ ném, bằng ⇒ thay, mới hơn ⇒ nối); time-range API ⇒ ném.
_CHART_JS_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const app = fs.readFileSync(process.argv[2], "utf8");
const bars = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const charts = [], timeouts = [], intervals = [];
const banned = () => { throw new Error("cấm time-range API"); };
function series() {
  const s = {data: []};
  s.setData = d => { s.data = d.map(p => Object.assign({}, p)); };
  s.update = p => {
    const last = s.data[s.data.length - 1];
    if (last && p.time < last.time) throw new Error("update cũ hơn bar cuối");
    if (last && p.time === last.time) s.data[s.data.length - 1] = Object.assign({}, p);
    else s.data.push(Object.assign({}, p));
  };
  s.createPriceLine = () => ({applyOptions() {}});
  return s;
}
function createChart() {
  const c = {series: []};
  const add = () => { const s = series(); c.series.push(s); return s; };
  const ts = {subscribeVisibleLogicalRangeChange() {}, getVisibleLogicalRange: () => null,
              setVisibleLogicalRange() {}, setVisibleRange: banned, getVisibleRange: banned,
              subscribeVisibleTimeRangeChange: banned};
  Object.assign(c, {addCandlestickSeries: add, addLineSeries: add, addHistogramSeries: add,
    timeScale: () => ts, subscribeCrosshairMove() {}, setCrosshairPosition() {}, resize() {},
    priceScale: () => ({}), priceToCoordinate: () => null});
  charts.push(c);
  return c;
}
const els = {};
let n = 0;
const ctx = {
  LightweightCharts: {createChart, CrosshairMode: {Normal: 0}, LineStyle: {Dashed: 2}},
  document: {getElementById: id => els[id] || (els[id] = {clientWidth: 800, clientHeight: 200,
             innerHTML: "", style: {}, appendChild() {}}),
             addEventListener() {}, body: {style: {}}, documentElement: {style: {}}},
  window: {addEventListener() {}}, console: {log() {}},
  setTimeout: f => timeouts.push(f), clearTimeout() {}, setInterval: f => intervals.push(f),
  fetch: () => Promise.resolve({ok: true, json: () => bars[Math.min(n++, bars.length - 1)]}),
};
vm.createContext(ctx);
vm.runInContext(app, ctx);
timeouts.splice(0).forEach(f => f());
const tick = () => new Promise(r => setImmediate(r));
(async () => {
  await tick();
  const poll = intervals.find(f => f.name === "_pollLastBar");
  for (let k = 1; k < bars.length; k++) { poll(); await tick(); }
  console.log(JSON.stringify(charts.map(c => c.series.map(s => s.data.map(p => p.time)))));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="cần node để chạy JS chart")
def test_live_new_bar_keeps_all_four_panels_same_bar_count(tmp_path):
    """Bất biến CLAUDE-NOTES: đồng bộ 4 panel bằng LOGICAL range ⇒ chỉ số bar phải 1:1.
    JSON live mang nến MỚI (time > bar cuối) mà chỉ nối vào series giá thì Volume/RSI/MACD
    hụt 1 bar mỗi nến mới ⇒ 4 panel lệch trục."""
    import subprocess
    lib = tmp_path / "lwc.min.js"
    lib.write_text("", encoding="utf-8")
    df = _rising()
    html, _ = _render_chart_html(lib, df, live_url="/app/static/today_bars/VCB.json")
    (tmp_path / "app.js").write_text(html[0].rsplit("<script>", 1)[1].split("</script>")[0],
                                     encoding="utf-8")
    t0, day = int(pd.Timestamp(df["time"].iloc[-1]).timestamp()), 86_400
    bar = {"open": 49.0, "high": 50.5, "low": 48.5, "close": 50.0, "volume": 1e5}
    bars = [{**bar, "time": t0},                       # bar cuối đang có: cập nhật tại chỗ
            {**bar, "time": t0 + day},                 # nến mới
            {**bar, "time": t0 + day, "close": 50.2},  # nến mới đó tick tiếp
            {**bar, "time": t0 + 2 * day}]             # thêm một nến mới nữa
    (tmp_path / "bars.json").write_text(json.dumps(bars), encoding="utf-8")
    (tmp_path / "harness.js").write_text(_CHART_JS_HARNESS, encoding="utf-8")

    out = subprocess.run(["node", str(tmp_path / "harness.js"), str(tmp_path / "app.js"),
                          str(tmp_path / "bars.json")],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)

    assert out.returncode == 0, out.stderr
    main, *panels = json.loads(out.stdout)
    candle_times = main[0]
    assert len(candle_times) == len(df) + 2 and candle_times[-2:] == [t0 + day, t0 + 2 * day]
    assert len(panels) == 3
    for panel in panels:
        assert panel, "panel không có series nào"
        for times in panel:
            assert times == candle_times


def test_repo_ships_lwc_library_with_license_header():
    head = (_ROOT / "lwc.min.js").read_text(encoding="utf-8")[:300]
    assert "TradingView Lightweight Charts" in head and "Apache License 2.0" in head


# ── df_from_preset: cột % ────────────────────────────────────────────────────

def test_preset_pct_columns_show_zero_and_hide_nan():
    """0.0 là số thật (đứng giá) ⇒ "0.0%"; NaN/None là thiếu data ⇒ "—"."""
    df_from_preset = load_source_fns("vnstock_dashboard.py", "df_from_preset",
                                     pd=pd)["df_from_preset"]
    out = df_from_preset({"results": [
        {"ticker": "AAA", "chg_1d_pct": 0.0, "chg_5d_pct": float("nan"),
         "chg_20d_pct": None, "bb_pct": 1.24, "52w_pct": -2.0, "rsi_14": 55.0},
        {"ticker": "BBB", "chg_1d_pct": -0.5, "chg_5d_pct": 3.0,
         "chg_20d_pct": 4.0, "bb_pct": None, "52w_pct": 0.0, "rsi_14": 0.0},
    ]})
    assert out["1D%"].tolist() == ["0.0%", "-0.5%"]
    assert out["5D%"].tolist() == ["—", "+3.0%"]
    assert out["20D%"].tolist() == ["—", "+4.0%"]
    assert out["BB%"].tolist() == ["+1.2%", "—"]
    assert out["52W%"].tolist() == ["-2.0%", "0.0%"]
    assert out["RSI"].tolist() == ["55.0", "0.0"]


def test_preset_rsi_vol_price_show_zero_and_hide_nan():
    """RSI 0.0 là số thật (14 phiên không phiên tăng — 18/10 có 13/140 mã oversold như DVM, PLE,
    KOS) ⇒ "0.0", không phải "—"; Vol× thiếu (mã không khớp lệnh, VHF) ⇒ "—", không phải "nan"."""
    df_from_preset = load_source_fns("vnstock_dashboard.py", "df_from_preset",
                                     pd=pd)["df_from_preset"]
    out = df_from_preset({"results": [
        {"ticker": "AAA", "rsi_14": 0.0, "vol_spike": None, "last_close": 2.6},
        {"ticker": "BBB", "rsi_14": 27.46, "vol_spike": 0.0, "last_close": None},
    ]})
    assert out["RSI"].tolist() == ["0.0", "27.5"]
    assert out["Vol×"].tolist() == ["—", "0.0"]
    assert out["Giá"].tolist() == ["2.6", "—"]


# ── Điều hướng st.navigation (P2 giao diện, thay st.pills) ──────────────────

_DASH_SRC = (_ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8")


def test_navigation_is_top_bar_built_from_registry():
    """5 nhóm ở thanh trên cùng, dựng từ dashboard/pages.py; pills cũ không quay lại."""
    assert 'st.navigation(_NAV_SPEC, position="top")' in _DASH_SRC
    assert "st.pills(" not in _DASH_SRC and "_TAB_OPTIONS" not in _DASH_SRC
    # thanh trạng thái vẽ TRƯỚC nội dung trang, trên mọi trang
    assert _DASH_SRC.index("_render_status_strip(_PAGE_OBJS") < _DASH_SRC.index("_nav.run()")


def _page_runner_ns(log_calls, shown):
    ui = types.SimpleNamespace(show_error=lambda msg, exc=None: shown.append((msg, exc)))
    log = types.SimpleNamespace(exception=lambda *a, **k: log_calls.append(a))
    return load_source_fns("vnstock_dashboard.py", "_page_runner",
                           _PAGES_MAIN="<main>", log=log, _ui=ui)


def test_page_error_is_logged_and_shown_as_one_sentence(monkeypatch):
    """st.error chỉ in 1 dòng — không log thì không ai lần ra lỗi gốc; traceback cho
    người dùng chỉ hiện ở chế độ chẩn đoán (ui.show_error)."""
    from dashboard.pages import PageSpec

    mod = types.ModuleType("_trang_thu")

    def _boom():
        raise RuntimeError("hỏng")
    mod.boom = _boom
    monkeypatch.setitem(sys.modules, "_trang_thu", mod)
    logged, shown = [], []
    run = _page_runner_ns(logged, shown)["_page_runner"](
        PageSpec("Thị trường", "Thử", ":material/science:", "thu", "_trang_thu", "boom"))
    run()
    assert logged and "Thử" in logged[0]
    assert shown[0][0] == "Không mở được trang Thử." and isinstance(shown[0][1], RuntimeError)
    assert run.__name__ == "page_thu"


def test_page_runner_calls_main_script_pages_from_globals():
    logged, shown, called = [], [], []
    ns = _page_runner_ns(logged, shown)
    ns["_page_he_thong_thu"] = lambda: called.append(1)
    from dashboard.pages import PageSpec
    ns["_page_runner"](PageSpec("Hệ thống", "Hệ thống", ":material/x:", "he-thong", "<main>",
                                "_page_he_thong_thu"))()
    assert called == [1] and not logged and not shown


# ── _fetch_order_stats_batch: cache đĩa theo TỪNG mã ────────────────────────

@pytest.fixture()
def order_env(tmp_path, monkeypatch):
    import os
    from datetime import datetime

    fetched: list = []

    class _Trading:
        def __init__(self, symbol):
            self.symbol = symbol

        def order_stats(self):
            fetched.append(self.symbol)
            return pd.DataFrame({
                "trading_date": pd.bdate_range("2026-10-05", periods=5),
                "total_buy_trade_volume": [1000.0] * 5,
                "total_buy_trade": [10.0] * 5,
                "total_sell_trade_volume": [1000.0] * 5,
                "total_sell_trade": [10.0] * 5,
            })

    monkeypatch.setitem(sys.modules, "vnstock_data",
                        types.SimpleNamespace(Trading=_Trading))
    path = tmp_path / "order_stats_cache.json"
    ns = load_source_fns(
        "vnstock_dashboard.py", "_fetch_order_stats_batch",
        _ORDER_CACHE_PATH=path, _ORDER_CACHE_MAX_AGE=1800,
        datetime=datetime, json=json, log=logging.getLogger("t"),
        np=np, pd=pd, os=os,
    )
    return ns["_fetch_order_stats_batch"], path, fetched


_CACHED = {tk: {"big_order_score": 50.0, "buy_sell_ratio": 0.7}
           for tk in ("AAA", "BBB", "CCC", "DDD")}


def test_order_stats_fetches_tickers_missing_from_fresh_cache(order_env):
    fetch, path, fetched = order_env
    path.write_text(json.dumps(_CACHED), encoding="utf-8")
    out = fetch(("AAA", "EEE"))
    assert fetched == ["EEE"]                       # AAA lấy từ cache
    assert set(out) == {"AAA", "EEE"}
    assert out["AAA"] == _CACHED["AAA"]
    assert out["EEE"]["buy_sell_ratio"] == 0.5
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {*_CACHED, "EEE"}


def test_order_stats_merge_does_not_extend_cache_age(order_env):
    """Gộp mã mới vào file KHÔNG được làm mới mtime: mã cũ trong file sẽ sống
    quá 30 phút mãi mãi nếu lượt nào cũng thiếu một mã."""
    import os
    import time

    fetch, path, _ = order_env
    path.write_text(json.dumps(_CACHED), encoding="utf-8")
    old = time.time() - 1000
    os.utime(path, (old, old))
    fetch(("AAA", "EEE"))
    assert abs(path.stat().st_mtime - old) < 2


def test_order_stats_full_cache_hit_makes_no_api_call(order_env):
    fetch, path, fetched = order_env
    path.write_text(json.dumps(_CACHED), encoding="utf-8")
    assert fetch(("BBB", "CCC")) == {tk: _CACHED[tk] for tk in ("BBB", "CCC")}
    assert fetched == []


# ── Screener cũ: so PHIÊN PHỦ, không so ngày lịch ───────────────────────────

@pytest.mark.parametrize("generated_at, now, stale", [
    ("2026-10-16 21:00:00", "2026-10-17 10:00", False),  # T7, kết quả T6 tối
    ("2026-10-16 21:00:00", "2026-10-18 20:00", False),  # CN
    ("2026-10-12 21:00:00", "2026-10-13 08:00", False),  # T3 sáng, kết quả T2 tối
    ("2026-10-12 21:00:00", "2026-10-13 16:00", True),   # T3 sau 15:05: có phiên mới
    ("2026-10-16 10:00:00", "2026-10-16 16:00", True),   # chạy giữa phiên T6
    ("—", "2026-10-13 16:00", False),                    # không đọc được ⇒ im
])
def test_screener_stale_compares_covered_sessions(generated_at, now, stale):
    from datetime import datetime
    fn = load_source_fns("vnstock_dashboard.py", "_screener_is_stale",
                         datetime=datetime)["_screener_is_stale"]
    assert fn(generated_at, datetime.fromisoformat(now)) is stale


def test_stale_warning_points_to_a_button_that_exists():
    """Nút "Cập nhật Screener" không tồn tại — chỉ đường phải trỏ nút thật."""
    start = _DASH_SRC.index("if _screener_stale:")
    warn = _DASH_SRC[start:_DASH_SRC.index("else:", start)]
    assert "Cập nhật Screener" not in warn
    assert "📥 Cập nhật giá" in warn and '"📥 Cập nhật giá"' in _DASH_SRC


# ── NN ròng theo cửa sổ: đếm PHIÊN có trong data, không đếm ngày lịch ───────

def _nn_df():
    # 6 phiên T6 09/10 → T6 16/10; phiên thứ i ròng (i+1) tỷ, mua 2×, bán 1×
    days = pd.bdate_range("2026-10-09", "2026-10-16")
    return pd.DataFrame({
        "symbol": ["AAA"] * len(days), "date": days,
        "net_value": [(i + 1) * 1e9 for i in range(len(days))],
        "buy_value": [(i + 1) * 2e9 for i in range(len(days))],
        "sell_value": [(i + 1) * 1e9 for i in range(len(days))],
    })


@pytest.fixture()
def nn_fns():
    ns = load_source_fns("vnstock_dashboard.py", "_NN_WINDOW_SESSIONS", "_nn_window",
                         "_aggregate_nn_by_window", "_aggregate_nn_buy_sell_by_window",
                         pd=pd)
    return ns["_aggregate_nn_by_window"], ns["_aggregate_nn_buy_sell_by_window"]


def test_nn_5d_window_sums_the_five_latest_sessions(nn_fns):
    """Tab Dòng Tiền gửi 5D = 7 (ngày lịch): phải ra đúng 5 phiên mới nhất,
    không 6 phiên khi đã có data hôm nay, không lệch theo giờ mở dashboard."""
    net, buy_sell = nn_fns
    assert net(_nn_df(), 7) == {"AAA": 2.0 + 3 + 4 + 5 + 6}
    assert buy_sell(_nn_df(), 7) == {"AAA": {"buy": 40.0, "sell": 20.0}}


def test_nn_1d_and_long_windows(nn_fns):
    net, _ = nn_fns
    assert net(_nn_df(), 0) == {"AAA": 6.0}
    assert net(_nn_df(), 30) == {"AAA": 21.0}   # data chỉ có 6 phiên


# ── Lỗi không được nuốt im ──────────────────────────────────────────────────
# Dispatch trang: test_page_error_is_logged_and_shown_as_one_sentence (trên).
# Badge file hỏng phải NÓI RA: tests/test_status_strip.py::test_corrupt_file_says_so_and_warns
# (3 badge sidebar gộp thành chấm "Hệ thống" ở P2 giao diện).

_DASH_TREE = ast.parse(_DASH_SRC)


# ── load_fundamental: khối lỗi phải có log và KHÔNG vào cache đĩa 24h ───────

def _fund_env(tmp_path, monkeypatch, overview_ok=True, ratio_ok=True):
    from datetime import datetime

    def _overview():
        if not overview_ok:
            raise RuntimeError("overview sập")
        return pd.DataFrame({"pe": [12.0], "pb": [1.5]})

    def _ratio(**kw):
        if not ratio_ok:
            raise ConnectionError("ratio sập")
        return pd.DataFrame({"roe": [0.18], "roa": [0.02]})

    monkeypatch.setitem(sys.modules, "vnstock_auth",
                        types.SimpleNamespace(ensure_api_key=lambda: None))
    monkeypatch.setitem(sys.modules, "vnstock_data", types.SimpleNamespace(
        Company=lambda symbol: types.SimpleNamespace(overview=_overview),
        Finance=lambda symbol, source=None: types.SimpleNamespace(ratio=_ratio),
    ))
    fn = load_source_fns(
        "vnstock_dashboard.py", "load_fundamental",
        _FUND_CACHE_DIR=tmp_path, _FUND_CACHE_VER=4, datetime=datetime, json=json,
        pd=pd, log=logging.getLogger("vnstock_dashboard"),
        _get_warehouse_last_close=lambda t: None,
    )["load_fundamental"]
    return fn, tmp_path / "AAA.json"


@pytest.mark.parametrize("overview_ok, ratio_ok, block, kept", [
    (False, True, "overview", ("roe", 18.0)),
    (True, False, "ratio", ("pe", 12.0)),
])
def test_partial_fundamental_is_logged_and_not_disk_cached(
        tmp_path, monkeypatch, caplog, overview_ok, ratio_ok, block, kept):
    fn, cache = _fund_env(tmp_path, monkeypatch, overview_ok, ratio_ok)
    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        out = fn("AAA")
    assert out[kept[0]] == kept[1]          # nửa còn lại vẫn hiện
    assert not cache.exists(), "kết quả thiếu một nửa bị khoá 24h trong cache đĩa"
    assert "AAA" in caplog.text and block in caplog.text


def test_complete_fundamental_is_disk_cached(tmp_path, monkeypatch):
    fn, cache = _fund_env(tmp_path, monkeypatch)
    out = fn("AAA")
    assert out["pe"] == 12.0 and out["roe"] == 18.0
    assert json.loads(cache.read_text(encoding="utf-8"))["roe"] == 18.0


# ── Live quote ghép vào nến intraday: đúng lưới timeframe, volume là phần chênh ─

def _merge_live_fn():
    from vnstock_price_units import normalize_live_price
    return load_source_fns("vnstock_dashboard.py", "_INTERVAL_FREQ", "_merge_live_quote",
                           pd=pd, _normalize_live_price=normalize_live_price)["_merge_live_quote"]


def _bars_15m():
    return pd.DataFrame({
        "time": pd.to_datetime(["2026-10-15 14:30", "2026-10-16 09:45", "2026-10-16 10:00"]),
        "open": [25.0, 25.0, 25.1], "high": [25.2, 25.2, 25.3],
        "low": [24.9, 24.9, 25.0], "close": [25.0, 25.1, 25.2],
        "volume": [500_000.0, 100_000.0, 95_000.0],
    })


def test_live_quote_inside_last_15m_bar_updates_it():
    """TF 15m, tick 10:07 ⇒ cập nhật nến 10:00, KHÔNG chèn nến '10:07' lệch lưới."""
    out = _merge_live_fn()(_bars_15m(), {"time": "2026-10-16 10:07:31", "price": 25.6,
                                         "volume": 3_200_000}, "15m")
    assert len(out) == 3
    last = out.iloc[-1]
    assert last["time"] == pd.Timestamp("2026-10-16 10:00")
    assert (last["open"], last["high"], last["low"], last["close"]) == (25.1, 25.6, 25.0, 25.6)
    assert last["volume"] == 95_000.0


def test_live_quote_in_next_15m_bar_appends_with_session_delta_volume():
    """Tick 10:16 ⇒ nến 10:15; volume = tích luỹ phiên − nến HÔM NAY đã có
    (nến hôm qua không trừ), không phải 3,2 triệu tích luỹ cả phiên."""
    out = _merge_live_fn()(_bars_15m(), {"time": "2026-10-16 10:16:02", "price": 25.4,
                                         "volume": 300_000}, "15m")
    assert len(out) == 4
    last = out.iloc[-1]
    assert last["time"] == pd.Timestamp("2026-10-16 10:15")
    assert last["volume"] == 300_000 - 100_000 - 95_000
    assert last["open"] == last["close"] == 25.4


def test_live_quote_new_bar_volume_never_negative():
    out = _merge_live_fn()(_bars_15m(), {"time": "2026-10-16 10:16", "price": 25.4,
                                         "volume": 50_000}, "15m")
    assert out.iloc[-1]["volume"] == 0


def test_stale_live_quote_older_than_last_bar_leaves_bars_untouched():
    """WSS rớt, quote đứng ở 10:07 trong khi VCI đã có nến tới 10:45. Append nến
    10:00 phẳng volume 0 thì render_chart sort + drop_duplicates(keep="last") thay
    nến 10:00 THẬT bằng doji đó."""
    bars = pd.DataFrame({
        "time": pd.to_datetime(["2026-10-16 10:00", "2026-10-16 10:15",
                                "2026-10-16 10:30", "2026-10-16 10:45"]),
        "open": [25.1, 25.2, 25.3, 25.4], "high": [25.3, 25.4, 25.5, 25.6],
        "low": [25.0, 25.1, 25.2, 25.3], "close": [25.2, 25.3, 25.4, 25.5],
        "volume": [95_000.0, 80_000.0, 70_000.0, 60_000.0],
    })
    out = _merge_live_fn()(bars.copy(), {"time": "2026-10-16 10:07:31", "price": 25.6,
                                         "volume": 3_200_000}, "15m")
    pd.testing.assert_frame_equal(out, bars)


# ── Market overview: dùng file pre-computed khi nó theo kịp kho, không theo tuổi file ─

@pytest.fixture()
def overview_is_current():
    return load_source_fns("vnstock_dashboard.py",
                           "_overview_file_is_current")["_overview_file_is_current"]


def test_overview_file_covering_warehouse_eod_is_used_even_when_40h_old(overview_is_current):
    """Tối T7 → T2: file ghi chiều T6 đã 40h+ nhưng kho vẫn chỉ tới T6 ⇒ dùng file,
    không tính lại 10–30s + ~40 call NN cho kết quả y hệt."""
    assert overview_is_current(40.0, "2026-10-16", "2026-10-16") is True
    assert overview_is_current(40.0, "2026-10-17", "2026-10-16") is True


def test_overview_file_trailing_warehouse_eod_is_recomputed(overview_is_current):
    assert overview_is_current(2.0, "2026-10-15", "2026-10-16") is False


def test_overview_without_known_dates_keeps_the_24h_rule(overview_is_current):
    assert overview_is_current(23.0, None, "2026-10-16") is True
    assert overview_is_current(25.0, "2026-10-16", None) is False
    assert overview_is_current(25.0, None, None) is False


def test_mid_session_overview_is_recomputed_once_warehouse_has_that_session(
        overview_is_current):
    """Bất biến CLAUDE.md: cùng phiên mà chốt trước SESSION_CLOSE_CUTOFF (15:05) là GIỮA
    PHIÊN ⇒ stale. File ghi 10:40 chỉ thấy nửa buổi sáng; tối đó kho đã có trọn phiên
    (EOD = hôm nay) ⇒ không dùng file, để Tầng 2 tính lại."""
    from datetime import datetime
    assert overview_is_current(9.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 16, 10, 40)) is False
    assert overview_is_current(9.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 16, 15, 4, 59)) is False


def test_mid_session_overview_still_used_while_warehouse_trails_it(overview_is_current):
    """Giữa phiên kho còn ở hôm qua: file 10:40 là bản mới nhất, tính lại từ kho chỉ ra
    phiên cũ."""
    from datetime import datetime
    assert overview_is_current(0.5, "2026-10-16", "2026-10-15",
                               datetime(2026, 10, 16, 10, 40)) is True


def test_overview_written_after_close_or_next_morning_is_current(overview_is_current):
    """Ghi từ 15:05, hoặc chạy bù sáng hôm sau từ data EOD: đã thấy trọn phiên."""
    from datetime import datetime
    assert overview_is_current(3.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 16, 15, 5)) is True
    assert overview_is_current(15.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 17, 7, 30)) is True
    assert overview_is_current(40.0, "2026-10-16", "2026-10-16", None) is True


def test_overview_mid_session_cutoff_follows_brief_constant(overview_is_current, monkeypatch):
    """Mốc chốt phiên là `vnstock_brief.SESSION_CLOSE_CUTOFF` (test khác canh nó khớp
    rollup), không chép cứng 15:05 lần nữa."""
    from datetime import datetime, time
    import vnstock_brief as vb
    monkeypatch.setattr(vb, "SESSION_CLOSE_CUTOFF", time(11, 0))
    assert overview_is_current(9.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 16, 11, 30)) is True
    assert overview_is_current(9.0, "2026-10-16", "2026-10-16",
                               datetime(2026, 10, 16, 10, 40)) is False


def test_market_data_loader_skips_mid_session_overview_file(tmp_path, monkeypatch):
    """Nơi gọi phải đưa `generated_at` của file vào phép so: file 10:40, kho EOD = hôm
    nay ⇒ Tầng 2 (kho tạm rỗng ⇒ rỗng); file ghi 15:30 ⇒ dùng file."""
    from datetime import datetime
    import vnstock_brief as vb
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-10-16")
    ov_path = tmp_path / "market_overview.json"
    payload = {"data_date": "2026-10-16", "generated_at": "2026-10-16 10:40:00",
               "sectors": [{"industry": "Ngân hàng"}], "breadth": {"up": 7},
               "tickers": [{"ticker": "VCB"}]}
    ov_path.write_text(json.dumps(payload), encoding="utf-8")
    load = load_source_fns(
        "vnstock_dashboard.py", "_overview_file_is_current", "_load_all_market_data",
        pd=pd, json=json, datetime=datetime, log=logging.getLogger("t"),
        _MARKET_OVERVIEW_PATH=ov_path, PRICES_DIR=tmp_path / "prices",
        INDUSTRY_PATH=tmp_path / "industry.parquet")["_load_all_market_data"]

    sectors, breadth, tickers = load()
    assert sectors.empty and breadth == {} and tickers.empty

    ov_path.write_text(json.dumps({**payload, "generated_at": "2026-10-16 15:30:00"}),
                       encoding="utf-8")
    sectors, breadth, tickers = load()
    assert breadth == {"up": 7} and list(tickers["ticker"]) == ["VCB"]


def _files(root: Path) -> dict:
    return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


def test_market_data_tier2_is_the_runner_overview_and_writes_nothing(tmp_path, monkeypatch):
    """Tầng 2 từng là ~300 dòng chép `compute_market_overview` đã trôi (thiếu Net BS,
    gom ngành khác, NN 3M = NN 1M). Nay gọi `vnstock_runner.build_market_overview`:
    cùng khoá với Tầng 1 (JSON runner ghi) và KHÔNG ghi gì vào kho (Dropbox)."""
    from datetime import datetime

    import vnstock_brief as vb
    import vnstock_runner as vr
    from tests.test_market_analyzer import fake_vnstock_data, mini_warehouse

    wh = mini_warehouse(tmp_path / "wh")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "vnstock_data", fake_vnstock_data(1e9))
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: None)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=20)
    nn_raw = pd.DataFrame({"symbol": "AAA", "date": days, "net_value": 1e9})
    ov_path = wh / "_meta" / "market_overview.json"

    def load(path):
        return load_source_fns(
            "vnstock_dashboard.py", "_overview_file_is_current", "_load_all_market_data",
            pd=pd, json=json, datetime=datetime, log=logging.getLogger("t"),
            _MARKET_OVERVIEW_PATH=path, PRICES_DIR=wh / "prices",
            _fetch_foreign_net_flow=lambda **k: nn_raw)["_load_all_market_data"]()

    vr.save_market_overview(vr.compute_market_overview(str(wh)), str(wh))
    sec1, br1, tick1 = load(ov_path)                    # Tầng 1: file runner vừa ghi
    ov_path.unlink()
    before = _files(tmp_path)
    sec2, br2, tick2 = load(ov_path)                    # Tầng 2: tính tại chỗ
    assert _files(tmp_path) == before

    assert not sec2.empty and not tick2.empty
    assert list(sec2.columns) == list(sec1.columns)
    assert list(tick2.columns) == list(tick1.columns)
    assert br2 == br1
    assert list(sec2["Ngành"]) == list(sec1["Ngành"])
    aaa = tick2.set_index("Mã").loc["AAA"]
    assert aaa["NN 1M (tỷ)"] == 20.0 and pd.isna(aaa["NN 3M (tỷ)"])


# ── Bảng chỉ số: GTGD là giá trị giao dịch thật, không phải điểm × khối lượng ─

def test_index_table_gtgd_is_real_traded_value_or_missing(monkeypatch):
    """`close` của chỉ số là ĐIỂM: 1,700 × 800 triệu cp / 1e9 = 1,360 "tỷ" trong khi
    phiên thật ~25 nghìn tỷ. GTGD phải là `total_value` (VND) của price_history quy
    về tỷ; ngày/chỉ số không có nguồn (HNX30, phiên chưa có batch EOD) ⇒ NaN ("—")."""
    import vnstock_session_stats as vss

    days = pd.bdate_range(end="2026-10-16", periods=3)
    quote = pd.DataFrame({"time": days, "close": [1700.0, 1710.0, 1690.0],
                          "volume": [800e6, 820e6, 790e6]})
    fake_stock = types.SimpleNamespace(quote=types.SimpleNamespace(
        history=lambda **k: quote.copy()))
    monkeypatch.setitem(sys.modules, "vnstock_auth",
                        types.SimpleNamespace(get_vnstock=lambda sym: fake_stock))
    ph = {"VNINDEX": pd.DataFrame({"trading_date": [d.date() for d in days[:2]],
                                   "total_value": [25_000e9, 26_500.4e9]})}
    monkeypatch.setattr(vss, "_fetch_price_history",
                        lambda name: ph.get(name, pd.DataFrame()))
    load = load_source_fns("vnstock_dashboard.py", "load_index_overview",
                           pd=pd)["load_index_overview"]

    out = load(days=3).set_index("time")
    assert out.loc[days[0], "VNINDEX_gtgd"] == pytest.approx(25_000.0)
    assert out.loc[days[1], "VNINDEX_gtgd"] == pytest.approx(26_500.4)
    assert pd.isna(out.loc[days[2], "VNINDEX_gtgd"])        # chưa có batch EOD
    for idx in ("VN30", "HNXINDEX", "HNX30"):
        assert out[f"{idx}_gtgd"].isna().all(), idx
    assert out.loc[days[2], "VNINDEX"] == 1690.0             # cột khác giữ nguyên


@pytest.mark.parametrize("ph", [
    pd.DataFrame({"trading_date": [pd.Timestamp("2026-10-16").date()]}),   # thiếu cột
    pd.DataFrame({"trading_date": [pd.Timestamp("2026-10-16").date()],
                  "total_value": ["n/a"]}),                                 # không phải số
])
def test_index_table_keeps_close_and_change_when_gtgd_source_is_broken(monkeypatch, ph):
    """Lỗi phần GTGD từng rơi vào `except: pass` của cả lượt tải ⇒ MẤT nguyên dòng
    VNINDEX (Close, %D) khỏi bảng chỉ số. Chỉ GTGD được thành NaN."""
    import vnstock_session_stats as vss

    days = pd.bdate_range(end="2026-10-16", periods=2)
    quote = pd.DataFrame({"time": days, "close": [1700.0, 1717.0], "volume": [8e8, 8e8]})
    fake_stock = types.SimpleNamespace(quote=types.SimpleNamespace(
        history=lambda **k: quote.copy()))
    monkeypatch.setitem(sys.modules, "vnstock_auth",
                        types.SimpleNamespace(get_vnstock=lambda sym: fake_stock))
    monkeypatch.setattr(vss, "_fetch_price_history",
                        lambda name: ph.copy() if name == "VNINDEX" else pd.DataFrame())
    load = load_source_fns("vnstock_dashboard.py", "load_index_overview", pd=pd,
                           log=logging.getLogger("vnstock_dashboard"))["load_index_overview"]

    out = load(days=2).set_index("time")
    assert out.loc[days[1], "VNINDEX"] == 1717.0
    assert out.loc[days[1], "VNINDEX_chg"] == pytest.approx(1.0)
    assert out["VNINDEX_gtgd"].isna().all()


def test_get_all_tickers_is_cached():
    """Không cache ⇒ iterdir ~1.700 thư mục + compile regex ở MỖI rerun tab Phân tích."""
    fn = next(n for n in _DASH_TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "get_all_tickers")
    assert any(ast.unparse(d).startswith("st.cache_data(") for d in fn.decorator_list)


# ── GTGD theo cửa sổ: đọc kho MỘT lần cho cả 1D/5D/20D, số khớp bản quét-mỗi-cửa-sổ ─

def _gtgd_by_window_old(window_days: int) -> dict:
    """Bản cũ của `_compute_gtgd_by_window` (trước khi gộp cache), chép nguyên
    để đối chứng — mỗi cửa sổ quét lại toàn kho."""
    import pyarrow.parquet as pq
    prices_dir = Path("data_warehouse") / "prices"
    if not prices_dir.exists():
        return {}
    year_limit = 2 if window_days <= 30 else 3
    result: dict[str, float] = {}
    for td in prices_dir.glob("ticker=*"):
        ticker = td.name.split("=", 1)[1]
        if not ticker.isalpha() or len(ticker) > 5:
            continue
        try:
            frames = []
            for yd in sorted(td.glob("year=*"))[-year_limit:]:
                for pf in yd.glob("*.parquet"):
                    frames.append(pq.read_table(
                        str(pf), columns=["time", "close", "volume"]
                    ).to_pandas())
            if not frames:
                continue
            df = pd.concat(frames)
            df["time"] = pd.to_datetime(df["time"])
            df["_date"] = df["time"].dt.date
            df = df.drop_duplicates(subset=["_date"], keep="last")
            df = df.sort_values("_date")
            n = max(1, window_days) if window_days > 0 else 1
            df = df.tail(n)
            close = pd.to_numeric(df["close"], errors="coerce").fillna(0).astype(float)
            close = close.where(close > 500, close * 1000)
            vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
            gtgd_vnd = float((close * vol).sum())
            if gtgd_vnd > 0:
                result[ticker] = round(gtgd_vnd / 1e9, 1)
        except Exception:
            continue
    return result


@pytest.fixture()
def gtgd_env(tmp_path, monkeypatch):
    def put(ticker, df):
        d = tmp_path / "data_warehouse" / "prices" / f"ticker={ticker}" / "year=2026"
        d.mkdir(parents=True)
        df.to_parquet(d / "data.parquet", index=False)

    days = pd.bdate_range("2026-09-01", periods=25)
    aaa = pd.DataFrame({"time": days, "close": [25.0 + i * 0.37 for i in range(25)],
                        "volume": [100_000.0 + i * 7_919 for i in range(25)]})
    # Dòng trùng ngày phiên cuối (file ghi 2 lần) + thứ tự file xáo trộn
    aaa = pd.concat([aaa, aaa.tail(1).assign(volume=999_999.0)]).sample(frac=1, random_state=1)
    put("AAA", aaa)
    put("BBB", pd.DataFrame({"time": days[-3:], "close": [15_000.0, 15_200.0, 15_100.0],
                             "volume": [2_000_000.0, float("nan"), 1_500_000.0]}))
    put("DDD", pd.DataFrame({"time": days[-2:], "close": [10.0, 10.5], "volume": [0.0, 0.0]}))
    put("E1VFVN30", pd.DataFrame({"time": days[-2:], "close": [20.0, 21.0],
                                  "volume": [1e6, 1e6]}))
    monkeypatch.chdir(tmp_path)

    import pyarrow.parquet as pq
    reads: list = []
    real_read = pq.read_table
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: reads.append(a[0]) or real_read(*a, **k))
    return reads


def test_gtgd_windows_match_old_per_window_scan(gtgd_env):
    import functools
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_daily_tail",
                         "_load_gtgd_daily", "_compute_gtgd_by_window", pd=pd, Path=Path)
    ns["_load_daily_tail"] = functools.lru_cache(maxsize=None)(ns["_load_daily_tail"])
    for n in (0, 1, 5, 20):
        old = _gtgd_by_window_old(n)
        assert old, n
        assert ns["_compute_gtgd_by_window"](n) == old, n


def test_gtgd_reads_each_ticker_once_for_all_windows(gtgd_env):
    """Đổi 1D→5D→20D từng quét toàn kho 3 lần (cache riêng theo window_days)."""
    import functools
    fn = next(n for n in _DASH_TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "_load_daily_tail")
    assert any(ast.unparse(d).startswith("st.cache_data(") for d in fn.decorator_list)
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_daily_tail",
                         "_load_gtgd_daily", "_compute_gtgd_by_window", pd=pd, Path=Path)
    ns["_load_daily_tail"] = functools.lru_cache(maxsize=None)(ns["_load_daily_tail"])
    for n in (1, 5, 20):
        ns["_compute_gtgd_by_window"](n)
    assert len(gtgd_env) == 3            # AAA, BBB, DDD — E1VFVN30 bị lọc trước khi đọc


def test_gtgd_high_priced_stock_counted_in_vnd(gtgd_env, tmp_path):
    """VNZ 18/10: 30 phiên cuối đều > 500 nghìn ⇒ `close.where(close > 500, …)` coi là VND, GTGD
    nhỏ đi 1000 lần. Mốc đơn vị phải lấy theo cả chuỗi đã đọc, không theo 20 phiên cuối."""
    days = pd.bdate_range("2026-08-03", periods=45)
    d = tmp_path / "data_warehouse" / "prices" / "ticker=HHH" / "year=2026"
    d.mkdir(parents=True)
    pd.DataFrame({"time": days, "close": [450.0] * 25 + [600.0] * 20,
                  "volume": [1_000.0] * 45}).to_parquet(d / "data.parquet", index=False)
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_daily_tail",
                         "_load_gtgd_daily", "_load_last_closes", pd=pd, Path=Path)
    assert ns["_load_gtgd_daily"]()["HHH"].tolist() == [600_000.0 * 1_000] * 20
    assert ns["_load_last_closes"]()["HHH"] == 600.0     # mốc đơn vị quote live: NGHÌN đồng


def test_last_close_skips_trailing_bar_without_close(gtgd_env, tmp_path):
    """Bar cuối close NaN/0 (`fillna(0)`) ⇒ mốc 0 ⇒ quote nghìn của HLB (660) rơi về ngưỡng
    cứng thành 0,66. Mốc phải là close DƯƠNG cuối cùng."""
    days = pd.bdate_range("2026-08-03", periods=30)
    d = tmp_path / "data_warehouse" / "prices" / "ticker=HHH" / "year=2026"
    d.mkdir(parents=True)
    pd.DataFrame({"time": days, "close": [450.0] * 25 + [660.0] * 4 + [float("nan")],
                  "volume": [1_000.0] * 30}).to_parquet(d / "data.parquet", index=False)
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_daily_tail",
                         "_load_last_closes", pd=pd, Path=Path)
    assert ns["_load_last_closes"]()["HHH"] == 660.0


def test_batch_live_quotes_price_unit_follows_warehouse_close(tmp_path, monkeypatch):
    """Bảng mã tab Dòng Tiền: ngưỡng cứng `price > 500 ⇒ /1000` chia quote nghìn của HLB (660)
    còn 0.66 và hiểu quote VND 300 của mã 300 đ là 300 nghìn. Mốc = close kho."""
    from datetime import datetime

    from vnstock_price_units import normalize_quote_price

    live = tmp_path / "data_warehouse" / "_live"
    live.mkdir(parents=True)
    for tk, price in (("HLB", 660.0), ("AVF", 300.0), ("VCB", 90_000.0), ("NEW", 25_000.0)):
        (live / f"quote_{tk}.json").write_text(
            json.dumps({"price": price, "volume": 1_000_000}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ns = load_source_fns(
        "vnstock_dashboard.py", "_batch_load_live_quotes",
        st=types.SimpleNamespace(session_state={}), datetime=datetime, Path=Path, json=json,
        _load_last_closes=lambda: {"HLB": 650.0, "AVF": 0.3, "VCB": 89.0},
        _normalize_quote_price=normalize_quote_price)
    out = ns["_batch_load_live_quotes"](["HLB", "AVF", "VCB", "NEW"])
    assert {tk: out[tk]["price"] for tk in ("HLB", "AVF", "VCB", "NEW")} == pytest.approx(
        {"HLB": 660.0, "AVF": 0.3, "VCB": 90.0, "NEW": 25.0})


@pytest.mark.parametrize("raw", ["null", "{}", "[1]", '[{"ticker": "VCB"}, "x"]'])
def test_load_alerts_rejects_json_that_is_not_a_list_of_dicts(alert_env, raw):
    """JSON HỢP LỆ nhưng sai dạng lọt qua ⇒ TypeError/AttributeError ở sidebar và
    fragment alert (chỉ bắt OSError/ValueError). Phải là ValueError để bị khoá ghi."""
    path = alert_env["ALERTS_PATH"]
    path.parent.mkdir(parents=True)
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        alert_env["load_alerts"]()


def test_load_alerts_returns_valid_list_unchanged(alert_env):
    al = [{"ticker": "VCB", "condition": "above", "target": 25.0, "fired": False}, {}]
    path = alert_env["ALERTS_PATH"]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(al), encoding="utf-8")
    assert alert_env["load_alerts"]() == al


# ── 3 nút pipeline khoá khi marker "pipeline đang chạy" còn tươi ────────────

def _run_pipeline_buttons(tmp_path, marker, override=False):
    """Chạy ĐÚNG thân hàm `_render_pipeline_controls` (📥/🧩/🚀, trang Hệ thống từ P2).
    Nút giả "được bấm" khi KHÔNG disabled — như người dùng bấm mọi nút bấm được."""
    from datetime import datetime

    import vnstock_pipeline_marker as pm
    from tests.test_tab_render_smoke import _fake_streamlit

    path = tmp_path / "pipeline_running.json"
    if marker is not None:
        write_json_atomic(marker, path)
    block = next(n for n in _DASH_TREE.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_render_pipeline_controls")
    st = _fake_streamlit()
    disabled, launched, warned = {}, [], []

    def _button(label, key=None, **k):
        disabled[key] = k.get("disabled", False)
        return not disabled[key]

    st.button = _button
    st.checkbox = lambda label, **k: override
    st.warning = lambda msg, **k: warned.append(msg)
    ns = {"st": st, "datetime": datetime,
          "_is_pipeline_running": pm.is_pipeline_running,
          "_read_pipeline_marker": pm.read_marker,
          "_pipeline_marker_path": lambda _wh: path,
          "launch_in_new_console":
              lambda commands, log_filename="": launched.append(commands) or (True, None)}
    exec(compile(ast.Module(block.body, []), "vnstock_dashboard.py", "exec"), ns)
    return disabled, launched, warned


def _started(minutes_ago):
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


_BUTTONS = ("run_updater", "run_all_no_sync", "run_all_pipeline")


def test_fresh_pipeline_marker_disables_all_three_buttons(tmp_path):
    disabled, launched, warned = _run_pipeline_buttons(
        tmp_path, {"machine": "PICHU", "started_at": _started(10), "command": "all"})
    assert disabled == dict.fromkeys(_BUTTONS, True) and launched == []
    assert len(warned) == 1 and "máy PICHU" in warned[0] and "(lệnh all)" in warned[0]


def test_van_chay_checkbox_unblocks_the_buttons(tmp_path):
    disabled, launched, _ = _run_pipeline_buttons(
        tmp_path, {"machine": "PICHU", "started_at": _started(10)}, override=True)
    assert disabled == dict.fromkeys(_BUTTONS, False) and len(launched) == 3


@pytest.mark.parametrize("marker", [None, {"machine": "PICHU", "started_at": _started(6 * 60)}])
def test_no_or_orphaned_marker_leaves_buttons_enabled_and_every_launch_writes_one(
        tmp_path, marker):
    import run

    disabled, launched, warned = _run_pipeline_buttons(tmp_path, marker)
    assert disabled == dict.fromkeys(_BUTTONS, False) and warned == []
    # Mọi bước mở ra phải tự GHI marker: run.py all|sync hoặc qua wrapper.
    steps = [c["args"] for cmds in launched for c in cmds]
    assert len(launched) == 3 and steps
    for a in steps:
        assert a[0] == "vnstock_pipeline_marker.py" or (
            a[0] == "run.py" and a[1] in run._PIPELINE_MARKED), a


def test_warehouse_last_close_keeps_price_above_500k(tmp_path, monkeypatch):
    """EPS/BV suy từ P/E, P/B: HLB 660 nghìn trên 500 không phải VND. Luật cũ `0 < close <=
    500 ⇒ ×1000` trên bar cuối file thô trả 660 đ ⇒ EPS/BV nhỏ 1000×. Phải đọc chuỗi ĐÃ
    chuẩn hoá (mốc = trung vị chuỗi)."""
    from datetime import datetime, timedelta

    import pyarrow.parquet as pq

    prices = tmp_path / "data_warehouse" / "prices"
    yd = prices / "ticker=HLB" / "year=2026"
    yd.mkdir(parents=True)
    closes = [300.0] * 30 + [660.0]
    pd.DataFrame({"time": pd.bdate_range("2026-09-01", periods=31),
                  "open": closes, "high": closes, "low": closes, "close": closes,
                  "volume": [1_000.0] * 31}).astype(
        {c: "float32" for c in ("open", "high", "low", "close")}
    ).to_parquet(yd / "p.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    ns = load_source_fns("vnstock_dashboard.py", "load_price_history", "_get_warehouse_last_close",
                         PRICES_DIR=prices, Path=Path, pq=pq, pd=pd, datetime=datetime,
                         timedelta=timedelta, _normalize_price_units=normalize_price_units)
    assert ns["_get_warehouse_last_close"]("HLB") == pytest.approx(660_000.0)
    assert ns["_get_warehouse_last_close"]("ZZZ") is None

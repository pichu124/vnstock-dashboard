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
from dashboard.watchlist_io import load_watchlist, save_watchlist
from vnstock_console_launch import build_ps_command
from vnstock_price_units import normalize_price_units
from vnstock_sectors import SECTOR_GROUPS, SECTOR_ORDER, get_sector


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
        assert cell_color("Trend", "UP") == "#10b981"

    @pytest.mark.parametrize("val", ["DOWN", "DN", "down", "dn"])
    def test_trend_down_variants_are_red(self, val):
        assert cell_color("Trend", val) == "#ef4444"

    def test_trend_unknown_is_neutral(self):
        assert cell_color("Trend", "SIDEWAY") == "#9ca3af"

    def test_ticker_and_industry_have_own_colors(self):
        assert cell_color("Ticker", "VCB") == "#60a5fa"
        assert cell_color("Ngành", "Ngân hàng") == "#a78bfa"

    def test_rsi_soft_bands(self):
        """Bậc 40/60 (cảnh báo mềm) — replica cũ nhảy thẳng từ 30 sang 70."""
        assert cell_color("RSI", "35") == "#6ee7b7"
        assert cell_color("RSI", "65") == "#fca5a5"
        assert cell_color("RSI", "50") == "#e5e7eb"

    @pytest.mark.parametrize("val,expected", [
        ("BUY", "#10b981"), ("BULL", "#34d399"),
        ("SELL", "#ef4444"), ("BEAR", "#f87171"),
        ("buy", "#10b981"),
    ])
    def test_macd_palette(self, val, expected):
        assert cell_color("MACD", val) == expected

    def test_macd_unknown_is_neutral(self):
        assert cell_color("MACD", "???") == "#9ca3af"

    def test_unknown_column_gets_default(self):
        assert cell_color("Vốn hoá", "12,345") == "#d1d5db"

    def test_empty_string_is_empty_gray(self):
        assert cell_color("Ticker", "") == "#4b5563"


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
    """Namespace chứa các hàm `names` của `relpath` (kể cả hàm lồng)."""
    tree = ast.parse((_ROOT / relpath).read_text(encoding="utf-8"))
    nodes: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            nodes.setdefault(n.name, n)
    ns = dict(globs)
    for name in names:
        node = nodes[name]
        node.decorator_list = []
        exec(compile(ast.Module([node], []), str(_ROOT / relpath), "exec"), ns)
    return ns


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
        send_telegram_alert=_send,
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
        "dashboard/analysis_tab.py", "_alert_checker", st=st,
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


def test_failed_telegram_send_is_logged(alert_env, caplog):
    alert_env["send_telegram_alert"] = lambda *a: False
    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        alert_env["check_and_fire_alerts"](
            [{"ticker": "VCB", "condition": "above", "target": 25.0}], "tok", "chat")
    assert "VCB" in caplog.text


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
    assert out["RSI"].tolist() == ["55.0", "—"]   # cột khác giữ nguyên format


# ── Điều hướng tab bằng st.pills ─────────────────────────────────────────────

_DASH_SRC = (_ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8")


def _run_nav(clicks: list) -> tuple:
    """Chạy ĐÚNG khối nav (trích từ source) qua nhiều lượt rerun với st giả."""
    start = _DASH_SRC.index("_TAB_OPTIONS = [")
    block = _DASH_SRC[start:_DASH_SRC.index("if _active_tab ==", start)]
    calls: list = []
    session: dict = {}
    tabs = []
    for value in clicks:
        def pills(label, options, **kw):
            calls.append((label, kw))
            return value
        ns = {"st": types.SimpleNamespace(pills=pills, session_state=session)}
        exec(block, ns)
        tabs.append(ns["_active_tab"])
    return tabs, calls


def test_reclicking_selected_pill_keeps_previous_tab():
    """Bấm lại pill đang chọn ⇒ st.pills trả None ⇒ vùng chính TRẮNG."""
    assert _run_nav(["💰 Dòng Tiền", None, None])[0] == ["💰 Dòng Tiền"] * 3


def test_first_run_with_no_selection_falls_back_to_screener():
    assert _run_nav([None])[0] == ["📊 Screener"]


def test_nav_pills_have_a_real_but_hidden_label():
    """label rỗng ⇒ Streamlit cảnh báo accessibility mỗi lượt."""
    label, kw = _run_nav(["📊 Screener"])[1][0]
    assert label.strip()
    assert kw.get("label_visibility") == "collapsed"


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

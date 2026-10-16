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
from vnstock_parquet_io import write_json_atomic
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


def _run_alert_sidebar(alert_env):
    """Chạy ĐÚNG khối 🔔 Price Alerts ở sidebar analysis_tab, bấm "✅ Tạo alert"
    (nút giả tôn trọng `disabled` như Streamlit thật)."""
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
    ns = {"st": st, "ALERTS_PATH": alert_env["ALERTS_PATH"],
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
        "dashboard/analysis_tab.py", "_alert_checker", st=st,
        load_alerts=alert_env["load_alerts"], save_alerts=alert_env["save_alerts"],
        check_and_fire_alerts=alert_env["check_and_fire_alerts"],
        log=logging.getLogger("vnstock_dashboard"), ALERTS_PATH=path,
    )["_alert_checker"]

    with caplog.at_level(logging.WARNING, logger="vnstock_dashboard"):
        frag()

    assert alert_env["sent"] == []
    assert path.read_bytes() == _TRUNCATED_ALERTS
    assert str(path) in caplog.text


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


# ── Lỗi không được nuốt im: dispatch tab + badge sidebar ────────────────────

_DASH_TREE = ast.parse(_DASH_SRC)


def test_every_tab_dispatch_logs_the_traceback():
    """st.error chỉ in 1 dòng — không log thì không ai lần ra lỗi gốc."""
    branches = [n for n in _DASH_TREE.body if isinstance(n, ast.If)
                and "_active_tab ==" in ast.unparse(n.test)]
    assert len(branches) >= 8
    for br in branches:
        for tr in (n for n in br.body if isinstance(n, ast.Try)):
            for h in tr.handlers:
                assert "log.exception(" in ast.unparse(h), ast.unparse(br.test)


@pytest.mark.parametrize("fname", ["test_status.json", "doctor_status.json",
                                   "model_status.json"])
def test_unreadable_sidebar_badge_says_so(fname, tmp_path, monkeypatch):
    """Badge biến mất khi file hỏng = user tưởng mọi thứ ổn."""
    tr = next(n for n in ast.walk(_DASH_TREE) if isinstance(n, ast.Try)
              and f"_meta/{fname}" in ast.unparse(n.body[0]))
    (tmp_path / "data_warehouse" / "_meta").mkdir(parents=True)
    (tmp_path / "data_warehouse" / "_meta" / fname).write_text("{hỏng", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    captions: list = []
    st = types.SimpleNamespace(caption=captions.append, markdown=lambda *a, **k: None)
    from datetime import datetime
    exec(compile(ast.Module([tr], []), "vnstock_dashboard.py", "exec"),
         {"st": st, "json": json, "Path": Path, "datetime": datetime})
    assert captions == [f"⚠ không đọc được {fname}"]


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
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_gtgd_daily",
                         "_compute_gtgd_by_window", pd=pd, Path=Path)
    ns["_load_gtgd_daily"] = functools.lru_cache(maxsize=None)(ns["_load_gtgd_daily"])
    for n in (0, 1, 5, 20):
        old = _gtgd_by_window_old(n)
        assert old, n
        assert ns["_compute_gtgd_by_window"](n) == old, n


def test_gtgd_reads_each_ticker_once_for_all_windows(gtgd_env):
    """Đổi 1D→5D→20D từng quét toàn kho 3 lần (cache riêng theo window_days)."""
    import functools
    fn = next(n for n in _DASH_TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "_load_gtgd_daily")
    assert any(ast.unparse(d).startswith("st.cache_data(") for d in fn.decorator_list)
    ns = load_source_fns("vnstock_dashboard.py", "_GTGD_SESSIONS", "_load_gtgd_daily",
                         "_compute_gtgd_by_window", pd=pd, Path=Path)
    ns["_load_gtgd_daily"] = functools.lru_cache(maxsize=None)(ns["_load_gtgd_daily"])
    for n in (1, 5, 20):
        ns["_compute_gtgd_by_window"](n)
    assert len(gtgd_env) == 3            # AAA, BBB, DDD — E1VFVN30 bị lọc trước khi đọc


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

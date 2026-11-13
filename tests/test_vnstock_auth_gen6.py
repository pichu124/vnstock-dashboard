"""vnstock thế hệ 6: nguồn khai MỘT chỗ (`VNSTOCK_SOURCE` / `VNSTOCK_SOURCE_ROUTES`) + mặt tiền `get_vnstock`.

Không gọi mạng: lệnh gọi dữ liệu thật cần khoá nguồn của user. Các test chạy cả khi CI không cài vnstock
(phần cần vnstock tự skip).
"""
from __future__ import annotations

import warnings

import pandas as pd
import pytest

import vnstock_auth as va


@pytest.fixture(autouse=True)
def _clean_source_env(monkeypatch):
    for k in ("VNSTOCK_SOURCE", "VNSTOCK_SOURCE_ROUTES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(va, "_SOURCES_DONE", False)


def test_parse_routes_reads_route_and_ordered_sources():
    got = va.parse_routes("fundamental.equity.*=a; market.equity.quote = b, c ;rác;=x;y=")
    assert got == [("fundamental.equity.*", ["a"]), ("market.equity.quote", ["b", "c"])]


def test_sources_configured_false_without_env():
    assert va.sources_configured() is False


def test_configure_sources_applies_default_then_routes(monkeypatch):
    calls = []
    vnstock = pytest.importorskip("vnstock")
    monkeypatch.setattr(vnstock.sources, "use", lambda *names, route="*": calls.append((names, route)))
    monkeypatch.setenv("VNSTOCK_SOURCE", "a,b")
    monkeypatch.setenv("VNSTOCK_SOURCE_ROUTES", "fundamental.equity.*=c")
    summary = va.configure_sources(force=True)
    assert summary == {"default": ["a", "b"], "routes": [("fundamental.equity.*", ["c"])]}
    assert calls == [(("a", "b"), "*"), (("c",), "fundamental.equity.*")]


def test_old_source_name_is_ignored_by_facade():
    shim = va.get_vnstock("fpt", "VCI")
    assert shim._symbol == "FPT"          # "VCI" không đi vào lệnh gọi thế hệ 6


def test_naive_local_time_daily_bar_at_7am_becomes_midnight_naive():
    df = pd.DataFrame({"time": pd.to_datetime(["2026-10-01T07:00:00+07:00", "2026-10-02T07:00:00+07:00"]),
                       "close": [1.0, 2.0]})
    out = va.naive_local_time(df, daily=True)
    assert out["time"].dt.tz is None
    assert out["time"].tolist() == [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")]
    assert df["time"].dt.tz is not None    # không sửa bảng gốc


def test_naive_local_time_minute_bars_keep_clock_time():
    df = pd.DataFrame({"time": pd.to_datetime(["2026-10-01T02:15:00+00:00"])})
    out = va.naive_local_time(df, daily=False)
    assert out["time"].iloc[0] == pd.Timestamp("2026-10-01 09:15")


def test_index_symbols_route_to_market_index():
    assert va.is_index_symbol("vnindex") and va.is_index_symbol("VN30")
    assert not va.is_index_symbol("FPT")


def test_quote_history_without_source_raises_typed_input_error():
    errors = pytest.importorskip("vnstock.errors")
    with pytest.raises(errors.InputError) as exc:
        va.get_vnstock("FPT").quote.history(start="2026-10-01")
    assert exc.value.code == "VNSTOCK_INPUT_SOURCE"


def test_quote_history_passes_interval_and_strips_old_only_args(monkeypatch):
    seen = {}

    class _Node:
        def ohlcv(self, **kw):
            seen.update(kw)
            return pd.DataFrame({"time": pd.to_datetime(["2026-10-01T07:00:00+07:00"]), "close": [77.7]})

    monkeypatch.setattr(va._Quote, "_node", lambda self: _Node())
    df = va.get_vnstock("FPT").quote.history(start="2026-10-01", end="2026-10-02", interval="1D",
                                             show_log=False, source="KBS")
    assert seen == {"start": "2026-10-01", "end": "2026-10-02", "interval": "1D"}
    assert df["time"].iloc[0] == pd.Timestamp("2026-10-01")


def test_delegate_renames_dropna_and_drops_source(monkeypatch):
    got = {}

    class _Fin:
        def balance_sheet(self, **kw):
            got.update(kw)
            return "ok"

    d = va._Delegate(_Fin())
    assert d.balance_sheet(period="quarter", dropna=False, source="VCI", show_log=False) == "ok"
    assert got == {"period": "quarter", "drop_empty": False}


def test_keep_schema_warnings_beats_blanket_ignore():
    errors = pytest.importorskip("vnstock.errors")
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("ignore")
        va.keep_schema_warnings()
        warnings.warn(errors.SchemaChangeWarning("bảng khác thế hệ 5", change="SCH-A03", severity="breaking",
                                                  route="market.equity.ohlcv"))
    assert any(issubclass(w.category, errors.SchemaChangeWarning) for w in rec)




def test_futures_symbols_route_to_market_futures(monkeypatch):
    vnstock = pytest.importorskip("vnstock")
    picked = []

    class _M:
        def index(self, s):
            picked.append(("index", s))

        def futures(self, s):
            picked.append(("futures", s))

        def equity(self, s):
            picked.append(("equity", s))

    monkeypatch.setattr(vnstock, "Market", _M)
    for sym in ("VN30F1M", "vn30f2512", "41I1G4000", "FPT", "VNINDEX"):
        va._Quote(sym)._node()
    assert picked == [("futures", "VN30F1M"), ("futures", "VN30F2512"), ("futures", "41I1G4000"),
                      ("equity", "FPT"), ("index", "VNINDEX")]


def test_bad_source_name_in_env_does_not_break_import_path(monkeypatch, capsys):
    vnstock = pytest.importorskip("vnstock")
    applied = []

    def _use(*names, route="*"):
        if "sai" in names:
            raise ValueError("nguồn không tồn tại")
        applied.append((names, route))

    monkeypatch.setattr(vnstock.sources, "use", _use)
    monkeypatch.setenv("VNSTOCK_SOURCE", "sai")
    monkeypatch.setenv("VNSTOCK_SOURCE_ROUTES", "fundamental.equity.*=x")
    va.configure_sources(force=True)            # không ném
    assert applied == [(("x",), "fundamental.equity.*")]
    assert "bỏ luật nguồn *=sai" in capsys.readouterr().err

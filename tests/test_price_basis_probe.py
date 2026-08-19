"""Lưới cho `scripts/probe_price_basis.py` — phân định KHO lệch cơ sở vs NGUỒN sai.

Hai chẩn đoán đòi cách chữa NGƯỢC NHAU (ghi đè lịch sử kho / cách ly bar hỏng
ở nguồn), nên phán nhầm là sửa nhầm chỗ. Phần fetch cần mạng nên không test
được offline; toàn bộ phép phán nằm ở hàm THUẦN `basis_report` — test ở đây
chấm đúng hàm đó, đúng kiểu tách "logic thuần khỏi I/O" của repo.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import probe_price_basis as ppb  # noqa: E402

BRK = date(2026, 6, 15)


def _df(pairs):
    return pd.DataFrame({"time": [p[0] for p in pairs],
                         "close": [p[1] for p in pairs]})


def _dates(n, start=date(2026, 6, 10)):
    return [start + pd.Timedelta(days=i) for i in range(n)]


def test_warehouse_keeps_the_old_basis_before_the_break():
    """Ca VVS: nguồn LIỀN MẠCH quanh 15/06 (71-72), kho thì 112.5 → 71.21.
    Tỉ lệ kho/nguồn đổi bậc đúng tại ngày vách ⇒ lịch sử kho giữ cơ sở CŨ."""
    d = [date(2026, 6, 11), date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 110.0), (d[1], 112.5), (d[2], 71.21), (d[3], 72.0)])
    src = _df([(d[0], 69.62), (d[1], 71.20), (d[2], 71.21), (d[3], 72.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "warehouse_basis"
    assert rep["ratio_before"] == pytest.approx(1.58, abs=0.01)
    assert rep["ratio_after"] == pytest.approx(1.0, abs=0.01)
    assert rep["shift"] == pytest.approx(1.58, abs=0.01)


def test_source_broken_the_same_way_is_not_a_warehouse_problem():
    """Nguồn cũng gãy y hệt ⇒ kho chép đúng. Ghi đè kho là vô ích — phán nhầm
    ở đây khiến người ta đi sửa sai chỗ."""
    d = [date(2026, 6, 11), date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 110.0), (d[1], 112.5), (d[2], 71.21), (d[3], 72.0)])
    rep = ppb.basis_report(wh, wh.copy(), BRK)
    assert rep["verdict"] == "source_error" and rep["has_break"]
    assert rep["ratio_before"] == pytest.approx(1.0, abs=1e-6)


def test_matching_series_without_a_break_is_aligned_not_broken():
    """Ca PNJ 18/08: kho đã khớp nguồn 1.0000× toàn dải và KHÔNG còn vách —
    tool vẫn hô "NGUỒN CŨNG GÃY". "Cùng bậc hai bên" chưa đủ để kết tội
    nguồn; phải CÓ VÁCH THẬT tại ngày đó đã."""
    d = [date(2026, 6, 11), date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 72.0), (d[1], 73.0), (d[2], 74.0), (d[3], 73.5)])
    rep = ppb.basis_report(wh, wh.copy(), BRK)
    assert rep["verdict"] == "aligned" and not rep["has_break"]


def test_small_rounding_differences_still_count_as_same_basis():
    """Chênh lệch làm tròn/bước giá (~1%) KHÔNG được đọc thành đổi cơ sở."""
    d = _dates(6)
    wh = _df([(x, 100.0 + i * 0.1) for i, x in enumerate(d)])
    src = _df([(x, (100.0 + i * 0.1) * 1.008) for i, x in enumerate(d)])
    # Ý test: KHÔNG được đọc thành đổi cơ sở. Chuỗi này mượt (không vách) nên
    # verdict đúng là `aligned`; điều phải giữ là "không phải warehouse_basis".
    assert ppb.basis_report(wh, src, BRK)["verdict"] != "warehouse_basis"


def test_no_overlap_is_reported_not_guessed():
    wh = _df([(date(2026, 1, 5), 10.0)])
    src = _df([(date(2026, 7, 5), 10.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "no_overlap" and rep["n"] == 0


def test_one_sided_window_is_inconclusive_not_a_verdict():
    """Chỉ có bar một phía ngày vách thì KHÔNG đủ để phán — phải nói rõ
    "chưa kết luận" thay vì chọn bừa một trong hai chẩn đoán."""
    d = [date(2026, 6, 11), date(2026, 6, 12)]
    wh = _df([(d[0], 110.0), (d[1], 112.5)])
    src = _df([(d[0], 69.62), (d[1], 71.20)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "inconclusive"
    assert rep["n_after"] == 0


def test_zero_and_negative_closes_are_dropped_before_dividing():
    """Bar giá 0 (mã nghỉ/giá tham chiếu lỗi) chia ra inf — phải loại trước."""
    d = [date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 112.5), (d[1], 0.0), (d[2], 72.0)])
    src = _df([(d[0], 71.20), (d[1], 71.21), (d[2], 72.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["n"] == 2                      # bar 0 bị loại
    assert rep["verdict"] == "warehouse_basis"


# ── Tự tìm ngày vách + chạy nhiều mã (thêm 18/08 sau bảng quét 149 mã) ──────

def _write_bars(wh: Path, ticker: str, closes, dates):
    import pandas as _pd
    d = wh / "prices" / f"ticker={ticker}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    _pd.DataFrame({"time": _pd.to_datetime(dates), "open": closes,
                   "high": closes, "low": closes, "close": closes,
                   "volume": [100_000] * len(closes)}).to_parquet(
        d / "p.parquet", index=False)


def test_break_date_is_found_from_the_warehouse(tmp_path):
    """Bảng quét ra 149 mã; bắt người dùng chép tay từng ngày vách là mời sai
    sót. Probe tự tìm vách NẶNG NHẤT, dùng lại `find_jumps` của tool kia để
    hai bên không bao giờ bất đồng về "đâu là vách"."""
    import pandas as _pd
    wh = tmp_path / "wh"
    dates = [str(d.date()) for d in _pd.bdate_range(end="2026-08-17", periods=4)]
    _write_bars(wh, "VHM", [148.10, 74.00, 75.0, 76.0], dates)
    assert ppb._find_break(wh / "prices", "VHM").isoformat() == dates[1]


def test_no_suspect_jump_returns_none_not_a_guess(tmp_path):
    import pandas as _pd
    wh = tmp_path / "wh"
    dates = [str(d.date()) for d in _pd.bdate_range(end="2026-08-17", periods=3)]
    _write_bars(wh, "AAA", [10.0, 10.1, 10.0], dates)
    assert ppb._find_break(wh / "prices", "AAA") is None


def test_missing_ticker_raises_instead_of_looking_clean(tmp_path):
    """VẾT 18/08: `_find_break` từng bọc try/except cả hàm rồi trả None, nên
    "kho sạch" và "tìm hỏng" in ra Y HỆT NHAU — user chạy rebase cho 4 mã,
    thấy 4 dòng ✅ và tưởng đã chữa xong, trong khi chưa soi được gì. Lỗi
    PHẢI nổi lên; chỉ "thật sự không có vách" mới được trả None."""
    import pytest as _pt
    with _pt.raises(Exception):
        ppb._find_break(tmp_path / "prices", "ZZZ")


# ── Không bao giờ hỏi nguồn về NGÀY MAI (vá 19/08) ─────────────────────────

def test_window_never_reaches_into_the_future():
    """Vết 19/08: vách càng gần hôm nay thì `brk + 30 ngày` càng vượt quá hôm
    nay. VNM/2026-08-01 sinh khoảng tới 2026-08-31 và nguồn nổ
    `UnboundLocalError` bọc trong RetryError — lỗi vô nghĩa với người đọc.
    Xin dữ liệu tương lai là vô nghĩa dù thư viện có xử êm hay không."""
    from datetime import date as _d, timedelta as _td
    assert ppb._clamp_today(_d.today() + _td(days=30)) == _d.today()
    assert ppb._clamp_today(_d.today()) == _d.today()
    past = _d.today() - _td(days=45)
    assert ppb._clamp_today(past) == past, "quá khứ KHÔNG được đụng vào"


def test_rebase_window_is_clamped_too():
    """Cùng lỗi ở công cụ chữa — nó cũng dựng cửa sổ quanh vách."""
    import inspect, sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import rebase_ticker_history as rth
    src = inspect.getsource(rth)
    assert "min(d1, date.today())" in src


# ── Quét lệch cơ sở theo universe (thêm 19/08 sau ca VNM) ──────────────────
#
# Vì sao: `check_unit_continuity` nhìn VÁCH GIÁ nên chỉ thấy lệch ≥30%. VNM
# lệch 3,27% (cỡ một lần cổ tức tiền mặt) hoàn toàn vô hình với nó — giá liền
# mạch, khớp giá live, mã được báo sạch, trong khi TOÀN BỘ lịch sử trước 23/06
# ở cơ sở cũ. Lớp lỗi này chỉ hiện qua TỈ LỆ kho/nguồn.

def _pair(n, ratio_before, ratio_after, split_at, start="2026-05-01"):
    d = pd.bdate_range(start=start, periods=n)
    src = [50.0 + i * 0.1 for i in range(n)]
    wh = [s * (ratio_before if i < split_at else ratio_after)
          for i, s in enumerate(src)]
    return (pd.DataFrame({"time": [x.date() for x in d], "close": wh}),
            pd.DataFrame({"time": [x.date() for x in d], "close": src}))


class TestFindBasisStep:

    def test_dividend_sized_step_is_found(self):
        """Ca VNM: 1.0327× trước, 1.0000× sau — dưới xa ngưỡng 30% của bộ dò
        vách giá, nên đây là lớp lỗi CHỈ chế độ này thấy."""
        wh, src = _pair(40, 1.0327, 1.0, 20)
        step = ppb.find_basis_step(wh, src)
        assert step is not None
        assert step["shift"] == pytest.approx(1.0327, abs=1e-3)
        assert step["break"] == wh["time"].iloc[20]

    def test_matching_series_reports_nothing(self):
        wh, src = _pair(40, 1.0, 1.0, 20)
        assert ppb.find_basis_step(wh, src) is None

    def test_rounding_noise_is_not_a_step(self):
        """Chênh do làm tròn/bước giá (~0,3%) KHÔNG được đọc thành đổi cơ sở —
        báo động oan ở đây là làm hỏng cả danh sách."""
        wh, src = _pair(40, 1.003, 1.0, 20)
        assert ppb.find_basis_step(wh, src) is None

    def test_one_bad_bar_does_not_fake_a_step(self):
        """Bar lỗi ĐƠN LẺ làm bước 1 (nhảy tỉ lệ) kêu, nhưng không đổi được
        trung vị hai phía — bước 2 phải loại nó."""
        wh, src = _pair(40, 1.0, 1.0, 20)
        wh.loc[15, "close"] = wh.loc[15, "close"] * 1.20
        assert ppb.find_basis_step(wh, src) is None

    def test_step_too_close_to_the_edge_is_refused(self):
        """Bậc sát mép cửa sổ thì một phía không đủ bar để trung vị có nghĩa."""
        wh, src = _pair(30, 1.05, 1.0, 2)
        assert ppb.find_basis_step(wh, src) is None

    def test_short_series_is_refused_not_guessed(self):
        wh, src = _pair(6, 1.05, 1.0, 3)
        assert ppb.find_basis_step(wh, src) is None

    def test_step_in_the_other_direction_too(self):
        wh, src = _pair(40, 1.0, 1.04, 20)
        step = ppb.find_basis_step(wh, src)
        assert step is not None and step["shift"] == pytest.approx(1 / 1.04, abs=1e-3)


class TestSweepCli:

    def test_sweep_flag_exists_and_ticker_optional(self):
        ns = ppb.__dict__
        import argparse
        assert "_sweep_universe" in ns
        p = Path("scripts/probe_price_basis.py").read_text(encoding="utf-8")
        assert '"--sweep"' in p and '"--min-gtgd"' in p and '"--limit"' in p

    def test_cut_by_limit_is_announced_not_silent(self):
        """Nếp repo: cắt bao nhiêu phải IN RA — cắt im lặng đọc thành
        'đã soi hết' trong khi chưa."""
        p = Path("scripts/probe_price_basis.py").read_text(encoding="utf-8")
        assert "CẮT còn" in p and "KHÔNG được soi" in p

    def test_unfetchable_tickers_are_not_counted_clean(self):
        """Vết 18/08: 'không soi được' ≠ 'sạch'. Phải in riêng."""
        p = Path("scripts/probe_price_basis.py").read_text(encoding="utf-8")
        assert "KHÔNG soi được (chưa kết luận gì)" in p

    def test_sweep_writes_a_stamp_for_the_badge(self, tmp_path):
        ppb._write_sweep_stamp(tmp_path, 120, ["VNM", "ABC"], ["XYZ"])
        import json as _j
        data = _j.loads((tmp_path / "_meta" / "basis_sweep_check.json")
                        .read_text(encoding="utf-8"))
        assert data["scanned"] == 120 and data["suspect"] == ["ABC", "VNM"]
        assert data["unchecked"] == ["XYZ"]


# ── Điểm mù ngưỡng GTGD ─────────────────────────────────────────────────────
# Ca NTP (19/08): lệch cơ sở từ 06/2026 nhưng chỉ LỘ RA khi thanh khoản nhích
# qua 5 tỷ và rơi vào tầm quét. Ngưỡng GTGD chỉ là PHỎNG ĐOÁN cho "mã nào quan
# trọng", còn universe huấn luyện chọn theo THÀNH PHẦN CHỈ SỐ (VN30/VNMID) —
# hai tiêu chí khác nhau, và khoảng hở giữa chúng đi thẳng vào backtest.

class TestUniverseBlindSpot:
    def _warehouse(self, tmp_path, tickers, gtgd_ty):
        """Kho giả: mỗi mã 20 bar với GTGD ~ `gtgd_ty` tỷ/phiên."""
        days = pd.bdate_range(end="2026-08-17", periods=20)
        for tk in tickers:
            d = tmp_path / "prices" / f"ticker={tk}" / "year=2026"
            d.mkdir(parents=True)
            close = 10.0
            vol = gtgd_ty[tk] * 1e6 / close      # close×volume/1e6 = tỷ
            pd.DataFrame({"time": days, "open": close, "high": close,
                          "low": close, "close": close,
                          "volume": [vol] * len(days)}).to_parquet(
                d / "p.parquet", index=False)
        return tmp_path

    def test_universe_ticker_below_the_threshold_is_still_scanned(
            self, tmp_path, monkeypatch, capsys):
        wh = self._warehouse(tmp_path, ["AAA", "NTP"],
                             {"AAA": 50.0, "NTP": 1.0})
        monkeypatch.setattr(ppb, "strategy_universe", lambda: {"NTP"})
        seen = []
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: seen.append(tk) or pd.DataFrame())
        ppb._sweep_universe(wh, min_gtgd=5.0, since_days=365, limit=0, delay=0)
        assert "NTP" in seen, "mã trong universe backtest bị bỏ sót vì thanh khoản"
        assert "NTP" in capsys.readouterr().out

    def test_no_universe_flag_restores_the_pure_liquidity_scan(
            self, tmp_path, monkeypatch):
        wh = self._warehouse(tmp_path, ["AAA", "NTP"],
                             {"AAA": 50.0, "NTP": 1.0})
        monkeypatch.setattr(ppb, "strategy_universe", lambda: {"NTP"})
        seen = []
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: seen.append(tk) or pd.DataFrame())
        ppb._sweep_universe(wh, min_gtgd=5.0, since_days=365, limit=0, delay=0,
                            with_universe=False)
        assert seen == ["AAA"]

    def test_a_ticker_is_never_scanned_twice(self, tmp_path, monkeypatch):
        """Mã vừa trên ngưỡng vừa trong universe — mỗi mã một lần gọi mạng."""
        wh = self._warehouse(tmp_path, ["AAA"], {"AAA": 50.0})
        monkeypatch.setattr(ppb, "strategy_universe", lambda: {"AAA"})
        seen = []
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: seen.append(tk) or pd.DataFrame())
        ppb._sweep_universe(wh, min_gtgd=5.0, since_days=365, limit=0, delay=0)
        assert seen == ["AAA"]

    def test_unavailable_universe_says_so_instead_of_going_quiet(
            self, tmp_path, monkeypatch, capsys):
        """Không lấy được universe = quét THIẾU. Im lặng ở đây là tệ nhất."""
        wh = self._warehouse(tmp_path, ["AAA"], {"AAA": 50.0})
        monkeypatch.setattr(ppb, "strategy_universe", lambda: set())
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: pd.DataFrame())
        ppb._sweep_universe(wh, min_gtgd=5.0, since_days=365, limit=0, delay=0)
        assert "BỎ SÓT" in capsys.readouterr().out

    def test_strategy_universe_is_never_none_and_upper_cased(self):
        u = ppb.strategy_universe()
        assert isinstance(u, set)
        assert all(t == t.upper() for t in u)

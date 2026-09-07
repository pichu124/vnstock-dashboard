"""Lưới cho bộ dò vách THỨ BA — vách suy từ MỨC (`level_break_report`).

**Ca thật, đo 26/08 trên máy user.** Lượt chạy thử 69 mã trong sổ cách ly:
56 mã qua, **13 mã bị `--whole-series` từ chối** — ACE · C22 · DBD · DRG ·
EMS · GH3 · ILB · MCH · PRE · SDV · TRS · VC3 · VSN. Cả 13 có chung một chữ
ký trong dòng từ chối::

    tỉ lệ LỞM CHỞM: 1.0000× → 1.0857×

Cận dưới **1.0000×** nghĩa là một phần chuỗi ĐÃ khớp nguồn. Đó không phải
lệch đồng đều — đó là **một vách thật**, và `--whole-series` từ chối đúng.

Vậy vì sao hai bộ dò bậc cũng im? Vì `find_basis_step` đòi đủ bar **mỗi
phía**::

    BASIS_MIN_SIDE = 5
    if i < BASIS_MIN_SIDE or len(r) - i < BASIS_MIN_SIDE:
        return None

Mã bị gác chặn sau ngày GDKHQ 3 phiên chỉ có 2-3 bar ở phía cơ sở mới ⇒ dưới
sàn ⇒ `None`. Và **phía đó không bao giờ mọc thêm**, vì chính cửa gác đang
chặn cập nhật. Lại một vòng tự khoá — khác vòng ở U42 nhưng cùng hình dạng:
*bộ dò đòi một thứ bằng chứng mà cửa gác không cho phép sinh ra.*

Bộ dò mới không đếm bar mỗi phía. Nó hỏi **chỗ nào tỉ lệ thôi lệch**: ngày
lệch cuối cùng + 1. Đổi lại nó đòi CHIA SẠCH — lệch xen kẽ thì trả None, vì
đoán một cái mốc còn tệ hơn không có mốc.
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebase_ticker_history.py"
_spec = importlib.util.spec_from_file_location("rebase_ticker_history_lb", _SCRIPT)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

FACTOR = 1.0857
N_BARS = 60
N_NEW = 3          # bar đã sang cơ sở mới — DƯỚI sàn 5 của bộ dò bậc


def _days(n=N_BARS, end_offset=2):
    last = date.today() - timedelta(days=end_offset)
    return [last - timedelta(days=n - 1 - i) for i in range(n)]


def _src_frame(days=None):
    days = days or _days()
    close = [100.0 + i for i in range(len(days))]
    return pd.DataFrame({
        "time": pd.to_datetime(days),
        "open": close, "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close], "close": close,
        "volume": [1000.0] * len(days),
    })


def _ratios(n=N_BARS, n_new=N_NEW, factor=FACTOR):
    """Kho giữ cơ sở CŨ ở phần lịch sử, đã sang cơ sở mới ở `n_new` bar cuối."""
    return [factor] * (n - n_new) + [1.0] * n_new


def _as_source(src):
    out = src[["time", "close"]].copy()
    out["time"] = pd.to_datetime(out["time"]).dt.date
    return out


def _pair(ratios):
    src = _src_frame()
    wh = src.copy()
    wh["close"] = [v * r for v, r in zip(src["close"], ratios)]
    return wh[["time", "close"]], src[["time", "close"]]


def _write_wh(root, tk, src, ratios):
    wh = src.copy()
    for c in ("open", "high", "low", "close"):
        wh[c] = [v * r for v, r in zip(src[c], ratios)]
    d = root / "prices" / f"ticker={tk}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    pq = d / "part-0.parquet"
    wh.to_parquet(pq, index=False)
    return pq


class TestTheGapIsReal:
    """Chứng minh bằng chính hàm thật, không phải suy diễn từ docstring."""

    def test_the_step_detector_goes_blind_when_the_new_side_is_short(self):
        from probe_price_basis import BASIS_MIN_SIDE, find_basis_step
        assert N_NEW < BASIS_MIN_SIDE
        assert find_basis_step(*_pair(_ratios())) is None

    def test_but_the_break_is_plainly_there(self):
        """Cùng bộ dữ liệu, bộ dò mới chỉ đúng ngày."""
        rep = R.level_break_report(*_pair(_ratios()))
        assert rep["break"] == _days()[N_BARS - N_NEW - 1] + timedelta(days=1)
        assert rep["ratio_before"] == pytest.approx(FACTOR, abs=1e-9)

    def test_the_step_detector_wakes_up_once_the_new_side_is_long_enough(self):
        """Không phải bộ dò cũ sai — nó chỉ có một sàn bar mà ca này không
        bao giờ chạm tới được."""
        from probe_price_basis import find_basis_step
        assert find_basis_step(*_pair(_ratios(n_new=20))) is not None

    def test_the_uniform_gate_correctly_refuses_this_shape(self):
        """`--whole-series` từ chối 13 mã ấy là ĐÚNG — chúng có vách, không
        lệch đều. Bản vá này không được nới cửa đó."""
        rep = R.uniform_offset_report(*_pair(_ratios()))
        assert rep["uniform"] is False and "LỞM CHỞM" in rep["why"]


class TestLevelBreakReport:
    def test_an_all_divergent_series_is_NOT_a_break(self):
        """Bất biến chia việc: lệch ở MỌI bar là ca `--whole-series`. Trả một
        cái mốc ở đây là hai đường chữa giành nhau cùng một mã."""
        rep = R.level_break_report(*_pair([FACTOR] * N_BARS))
        assert rep["break"] is None and "MỌI bar" in rep["why"]

    def test_an_aligned_series_is_not_a_break_either(self):
        rep = R.level_break_report(*_pair([1.0] * N_BARS))
        assert rep["break"] is None and "đã khớp nguồn" in rep["why"]

    def test_one_new_bar_is_not_enough(self):
        rep = R.level_break_report(*_pair(_ratios(n_new=1)))
        assert rep["break"] is None and "chưa đủ để nói có vách" in rep["why"]

    def test_the_minimum_is_below_the_step_detector_floor(self):
        """Nếu đặt bằng hoặc cao hơn sàn của bộ dò bậc thì bộ dò mới không vá
        được gì — nó sẽ mù ở đúng chỗ bộ dò cũ mù."""
        from probe_price_basis import BASIS_MIN_SIDE
        assert R.LEVEL_BREAK_MIN_AFTER < BASIS_MIN_SIDE

    def test_an_interleaved_divergence_is_refused(self):
        """Lệch xen kẽ không phải MỘT vách — đoán một cái mốc ở đây là ghi đè
        nhầm nửa lịch sử."""
        rat = [FACTOR if i % 2 else 1.0 for i in range(N_BARS - 3)] + [1.0] * 3
        rep = R.level_break_report(*_pair(rat))
        assert rep["break"] is None and "xen kẽ" in rep["why"]

    def test_a_few_clean_bars_before_the_break_are_tolerated(self):
        """Chia sạch không có nghĩa là hoàn hảo: vài bar khớp nguồn do làm
        tròn là chuyện thường, chặn hết thì bộ dò vô dụng trên data thật."""
        rat = _ratios()
        rat[0] = 1.0
        assert R.level_break_report(*_pair(rat))["break"] is not None

    def test_its_tolerance_matches_the_guard(self):
        import inspect
        from vnstock_basis_guard import TOL
        sig = inspect.signature(R.level_break_report)
        assert sig.parameters["tol"].default == pytest.approx(TOL)

    def test_it_never_raises_on_garbage(self):
        rep = R.level_break_report(pd.DataFrame({"x": [1]}), pd.DataFrame())
        assert rep["break"] is None and rep["why"]

    def test_a_broken_source_never_raises(self, tmp_path, monkeypatch):
        import probe_price_basis as ppb
        monkeypatch.setattr(ppb, "load_wh",
                            lambda *a, **k: (_ for _ in ()).throw(IOError("hỏng")))
        assert R._level_break_of("VCB", tmp_path)["break"] is None

    def test_a_missing_ticker_is_not_an_error(self, tmp_path):
        assert R._level_break_of("KHONGCO", tmp_path)["break"] is None


class TestEndToEnd:
    @pytest.fixture
    def stuck(self, tmp_path, monkeypatch):
        src = _src_frame()
        pq = _write_wh(tmp_path, "ACE", src, _ratios())
        import probe_price_basis as ppb
        import vnstock_updater as upd
        monkeypatch.setattr(upd, "_fetch_prices", lambda tk, d0, d1: src.copy())
        monkeypatch.setattr(ppb, "fetch_source", lambda tk, d0, d1: _as_source(src))
        return tmp_path, src, pq

    def test_the_ticker_is_no_longer_stuck(self, stuck, capsys):
        """Trước bản vá: cả ba bộ dò im ⇒ rơi vào nhánh lệch-đều ⇒
        `--whole-series` từ chối vì lởm chởm ⇒ **không đường nào chữa được**."""
        root, src, _ = stuck
        rc = R._rebase_one("ACE", root, apply=True)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "MỨC lệch DỪNG tại" in out

    def test_the_whole_history_lands_on_the_source_basis(self, stuck):
        root, src, pq = stuck
        R._rebase_one("ACE", root, apply=True)
        got = pd.read_parquet(pq).sort_values("time").reset_index(drop=True)
        assert got["close"].tolist() == pytest.approx(src["close"].tolist())
        assert R._residual_level(root / "prices", "ACE", src) is None

    def test_it_needs_no_whole_series_flag(self, stuck):
        """Đây là vách THẬT ⇒ đi đường vách, không cần cờ ghi-đè-trọn-lịch-sử.
        Bắt user gõ cờ mạnh tay cho một ca không cần là dạy sai thói quen."""
        root, _, _ = stuck
        assert R._rebase_one("ACE", root, apply=True, whole_series=False) == 0

    def test_dry_run_still_writes_nothing(self, stuck):
        root, _, pq = stuck
        before = pq.read_bytes()
        assert R._rebase_one("ACE", root, apply=False) == 0
        assert pq.read_bytes() == before

    def test_the_level_break_runs_before_the_uniform_branch(self):
        """Thứ tự là bất biến: có phía 'cơ sở mới' thì đó là vách, và đường
        vách chính xác hơn (chỉ đụng phần trước mốc)."""
        import inspect
        s = inspect.getsource(R._rebase_one)
        assert s.index("_level_break_of") < s.index("_uniform_probe")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

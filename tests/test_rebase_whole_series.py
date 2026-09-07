"""Lưới cho chế độ `--whole-series` của `rebase_ticker_history`.

**Vì sao cần một đường chữa RIÊNG.** Đường chữa cũ dựng trên một giả định:
có một VÁCH, trước vách là cơ sở cũ, sau vách là cơ sở mới, hệ số = trung vị
trước / trung vị sau. Lớp lỗi đo được 26/08 phá đúng giả định đó — nguồn
back-adjust TRỌN lịch sử nên kho lệch nguồn **cùng một hệ số ở MỌI bar**:

* `_find_break` (vách giá ≥30% trong kho) — không thấy gì, kho tự nó liền mạch;
* `find_basis_step` (`jumps = |r[1:]/r[:-1] − 1|`) — đạo hàm bằng 0 ở mọi điểm;
* `_probe` → `basis_report` — so trung vị HAI PHÍA mốc, mà trước = sau nên nó
  luôn phán `aligned`, tức cửa `verdict == "warehouse_basis"` KHÔNG BAO GIỜ mở.

Chỉ cửa gác (`check_basis`, đo MỨC) và `last_divergent_day` thấy. Đo trên máy
user: SDK **1.4857×** mà `probe_price_basis --ticker SDK` in *"không tìm thấy
vách nghi vấn trong 365 ngày"*.

**Cửa vào của chế độ này KHÔNG phải `_probe`** (hỏi nó là hỏi sai câu) mà là
`uniform_offset_report` — chặt hơn, vì ghi đè trọn lịch sử là việc không lùi
được: đòi tỉ lệ vừa LỆCH vừa ỔN ĐỊNH (`max/min ≤ UNIFORM_SPREAD_MAX`) trên
≥`UNIFORM_MIN_BARS` bar. Lệch lởm chởm = còn chuyện khác trộn vào, nhân cả
chuỗi bằng một hệ số là bôi cái sai ra khắp lịch sử.

**Và bước tự kiểm phải đổi theo.** Hai bước tự kiểm cũ (`find_jumps`,
`_residual_basis_step`) đều đo ĐẠO HÀM ⇒ mù đúng lớp lỗi mà chế độ này sinh ra
để chữa. Chữa hụt hệ số để lại một chuỗi vẫn lệch ĐỀU, và cả hai in xanh. Nên
có bước thứ ba `_residual_level`, đo MỨC.
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebase_ticker_history.py"
_spec = importlib.util.spec_from_file_location("rebase_ticker_history_ws", _SCRIPT)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

RATIO = 1.4857
N_BARS = 60


def _days(n=N_BARS, end_offset=10):
    """`n` ngày liên tiếp kết thúc trước hôm nay — phải nằm trong 365 ngày mà
    mọi bộ dò đều soi, và KHÔNG chạm bar hôm nay (phiên dở dang không phải
    lệch cơ sở, `last_divergent_day` cố tình bỏ)."""
    last = date.today() - timedelta(days=end_offset)
    return [last - timedelta(days=n - 1 - i) for i in range(n)]


def _src_frame(days=None) -> pd.DataFrame:
    days = days or _days()
    close = [100.0 + i for i in range(len(days))]
    return pd.DataFrame({
        "time": pd.to_datetime(days),
        "open": close, "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close], "close": close,
        "volume": [1000.0] * len(days),
    })


def _as_source(src: pd.DataFrame) -> pd.DataFrame:
    """Đúng hợp đồng của `probe_price_basis.fetch_source`: hai cột, `time` là
    `date` THUẦN. Stub trả datetime64 là merge nổ ngay trong bộ dò — và nổ ở
    chỗ ấy thì test đỏ vì lý do chẳng liên quan gì tới thứ đang đo."""
    out = src[["time", "close"]].copy()
    out["time"] = pd.to_datetime(out["time"]).dt.date
    return out


def _write_wh(root: Path, tk: str, src: pd.DataFrame, ratios) -> Path:
    """Kho = nguồn × `ratios` (số → lệch đều, list → lệch lởm chởm)."""
    if not hasattr(ratios, "__len__"):
        ratios = [float(ratios)] * len(src)
    wh = src.copy()
    for c in ("open", "high", "low", "close"):
        wh[c] = [v * r for v, r in zip(src[c], ratios)]
    d = root / "prices" / f"ticker={tk}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    pq = d / "part-0.parquet"
    wh.to_parquet(pq, index=False)
    return pq


@pytest.fixture
def offset_wh(tmp_path, monkeypatch):
    """Một mã lệch ĐỒNG ĐỀU `RATIO`× — không vách, không bậc, chỉ lệch mức."""
    src = _src_frame()
    _write_wh(tmp_path, "SDK", src, RATIO)
    import probe_price_basis as ppb
    import vnstock_updater as upd
    monkeypatch.setattr(upd, "_fetch_prices", lambda tk, d0, d1: src.copy())
    monkeypatch.setattr(ppb, "fetch_source",
                        lambda tk, d0, d1: _as_source(src))
    return tmp_path, src


# --------------------------------------------------------------------------
class TestUniformOffsetReport:
    """Cửa DUY NHẤT cho phép ghi đè trọn lịch sử — nó phải chặt."""

    def _pair(self, ratios):
        src = _src_frame()
        wh = src.copy()
        if not hasattr(ratios, "__len__"):
            ratios = [float(ratios)] * len(src)
        wh["close"] = [v * r for v, r in zip(src["close"], ratios)]
        return wh[["time", "close"]], src[["time", "close"]]

    def test_a_clean_uniform_offset_opens_the_gate(self):
        wh, src = self._pair(RATIO)
        rep = R.uniform_offset_report(wh, src)
        assert rep["uniform"] is True
        assert rep["ratio"] == pytest.approx(RATIO, abs=1e-9)
        assert rep["n"] == N_BARS

    def test_a_ragged_offset_is_refused(self):
        """Lệch lởm chởm = còn chuyện khác trộn vào; nhân cả chuỗi bằng MỘT hệ
        số khi đó là bôi cái sai ra khắp lịch sử."""
        n = N_BARS
        ratios = [RATIO * (1 + 0.08 * i / (n - 1)) for i in range(n)]
        rep = R.uniform_offset_report(*self._pair(ratios))
        assert rep["uniform"] is False
        assert "LỞM CHỞM" in rep["why"]

    def test_an_aligned_series_is_refused_as_nothing_to_fix(self):
        rep = R.uniform_offset_report(*self._pair(1.0))
        assert rep["uniform"] is False
        assert "KHÔNG lệch" in rep["why"]

    def test_a_few_bars_crammed_into_a_few_weeks_is_refused(self):
        """Ít bar VÀ chụm lại thì không nói được gì: một lần đổi cơ sở ngay
        ngoài cửa sổ ấy vẫn vô hình."""
        src = _src_frame(_days(n=R.UNIFORM_MIN_BARS - 1))     # 19 bar, 18 ngày
        wh = src.copy()
        wh["close"] = wh["close"] * RATIO
        rep = R.uniform_offset_report(wh[["time", "close"]], src[["time", "close"]])
        assert rep["uniform"] is False and "quá mỏng" in rep["why"]
        assert f"{rep['span_days']} ngày" in rep["why"]

    def test_the_refusal_shows_the_measurements_not_just_the_verdict(self):
        """"Quá ít bar" không nói được là mã ấy đáng xét tiếp hay đáng bỏ —
        vết GH3 07/09: dòng từ chối giấu mất spread 1.0011, tức giấu đúng con
        số quyết định."""
        src = _src_frame(_days(n=10))
        wh = src.copy()
        wh["close"] = wh["close"] * RATIO
        rep = R.uniform_offset_report(wh[["time", "close"]], src[["time", "close"]])
        assert "1.1" in rep["why"] or f"{RATIO:.4f}" in rep["why"]
        assert "spread" in rep["why"]



    def test_no_overlap_at_all_is_refused_not_crashed(self):
        wh, _ = self._pair(RATIO)
        src = _src_frame(_days(end_offset=900))
        rep = R.uniform_offset_report(wh, src[["time", "close"]])
        assert rep["uniform"] is False and rep["n"] == 0

    def test_it_never_raises_on_garbage(self):
        rep = R.uniform_offset_report(pd.DataFrame({"x": [1]}), pd.DataFrame())
        assert rep["uniform"] is False and rep["why"]

    def test_the_spread_ceiling_is_tighter_than_the_guard_tolerance(self):
        """Cửa ghi-đè-trọn-lịch-sử phải CHẶT HƠN cửa gác chặn hằng đêm; lỏng
        hơn thì có ca gác chặn mà công cụ vẫn hồn nhiên ghi đè."""
        from vnstock_basis_guard import TOL
        assert (R.UNIFORM_SPREAD_MAX - 1.0) < TOL


# --------------------------------------------------------------------------
class TestSparseGate:
    """Cửa THƯA — mã gần như không giao dịch.

    Vết GH3 (07/09): 13 bar chồng nhau trong 365 ngày, **spread 1.0011** —
    chặt ngang mọi mã đã chữa sạch trong ngày (1.0003-1.0014). Sàn 20 bar là
    cách ĐẾM để trả lời câu thật sự cần hỏi: *chứng cứ có phủ đủ rộng không?*
    Với mã thưa, đếm bar hỏi sai câu.

    Thứ đo trực tiếp hơn là TẦM PHỦ: bar rải trên nửa năm thì một lần đổi cơ
    sở trong nửa năm ấy chắc chắn nằm giữa hai bar nào đó ⇒ tỉ lệ phải gãy ⇒
    spread phải nở. Spread không nở nghĩa là không có lần đổi nào.
    """

    def _sparse(self, n, span_days, ratios=None, end_offset=2):
        """`n` bar rải ĐỀU trên `span_days` ngày."""
        last = date.today() - timedelta(days=end_offset)
        step = max(1, span_days // (n - 1))
        days = [last - timedelta(days=step * (n - 1 - i)) for i in range(n)]
        close = [100.0 + i for i in range(n)]
        src = pd.DataFrame({"time": pd.to_datetime(days), "close": close})
        rat = ratios or [RATIO] * n
        wh = pd.DataFrame({"time": pd.to_datetime(days),
                           "close": [c * r for c, r in zip(close, rat)]})
        return wh, src

    def test_few_bars_spread_over_half_a_year_are_enough(self):
        rep = R.uniform_offset_report(*self._sparse(13, 330))
        assert rep["uniform"] is True
        assert rep["span_days"] >= R.UNIFORM_SPARSE_MIN_SPAN_DAYS

    def test_the_message_says_it_went_through_the_sparse_gate(self):
        """Qua một cửa KHÁC thì phải nói ra — người đọc log cần biết bằng
        chứng ở đây mỏng hơn thường lệ."""
        rep = R.uniform_offset_report(*self._sparse(13, 330))
        assert "CỬA THƯA" in rep["why"]

    def test_the_same_bars_crammed_together_are_NOT_enough(self):
        """Cùng 13 bar, cùng tỉ lệ, chỉ khác tầm phủ — và đó mới là thứ đang
        được hỏi."""
        rep = R.uniform_offset_report(*self._sparse(13, 20))
        assert rep["uniform"] is False and "quá mỏng" in rep["why"]

    def test_too_few_bars_is_still_refused_however_wide_the_span(self):
        """Hai bar cách nhau một năm cũng "phủ rộng" — mà hai điểm thì tỉ lệ
        nào cũng "đều"."""
        rep = R.uniform_offset_report(*self._sparse(4, 330))
        assert rep["uniform"] is False

    def test_the_sparse_gate_does_NOT_relax_the_spread_ceiling(self):
        """Cửa thưa chỉ nới điều kiện CHỨNG CỨ, không nới điều kiện KẾT LUẬN.
        Lệch lởm chởm vẫn là lởm chởm dù bar thưa hay dày."""
        n = 13
        rat = [RATIO * (1 + 0.08 * i / (n - 1)) for i in range(n)]
        rep = R.uniform_offset_report(*self._sparse(n, 330, ratios=rat))
        assert rep["uniform"] is False and "LỞM CHỞM" in rep["why"]

    def test_the_sparse_floor_sits_below_the_dense_one(self):
        assert R.UNIFORM_SPARSE_MIN_BARS < R.UNIFORM_MIN_BARS

    def test_a_dense_series_never_needs_the_sparse_gate(self):
        rep = R.uniform_offset_report(*self._sparse(60, 90))
        assert rep["uniform"] is True and "CỬA THƯA" not in rep["why"]


class TestLastWarehouseBar:
    def test_it_reads_the_newest_bar(self, tmp_path):
        src = _src_frame()
        _write_wh(tmp_path, "SDK", src, RATIO)
        assert R._last_wh_bar("SDK", tmp_path) == src["time"].max().date()

    def test_a_missing_ticker_is_none_not_a_guess(self, tmp_path):
        assert R._last_wh_bar("KHONGCO", tmp_path) is None


# --------------------------------------------------------------------------
class TestResidualLevelSelfCheck:
    """Bước tự kiểm thứ ba. Không có nó thì chế độ mới TỰ CHỨNG NHẬN bằng hai
    bộ dò mù đúng lớp lỗi của chính nó."""

    def _setup(self, tmp_path, ratio):
        src = _src_frame()
        _write_wh(tmp_path, "SDK", src, ratio)
        return tmp_path / "prices", src

    def test_it_sees_a_residual_uniform_offset(self, tmp_path):
        prices, src = self._setup(tmp_path, RATIO)
        assert R._residual_level(prices, "SDK", src) is not None

    def test_it_is_silent_when_the_fix_landed(self, tmp_path):
        prices, src = self._setup(tmp_path, 1.0)
        assert R._residual_level(prices, "SDK", src) is None

    def test_the_two_older_self_checks_are_blind_to_exactly_this(self, tmp_path):
        """Bằng chứng bằng chính hàm thật, không phải suy diễn: cùng bộ dữ
        liệu, hai bước cũ im, bước mới kêu."""
        from check_unit_continuity import find_jumps, load_bars
        prices, src = self._setup(tmp_path, RATIO)
        assert not [j for j in find_jumps(load_bars(prices, "SDK")) if j["suspect"]]
        assert R._residual_basis_step(prices, "SDK", src) is None
        assert R._residual_level(prices, "SDK", src) is not None

    def test_it_never_fetches_the_network_again(self):
        """Tự kiểm mà gọi mạng lần nữa thì đỏ/xanh không còn nói về việc mình
        vừa làm — nguồn có thể đã đổi giữa chừng."""
        import inspect
        src = inspect.getsource(R._residual_level)
        assert "fetch_source" not in src and "_fetch_prices" not in src

    def test_its_tolerance_matches_the_guard(self):
        import inspect
        from vnstock_basis_guard import TOL
        sig = inspect.signature(R._residual_level)
        assert sig.parameters["tol"].default == pytest.approx(TOL)

    def test_it_runs_before_the_success_line(self):
        import inspect
        src = inspect.getsource(R._rebase_one)
        assert src.index("_residual_level") < src.index("chuỗi đã liền")


# --------------------------------------------------------------------------
class TestWholeSeriesEndToEnd:
    def test_without_the_flag_it_refuses_and_points_at_the_flag(
            self, offset_wh, capsys):
        """Mặc định vẫn là từ chối thật thà — chế độ mạnh tay phải do người
        gọi tên."""
        root, _ = offset_wh
        assert R._rebase_one("SDK", root, apply=True) == 1
        assert "--whole-series" in capsys.readouterr().out

    def test_dry_run_changes_nothing_on_disk(self, offset_wh):
        root, src = offset_wh
        pq = next((root / "prices" / "ticker=SDK").glob("year=*/*.parquet"))
        before = pq.read_bytes()
        assert R._rebase_one("SDK", root, apply=False, whole_series=True) == 0
        assert pq.read_bytes() == before

    def test_apply_puts_the_whole_history_back_on_the_source_basis(
            self, offset_wh, capsys):
        root, src = offset_wh
        rc = R._rebase_one("SDK", root, apply=True, whole_series=True)
        out = capsys.readouterr().out
        assert rc == 0, out
        got = pd.read_parquet(
            next((root / "prices" / "ticker=SDK").glob("year=*/*.parquet")))
        got = got.sort_values("time").reset_index(drop=True)
        assert got["close"].tolist() == pytest.approx(src["close"].tolist())
        assert R._residual_level(root / "prices", "SDK", src) is None

    def test_it_never_prints_the_clean_line_after_deciding_to_fix(
            self, offset_wh, capsys):
        """Vết bắt được lúc viết lưới này: nhánh --whole-series ĐẶT mốc ảo rồi
        đi tiếp, nhưng dòng "✅ không còn vách nghi vấn" nằm CÙNG khối `if brk
        is None` nên vẫn chạy — in "LỆCH ĐỒNG ĐỀU" xong in luôn "✅ sạch" rồi
        exit 0 mà không ghi gì. Đúng cái bệnh báo-thành-công-sai mà chế độ này
        sinh ra để chữa."""
        R._rebase_one("SDK", offset_wh[0], apply=True, whole_series=True)
        out = capsys.readouterr().out
        assert "LỆCH ĐỒNG ĐỀU" in out
        assert "không còn vách nghi vấn" not in out

    def test_it_backs_up_before_writing(self, offset_wh):
        """Ghi đè TRỌN lịch sử — không có sao lưu thì sai một lần là mất cả
        chiều sâu backtest."""
        root, _ = offset_wh
        R._rebase_one("SDK", root, apply=True, whole_series=True)
        assert list((root / "_meta" / "backup_rebase").glob("SDK_*"))

    def test_it_does_not_inflate_volume(self, offset_wh):
        """Back-adjust GIÁ không tạo thêm cổ phiếu nào. Không có vách thì cũng
        không có bậc nhảy khối lượng để làm bằng chứng — mặc định phải là giữ
        nguyên, không phải nhân."""
        root, src = offset_wh
        R._rebase_one("SDK", root, apply=True, whole_series=True)
        got = pd.read_parquet(
            next((root / "prices" / "ticker=SDK").glob("year=*/*.parquet")))
        assert got["volume"].tolist() == pytest.approx(src["volume"].tolist())

    def test_the_volume_reason_does_not_talk_about_a_nonexistent_step(
            self, offset_wh, capsys):
        """Mốc là ẢO nên phía 'sau vách' rỗng ⇒ `_volume_step` = nan. In "bậc
        nhảy = nan×" rồi lấy chính nan đó làm lý do là đúng số mà sai chuyện —
        người đọc đi tìm một cái vách không tồn tại."""
        R._rebase_one("SDK", offset_wh[0], apply=True, whole_series=True)
        out = capsys.readouterr().out
        assert "nan" not in out
        assert "không tạo thêm cổ phiếu" in out

    def test_volume_adjust_can_still_be_forced(self, offset_wh):
        """Giữ nguyên là MẶC ĐỊNH an toàn, không phải cái chốt chết: chia
        tách thật thì người dùng vẫn ép được."""
        root, src = offset_wh
        R._rebase_one("SDK", root, apply=True, volume_mode="adjust",
                      whole_series=True)
        got = pd.read_parquet(
            next((root / "prices" / "ticker=SDK").glob("year=*/*.parquet")))
        assert got["volume"].tolist() == pytest.approx(
            [v * RATIO for v in src["volume"]])

    def test_a_ragged_offset_is_refused_even_with_the_flag(
            self, tmp_path, monkeypatch, capsys):
        src = _src_frame()
        n = len(src)
        ratios = [RATIO * (1 + 0.08 * i / (n - 1)) for i in range(n)]
        pq = _write_wh(tmp_path, "SDK", src, ratios)
        before = pq.read_bytes()
        import probe_price_basis as ppb
        import vnstock_updater as upd
        monkeypatch.setattr(upd, "_fetch_prices", lambda tk, d0, d1: src.copy())
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: _as_source(src))
        rc = R._rebase_one("SDK", tmp_path, apply=True, whole_series=True)
        out = capsys.readouterr().out
        assert rc == 1 and "TỪ CHỐI --whole-series" in out
        assert pq.read_bytes() == before, "từ chối mà vẫn ghi"

    def test_a_clean_ticker_stays_clean_with_the_flag_on(
            self, tmp_path, monkeypatch, capsys):
        """Bật cờ KHÔNG được biến mã sạch thành một lượt ghi đè."""
        src = _src_frame()
        pq = _write_wh(tmp_path, "SDK", src, 1.0)
        before = pq.read_bytes()
        import probe_price_basis as ppb
        import vnstock_updater as upd
        monkeypatch.setattr(upd, "_fetch_prices", lambda tk, d0, d1: src.copy())
        monkeypatch.setattr(ppb, "fetch_source",
                            lambda tk, d0, d1: _as_source(src))
        rc = R._rebase_one("SDK", tmp_path, apply=True, whole_series=True)
        assert rc == 0 and "✅" in capsys.readouterr().out
        assert pq.read_bytes() == before

    def test_it_never_calls_the_probe_gate(self, offset_wh, monkeypatch):
        """`_probe` so trung vị hai phía mốc; ở đây trước = sau nên nó luôn
        phán 'aligned' và cửa không bao giờ mở. Hỏi nó là hỏi sai câu."""
        root, _ = offset_wh
        monkeypatch.setattr(R, "_probe",
                            lambda *a, **k: pytest.fail("không được hỏi _probe"))
        assert R._rebase_one("SDK", root, apply=True, whole_series=True) == 0

    def test_it_refuses_when_the_last_bar_cannot_be_read(
            self, offset_wh, monkeypatch, capsys):
        """Không đọc được mốc thì DỪNG — đoán đại một mốc là ghi đè nhầm nửa
        lịch sử."""
        root, _ = offset_wh
        monkeypatch.setattr(R, "_last_wh_bar", lambda *a, **k: None)
        assert R._rebase_one("SDK", root, apply=True, whole_series=True) == 1
        assert "bar cuối" in capsys.readouterr().out

    def test_it_clears_the_quarantine_ledger_after_a_real_fix(
            self, offset_wh, monkeypatch):
        """Chữa xong mà để mã lại trong sổ thì doctor kêu mãi, và người dùng
        học cách bỏ qua badge."""
        seen = []
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift",
                            lambda wh, tk: seen.append(tk))
        R._rebase_one("SDK", offset_wh[0], apply=True, whole_series=True)
        assert seen == ["SDK"]


# --------------------------------------------------------------------------
class TestUnitScaleRail:
    """Lệch ĐƠN VỊ (đồng ⇄ nghìn đồng) cũng đều tăm tắp ⇒ nó qua được cửa
    "spread" một cách hoàn hảo. Không có trần hệ số thì `--whole-series` sẽ
    ghi đè trọn lịch sử vì một lý do hoàn toàn khác — và đó là việc của
    `check_unit_continuity`, không phải của bộ chữa cơ sở."""

    def _pair(self, ratio):
        src = _src_frame()
        wh = src.copy()
        wh["close"] = wh["close"] * ratio
        return wh[["time", "close"]], src[["time", "close"]]

    def test_a_thousand_fold_ratio_is_refused_as_a_unit_error(self):
        rep = R.uniform_offset_report(*self._pair(1000.0))
        assert rep["uniform"] is False and "SAI ĐƠN VỊ" in rep["why"]

    def test_the_inverse_unit_error_is_refused_too(self):
        rep = R.uniform_offset_report(*self._pair(0.001))
        assert rep["uniform"] is False and "SAI ĐƠN VỊ" in rep["why"]

    def test_a_real_split_ratio_still_passes(self):
        """Trần phải nằm TRÊN mọi sự kiện quyền thật — chia tách 1:4 là 5×."""
        rep = R.uniform_offset_report(*self._pair(5.0))
        assert rep["uniform"] is True

    def test_the_ceiling_leaves_room_above_the_largest_real_event(self):
        assert R.UNIFORM_MAX_FACTOR > 5.0


class TestDriftLedgerAsBatchSource:
    """`--from-sweep` KHÔNG dùng được cho lớp mã này: vết quét cũng dựng trên
    `find_basis_step`, tức cùng bộ dò đạo hàm đang mù. Sổ cách ly do cửa gác
    ghi, mà gác đo MỨC — nó là nguồn duy nhất liệt kê đúng lớp này."""

    def test_it_reads_the_ledger(self, tmp_path, monkeypatch):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "load_pending",
                            lambda wh: {"SDK": {}, "AAM": {}})
        assert R._drift_ledger_targets(tmp_path) == ["AAM", "SDK"]

    def test_an_unreadable_ledger_yields_nothing_not_a_guess(
            self, tmp_path, monkeypatch, capsys):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "load_pending",
                            lambda wh: (_ for _ in ()).throw(IOError("hỏng")))
        assert R._drift_ledger_targets(tmp_path) == []
        assert "không đọc được sổ cách ly" in capsys.readouterr().out

    def test_the_flag_drives_every_ticker_in_the_ledger(
            self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(R, "_drift_ledger_targets",
                            lambda wh: ["AAM", "SDK"])
        monkeypatch.setattr(R, "_rebase_one",
                            lambda tk, *a, **k: seen.append(tk) or 0)
        R.main(["--warehouse", str(tmp_path), "--from-drift-ledger",
                "--whole-series"])
        assert seen == ["AAM", "SDK"]

    def test_an_empty_ledger_is_success_not_an_error(
            self, tmp_path, monkeypatch, capsys):
        """Sổ rỗng nghĩa là KHÔNG CÒN GÌ ĐỂ CHỮA — thoát 2 ở đây thì lệnh này
        không bao giờ dùng được trong một chuỗi tự động."""
        monkeypatch.setattr(R, "_drift_ledger_targets", lambda wh: [])
        assert R.main(["--warehouse", str(tmp_path), "--from-drift-ledger"]) == 0
        assert "RỖNG" in capsys.readouterr().out

    def test_it_still_needs_apply_to_write(self, tmp_path, monkeypatch):
        got = {}
        monkeypatch.setattr(R, "_drift_ledger_targets", lambda wh: ["SDK"])
        monkeypatch.setattr(R, "_rebase_one",
                            lambda tk, wh, apply, *a, **k: got.update(
                                {"apply": apply}) or 0)
        R.main(["--warehouse", str(tmp_path), "--from-drift-ledger"])
        assert got["apply"] is False


# --------------------------------------------------------------------------
class TestCli:
    def test_the_flag_reaches_rebase_one(self, tmp_path, monkeypatch):
        got = {}
        monkeypatch.setattr(R, "_rebase_one",
                            lambda *a, **k: got.update(k) or 0)
        R.main(["--ticker", "SDK", "--warehouse", str(tmp_path), "--whole-series"])
        assert got.get("whole_series") is True

    def test_it_is_off_by_default(self, tmp_path, monkeypatch):
        got = {}
        monkeypatch.setattr(R, "_rebase_one",
                            lambda *a, **k: got.update(k) or 0)
        R.main(["--ticker", "SDK", "--warehouse", str(tmp_path)])
        assert got.get("whole_series") is False

    def test_it_refuses_to_be_combined_with_break_date(self, tmp_path):
        """Nhận cả hai rồi âm thầm bỏ một cái là cách chắc chắn để người dùng
        tưởng mình đã chạy chế độ kia."""
        with pytest.raises(SystemExit):
            R.main(["--ticker", "SDK", "--warehouse", str(tmp_path),
                    "--whole-series", "--break-date", "2026-01-01"])

    def test_writing_still_needs_apply(self, tmp_path, monkeypatch):
        got = {}
        monkeypatch.setattr(R, "_rebase_one",
                            lambda tk, wh, apply, *a, **k: got.update(
                                {"apply": apply}) or 0)
        R.main(["--ticker", "SDK", "--warehouse", str(tmp_path), "--whole-series"])
        assert got["apply"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

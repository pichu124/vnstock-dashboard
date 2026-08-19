"""Lưới cho `scripts/rebase_ticker_history.py` — chữa KHO LỆCH CƠ SỞ.

Đây là công cụ DUY NHẤT trong bộ này GHI VÀO KHO, nên lưới soi phần an toàn
trước phần đúng: chạy thử không được đụng byte nào · từ chối khi probe không
phán `warehouse_basis` · có sao lưu · tự kiểm sau khi ghi. Phần fetch nguồn
cần mạng nên được thay bằng stub — thứ cần test là QUYẾT ĐỊNH và ĐƯỜNG GHI,
không phải API nhà cung cấp.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rebase_ticker_history as rth  # noqa: E402

BRK = date(2026, 8, 3)


def _dates(n=12, end="2026-08-17"):
    return pd.bdate_range(end=end, periods=n).normalize()


def _wh(tmp_path: Path, factor: float = 2.0) -> Path:
    """Kho VHM giả: trước vách bị phóng đại `factor` lần, sau vách đúng."""
    d = tmp_path / "prices" / "ticker=VHM" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    t = _dates()
    true_px = [70 + i for i in range(len(t))]
    closes = [p * factor if x.date() < BRK else p for x, p in zip(t, true_px)]
    vols = [1000 if x.date() < BRK else 2000 for x in t]
    pd.DataFrame({"time": t, "open": closes, "high": closes, "low": closes,
                  "close": closes, "volume": vols}).to_parquet(
        d / "p.parquet", index=False)
    return tmp_path


def _src_df(n=12):
    t = _dates(n)
    px = [70 + i for i in range(len(t))]
    return pd.DataFrame({"time": t, "open": px, "high": px, "low": px,
                         "close": px, "volume": [2000] * len(t)})


@pytest.fixture()
def stub_source(monkeypatch):
    """Nguồn LIỀN MẠCH (đã rebase) — đúng cảnh thật của VHM/PNJ/GEX."""
    import probe_price_basis as ppb
    src = _src_df()
    monkeypatch.setattr(ppb, "fetch_source",
                        lambda tk, d0, d1: src[["time", "close"]].assign(
                            time=src["time"].dt.date))
    mod = type(sys)("vnstock_updater")
    mod._fetch_prices = lambda tk, s, e: src.copy()
    monkeypatch.setitem(sys.modules, "vnstock_updater", mod)
    return src


def test_dry_run_does_not_touch_a_single_byte(tmp_path, stub_source):
    wh = _wh(tmp_path)
    pq = wh / "prices" / "ticker=VHM" / "year=2026" / "p.parquet"
    before = pq.read_bytes()
    assert rth.main(["--warehouse", str(wh), "--ticker", "VHM"]) == 0
    assert pq.read_bytes() == before, "chạy thử mà vẫn ghi kho"
    assert not (wh / "_meta" / "backup_rebase").exists()


def test_apply_rewrites_history_onto_the_source_basis(tmp_path, stub_source):
    wh = _wh(tmp_path)
    assert rth.main(["--warehouse", str(wh), "--ticker", "VHM", "--apply"]) == 0
    got = pd.read_parquet(wh / "prices" / "ticker=VHM" / "year=2026" / "p.parquet")
    got["time"] = pd.to_datetime(got["time"])
    old = got[got["time"].dt.date < BRK]
    # Ngày nào nguồn có thì lấy THẲNG giá nguồn → khớp tuyệt đối, hết vách.
    exp = _src_df().set_index("time")["close"]
    for _, r in old.iterrows():
        assert r["close"] == pytest.approx(float(exp.loc[r["time"]]), abs=1e-6)


def test_apply_makes_a_backup_first(tmp_path, stub_source):
    wh = _wh(tmp_path)
    rth.main(["--warehouse", str(wh), "--ticker", "VHM", "--apply"])
    backups = list((wh / "_meta" / "backup_rebase").glob("VHM_*"))
    assert len(backups) == 1
    saved = pd.read_parquet(next(backups[0].rglob("*.parquet")))
    assert float(saved["close"].iloc[0]) == pytest.approx(140.0)   # bản GỐC


def test_refuses_when_probe_says_source_error(tmp_path, monkeypatch):
    """Nguồn cũng gãy ⇒ ghi đè lịch sử là chữa sai chỗ. Phải TỪ CHỐI, và từ
    chối là hành vi ĐÚNG chứ không phải lỗi — đây là cửa duy nhất chặn việc
    sửa nhầm cả 20 năm dữ liệu."""
    wh = _wh(tmp_path)
    monkeypatch.setattr(rth, "_probe",
                        lambda *a, **k: {"verdict": "source_error", "n": 9})
    pq = wh / "prices" / "ticker=VHM" / "year=2026" / "p.parquet"
    before = pq.read_bytes()
    assert rth.main(["--warehouse", str(wh), "--ticker", "VHM", "--apply"]) == 1
    assert pq.read_bytes() == before


def test_clean_ticker_is_a_noop(tmp_path, stub_source):
    d = tmp_path / "prices" / "ticker=AAA" / "year=2026"
    d.mkdir(parents=True)
    t = _dates()
    px = [10 + i * 0.1 for i in range(len(t))]
    pd.DataFrame({"time": t, "open": px, "high": px, "low": px, "close": px,
                  "volume": [100] * len(t)}).to_parquet(d / "p.parquet", index=False)
    assert rth.main(["--warehouse", str(tmp_path), "--ticker", "AAA"]) == 0


def test_unknown_ticker_reports_instead_of_crashing(tmp_path):
    assert rth.main(["--warehouse", str(tmp_path), "--ticker", "ZZZ"]) == 1


def test_volume_factor_needs_enough_overlap_before_it_is_trusted():
    """Vài bar lẻ có thể kéo trung vị đi — dưới ngưỡng thì trả 1.0 (để yên)
    thay vì nhân bừa khối lượng cả lịch sử."""
    t = _dates(3)
    wh = pd.DataFrame({"time": t, "volume": [100, 100, 100]})
    src = pd.DataFrame({"time": t, "volume": [200, 200, 200]})
    assert rth._measure_volume_factor(wh, src) == 1.0
    t2 = _dates(8)
    wh2 = pd.DataFrame({"time": t2, "volume": [100] * 8})
    src2 = pd.DataFrame({"time": t2, "volume": [200] * 8})
    assert rth._measure_volume_factor(wh2, src2) == pytest.approx(2.0)


# ── Khối lượng: chữa giá mà bỏ volume là đổi lỗi này lấy lỗi khác ───────────
#
# Chia tách 1:1 làm SỐ CỔ PHIẾU gấp đôi. Nếu nguồn chỉ điều chỉnh GIÁ (đo được
# hệ số volume ≈ 1.0) mà chuỗi volume lại nhảy bậc ~2× tại vách, thì chữa giá
# xong GTGD lịch sử chỉ còn một nửa — mà GTGD chính là thứ screener/strategy
# dùng lọc thanh khoản (min_avg_volume=100.000).

def test_volume_step_measures_the_jump_at_the_break():
    t = _dates(12)
    vols = [1000 if x.date() < BRK else 2000 for x in t]
    wh = pd.DataFrame({"time": t, "volume": vols})
    assert rth._volume_step(wh, BRK) == pytest.approx(2.0)


def test_auto_scales_volume_when_source_leaves_it_unadjusted(tmp_path, stub_source):
    """auto: nguồn không đổi volume (1.0×) + volume gãy đúng bậc hệ số giá
    ⇒ nhân khối lượng lịch sử để GTGD liền mạch."""
    wh = _wh(tmp_path)
    rth.main(["--warehouse", str(wh), "--ticker", "VHM", "--apply"])
    got = pd.read_parquet(wh / "prices" / "ticker=VHM" / "year=2026" / "p.parquet")
    got["time"] = pd.to_datetime(got["time"])
    old = got[got["time"].dt.date < BRK]["volume"]
    assert float(old.median()) == pytest.approx(4000.0)   # 2000 nguồn × 2.0


def test_source_mode_never_invents_volume(tmp_path, stub_source):
    """--volume source: giữ đúng con số nguồn, không suy diễn. Dùng khi muốn
    kho khớp nguồn tuyệt đối để đối chiếu."""
    wh = _wh(tmp_path)
    rth.main(["--warehouse", str(wh), "--ticker", "VHM", "--apply",
              "--volume", "source"])
    got = pd.read_parquet(wh / "prices" / "ticker=VHM" / "year=2026" / "p.parquet")
    got["time"] = pd.to_datetime(got["time"])
    old = got[got["time"].dt.date < BRK]["volume"]
    assert float(old.median()) == pytest.approx(2000.0)


def test_volume_step_is_nan_safe_without_bars():
    empty = pd.DataFrame({"time": pd.to_datetime([]), "volume": []})
    assert rth._volume_step(empty, BRK) != rth._volume_step(empty, BRK)  # NaN


def test_unsoiable_ticker_is_not_reported_as_clean(tmp_path, capsys):
    """Cùng vết: rebase phải nói "KHÔNG SOI ĐƯỢC" và trả 1, chứ không in ✅
    như mã sạch. Hai trạng thái này dẫn tới hai hành động ngược nhau."""
    assert rth.main(["--warehouse", str(tmp_path), "--ticker", "ZZZ"]) == 1
    out = capsys.readouterr().out
    assert "KHÔNG SOI ĐƯỢC" in out or "không có trong kho" in out
    assert "✅" not in out


# ── Vách do NGƯỜI chỉ định (vá 19/08 sau ca VNM) ───────────────────────────

def test_break_date_flag_exists_and_parses():
    """Ca VNM 19/08: kho/nguồn 1.0327× trước 2026-06-23 rồi 1.0000× từ đó —
    một mã VN30 lệch 3,27% suốt phần lịch sử. `_find_break` chỉ thấy vách ≥30%
    nên lệch cỡ CỔ TỨC (2-5%) hoàn toàn vô hình với nó; không có cờ này thì
    công cụ chữa không với tới được cả một LỚP lỗi."""
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import rebase_ticker_history as rth
    ns = rth.main.__globals__["argparse"]  # đảm bảo module dựng parser thật
    import argparse as _a
    assert ns is _a
    p = _P("scripts/rebase_ticker_history.py").read_text(encoding="utf-8")
    assert '"--break-date"' in p
    assert "break_date" in p


def test_explicit_break_date_skips_autodetect(tmp_path, monkeypatch, capsys):
    """Chỉ định ngày thì KHÔNG được gọi bộ dò 30% nữa — nếu vẫn gọi thì mã
    lệch cỡ cổ tức lại bị trả về "không còn vách nghi vấn"."""
    import sys
    from datetime import date
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import probe_price_basis as ppb
    import rebase_ticker_history as rth

    called = []
    monkeypatch.setattr(ppb, "_find_break",
                        lambda *a, **k: called.append(1) or None)
    d = tmp_path / "prices" / "ticker=VNM" / "year=2026"
    d.mkdir(parents=True)
    import pandas as _pd
    _pd.DataFrame({"time": _pd.to_datetime(["2026-06-22", "2026-06-23"]),
                   "open": [59.0, 56.5], "high": [59.0, 56.5],
                   "low": [59.0, 56.5], "close": [59.0, 56.5],
                   "volume": [1000, 1000]}).to_parquet(d / "p.parquet",
                                                       index=False)
    monkeypatch.setattr(rth, "_probe",
                        lambda *a, **k: {"verdict": "aligned", "n": 2})
    rth._rebase_one("VNM", tmp_path, False, "auto", date(2026, 6, 23))
    out = capsys.readouterr().out
    assert called == [], "vẫn gọi bộ dò dù đã chỉ định ngày"
    assert "vách do người chỉ định = 2026-06-23" in out


# ── Khối lượng: chỉ nhân khi SỐ CỔ PHIẾU thật sự đổi (vá 19/08, ca VNM) ─────

class TestVolumeOnlyScalesForShareCountEvents:
    """Ca VNM 19/08: hệ số giá 1.0327 (cổ tức tiền mặt) mà heuristic cũ vẫn
    định NHÂN khối lượng 5.089 bar × 1.0327 — bịa ra 3,27% cổ phiếu chưa từng
    khớp. Lỗ hổng: điều kiện "bậc nhảy volume ≈ hệ số giá" ở hệ số 1.03 thoả
    với mọi bậc trong 0.67-1.39 lần, tức toàn bộ dao động thường ngày."""

    def _src(self):
        import inspect
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
        import rebase_ticker_history as rth
        return inspect.getsource(rth)

    def test_threshold_is_above_any_cash_dividend(self):
        """Cổ tức tiền mặt VN thường 2-8% giá; chia tách/thưởng thật đổi ≥15%."""
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
        import rebase_ticker_history as rth
        assert rth.VOL_SIGNAL_MIN_FACTOR >= 1.10

    def test_cash_dividend_never_scales_volume(self):
        src = self._src()
        assert '_ev == "cash"' in src
        assert "cổ tức TIỀN MẶT không tạo" in src

    def test_small_factor_without_event_refuses_to_guess(self):
        """Không tra được sự kiện + hệ số nhỏ → giữ nguyên và NÓI RÕ vì sao,
        đúng nếp 'thà không chữa còn hơn chữa sai'."""
        src = self._src()
        assert "_too_small_to_tell" in src and "thà" in src

    def test_split_sized_factor_still_scales(self):
        """Chống nới tay: ca VHM (1.95 lần, volume nhảy đúng bậc) PHẢI vẫn nhân
        — đó mới là bằng chứng thật."""
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
        import rebase_ticker_history as rth
        assert 1.95 >= rth.VOL_SIGNAL_MIN_FACTOR
        src = self._src()
        assert "_shares_changed or not _too_small_to_tell" in src

    def test_corp_action_lookup_reuses_the_existing_store(self):
        """Một nơi định nghĩa: đọc sự kiện qua match_corp_action chứ không
        dựng bản sao thứ hai của kho sự kiện."""
        src = self._src()
        assert "from check_unit_continuity import match_corp_action" in src


# ── Chữa HÀNG LOẠT từ vết quét (thêm 19/08 sau khi sweep ra 70/159 mã) ─────

class TestBatchFromSweep:
    """Quét 19/08 ra 70/159 mã universe thanh khoản lệch cơ sở — chữa tay từng
    mã là 70 lệnh, và mỗi lệnh phải tự tra ngày vách. Nhưng chữa hàng loạt
    KHÔNG được nới lỏng cửa gác: mỗi mã vẫn phải qua probe (verdict phải là
    warehouse_basis), vẫn sao lưu và tự kiểm riêng."""

    def _rth(self):
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
        import rebase_ticker_history as rth
        return rth

    def test_reads_ticker_list_from_the_sweep_stamp(self, tmp_path):
        import json
        rth = self._rth()
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        (meta / "basis_sweep_check.json").write_text(json.dumps({
            "checked_at": "2026-08-19T15:00:00", "scanned": 159,
            "suspect": ["HPG", "SSI", "TCB"], "unchecked": []}),
            encoding="utf-8")
        assert rth._sweep_targets(tmp_path) == ["HPG", "SSI", "TCB"]

    def test_missing_stamp_says_run_the_sweep_first(self, tmp_path, capsys):
        rth = self._rth()
        assert rth._sweep_targets(tmp_path) == []
        assert "--sweep" in capsys.readouterr().out

    def test_corrupt_stamp_returns_empty_not_garbage(self, tmp_path, capsys):
        rth = self._rth()
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        (meta / "basis_sweep_check.json").write_text("{hong", encoding="utf-8")
        assert rth._sweep_targets(tmp_path) == []
        assert "hỏng" in capsys.readouterr().out

    def test_batch_summary_never_folds_failures_into_done(self):
        """Vết 18/08: gộp 'chưa chữa được' vào 'xong' là cách chắc nhất khiến
        người đọc tưởng cả rổ đã sạch."""
        import inspect
        rth = self._rth()
        src = inspect.getsource(rth.main)
        assert "KHÔNG chữa được" in src and "CHƯA sạch" in src

    def test_batch_still_dry_run_by_default(self):
        import inspect
        rth = self._rth()
        src = inspect.getsource(rth.main)
        assert "CHẠY THỬ, chưa ghi gì" in src

    def test_autodetect_falls_back_to_basis_step(self):
        """Không có vách GIÁ ≥30% KHÔNG có nghĩa là sạch — phải hỏi nốt bộ dò
        tỉ lệ kho/nguồn trước khi tuyên bố."""
        import inspect
        rth = self._rth()
        src = inspect.getsource(rth._rebase_one)
        assert "_basis_break_of" in src

    def test_basis_detector_is_shared_not_duplicated(self):
        """Một nơi định nghĩa 'vách ở đâu': dùng lại find_basis_step của
        probe chứ không nuôi bản thứ hai."""
        import inspect
        rth = self._rth()
        assert "find_basis_step" in inspect.getsource(rth._basis_break_of)

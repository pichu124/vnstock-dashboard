"""Lưới cho `vnstock_basis_guard` (V1) — cửa gác lệch cơ sở ở ĐƯỜNG GHI CHÍNH.

Vì sao có cửa gác này: 19/08 quét ra 70/159 mã thanh khoản (44%) lệch cơ sở,
gần trọn VN30. Cơ chế đã dựng lại được: nguồn back-adjust toàn chuỗi sau sự
kiện quyền, `update_ticker` chỉ fetch từ `last_date` rồi merge keep="last" →
sinh đúng một bậc giả tại `last_date`, im lặng. Bộ quét là phát hiện SAU; đây
là chỗ duy nhất chặn được TRƯỚC KHI GHI.

Lưới soi 3 thứ theo đúng thứ tự rủi ro: (1) hàm thuần phán đúng chưa,
(2) phát hiện rồi thì KHÔNG được ghi một byte nào, (3) trường hợp bình thường
phải giữ nguyên hành vi cũ — nới cửa sổ fetch mà làm dày kho là đổi một lỗi
lấy một lỗi khác.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import vnstock_basis_guard as bg

_LAST = date(2026, 8, 17)


def _series(ratio: float, n: int = 12, last: date = _LAST):
    """(kho, nguồn) trên n phiên tới `last`; kho = nguồn × ratio."""
    days = list(pd.bdate_range(end=last, periods=n).date)
    src = {d: 100.0 + i for i, d in enumerate(days)}
    wh = {d: v * ratio for d, v in src.items()}
    return wh, src, days


# ── Hàm thuần ───────────────────────────────────────────────────────────────

def test_same_basis_is_aligned():
    wh, src, _ = _series(1.0)
    out = bg.check_basis(wh, src, _LAST)
    assert out["verdict"] == "aligned"


def test_source_rebased_under_the_warehouse_is_caught():
    wh, src, _ = _series(1.17)          # nguồn vừa chia lại, kho còn cơ sở cũ
    out = bg.check_basis(wh, src, _LAST)
    assert out["verdict"] == "basis_changed"
    assert out["ratio"] == pytest.approx(1.17)
    assert out["pct"] == pytest.approx(17.0, abs=0.01)


def test_dividend_sized_drift_is_caught_not_just_splits():
    """Lớp lỗi VNM: 1.0327× — dưới xa ngưỡng 30% của bộ dò vách giá."""
    wh, src, _ = _series(1.0327)
    assert bg.check_basis(wh, src, _LAST)["verdict"] == "basis_changed"


def test_rounding_noise_is_not_a_basis_change():
    """±0,8% là nhiễu làm tròn/bước giá — báo động ở đây là alarm fatigue."""
    wh, src, days = _series(1.0)
    for i, d in enumerate(days):
        wh[d] = src[d] * (1.008 if i % 2 else 0.992)
    assert bg.check_basis(wh, src, _LAST)["verdict"] == "aligned"


def test_partial_last_bar_can_never_trigger_the_guard():
    """Bar `last_date` có thể DỞ DANG (updater từng chạy trong phiên) — đó là
    nguồn báo động giả đáng kể duy nhất ở ngưỡng 1,2%, nên bỏ hẳn khỏi phép so."""
    wh, src, _ = _series(1.0)
    wh[_LAST] = src[_LAST] * 1.40                   # bar dở lệch 40%
    assert bg.check_basis(wh, src, _LAST)["verdict"] == "aligned"


def test_too_few_overlapping_bars_says_so_instead_of_guessing():
    wh, src, days = _series(1.17, n=3)
    out = bg.check_basis(wh, src, _LAST)
    assert out["verdict"] == "no_overlap"           # mã mới niêm yết / nghỉ dài
    assert out["n"] < bg.MIN_BARS


def test_zero_and_missing_closes_do_not_poison_the_median():
    wh, src, days = _series(1.0)
    wh[days[0]] = 0.0                               # bar hỏng
    src.pop(days[1])                                # nguồn thiếu bar
    assert bg.check_basis(wh, src, _LAST)["verdict"] == "aligned"


def test_threshold_matches_the_sweep_tool():
    """Hai ngưỡng phải khớp: guard cho qua mà bộ quét gắn cờ = mã không ai chữa."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from probe_price_basis import SAME_BASIS_TOL
    assert bg.TOL == SAME_BASIS_TOL


def test_fetch_window_reaches_back_far_enough_for_a_median():
    start = bg.fetch_start(_LAST)
    assert (_LAST - start).days == bg.LOOKBACK_DAYS
    # đủ chỗ cho MIN_BARS phiên kể cả tuần lễ dài
    assert len(pd.bdate_range(start, _LAST)) > bg.MIN_BARS


# ── Kill-switch ─────────────────────────────────────────────────────────────

def test_guard_is_on_by_default_and_has_a_kill_switch(monkeypatch):
    monkeypatch.delenv("VNSTOCK_BASIS_GUARD", raising=False)
    assert bg.enabled()
    monkeypatch.setenv("VNSTOCK_BASIS_GUARD", "0")
    assert not bg.enabled()


# ── Sổ cách ly ──────────────────────────────────────────────────────────────

def test_pending_sheet_round_trip_and_atomic_write(tmp_path):
    assert bg.load_pending(tmp_path) == {}
    bg.record_drift(tmp_path, "vtp", {"ratio": 1.17, "pct": 17.0, "n": 9,
                                      "first": "2026-08-01",
                                      "last": "2026-08-14", "event": "bonus"},
                    today=date(2026, 8, 17))
    data = bg.load_pending(tmp_path)
    assert "VTP" in data                              # chuẩn hoá hoa
    assert data["VTP"]["ratio"] == pytest.approx(1.17)
    assert data["VTP"]["event"] == "bonus"
    assert "rebase_ticker_history" in data["VTP"]["fix"]
    assert not list((tmp_path / "_meta").glob("*.tmp")), "còn file tạm"
    bg.clear_drift(tmp_path, "VTP")
    assert bg.load_pending(tmp_path) == {}


def test_corrupt_pending_sheet_returns_empty_instead_of_raising(tmp_path):
    p = bg.pending_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("{ khong phai json", encoding="utf-8")
    assert bg.load_pending(tmp_path) == {}           # doctor gọi hàm này


def test_recording_never_raises_even_when_the_path_is_unwritable(tmp_path):
    blocked = tmp_path / "file_khong_phai_thu_muc"
    blocked.write_text("x", encoding="utf-8")
    bg.record_drift(blocked, "VTP", {"ratio": 1.2})   # không được ném
    bg.clear_drift(blocked, "VTP")


# ── Doctor badge ────────────────────────────────────────────────────────────

def test_doctor_badge_is_green_when_nothing_is_quarantined(tmp_path, monkeypatch):
    import vnstock_doctor as d
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    assert d.check_basis_drift()["status"] == "ok"


def test_doctor_badge_warns_and_names_the_tickers(tmp_path, monkeypatch):
    import vnstock_doctor as d
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    bg.record_drift(tmp_path, "VTP", {"ratio": 1.17, "n": 9},
                    today=date(2026, 8, 17))
    out = d.check_basis_drift()
    assert out["status"] == "warn"
    assert "VTP" in out["message"]
    assert "ĐANG KHÔNG cập nhật" in out["message"]
    assert "rebase_ticker_history" in out["fix"]


# ── Integration: đường ghi thật ─────────────────────────────────────────────

def _updater_or_skip():
    try:
        import vnstock_updater as up
        return up
    except Exception as e:
        pytest.skip(f"vnstock_updater không import được ({e})")


def _seed(tmp_path, ratio: float = 1.0, n: int = 12):
    """Kho n phiên tới _LAST, giá = giá 'thật' × ratio."""
    tdir = tmp_path / "prices" / f"ticker=VTP"
    ydir = tdir / "year=2026"
    ydir.mkdir(parents=True)
    days = list(pd.bdate_range(end=_LAST, periods=n).date)
    px = [(100.0 + i) * ratio for i in range(n)]
    pd.DataFrame({"time": days, "open": px, "high": px, "low": px,
                  "close": px, "volume": [1e6] * n}).to_parquet(
        ydir / "data.parquet", index=False)
    return tmp_path / "prices", tdir, days


def _source_df(days, extra_days=1):
    """Nguồn ở cơ sở 'thật' (ratio 1.0), có thêm bar mới sau _LAST."""
    allday = list(days) + [_LAST + timedelta(days=i) for i in (1,)][:extra_days]
    px = [100.0 + i for i in range(len(allday))]
    return pd.DataFrame({"time": allday, "open": px, "high": px, "low": px,
                         "close": px, "volume": [1e6] * len(allday)})


def test_rebased_source_is_refused_and_the_warehouse_is_untouched(
        tmp_path, monkeypatch):
    """Ca thật: kho còn cơ sở cũ (×1.17), nguồn vừa chia lại. Ghi tiếp là sinh
    bậc giả — phải TỪ CHỐI, cách ly, và không đụng một byte nào của kho."""
    up = _updater_or_skip()
    prices_dir, tdir, days = _seed(tmp_path, ratio=1.17)
    pq = tdir / "year=2026" / "data.parquet"
    before = pq.read_bytes()
    monkeypatch.setattr(up, "_fetch_prices",
                        lambda t, start, end: _source_df(days))

    r = up.update_ticker("VTP", prices_dir, _LAST + timedelta(days=1))

    assert r["status"] == "basis_drift"
    assert r["ratio"] == pytest.approx(1.17, abs=1e-6)
    assert pq.read_bytes() == before, "đã từ chối mà vẫn ghi kho"
    pending = bg.load_pending(tmp_path)
    assert "VTP" in pending and pending["VTP"]["ratio"] == pytest.approx(1.17)


def test_aligned_source_updates_exactly_like_before_the_guard(
        tmp_path, monkeypatch):
    """Cửa sổ fetch nới ra CHỈ để đối chiếu — không được làm dày kho thêm bar
    nào, không được đổi số ngày mới."""
    up = _updater_or_skip()
    prices_dir, tdir, days = _seed(tmp_path, ratio=1.0)
    monkeypatch.setattr(up, "_fetch_prices",
                        lambda t, start, end: _source_df(days))

    r = up.update_ticker("VTP", prices_dir, _LAST + timedelta(days=1))

    assert r["status"] == "updated"
    assert r["new_days"] == 1
    merged = pd.read_parquet(tdir / "year=2026")
    assert len(merged) == len(days) + 1
    assert bg.load_pending(tmp_path) == {}


def test_kill_switch_restores_the_old_silent_behaviour(tmp_path, monkeypatch):
    """Tắt guard = hành vi y như trước 19/08: nối bừa, sinh bậc, không kêu."""
    up = _updater_or_skip()
    monkeypatch.setenv("VNSTOCK_BASIS_GUARD", "0")
    prices_dir, tdir, days = _seed(tmp_path, ratio=1.17)
    monkeypatch.setattr(up, "_fetch_prices",
                        lambda t, start, end: _source_df(days))

    r = up.update_ticker("VTP", prices_dir, _LAST + timedelta(days=1))

    assert r["status"] == "updated"
    assert bg.load_pending(tmp_path) == {}


def test_repairing_a_ticker_clears_it_from_the_quarantine_sheet(tmp_path):
    """Chữa xong mà sổ còn tên thì doctor kêu mãi và badge mất giá trị."""
    bg.record_drift(tmp_path, "VTP", {"ratio": 1.17, "n": 9})
    assert "VTP" in bg.load_pending(tmp_path)
    bg.clear_drift(tmp_path, "VTP")
    assert bg.load_pending(tmp_path) == {}


class TestOverlapWindowIsNoWiderThanNeeded:
    """
    Bản V1 nới thẳng 30 ngày cho MỌI mã MỌI đêm, trong khi lượt cập nhật
    thường chỉ cần 1-3 ngày ⇒ cửa sổ fetch phình ~16× trên ~1.600 mã.

    Đo trên máy thật 24/08: `updater` **5.659s = 57% cả phát**, và cả phát
    **166,3′ chỉ còn 13,7′ đệm** dưới trần task 3 giờ. Trần task cắt TRƯỚC
    bước brief (bước 14/14) nên phình thêm chút nữa là mất brief cả đêm.

    Bất biến phải giữ: hẹp đi nhưng **sức phát hiện KHÔNG đổi** — vùng chồng
    lấn luôn còn ≥ `MIN_BARS` bar, và mã nghỉ giao dịch dài vẫn được giãn tới
    trần.
    """
    from datetime import date as _d, timedelta as _td

    FF = _d(2026, 8, 24)

    def _liquid(self):
        return [self.FF - self._td(days=i) for i in range(40)
                if (self.FF - self._td(days=i)).weekday() < 5]

    def test_a_liquid_ticker_gets_a_much_narrower_window(self):
        import vnstock_basis_guard as bg
        back = (self.FF - bg.window_start(self._liquid(), self.FF)).days
        assert back < bg.LOOKBACK_DAYS
        assert back <= 15                      # ~2 tuần, không phải ~5 tuần

    def test_the_narrow_window_still_holds_enough_bars_to_decide(self):
        import vnstock_basis_guard as bg
        start = bg.window_start(self._liquid(), self.FF)
        kept = [d for d in self._liquid() if start <= d <= self.FF]
        assert len(kept) >= bg.MIN_BARS

    def test_a_thinly_traded_ticker_still_stretches_to_the_ceiling(self):
        import vnstock_basis_guard as bg
        sparse = [self.FF - self._td(days=i) for i in (1, 15, 33)]
        assert bg.window_start(sparse, self.FF) == bg.fetch_start(self.FF)

    def test_no_warehouse_bars_falls_back_to_the_ceiling(self):
        # Chưa biết gì thì ĐỪNG thu hẹp
        import vnstock_basis_guard as bg
        assert bg.window_start([], self.FF) == bg.fetch_start(self.FF)
        assert bg.window_start(None, self.FF) == bg.fetch_start(self.FF)

    def test_never_narrower_than_the_floor(self):
        import vnstock_basis_guard as bg
        dense = [self.FF - self._td(days=i) for i in range(12)]
        back = (self.FF - bg.window_start(dense, self.FF)).days
        assert back >= bg.MIN_LOOKBACK_DAYS

    def test_never_wider_than_the_ceiling(self):
        import vnstock_basis_guard as bg
        ancient = [self.FF - self._td(days=i) for i in range(200)]
        assert bg.window_start(ancient, self.FF) >= bg.fetch_start(self.FF)

    def test_future_dates_in_the_warehouse_are_ignored(self):
        import vnstock_basis_guard as bg
        mixed = self._liquid() + [self.FF + self._td(days=5)]
        assert bg.window_start(mixed, self.FF) <= self.FF

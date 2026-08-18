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

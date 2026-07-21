"""Tests cho resolve_current_price (dashboard/portfolio_tab.py) — fix 20/07.

Tái hiện đúng bug user bắt trên máy thật: quote WSS cũ (SSI 26,650) đóng băng
"Giá hiện tại" trong khi kho đã có bar 20/07 = 22.70 (nghìn đồng). Hermetic:
kho parquet + quote json đều nằm trong tmp_path.
"""

import json
from datetime import date, timedelta

import pytest

from dashboard.portfolio_tab import resolve_current_price, _quote_price_date

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

TODAY = date.today()
D = [TODAY - timedelta(days=i) for i in (4, 3, 1, 0)]  # 4 phiên gần nhất


def _write_prices(wh, ticker, rows, fname="prices.parquet", year_dir="year=x"):
    """rows = [(date, close)] — ghi 1 file parquet kiểu kho."""
    pdir = wh / "prices" / f"ticker={ticker}" / year_dir
    pdir.mkdir(parents=True, exist_ok=True)
    closes = [c for _, c in rows]
    df = pd.DataFrame({
        "time": [str(d) for d, _ in rows],
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1000] * len(rows),
    })
    df.to_parquet(pdir / fname, index=False)


def _write_quote(wh, ticker, price, day=None, with_time=True):
    live = wh / "_live"
    live.mkdir(parents=True, exist_ok=True)
    q = {"ticker": ticker, "price": price}
    if with_time and day is not None:
        q["time"] = f"{day}T10:30:00"
    (live / f"quote_{ticker}.json").write_text(json.dumps(q))


def test_stale_quote_loses_to_fresh_warehouse(tmp_path):
    """Kịch bản bug thật: quote cũ 26,650 (VND) vs kho có bar HÔM NAY 22.70
    (nghìn) → kho thắng, giá neo về đơn vị buy_price = 22,700."""
    _write_prices(tmp_path, "SSI",
                  [(D[0], 25.0), (D[1], 24.25), (D[3], 22.7)])
    _write_quote(tmp_path, "SSI", 26650.0, day=str(TODAY - timedelta(days=12)))
    price, day, src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert src == "kho"
    assert day == str(D[3])
    assert abs(price - 22700.0) < 1.0


def test_fresh_quote_wins_on_same_day(tmp_path):
    """Quote CÙNG NGÀY với bar kho → live thắng (trong phiên tươi hơn EOD)."""
    _write_prices(tmp_path, "SSI", [(D[2], 23.1), (D[3], 22.7)])
    _write_quote(tmp_path, "SSI", 23150.0, day=str(D[3]))
    price, day, src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert src == "live"
    assert abs(price - 23150.0) < 1.0


def test_quote_newer_than_warehouse_wins(tmp_path):
    """Kho dừng ở hôm qua, quote hôm nay → live thắng."""
    _write_prices(tmp_path, "SSI", [(D[1], 24.25), (D[2], 23.0)])
    _write_quote(tmp_path, "SSI", 22900.0, day=str(D[3]))
    price, day, src = resolve_current_price(
        "SSI", 23000.0, str(D[2]), tmp_path)
    assert src == "live"
    assert day == str(D[3])
    assert abs(price - 22900.0) < 1.0


def test_quote_in_nghin_anchored_to_buy_price(tmp_path):
    """Quote ghi theo nghìn đồng (22.7) mà buy_price VND thô → neo ×1000."""
    _write_quote(tmp_path, "SSI", 22.7, day=str(D[3]))
    price, _day, src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert src == "live"
    assert abs(price - 22700.0) < 1.0


def test_conflicted_copy_newest_bar_wins_by_time(tmp_path):
    """Bar mới nhất nằm trong file Dropbox conflicted copy — chọn theo THỜI
    GIAN chứ không phải iloc[-1] của file đầu theo tên (bug cũ)."""
    _write_prices(tmp_path, "SSI", [(D[0], 26.65), (D[1], 25.0)],
                  fname="prices.parquet")
    _write_prices(tmp_path, "SSI", [(D[2], 24.0), (D[3], 22.7)],
                  fname="prices (conflicted copy).parquet")
    price, day, src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert src == "kho"
    assert day == str(D[3])
    assert abs(price - 22700.0) < 1.0


def test_quote_without_time_field_uses_mtime(tmp_path):
    """Quote thiếu field time → lấy ngày từ mtime file (hôm nay) → vẫn thắng
    kho dừng hôm qua."""
    _write_prices(tmp_path, "SSI", [(D[2], 23.0)])
    _write_quote(tmp_path, "SSI", 22850.0, with_time=False)
    got = _quote_price_date("SSI", tmp_path)
    assert got is not None and got[1] == str(TODAY)
    price, _day, src = resolve_current_price(
        "SSI", 23000.0, str(D[2]), tmp_path)
    assert src == "live"
    assert abs(price - 22850.0) < 1.0


def test_no_sources_returns_zero(tmp_path):
    assert resolve_current_price("XXX", 10000.0, str(TODAY), tmp_path) == \
        (0.0, "", "")


def test_float32_noise_rounded_away(tmp_path):
    """Kho lưu close float32 → 22.700001 × 1000 = 22,700.001 làm GT hiện tại
    ra '454,000,015' — resolver làm tròn 6 chữ số có nghĩa → đúng 22,700."""
    _write_prices(tmp_path, "SSI", [(D[2], 23.0), (D[3], 22.700001)])
    price, _day, _src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert price == 22700.0
    assert price * 20000 == 454_000_000.0


def test_bad_quote_ignored_warehouse_used(tmp_path):
    _write_prices(tmp_path, "SSI", [(D[2], 23.0), (D[3], 22.7)])
    (tmp_path / "_live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_live" / "quote_SSI.json").write_text("{corrupt")
    price, _day, src = resolve_current_price(
        "SSI", 23000.0, str(TODAY), tmp_path)
    assert src == "kho"
    assert abs(price - 22700.0) < 1.0

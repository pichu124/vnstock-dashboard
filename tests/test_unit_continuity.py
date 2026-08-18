"""Lưới cho `scripts/check_unit_continuity.py` — công cụ đổi việc SOI MẮT
"giá có liên tục không" (badge doctor giao lại) thành ngưỡng deterministic.

Ba nhóm ca, mỗi nhóm là một CHẨN ĐOÁN KHÁC NHAU nên phải phân biệt được:
vết quy đổi sót (~1000×) · chia tách chưa back-adjust (~2×) · kho lệch giá
live (không phải lỗi đơn vị, chữa ở sync). Ca "sạch" quan trọng ngang ca
"bẩn": báo động giả thì lần sau không ai đọc badge nữa.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_unit_continuity as cuc  # noqa: E402


def _series(closes, start="2026-08-01"):
    times = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame({
        "time": times, "open": closes, "high": closes,
        "low": closes, "close": closes, "volume": [1000] * len(closes),
    })


def _write_bars(wh: Path, ticker: str, df: pd.DataFrame) -> None:
    d = wh / "prices" / f"ticker={ticker}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    df.to_parquet(d / "part.parquet", index=False)


# ── find_jumps: phân loại đúng nguyên nhân ───────────────────────────────────

def test_continuous_series_has_no_jumps():
    """Dao động thường ngày (±5%) KHÔNG được báo — báo động giả giết badge."""
    assert cuc.find_jumps(_series([10.0, 10.4, 9.9, 10.2, 9.8])) == []


def test_band_limit_move_is_not_a_jump():
    """Trần/sàn UPCOM ±15% là hợp lệ, phải đứng dưới ngưỡng 30%."""
    assert cuc.find_jumps(_series([10.0, 11.5, 13.2])) == []


def test_thousand_fold_cliff_flagged_as_unit_residue():
    """Vết quy đổi sót: bar nhảy ~1000× — chữ ký VND lẫn nghìn VND."""
    jumps = cuc.find_jumps(_series([9.8, 10.0, 10_200.0, 10.1]))
    assert len(jumps) == 2                       # lên rồi xuống
    assert all("QUY ĐỔI SÓT" in j["why"] for j in jumps)


def test_halving_flagged_as_possible_split():
    """Rơi ~1/2 trong một phiên là bất khả trên sàn VN → nghi chia tách."""
    jumps = cuc.find_jumps(_series([20.0, 20.2, 10.1, 10.0]))
    assert len(jumps) == 1
    assert "CHIA TÁCH" in jumps[0]["why"]
    assert jumps[0]["pct"] == pytest.approx(-50.0, abs=0.1)


def test_odd_gap_is_reported_without_guessing_a_cause():
    """Vách 60% không khớp chữ ký nào — nói "dữ liệu lỗi/thiếu phiên", không
    bịa nguyên nhân (bài học: đoán sai nguyên nhân tệ hơn không đoán)."""
    jumps = cuc.find_jumps(_series([10.0, 16.5]))
    assert len(jumps) == 1
    assert "biên độ sàn" in jumps[0]["why"]


# ── live_gap: kho vs giá live ────────────────────────────────────────────────

def test_live_gap_converts_vnd_to_thousand_before_comparing(tmp_path):
    """Quote live ở VND, kho ở nghìn VND — so thẳng là luôn lệch 1000×."""
    live = tmp_path / "_live"
    live.mkdir()
    (live / "quote_YBM.json").write_text(json.dumps({"price": 9700.0}))
    gap = cuc.live_gap(live, "YBM", last_close=9.70)
    assert gap["ok"] and gap["ratio"] == pytest.approx(1.0, abs=0.01)


def test_live_gap_flags_warehouse_far_from_live(tmp_path):
    """Ca XPH 18/08: live 15,600 VND mà kho 10.20 nghìn → lệch 1.53×."""
    live = tmp_path / "_live"
    live.mkdir()
    (live / "quote_XPH.json").write_text(json.dumps({"price": 15600.0}))
    gap = cuc.live_gap(live, "XPH", last_close=10.20)
    assert not gap["ok"]
    assert gap["ratio"] == pytest.approx(1.53, abs=0.01)


def test_live_gap_silent_without_quote(tmp_path):
    """Không có quote (ngoài phiên) → None, KHÔNG phải "lệch"."""
    assert cuc.live_gap(tmp_path, "ZZZ", last_close=10.0) is None


# ── main: chọn mã theo đúng nguồn badge doctor đọc ───────────────────────────

def _seed_events(wh: Path, tickers) -> None:
    meta = wh / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "unit_normalizations.json").write_text(json.dumps({"events": [
        {"at": pd.Timestamp.now().isoformat(timespec="seconds"),
         "ticker": t, "ratio": 937.5, "rows": 1} for t in tickers]}))


def test_main_reads_the_same_source_as_the_doctor_badge(tmp_path, capsys):
    """Doctor và công cụ này PHẢI nói về cùng một tập mã — đọc chung
    `_meta/unit_normalizations.json`, không ai tự giữ danh sách riêng."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["WSS", "YBM"])
    _write_bars(wh, "WSS", _series([6.0, 6.1, 6.05]))
    _write_bars(wh, "YBM", _series([9.7, 9.8, 9.7]))

    rc = cuc.main(["--warehouse", str(wh)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WSS" in out and "YBM" in out
    assert "2 mã đều liên tục" in out


def test_main_exits_1_when_a_ticker_needs_eyes(tmp_path, capsys):
    wh = tmp_path / "wh"
    _seed_events(wh, ["XPH"])
    _write_bars(wh, "XPH", _series([10.0, 10_200.0, 10.1]))
    assert cuc.main(["--warehouse", str(wh)]) == 1
    assert "cần soi tay" in capsys.readouterr().out


def test_main_exits_2_without_a_warehouse(tmp_path, capsys):
    assert cuc.main(["--warehouse", str(tmp_path / "trống")]) == 2
    assert "không thấy kho giá" in capsys.readouterr().out


def test_explicit_ticker_overrides_the_event_list(tmp_path, capsys):
    """Soi lại một mã bất kỳ sau này (không còn vết quy đổi) vẫn phải được."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["WSS"])
    _write_bars(wh, "YEG", _series([7.7, 7.6, 7.63]))
    rc = cuc.main(["--warehouse", str(wh), "--ticker", "yeg"])
    out = capsys.readouterr().out
    assert rc == 0 and "YEG" in out and "WSS" not in out


def test_missing_ticker_data_is_not_a_failure(tmp_path, capsys):
    """Mã có vết nhưng kho chưa có bar (mã mới) → nói ⬜, không đỏ oan."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["NEW"])
    (wh / "prices").mkdir(parents=True, exist_ok=True)
    assert cuc.main(["--warehouse", str(wh)]) == 0
    assert "không có dữ liệu trong kho" in capsys.readouterr().out

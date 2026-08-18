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
    assert all("QUY ĐỔI SÓT" in j["why"] and j["suspect"] for j in jumps)


def test_halving_flagged_as_possible_split():
    """Rơi ~1/2 trong một phiên là bất khả trên sàn VN → nghi chia tách."""
    jumps = cuc.find_jumps(_series([20.0, 20.2, 10.1, 10.0]))
    assert len(jumps) == 1
    assert "CHIA TÁCH" in jumps[0]["why"] and jumps[0]["suspect"]
    assert jumps[0]["pct"] == pytest.approx(-50.0, abs=0.1)


def test_odd_gap_is_reported_without_guessing_a_cause():
    """Vách 60% không khớp chữ ký nào — nói "dữ liệu lỗi", không bịa nguyên
    nhân (bài học: đoán sai nguyên nhân tệ hơn không đoán)."""
    jumps = cuc.find_jumps(_series([10.0, 16.5]))
    assert len(jumps) == 1
    assert "vượt biên độ sàn" in jumps[0]["why"] and jumps[0]["suspect"]


# ── Khoảng cách ngày: điều kiện thứ hai, thêm sau lần chạy thật 18/08 ────────

def _gapped(closes, dates):
    return pd.DataFrame({"time": pd.to_datetime(dates), "open": closes,
                         "high": closes, "low": closes, "close": closes,
                         "volume": [100] * len(closes)})


def test_move_across_a_trading_gap_is_reported_but_not_suspect():
    """Ca THẬT 18/08 (VTS): bar 2026-03-10 → 2026-08-07 rơi 40%. Mã kém thanh
    khoản nghỉ 5 tháng thì "hai bar liền nhau" KHÔNG phải "hai phiên liền
    nhau" — chấm biên độ sàn lên quãng đó là báo động giả (8/50 mã dính)."""
    jumps = cuc.find_jumps(_gapped([7.0, 4.2], ["2026-03-10", "2026-08-07"]))
    assert len(jumps) == 1
    j = jumps[0]
    assert not j["suspect"]                    # ghi nhận, KHÔNG kết tội
    assert "không kết luận" in j["why"].lower()
    assert j["gap_days"] == 150


def test_weekend_still_counts_as_adjacent():
    """Thứ Sáu → thứ Hai cách 3 ngày lịch — vẫn là hai phiên kề nhau."""
    jumps = cuc.find_jumps(_gapped([10.0, 6.0], ["2026-08-14", "2026-08-17"]))
    assert jumps and jumps[0]["suspect"]


def test_unit_residue_is_suspect_even_across_a_long_gap():
    """Không quãng thời gian nào biến giá thành SAI ĐƠN VỊ — vách ~1000× luôn
    là nghi vấn, kể cả khi hai bar cách nhau nửa năm."""
    jumps = cuc.find_jumps(_gapped([10.0, 10_100.0], ["2026-01-05", "2026-08-17"]))
    assert jumps and jumps[0]["suspect"]
    assert "QUY ĐỔI SÓT" in jumps[0]["why"]


# ── Đối chiếu sự kiện quyền: nói VÌ SAO, không chỉ nói "có vách" ────────────

def _write_events(wh: Path, ticker: str, rows: list[dict]) -> None:
    d = wh / "_meta" / "corp_actions"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(d / f"{ticker}.parquet", index=False)


def test_suspect_jump_matching_a_corp_action_names_the_cause(tmp_path, capsys):
    """Ca THẬT 18/08 (VVS): kề phiên rơi 36.7%, hệ số 1.58×. Biết "có vách"
    mới xong nửa việc — trùng ngày GDKHQ thì nguyên nhân là back-adjust chưa
    áp (chữa ở tầng điều chỉnh), KHÁC HẲN "dữ liệu lỗi" (chữa ở nguồn)."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["VVS"])
    _write_bars(wh, "VVS", _gapped([112.50, 71.21, 72.0],
                                   ["2026-06-12", "2026-06-15", "2026-06-16"]))
    _write_events(wh, "VVS", [{"ticker": "VVS", "ex_date": "2026-06-15",
                               "type": "bonus", "cash_amount": None,
                               "ratio": 1.58, "raw": "Thưởng CP tỉ lệ 100:58"}])
    rc = cuc.main(["--warehouse", str(wh)])
    out = capsys.readouterr().out
    assert rc == 1                              # vẫn phải sửa, nhưng biết sửa gì
    assert "TRÙNG SỰ KIỆN QUYỀN" in out and "bonus" in out
    assert "back-adjust" in out
    assert "1.580" in out                       # hệ số quan sát ≈ ratio sự kiện
    assert "100:58" in out                      # nguyên văn để đối chiếu tay


def test_jump_without_a_matching_event_points_at_the_basis_probe(tmp_path, capsys):
    """Không có sự kiện trùng → KHÔNG bịa nguyên nhân, nhưng cũng đừng bỏ lửng
    ở chữ "lỗi": ca VVS 18/08 chứng minh chữ ký này thường là KHO LỆCH CƠ SỞ
    (nguồn rebase sau sự kiện quyền), nên trỏ thẳng sang bước phân định."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["ABC"])
    _write_bars(wh, "ABC", _gapped([10.0, 6.0], ["2026-08-14", "2026-08-17"]))
    _write_events(wh, "ABC", [{"ticker": "ABC", "ex_date": "2025-01-02",
                               "type": "cash", "cash_amount": 1000.0,
                               "ratio": None, "raw": "cổ tức tiền mặt"}])
    cuc.main(["--warehouse", str(wh)])
    out = capsys.readouterr().out
    assert "TRÙNG SỰ KIỆN" not in out
    assert "LỆCH CƠ SỞ" in out and "probe_price_basis" in out


def test_all_mode_sweeps_the_warehouse_and_hides_clean_tickers(tmp_path, capsys):
    """Sau ca VVS: phải quét được TOÀN KHO để biết còn mã nào cùng triệu chứng.
    In cả nghìn mã sạch thì phần đáng đọc chìm nghỉm → --all chỉ in mã nghi
    vấn, nhưng TỔNG vẫn đếm trên toàn bộ mã có dữ liệu."""
    wh = tmp_path / "wh"
    _write_bars(wh, "AAA", _series([10.0, 10.1, 10.0]))
    _write_bars(wh, "BBB", _series([20.0, 20.1, 20.0]))
    _write_bars(wh, "CCC", _gapped([112.5, 71.21],
                                   ["2026-06-12", "2026-06-15"]))
    rc = cuc.main(["--warehouse", str(wh), "--all"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "3 mã" in out                       # quét đủ 3
    assert "CCC" in out and "1/3 mã cần soi tay" in out
    assert "AAA" not in out and "BBB" not in out   # mã sạch bị ẩn


def test_gap_moves_are_not_blamed_on_corp_actions(tmp_path, capsys):
    """Vách qua quãng nghỉ không phải nghi vấn → đừng đi tra sự kiện rồi gán
    nguyên nhân cho nó; giữ nguyên thông điệp "không kết luận được"."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["VTS"])
    _write_bars(wh, "VTS", _gapped([7.0, 4.2], ["2026-03-10", "2026-08-07"]))
    _write_events(wh, "VTS", [{"ticker": "VTS", "ex_date": "2026-08-07",
                               "type": "bonus", "cash_amount": None,
                               "ratio": 1.6, "raw": "x"}])
    assert cuc.main(["--warehouse", str(wh)]) == 0
    assert "TRÙNG SỰ KIỆN" not in capsys.readouterr().out


def test_missing_event_cache_is_silent(tmp_path):
    """Không có cache sự kiện (máy vừa dựng) → None, không nổ."""
    assert cuc.match_corp_action("ZZZ", tmp_path, "2026-06-15") is None


def test_ticker_with_only_gap_moves_is_clean(tmp_path, capsys):
    """Mã chỉ có vách qua quãng nghỉ → status sạch, exit 0. Đây là điều kiện
    để badge/tool không kêu oan hàng chục mã mỗi lần chạy."""
    wh = tmp_path / "wh"
    _seed_events(wh, ["VTS"])
    _write_bars(wh, "VTS", _gapped([7.0, 4.2, 4.3],
                                   ["2026-03-10", "2026-08-07", "2026-08-10"]))
    assert cuc.main(["--warehouse", str(wh)]) == 0
    out = capsys.readouterr().out
    assert "ℹ" in out                          # vẫn in ra để đọc
    assert "cần soi tay" not in out


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


# ── Lọc loại chứng khoán + cửa sổ thời gian (sau lần quét toàn kho 18/08) ────
#
# Lần quét đầu gắn cờ 1.902/3.125 mã. Hai nguyên nhân, cả hai đều là lỗi của
# công cụ chứ không phải của kho: chấm CW/trái phiếu/chỉ số bằng thước biên độ
# cổ phiếu, và quét cả 20 năm lịch sử nên nhiễu cũ nhấn chìm tín hiệu mới.

def test_is_equity_rejects_non_stock_instruments():
    for bad in ("CFPT2528", "CHPG2601", "CVNM2204",   # chứng quyền
                "CTG121030", "MBB125008", "VBA121033",  # trái phiếu
                "41I1G4000",                            # phái sinh HNX
                "VNINDEX", "VN30"):                     # chỉ số
        assert not cuc._is_equity(bad), bad
    for good in ("VVS", "XPH", "VNM", "FPT", "SSI"):
        assert cuc._is_equity(good), good


def test_all_mode_skips_non_equities(tmp_path, capsys):
    """CW nhảy 40% một phiên là BÌNH THƯỜNG (không có biên độ) — quét toàn kho
    mà chấm nó bằng thước cổ phiếu thì 1.900 dòng báo động giả."""
    wh = tmp_path / "wh"
    _write_bars(wh, "CFPT2528", _gapped([1.0, 0.5], ["2026-08-14", "2026-08-17"]))
    _write_bars(wh, "AAA", _series([10.0, 10.1, 10.0]))
    rc = cuc.main(["--warehouse", str(wh), "--all"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CFPT2528" not in out
    assert "bỏ 1" in out                      # nói rõ đã bỏ bao nhiêu mã


def test_since_window_hides_ancient_noise(tmp_path, capsys):
    """Vách năm 2010 không nói gì về kho hôm nay. --all cắt cửa sổ 365 ngày;
    soi mã lẻ thì vẫn xem toàn lịch sử (0 = không cắt)."""
    wh = tmp_path / "wh"
    _write_bars(wh, "AAA", _gapped([10.0, 6.0, 6.1],
                                   ["2010-03-01", "2010-03-02", "2010-03-03"]))
    assert cuc.main(["--warehouse", str(wh), "--all"]) == 0        # cửa sổ 365
    assert cuc.main(["--warehouse", str(wh), "--ticker", "AAA"]) == 1  # toàn bộ
    assert "2010-03-02" in capsys.readouterr().out


def test_all_mode_ranks_by_liquidity_not_alphabet(tmp_path, capsys):
    """149 dòng TÊN thì không xếp được ưu tiên: penny không ai giao dịch nằm
    lẫn với mã có thể vào universe chiến lược. Quét rộng phải trả lời "mã nào
    ĐÁNG LO", nên xếp theo GTGD giảm dần và in kèm ngày vách + hệ số."""
    dates = [str(d.date()) for d in pd.bdate_range(end="2026-08-17", periods=2)]
    for tk, close, vol in (("PENNY", [1.0, 0.6], 3_000),
                           ("BIGLQ", [112.5, 71.21], 200_000)):
        d = tmp_path / "wh" / "prices" / f"ticker={tk}" / "year=2026"
        d.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"time": pd.to_datetime(dates), "open": close,
                      "high": close, "low": close, "close": close,
                      "volume": [vol] * 2}).to_parquet(d / "p.parquet", index=False)

    cuc.main(["--warehouse", str(tmp_path / "wh"), "--all"])
    out = capsys.readouterr().out
    assert out.index("BIGLQ") < out.index("PENNY")     # thanh khoản cao lên trước
    assert "1.580×" in out and "GTGD20" in out         # hệ số + thanh khoản

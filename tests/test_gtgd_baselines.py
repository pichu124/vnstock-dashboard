"""Tests cho vnstock_brief._gtgd_baselines — gate coverage baseline GTGD.

Review 21/07: cùng baseline TB20 nhưng bản close 01:22 ra "+28%" còn bản
16:18 ra "+0%" — map gtgd_by_date cộng dồn 22 bar cuối CỦA TỪNG MÃ nên
ngày nào rơi ngoài cửa sổ của mã sync trễ sẽ hụt tổng, kéo TB5/TB20 lệch
theo trạng thái kho lúc chạy screener. Fix: loại ngày có count < 70%
median(count) khỏi baseline (count thấp = thiếu data, không phải phiên vắng).
"""

from vnstock_brief import _gtgd_baselines

DATA_DATE = "2026-07-21"


def _byd(rows):
    """rows = [(day_of_july, total, count)] → map {iso: {total, count}}."""
    return {f"2026-07-{d:02d}": {"total": float(t), "count": c}
            for d, t, c in rows}


def test_full_coverage_plain_averages():
    byd = _byd([(d, 20_000.0, 800) for d in range(1, 21)])
    cmp = _gtgd_baselines(byd, DATA_DATE)
    assert cmp == {"prev": 20_000.0, "avg5": 20_000.0, "avg20": 20_000.0}


def test_undercovered_old_days_dropped_from_avg20():
    """Kịch bản 21/07: 15 phiên coverage đủ ~20,400 tỷ + 5 phiên mép cũ chỉ
    còn nửa số mã đóng góp (count 300 < 70%×800) tổng hụt còn 8,000 tỷ.
    Không gate: avg20 ≈ 17,300 → "+18%" ảo. Gate: avg20 = 20,400 → "+0%" thật."""
    rows = [(d, 20_400.0, 800) for d in range(6, 21)]      # 15 phiên đủ
    rows += [(d, 8_000.0, 300) for d in range(1, 6)]       # 5 phiên hụt
    cmp = _gtgd_baselines(_byd(rows), DATA_DATE)
    assert cmp["avg20"] == 20_400.0
    assert cmp["avg5"] == 20_400.0


def test_prev_skips_undercovered_session():
    """Phiên NGAY TRƯỚC bị hụt coverage → prev = phiên gần nhất ĐÃ QUA gate."""
    rows = [(20, 9_000.0, 250)] + [(d, 21_000.0, 800) for d in range(1, 20)]
    cmp = _gtgd_baselines(_byd(rows), DATA_DATE)
    assert cmp["prev"] == 21_000.0


def test_gate_boundary_exactly_70pct_kept():
    rows = [(d, 20_000.0, 1000) for d in range(2, 21)]
    rows += [(1, 14_000.0, 700)]          # đúng 70% median → GIỮ (≥)
    cmp = _gtgd_baselines(_byd(rows), DATA_DATE)
    assert cmp["avg20"] == round((19 * 20_000.0 + 14_000.0) / 20, 1)


def test_legacy_map_without_counts_not_gated():
    """Map cũ không có count (0/None) → giữ hành vi cũ, không gate."""
    byd = {f"2026-07-{d:02d}": {"total": 15_000.0, "count": 0}
           for d in range(1, 21)}
    cmp = _gtgd_baselines(byd, DATA_DATE)
    assert cmp["avg20"] == 15_000.0


def test_fewer_than_15_gated_sessions_no_avg20():
    rows = [(d, 20_000.0, 800) for d in range(11, 21)]     # 10 phiên đủ
    rows += [(d, 8_000.0, 200) for d in range(1, 11)]      # 10 phiên hụt
    cmp = _gtgd_baselines(_byd(rows), DATA_DATE)
    assert "avg20" not in cmp
    assert cmp["avg5"] == 20_000.0


def test_only_prior_sessions_used():
    """Ngày ≥ data_date (chính phiên đang so / tương lai) không vào baseline."""
    byd = _byd([(d, 20_000.0, 800) for d in range(15, 21)])
    byd["2026-07-21"] = {"total": 99_000.0, "count": 800}
    byd["2026-07-22"] = {"total": 99_000.0, "count": 800}
    cmp = _gtgd_baselines(byd, DATA_DATE)
    assert cmp["prev"] == 20_000.0
    assert cmp["avg5"] == 20_000.0


def test_empty_or_no_prior_returns_none():
    assert _gtgd_baselines({}, DATA_DATE) is None
    assert _gtgd_baselines(
        {"2026-07-21": {"total": 20_000.0, "count": 800}}, DATA_DATE) is None

"""Exit mix + cổng "chốt lời phải với tới được" (13/08).

Lý do thoát ("tp"/"sl"/"expire") được ghi vào TỪNG lệnh từ đầu nhưng chưa bao
giờ được gom — nên win rate 45% che mất sự thật "0/49 lệnh chạm chốt lời".
User phải đợi 49 khuyến nghị THẬT qua nhiều tuần mới thấy điều mà mọi backtest
tính ra được ngay. Giờ:

* `exit_mix(trades)` — con số nằm trong metrics của mọi backtest;
* `validate_backtest_quality` thêm lý do trượt khi TP gần như không bao giờ
  tới — chiến lược tp≈0 là chết từ thiết kế, bất kể p-value.

Cổng theo đúng doctrine "không đo được ≠ đo ra xấu": chỉ kết luận khi đủ lệnh
ĐÃ ĐÓNG (`_TP_REACH_MIN_CLOSED`), và "hold" không được tính là lệnh đóng.
"""
import pytest

from vnstock_strategy import (
    _TP_REACH_MIN_CLOSED,
    _TP_REACH_MIN_SHARE,
    exit_mix,
    validate_backtest_quality,
)


def _trades(reasons, pnl=1.0):
    return [{"ticker": "AAA", "start_idx": i, "action": "buy",
             "pnl": pnl if r == "tp" else (-1.0 if r == "sl" else 0.3),
             "reason": r, "confidence": 0.5}
            for i, r in enumerate(reasons)]


# ── exit_mix ────────────────────────────────────────────────────────────────

def test_exit_mix_shares_sum_to_one():
    mix = exit_mix(_trades(["tp"] * 2 + ["sl"] * 3 + ["expire"] * 5))
    assert mix == {"expire": 0.5, "sl": 0.3, "tp": 0.2}
    assert abs(sum(mix.values()) - 1.0) < 1e-9


def test_exit_mix_empty_and_reasonless():
    assert exit_mix([]) == {}
    assert exit_mix([{"pnl": 1.0}]) == {}       # lệnh không có reason → bỏ qua


def test_exit_mix_keeps_unknown_reasons():
    """Reason lạ (vd "hold") vẫn hiện — giấu đi là lại tạo một góc mù mới."""
    assert "hold" in exit_mix(_trades(["hold", "tp"]))


# ── Cổng TP-với-tới-được ───────────────────────────────────────────────────

def _tp_reason(val):
    return [r for r in (val or {}).get("reasons", []) if "chạm chốt lời" in r]


def test_zero_tp_over_enough_closed_trades_fails():
    """CA THẬT: đủ mẫu mà không lệnh nào chạm TP → trượt, kèm lý do đọc được."""
    val = validate_backtest_quality(_trades(["expire"] * 30 + ["sl"] * 10))
    assert val is not None
    reasons = _tp_reason(val)
    assert reasons, "TP 0% trên 40 lệnh đóng mà không có lý do trượt"
    assert "TP nằm ngoài tầm với" in reasons[0]
    assert val["passed"] is False


def test_healthy_tp_share_adds_no_reason():
    val = validate_backtest_quality(
        _trades(["tp"] * 12 + ["sl"] * 10 + ["expire"] * 18))
    assert not _tp_reason(val)


def test_small_sample_stays_silent():
    """Dưới ngưỡng lệnh đóng → KHÔNG kết luận, dù tp = 0%. Không đo được
    khác đo ra kết quả xấu."""
    val = validate_backtest_quality(_trades(["expire"] * (_TP_REACH_MIN_CLOSED - 1)))
    assert not _tp_reason(val)


def test_hold_trades_do_not_count_as_closed():
    """25 lệnh nhưng 20 là "hold" → chỉ 5 lệnh đóng, dưới ngưỡng → im."""
    val = validate_backtest_quality(_trades(["hold"] * 20 + ["expire"] * 5))
    assert not _tp_reason(val)


def test_share_just_above_threshold_passes_the_gate():
    n = _TP_REACH_MIN_CLOSED * 2
    n_tp = int(n * _TP_REACH_MIN_SHARE) + 1
    val = validate_backtest_quality(_trades(["tp"] * n_tp + ["expire"] * (n - n_tp)))
    assert not _tp_reason(val)

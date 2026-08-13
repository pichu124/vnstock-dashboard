"""Bốn lỗ tìm ra khi user soi brief chiều 13/08 — mỗi lỗ một lưới.

Bốn thứ khác nhau nhưng CÙNG một họ: hệ thống biết sự thật, chỉ là không nói
ra, hoặc nói ra thành thứ khác.

1. **Chiến lược trượt kiểm định vẫn phát khuyến nghị mà không nói.**
   `_recommendation_block` viết trong docstring là "open recommendations from
   VALIDATED strategies" nhưng CHƯA HỀ kiểm. Chiến lược đang hoạt động có
   p=0.974 (Sharpe không hơn ăn may), expectancy −0.58, **0/49 lệnh chạm chốt
   lời** — vẫn vào brief y như một chiến lược đạt.
   Bản đầu (13/08 sáng) chọn cảnh-báo-kèm-theo; user chốt cùng ngày: **trượt
   thì KHÔNG khuyến nghị gì** — block thay danh sách bằng sentinel KHÔNG CÓ,
   guard hạ xuống vai trò hàng rào dự phòng cho đường rec_block tự dựng.
2. **Ký hiệu nội bộ rò ra brief.** Mistral viết "cắt lỗ 77,600 (entry < TP >
   SL)" — nhại ràng buộc trong prompt, và nhại SAI (đúng là SL < entry < TP).
3. **Cùng một con số, ba nhãn khác nhau.** 11% trên MA200 + A/D 1.08: một agent
   gọi "TÍCH CỰC", ba agent gọi "yếu", dashboard gán 🔴 "đa số giảm".
4. **"0%" khi mẫu là 2.** Bảng độ chính xác hiện `0%` cho agent mới chấm được
   1-2 brief → đọc ra thành "agent sai hết", sự thật là "chưa đủ mẫu".

Lỗ 1 và 4 là cùng một bài học đã vấp nhiều lần: **không đo được ≠ đo ra kết
quả xấu** — nhưng ở hai chiều ngược nhau (1: xấu mà im; 4: chưa biết mà kêu).
"""
import json
import sys
import types

import pytest

import vnstock_brief as vb


# ── 1. Chiến lược trượt kiểm định phải NÓI RA ───────────────────────────────

_RECS_TEXT = ("## 💡 Đề xuất giao dịch\n"
              "- GAS MUA entry=80,000 TP=82,400 SL=77,600\n"
              "\n## ⚠️ Rủi ro cần lưu ý\n- ...")


def _ctx(passed, known=True, p=0.974, recs_in_prompt=True):
    return {"strategy_validation": {"known": known, "passed": passed,
                                    "p": p, "reasons": ["p-value 0.974 ≥ 0.1"]},
            "strategy_recs_in_prompt": recs_in_prompt}


def test_failed_validation_adds_a_caveat():
    """Đường dự phòng: rec ĐÃ lọt vào prompt (cờ True) + trượt → phải nói ra."""
    out = vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, _ctx(passed=False))
    assert "CHƯA QUA kiểm định" in out
    assert "p=0.974" in out


def test_caveat_lands_inside_the_recommendation_section():
    """Phải nằm NGAY DƯỚI khuyến nghị, không trôi xuống cuối brief — người đọc
    lướt qua mục đó phải thấy cảnh báo cùng lúc với ý tưởng mua."""
    out = vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, _ctx(passed=False))
    lines = out.splitlines()
    i_caveat = next(i for i, l in enumerate(lines) if "CHƯA QUA kiểm định" in l)
    i_risk = next(i for i, l in enumerate(lines) if "Rủi ro cần lưu ý" in l)
    assert i_caveat < i_risk


def test_caveat_silent_when_recs_were_suppressed_at_source():
    """Đường CHÍNH từ 13/08: block đã chặn ở nguồn (cờ False) → setup còn lại
    trong mục Đề xuất đến từ movers ⭐, KHÔNG phải từ chiến lược. Bắn caveat
    lúc này là nói sai nguồn — gắn nhãn "chiến lược chưa kiểm định" lên setup
    không liên quan gì tới chiến lược."""
    ctx = _ctx(passed=False, recs_in_prompt=False)
    assert vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, ctx) == _RECS_TEXT


def test_passing_strategy_says_nothing():
    assert vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, _ctx(passed=True)) == _RECS_TEXT


def test_unknown_validation_stays_silent():
    """Chưa có chiến lược / chưa backtest / DB lỗi = KHÔNG ĐO ĐƯỢC, không phải
    trượt. Cảnh báo oan làm người ta ngừng đọc cảnh báo thật."""
    assert vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, _ctx(None, known=False)) == _RECS_TEXT
    assert vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, {}) == _RECS_TEXT


def test_no_recommendation_section_no_caveat():
    text = "## 📊 Tổng kết phiên\nVNINDEX tăng 1.11%."
    assert vb.enforce_unvalidated_strategy_caveat(text, _ctx(passed=False)) == text


def test_empty_recommendation_section_no_caveat():
    text = "## 💡 Đề xuất giao dịch\n\n## ⚠️ Rủi ro\n- x"
    assert vb.enforce_unvalidated_strategy_caveat(text, _ctx(passed=False)) == text


def test_caveat_is_idempotent():
    once = vb.enforce_unvalidated_strategy_caveat(_RECS_TEXT, _ctx(passed=False))
    assert vb.enforce_unvalidated_strategy_caveat(once, _ctx(passed=False)) == once


def test_caveat_survives_the_whole_chain():
    """Điểm parity: đi qua CẢ chuỗi thì cảnh báo vẫn còn (guard sau không xoá)."""
    out = vb.apply_brief_guards(_RECS_TEXT, _ctx(passed=False))
    assert "CHƯA QUA kiểm định" in out
    assert vb.apply_brief_guards(out, _ctx(passed=False)) == out


# ── _recommendation_block: gắn cảnh báo vào PROMPT ──────────────────────────

def _fake_memory(monkeypatch, *, validation, recs=None):
    from datetime import datetime
    m = types.ModuleType("vnstock_memory")
    m.open_recommendations = lambda: (recs if recs is not None else [{
        "ticker": "GAS", "action": "buy", "entry_price": 80.0,
        "take_profit": 82.4, "cut_loss": 77.6, "horizon_days": 5,
        "created_at": datetime.now().isoformat(),
    }])
    m.get_active_family = lambda: {"id": 1}
    m.latest_backtest = lambda sid: (
        {"metrics_json": json.dumps({"validation": validation})}
        if validation is not None else None)
    monkeypatch.setitem(sys.modules, "vnstock_memory", m)
    return m


def test_block_suppresses_recs_when_strategy_failed(monkeypatch):
    """USER CHỐT 13/08: trượt kiểm định → KHÔNG khuyến nghị gì. Không còn là
    "kèm cảnh báo" — danh sách mã phải BIẾN MẤT khỏi prompt."""
    _fake_memory(monkeypatch, validation={"passed": False, "p_value_sharpe": 0.974,
                                          "reasons": ["p-value 0.974 ≥ 0.1"]})
    ctx = {}
    block = vb._recommendation_block(ctx)
    assert "GAS" not in block                       # mã bị chặn ở nguồn
    assert "KHÔNG CÓ khuyến nghị" in block          # sentinel, không phải im lặng
    assert "p=0.974" in block
    assert ctx["strategy_recs_in_prompt"] is False
    assert ctx["strategy_validation"]["passed"] is False


def test_suppression_is_a_sentinel_not_a_vacuum(monkeypatch):
    """Cùng bất biến chống-khoảng-trống của build_prompt: block biến mất âm
    thầm thì template vẫn trỏ tới "block Khuyến nghị" và model tự bịa. Sentinel
    phải CẤM rõ ràng, không chỉ ghi nhận thiếu."""
    _fake_memory(monkeypatch, validation={"passed": False, "p_value_sharpe": 0.974,
                                          "reasons": []})
    block = vb._recommendation_block({})
    assert "KHÔNG viết câu kiểu" in block
    assert "⭐" in block                             # chỉ đường thay thế hợp lệ


def test_block_lists_recs_when_strategy_passed(monkeypatch):
    _fake_memory(monkeypatch, validation={"passed": True, "p_value_sharpe": 0.01})
    ctx = {}
    block = vb._recommendation_block(ctx)
    assert "GAS" in block and "KHÔNG CÓ khuyến nghị" not in block
    assert ctx["strategy_recs_in_prompt"] is True


def test_block_lists_recs_when_no_backtest(monkeypatch):
    """Không đo được ≠ trượt: backtest cũ chưa có validation → vẫn phát."""
    _fake_memory(monkeypatch, validation=None)
    ctx = {}
    block = vb._recommendation_block(ctx)
    assert "GAS" in block and "KHÔNG CÓ khuyến nghị" not in block
    assert ctx["strategy_recs_in_prompt"] is True


def test_block_prefers_selection_adjusted_pvalue(monkeypatch):
    """p hiệu chỉnh chọn-lọc nghiêm hơn p thô — phải ưu tiên nó, giống panel."""
    _fake_memory(monkeypatch, validation={"passed": False, "p_value_sharpe": 0.20,
                                          "p_value_adj": 0.974, "reasons": []})
    ctx = {}
    vb._recommendation_block(ctx)
    assert ctx["strategy_validation"]["p"] == 0.974


def test_validation_reader_never_raises(monkeypatch):
    """Chạy trong đường sinh brief lúc 18:00 — nó mà ném thì mất cả brief."""
    broken = types.ModuleType("vnstock_memory")
    monkeypatch.setitem(sys.modules, "vnstock_memory", broken)
    ctx = {}
    out = vb._active_strategy_validation(ctx)
    assert out["known"] is False
    assert "strategy_validation" in ctx.get("loader_errors", {})


# ── 2. Ký hiệu ràng buộc nội bộ ─────────────────────────────────────────────

@pytest.mark.parametrize("raw,clean", [
    ("cắt lỗ 77,600 (entry < TP > SL) — tín hiệu tăng",
     "cắt lỗ 77,600 — tín hiệu tăng"),
    ("MUA vùng 32,250 (SL < entry < TP) tiếp", "MUA vùng 32,250 tiếp"),
    ("chốt lời 20,700 (TP > entry)", "chốt lời 20,700"),
])
def test_constraint_notation_is_stripped(raw, clean):
    assert vb.enforce_no_constraint_notation(raw) == clean


@pytest.mark.parametrize("keep", [
    "entry quanh 80,000 là hợp lý (giá tốt)",       # câu tiếng Việt bình thường
    "GAS (Giá 80,000) — MUA vùng 77,600",           # ngoặc chứa giá, không phải ràng buộc
    "Vị trí trong range: 98% (gần đỉnh range)",
])
def test_normal_parentheses_untouched(keep):
    assert vb.enforce_no_constraint_notation(keep) == keep


def test_constraint_notation_idempotent():
    t = "cắt lỗ 77,600 (entry < TP > SL) xong"
    once = vb.enforce_no_constraint_notation(t)
    assert vb.enforce_no_constraint_notation(once) == once


def test_constraint_notation_runs_in_the_chain():
    out = vb.apply_brief_guards("- GAS MUA vùng 80,000 · cắt lỗ 77,600 (entry < TP > SL)", {})
    assert "entry < TP" not in out


# ── 3. Độ rộng: 11% trên MA200 thì không thể "tích cực" ─────────────────────

_BREADTH_TEXT = "Độ rộng thị trường TÍCH CỰC với A/D 1.08, dù chỉ 11% mã trên MA200."


def test_very_weak_breadth_is_softened_even_with_positive_momentum():
    """CA THẬT 13/08: momentum +16 nên guard cũ đứng ngoài, một agent gọi độ
    rộng "TÍCH CỰC" trong khi ba agent kia gọi "yếu" trên CÙNG bộ số."""
    ctx = {"breadth": {"above_ma200_pct": 11.0, "ad_ratio": 1.08},
           "market_sentiment": {"momentum": 16}}
    assert "trái chiều" in vb.enforce_breadth_quality(_BREADTH_TEXT, ctx)


def test_broad_market_is_left_alone():
    """Thị trường rộng thật thì tuyệt đối không được đụng vào."""
    t = "Độ rộng thị trường tích cực với A/D 1.40 và 62% trên MA200."
    ctx = {"breadth": {"above_ma200_pct": 62.0, "ad_ratio": 1.40},
           "market_sentiment": {"momentum": 40}}
    assert vb.enforce_breadth_quality(t, ctx) == t


def test_middle_band_keeps_the_old_momentum_gate():
    """35% trên MA200 + momentum dương = vùng xám, giữ nguyên hành vi cũ."""
    ctx = {"breadth": {"above_ma200_pct": 35.0, "ad_ratio": 1.1},
           "market_sentiment": {"momentum": 20}}
    assert vb.enforce_breadth_quality(_BREADTH_TEXT, ctx) == _BREADTH_TEXT


def test_threshold_matches_the_dashboard_red_band():
    """Brief và dashboard phải gán CÙNG nhãn cho cùng một con số. Ngưỡng 🔴 của
    bảng nhận định và ngưỡng "không thể gọi tích cực" của guard phải bằng nhau
    — trôi khỏi nhau là hai màn hình nói hai kiểu."""
    from dashboard.market_commentary import _MA200_MIXED
    from vnstock_brief_guards_numbers import _MA200_CALL_IT_WEAK
    assert _MA200_CALL_IT_WEAK == _MA200_MIXED


# ── 4. "0%" khi mẫu là 2 ────────────────────────────────────────────────────

@pytest.mark.parametrize("n,acc,expect", [
    (0, None, "—"),                 # chưa chấm được gì
    (1, 1.0, "— (n=1)"),            # 100% với 1 mẫu cũng vô nghĩa
    (2, 0.0, "— (n=2)"),            # CA THẬT: trước đây hiện "0%"
    (4, 0.5, "— (n=4)"),
    (5, 0.4, "40% (n=5)"),          # đủ mẫu → mới hiện số
    (20, 0.65, "65% (n=20)"),
])
def test_accuracy_hides_the_number_until_the_sample_is_enough(n, acc, expect):
    assert vb.format_accuracy({"n_evaluated": n, "accuracy": acc}) == expect


def test_small_sample_never_reads_as_zero_percent():
    """Điểm cốt lõi: 0/2 KHÔNG được hiện ra dưới dạng một con số phần trăm."""
    assert "%" not in vb.format_accuracy({"n_evaluated": 2, "accuracy": 0.0})


def test_summary_marks_reliability(monkeypatch):
    monkeypatch.setattr(vb, "_load_vnindex_closes", lambda *a, **k: {})
    briefs = [{"agent_name": "A", "brief_type": "morning", "content": "x",
               "created_at": "2026-08-12T10:00:00"}]
    out = vb.agent_accuracy_summary(briefs, horizon_days=1)
    assert out["A"]["reliable"] is False


def test_sample_threshold_is_at_least_three():
    """Chốt ngưỡng khỏi bị hạ xuống 1-2 cho 'đỡ trống bảng'."""
    assert vb._ACCURACY_MIN_SAMPLE >= 3

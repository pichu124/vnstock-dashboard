"""Hai tầng chiến lược chạy song song (13/08 — user chốt "theo dõi cả ngắn/dài").

`tier` là cột mới trên bảng strategies: 'short' (5 phiên — mọi chiến lược cũ)
và 'position' (20 phiên — chọn từ SỐ ĐO reachability trên máy user: p60 MFE
tại 20 phiên = 2.89×ATR khớp dải tp_atr_mult 2.5–3.0; TP 2.5×ATR với tới 46%
so với 16% ở 5 phiên).

Bốn hợp đồng phải giữ:
1. **Di sản nguyên vẹn** — dữ liệu cũ mặc định 'short'; mọi chỗ gọi
   `get_active_family()` không tham số vẫn nhận đúng chiến lược như trước.
2. **Ghế riêng từng tier** — promote tầng này không kéo tầng kia xuống.
3. **step ≥ horizon** — hai lệnh backtest chồng cửa sổ là cùng một cú sóng
   đếm nhiều lần; mẫu "độc lập" giả làm p-value đẹp giả, kiểm định chống-ăn-may
   thành trang trí.
4. **Gating brief theo TỪNG chiến lược** — rec tầng vị thế không bị xử theo
   kiểm định của tầng 5 phiên (và ngược lại).
"""
import json
import sys
import types
from datetime import datetime

import pytest

import vnstock_memory as vm
from vnstock_strategy import DEFAULT_HORIZON_DAYS, TIER_CONFIGS, tier_config


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "DB_PATH", tmp_path / "brief_memory.db")
    vm.init_db()
    return vm


def _add(mem, name, tier="short", status="draft"):
    return mem.save_strategy(agent_name="test", name=name, code="def signal(): pass",
                             tier=tier, status=status)


# ── 1+2. Schema & ghế riêng ─────────────────────────────────────────────────

def test_legacy_rows_default_to_short(mem_db):
    """Chiến lược cũ (không khai tier) phải là 'short' — dữ liệu trên máy user
    có 29 chiến lược thật, đổi nghĩa của chúng là phá lịch sử."""
    sid = mem_db.save_strategy(agent_name="a", name="cũ", code="x")
    mem_db.promote_strategy(sid)
    active = mem_db.get_active_family()          # gọi KHÔNG tham số như code cũ
    assert active is not None and active["id"] == sid
    assert active["tier"] == "short"


def test_each_tier_has_its_own_active_seat(mem_db):
    s1 = _add(mem_db, "ngắn", tier="short")
    s2 = _add(mem_db, "vị thế", tier="position")
    mem_db.promote_strategy(s1)
    mem_db.promote_strategy(s2)
    assert mem_db.get_active_family(tier="short")["id"] == s1
    assert mem_db.get_active_family(tier="position")["id"] == s2


def test_promoting_one_tier_does_not_retire_the_other(mem_db):
    """LÝ DO tier tồn tại như một cột chứ không phải quy ước đặt tên: promote
    có `retire_others=True` — không scope theo tier thì tạo tầng vị thế xong
    là tầng 5 phiên mất ghế ngay lập tức."""
    s1 = _add(mem_db, "ngắn", tier="short")
    s2a = _add(mem_db, "vị thế A", tier="position")
    s2b = _add(mem_db, "vị thế B", tier="position")
    mem_db.promote_strategy(s1)
    mem_db.promote_strategy(s2a)
    mem_db.promote_strategy(s2b)                 # thay ghế position
    assert mem_db.get_active_family(tier="short")["id"] == s1      # còn nguyên
    assert mem_db.get_active_family(tier="position")["id"] == s2b  # s2a mất ghế


def test_migration_is_idempotent(mem_db):
    mem_db.init_db()
    mem_db.init_db()                              # chạy lại không nổ
    assert mem_db.get_active_family(tier="position") is None


# ── 3. Cấu hình tier ────────────────────────────────────────────────────────

def test_position_tier_is_20_sessions_from_measurement():
    assert TIER_CONFIGS["position"]["horizon_days"] == 20


def test_short_tier_matches_legacy_default():
    assert TIER_CONFIGS["short"]["horizon_days"] == DEFAULT_HORIZON_DAYS


@pytest.mark.parametrize("tier", sorted(TIER_CONFIGS))
def test_step_never_smaller_than_horizon(tier):
    """Bất biến chống pseudo-replication: step < horizon là các lệnh chồng cửa
    sổ — cùng một cú sóng đếm nhiều lần, p-value đẹp giả."""
    t = TIER_CONFIGS[tier]
    assert t["step_days"] >= t["horizon_days"], (
        f"tier {tier}: step {t['step_days']} < horizon {t['horizon_days']}")


def test_tier_config_builds_backtest_config():
    cfg = tier_config("position", ["VCB", "FPT"])
    assert cfg.horizon_days == 20 and cfg.step_days >= 20
    assert cfg.lookback_days > 365               # horizon dài cần lookback dài
    assert cfg.universe == ["VCB", "FPT"]


def test_unknown_tier_raises_not_guesses():
    with pytest.raises(ValueError):
        tier_config("swing", ["VCB"])


# ── 4. Brief gating theo từng chiến lược ────────────────────────────────────

def _fake_memory_two_tiers(monkeypatch):
    """Short (id=1) TRƯỢT kiểm định; position (id=2) ĐẠT. Mỗi tier một rec."""
    import vnstock_brief as vb
    m = types.ModuleType("vnstock_memory")
    now = datetime.now().isoformat()
    m.open_recommendations = lambda: [
        {"ticker": "GAS", "action": "buy", "entry_price": 80.0, "take_profit": 82.4,
         "cut_loss": 77.6, "horizon_days": 5, "created_at": now, "strategy_id": 1},
        {"ticker": "FPT", "action": "buy", "entry_price": 140.0, "take_profit": 155.0,
         "cut_loss": 132.0, "horizon_days": 20, "created_at": now, "strategy_id": 2},
    ]
    m.get_active_family = lambda *a, **k: {"id": 1}
    _vals = {1: {"passed": False, "p_value_sharpe": 0.974, "reasons": ["p cao"]},
             2: {"passed": True, "p_value_sharpe": 0.02, "reasons": []}}
    m.latest_backtest = lambda sid: {"metrics_json": json.dumps({"validation": _vals[sid]})}
    monkeypatch.setitem(sys.modules, "vnstock_memory", m)
    return vb


def test_position_recs_survive_when_short_tier_fails(monkeypatch):
    """CỐT LÕI của gating theo chiến lược: tầng 5 phiên trượt (p=0.974) nhưng
    tầng vị thế đạt — rec vị thế PHẢI ra, rec 5 phiên PHẢI ẩn."""
    vb = _fake_memory_two_tiers(monkeypatch)
    ctx = {}
    block = vb._recommendation_block(ctx)
    assert "FPT" in block                        # tier đạt → phát
    assert "GAS" not in block                    # tier trượt → ẩn
    assert ctx["strategy_recs_in_prompt"] is True
    assert "đã bị ẩn" in block                   # nói ra, không ẩn âm thầm


def test_position_rec_carries_its_horizon_label(monkeypatch):
    """Nhãn khung thời gian ghi RÕ — bài học "Giá 1T %": người đọc phải biết
    setup này giữ ~20 phiên, không phải 5."""
    vb = _fake_memory_two_tiers(monkeypatch)
    block = vb._recommendation_block({})
    assert "[vị thế ~20 phiên]" in block


def test_all_tiers_failed_gives_the_sentinel(monkeypatch):
    vb = _fake_memory_two_tiers(monkeypatch)
    import vnstock_memory as m
    m.latest_backtest = lambda sid: {"metrics_json": json.dumps(
        {"validation": {"passed": False, "p_value_sharpe": 0.9, "reasons": []}})}
    ctx = {}
    block = vb._recommendation_block(ctx)
    assert "KHÔNG CÓ khuyến nghị" in block
    assert "FPT" not in block and "GAS" not in block
    assert ctx["strategy_recs_in_prompt"] is False


def test_rec_without_strategy_id_uses_active_short_validation(monkeypatch):
    """Rec di sản (trước khi có strategy_id) → xử theo active short — đúng
    hành vi cũ, không đổi nghĩa dữ liệu cũ."""
    vb = _fake_memory_two_tiers(monkeypatch)
    import vnstock_memory as m
    now = datetime.now().isoformat()
    m.open_recommendations = lambda: [
        {"ticker": "HPG", "action": "buy", "entry_price": 25.0, "take_profit": 26.0,
         "cut_loss": 24.0, "horizon_days": 5, "created_at": now}]   # không sid
    block = vb._recommendation_block({})
    assert "KHÔNG CÓ khuyến nghị" in block       # active short đang trượt


# ── Hint đo-được cho prompt sinh chiến lược ─────────────────────────────────

def test_reachability_hint_reads_the_measurement(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    meta = tmp_path / "data_warehouse" / "_meta"
    meta.mkdir(parents=True)
    (meta / "reachability.json").write_text(json.dumps({
        "generated_at": "2026-08-13T21:00:00", "tickers_measured": 30,
        "summary": {"20": {"mfe_atr": {"p60": 2.89},
                           "tp_reach_share": {"2.5": 0.46}}},
    }), encoding="utf-8")
    from vnstock_strategy import _reachability_hint
    hint = _reachability_hint(20)
    assert "2.89×ATR" in hint and "46%" in hint
    assert "tp_atr_mult quanh 2.9" in hint


def test_reachability_hint_silent_without_measurement(tmp_path, monkeypatch):
    """Chưa đo thì KHÔNG bịa neo — prompt như cũ, không phải neo số 0."""
    monkeypatch.chdir(tmp_path)
    from vnstock_strategy import _reachability_hint
    assert _reachability_hint(20) == ""


# ── Mọi cổng adopt/promote đều phải có SÀN SỐ LỆNH ──────────────────────────

@pytest.mark.parametrize("path", ["vnstock_strategy.py", "vnstock_genetic.py"])
def test_every_adoption_gate_has_a_trade_floor(path):
    """Lộ 13/08 khi chạy thật: cổng TUNE thiếu sàn n_trades mà cold-start và
    revise đều có — tune thi đấu theo expectancy, và CO MẪU (67 lệnh → 19) là
    cách rẻ nhất để thổi expectancy. Lưới: mọi biểu thức gọi `_validation_ok`
    phải kèm `MIN_TRADES_TO_VALIDATE` trong CÙNG điều kiện — thêm cổng adopt
    mới mà quên sàn là đỏ ngay."""
    import ast as _ast
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
    tree = _ast.parse(src)
    bad = []
    for node in _ast.walk(tree):
        expr = None
        if isinstance(node, _ast.If):
            expr = node.test
        elif isinstance(node, _ast.Assign):
            expr = node.value
        if expr is None:
            continue
        text = _ast.unparse(expr)
        if "_validation_ok(" not in text:
            continue
        # Sàn hợp lệ: hằng số chung HOẶC sàn config-aware của chính run
        # (genetic dùng `min_trades` — lite hạ sàn có chủ đích cho smoke test).
        if "MIN_TRADES_TO_VALIDATE" not in text and "min_trades" not in text:
            bad.append(f"{path}:{node.lineno}: {text[:80]}")
    assert not bad, ("Cổng adopt gọi _validation_ok mà KHÔNG có sàn n_trades:\n  "
                     + "\n  ".join(bad))

"""Lệnh mở XUYÊN QUA ngày GDKHQ — không được chấm trên mốc chưa quy đổi.

Ca thật 05–06/10: GMD đang mở BUY @78, thưởng 50% GDKHQ 07/10 ⇒ giá tham chiếu
≈ 52. `reconcile_recommendations` so entry/TP/SL trong sổ (cơ sở CŨ) với bar
trong kho, nên:
  * bar thô ~52 lọt vào kho ⇒ chấm "sl" ngay đêm 07/10;
  * hoặc kho đứng im (cửa gác lệch cơ sở chặn) tới khi rebase tay ⇒ mọi bar từ
    ngày mở lệnh bị chia 1.5 ⇒ chấm "sl" ở bar đầu tiên.
Đóng lệnh là VĨNH VIỄN và kết quả chảy vào kiểm định chiến lược.

Luật (user chốt 06/10, "A trước, B sau"):
  A. Có sự kiện đổi giá ĐÁNG KỂ trong (ngày mở, hôm nay] mà kho CHƯA rebase ⇒
     chỉ chấm các bar TRƯỚC ngày GDKHQ; không chạm thì TREO. Treo quá hạn +
     grace ⇒ đóng trung tính `corp_action` (không giá, không vào thống kê).
  B. Kho ĐÃ rebase (close tại NEO cơ sở lệch khỏi lúc chụp) ⇒ nhân entry/TP/SL
     với đúng hệ số đo được rồi chấm như thường; giá thoát quy về cơ sở cũ để
     pnl tính đúng trên entry gốc trong sổ. Không ghi đè sổ ⇒ `--restore` bản
     sao lưu thì hệ số tự về 1 và lệnh tự quay lại trạng thái treo.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

import vnstock_events as ev

_BONUS = "Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%"


def _weekday_back(n_days: int) -> date:
    d = date.today() - timedelta(days=n_days)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _bdays_after(d: date, n: int) -> date:
    return pd.bdate_range(d + timedelta(days=1), periods=n)[-1].date()


class _FakeMem:
    def __init__(self, recs, anchors=None):
        self.recs, self.closed = recs, []
        self.anchors = dict(anchors or {})
        self.anchor_writes = 0

    def open_recommendations(self):
        done = {c["id"] for c in self.closed}
        return [r for r in self.recs if r["id"] not in done]

    def close_recommendation(self, rid, exit_price=None, hit_target=None, notes=""):
        self.closed.append({"id": rid, "exit": exit_price, "hit": hit_target,
                            "notes": notes})

    def basis_anchor(self, rid):
        return self.anchors.get(rid)

    def set_basis_anchor(self, rid, bar_date, close):
        self.anchor_writes += 1
        self.anchors.setdefault(rid, {"bar_date": bar_date, "close": float(close)})


def _hist(days, close_fn, low_fn=None, high_fn=None):
    rows = []
    for d in days:
        c = close_fn(d)
        rows.append({"time": pd.Timestamp(d), "open": c,
                     "high": high_fn(d) if high_fn else c + 0.5,
                     "low": low_fn(d) if low_fn else c - 0.5,
                     "close": c, "volume": 1_000})
    return pd.DataFrame(rows)


def _events(*rows):
    """Ghi sự kiện vào sổ đã-qua (conftest đã chuyển `ev._META` sang tmp)."""
    ev._record_ledger([{"ticker": t, "ex_date": d.isoformat(), "title": ti}
                       for t, d, ti in rows])


@pytest.fixture
def gmd(monkeypatch):
    """Lệnh GMD BUY @78 / TP 85 / SL 74, tầng 20 phiên, mở 14 ngày trước."""
    import vnstock_strategy as vs
    import vnstock_train as vt

    def _make(*, age_days=14, anchors="auto", hist_fn=None, rec_over=None):
        d0 = _weekday_back(age_days)
        created = datetime.combine(d0, time(18, 0))
        rec = {"id": 7, "ticker": "GMD", "created_at": created.isoformat(),
               "entry_price": 78.0, "take_profit": 85.0, "cut_loss": 74.0,
               "horizon_days": 20, **(rec_over or {})}
        anc = ({7: {"bar_date": d0.isoformat(), "close": 78.0}}
               if anchors == "auto" else anchors)
        mem = _FakeMem([rec], anc)
        days = list(pd.bdate_range(d0, date.today()).date)
        h = hist_fn(d0, days)
        monkeypatch.setattr(vt, "mem", mem)
        monkeypatch.setattr(vs, "_load_history", lambda t, days=0: h)
        monkeypatch.setattr(vs, "check_strategy_decay", lambda: None, raising=False)
        return mem, d0

    return _make


def _run():
    import vnstock_train as vt
    return vt.reconcile_recommendations(verbose=False)


# ── A: kho CHƯA rebase ⇒ chỉ chấm bar trước GDKHQ, rồi treo ─────────────────

def test_raw_bar_after_exdate_is_not_graded_as_a_stop_loss(gmd):
    """Ca đau nhất: bar thô ~52 lọt vào kho. Bản cũ chấm "sl" ngay đêm đó."""
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist(days, lambda d: 78.0 if d < ex else 52.0)
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    s = _run()
    assert mem.closed == []
    assert s["held"] == 1


def test_kill_switch_restores_the_old_grading(gmd, monkeypatch):
    monkeypatch.setenv("VNSTOCK_REC_GDKHQ_HOLD", "0")
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist(days, lambda d: 78.0 if d < ex else 52.0)
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    _run()
    assert [c["hit"] for c in mem.closed] == ["sl"]


def test_frozen_warehouse_is_held_not_graded(gmd):
    """Cửa gác lệch cơ sở chặn nối ⇒ kho đứng im trước GDKHQ: treo."""
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist([d for d in days if d < ex], lambda d: 78.0)
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    assert _run()["held"] == 1 and mem.closed == []


def test_a_hit_before_the_exdate_is_still_a_real_outcome(gmd):
    """Bar TRƯỚC GDKHQ cùng cơ sở với entry ⇒ chạm SL thật vẫn phải đóng."""
    def h(d0, days):
        ex, bad = _bdays_after(d0, 5), _bdays_after(d0, 2)
        return _hist(days, lambda d: 78.0 if d < ex else 52.0,
                     low_fn=lambda d: 73.0 if d == bad else (77.5 if d < ex else 51.5))
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    _run()
    assert [(c["hit"], c["exit"]) for c in mem.closed] == [("sl", 74.0)]


def test_held_past_horizon_and_grace_closes_neutral(gmd):
    """Không ai rebase ⇒ treo tới quá hạn + grace rồi đóng KHÔNG GIÁ."""
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist(days, lambda d: 78.0 if d < ex else 52.0)
    mem, d0 = gmd(age_days=45, hist_fn=h)
    ex = _bdays_after(d0, 5)
    _events(("GMD", ex, _BONUS))
    s = _run()
    assert [(c["hit"], c["exit"]) for c in mem.closed] == [("corp_action", None)]
    assert ex.isoformat() in mem.closed[0]["notes"]
    assert s["corp_action"] == 1


def test_no_anchor_means_no_grading_at_all_once_an_event_passed(gmd):
    """Không có neo thì không biết bar trước GDKHQ đã bị rebase chưa — chấm
    chúng trên mốc cũ có thể ra SL giả. Treo."""
    def h(d0, days):
        ex, bad = _bdays_after(d0, 5), _bdays_after(d0, 2)
        return _hist(days, lambda d: 52.0,
                     low_fn=lambda d: 51.0 if d == bad else 51.5)
    mem, d0 = gmd(anchors={}, hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    assert _run()["held"] == 1 and mem.closed == []


def test_unreadable_but_price_adjusting_event_is_material(gmd):
    """Quyền mua: không quy đổi được từ tiêu đề ⇒ coi là ĐÁNG KỂ, treo."""
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist(days, lambda d: 78.0 if d < ex else 60.0)
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), "Quyền mua cổ phiếu, tỷ lệ 5:1"))
    assert _run()["held"] == 1 and mem.closed == []


# ── Sự kiện KHÔNG đáng kể / ngoài cửa sổ ⇒ chấm như thường ─────────────────

def _crash_after_ex(d0, days):
    ex = _bdays_after(d0, 5)
    return _hist(days, lambda d: 78.0 if d < ex else 77.3,
                 low_fn=lambda d: 73.0 if d == _bdays_after(d0, 6) else 76.8)


def test_small_cash_dividend_below_basis_tolerance_is_graded_normally(gmd):
    """500đ trên 78.000đ = 0,64% < ngưỡng cửa gác 1,2%: chính cửa gác cũng coi
    là CÙNG cơ sở, nên chấm như thường — SL thật vẫn đóng."""
    mem, d0 = gmd(hist_fn=_crash_after_ex)
    _events(("GMD", _bdays_after(d0, 5),
             "Trả cổ tức bằng tiền mặt - Đợt 1 2026 - 500 VND"))
    _run()
    assert [c["hit"] for c in mem.closed] == ["sl"]


def test_meeting_events_do_not_adjust_prices(gmd):
    mem, d0 = gmd(hist_fn=_crash_after_ex)
    _events(("GMD", _bdays_after(d0, 5), "Đại hội cổ đông thường niên 2026"))
    _run()
    assert [c["hit"] for c in mem.closed] == ["sl"]


def test_event_before_the_rec_was_opened_is_ignored(gmd):
    mem, d0 = gmd(hist_fn=_crash_after_ex)
    _events(("GMD", d0 - timedelta(days=3), _BONUS))
    _run()
    assert [c["hit"] for c in mem.closed] == ["sl"]


# ── B: kho ĐÃ rebase ⇒ quy đổi mốc theo hệ số đo được ─────────────────────

def _rebased(d0, days, *, tp_day=None):
    """Kho sau rebase: MỌI bar (kể cả ngày mở lệnh) ở cơ sở mới = cũ / 1.5."""
    return _hist(days, lambda d: 52.0,
                 high_fn=lambda d: 57.0 if d == tp_day else 52.5)


def test_rebased_warehouse_rescales_levels_instead_of_a_false_stop(gmd):
    mem, d0 = gmd(hist_fn=_rebased)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    s = _run()
    assert mem.closed == []                 # SL 74 ⇒ 49.33: bar 51.5 không chạm
    assert s["held"] == 0                   # đã quy đổi được ⇒ chấm, không treo


def test_rebased_tp_is_recorded_in_the_original_basis(gmd):
    """TP 85 × (52/78) = 56.67; bar high 57 chạm ⇒ thoát 85 trên cơ sở cũ."""
    mem, d0 = gmd(hist_fn=lambda d0, days: _rebased(d0, days,
                                                    tp_day=_bdays_after(d0, 7)))
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    _run()
    assert [c["hit"] for c in mem.closed] == ["tp"]
    assert mem.closed[0]["exit"] == pytest.approx(85.0)


def test_rebase_is_detected_from_the_anchor_even_without_a_known_event(gmd):
    """Sự kiện lọt khỏi sổ (mã ngoài universe) nhưng kho đã bị rebase cả chuỗi:
    neo vẫn thấy hệ số ⇒ quy đổi, không chấm SL giả."""
    mem, d0 = gmd(hist_fn=_rebased)
    _run()
    assert mem.closed == []


def test_two_exdates_in_one_window_are_held_even_if_rebased(gmd):
    """Một hệ số không đại diện được cho hai lần đổi cơ sở — không đoán."""
    mem, d0 = gmd(hist_fn=_rebased)
    _events(("GMD", _bdays_after(d0, 3), _BONUS),
            ("GMD", _bdays_after(d0, 6), "Trả cổ tức bằng cổ phiếu, tỷ lệ 10:1"))
    assert _run()["held"] == 1 and mem.closed == []


# ── Neo cơ sở ──────────────────────────────────────────────────────────────

def test_anchor_is_captured_in_a_clean_state(gmd):
    mem, d0 = gmd(anchors={}, hist_fn=lambda d0, days: _hist(days, lambda d: 78.0))
    _run()
    assert mem.anchors[7] == {"bar_date": d0.isoformat(), "close": 78.0}


def test_anchor_is_not_captured_once_an_event_passed(gmd):
    """Sau GDKHQ kho có thể đã rebase ⇒ chụp lúc đó là chụp nhầm cơ sở mới."""
    mem, d0 = gmd(anchors={}, hist_fn=lambda d0, days: _hist(days, lambda d: 78.0))
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    _run()
    assert mem.anchor_writes == 0


def test_emit_captures_the_anchor_at_creation(monkeypatch):
    """Chụp ngay lúc tạo lệnh: lệnh mở tối 06/10, GDKHQ 07/10 thì lượt chấm
    kế tiếp đã thấy sự kiện — không còn trạng thái sạch để chụp."""
    import vnstock_strategy as vs
    anchors = {}

    class _Mem:
        best_strategies = staticmethod(lambda limit=3: [
            {"id": 1, "name": "s", "code": "x", "tier": "position",
             "params_json": "{}"}])
        supersede_open_recommendations = staticmethod(lambda t: 0)
        save_recommendation = staticmethod(lambda **k: 99)

        @staticmethod
        def set_basis_anchor(rid, bar_date, close):
            anchors[rid] = (bar_date, close)

    class _Exec:
        @staticmethod
        def run(code, window, params):
            return {"action": "buy", "entry": 78.0, "tp": 85.0, "sl": 74.0,
                    "confidence": 0.7}

    h = _hist(list(pd.bdate_range(end=date(2026, 10, 6), periods=80).date),
              lambda d: 78.0).assign(volume=500_000)
    monkeypatch.setattr(vs, "mem", _Mem)
    monkeypatch.setattr(vs, "EXECUTOR", _Exec)
    monkeypatch.setattr(vs, "_load_history", lambda t, days=0: h)
    recs = vs.emit_recommendations(["GMD"], max_recs=1)
    assert recs[0]["id"] == 99
    assert anchors == {99: ("2026-10-06", 78.0)}


def test_basis_anchor_first_capture_wins(tmp_path, monkeypatch):
    import vnstock_memory as vm
    monkeypatch.setattr(vm, "DB_PATH", tmp_path / "m.db")
    vm.init_db()
    assert vm.basis_anchor(1) is None
    vm.set_basis_anchor(1, "2026-09-24", 78.0)
    vm.set_basis_anchor(1, "2026-10-08", 52.0)
    assert vm.basis_anchor(1) == {"bar_date": "2026-09-24", "close": 78.0}


# ── Sổ sự kiện đã qua (cache xoá sự kiện 2 ngày sau GDKHQ) ─────────────────

def _cache(path, rows):
    pd.DataFrame([{"category": "x", **r} for r in rows]).to_parquet(path, index=False)


def test_refresh_moves_aged_events_into_the_ledger(tmp_path, monkeypatch):
    """Sự kiện ĐÃ QUA bị cắt khỏi cache phải còn trong sổ; sự kiện tương lai
    biến mất sau một lần fetch THÀNH CÔNG là bị HUỶ — không ghi sổ."""
    p = tmp_path / "upcoming_events.parquet"
    past = date.today() - timedelta(days=10)
    _cache(p, [{"ticker": "GMD", "ex_date": past.isoformat(), "title": _BONUS},
               {"ticker": "GMD", "ex_date": "2099-01-05", "title": "huỷ"}])
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", p)
    monkeypatch.setattr(ev, "_fetch_vci_events", lambda t: pd.DataFrame())
    ev.refresh_upcoming(tickers=["GMD"])
    got = ev.price_events("GMD", past - timedelta(days=1), date(2100, 1, 1))
    assert [(e["ex_date"], e["title"]) for e in got] == [(past, _BONUS)]


def test_price_events_reads_cache_and_drops_meeting_events(tmp_path):
    d = date.today()
    _cache(ev._META / "upcoming_events.parquet",
           [{"ticker": "GMD", "ex_date": d.isoformat(), "title": _BONUS},
            {"ticker": "GMD", "ex_date": d.isoformat(),
             "title": "Đại hội cổ đông thường niên"},
            {"ticker": "MWG", "ex_date": d.isoformat(), "title": "Trả cổ tức"}])
    got = ev.price_events("gmd", d - timedelta(days=1), d)
    assert [e["title"] for e in got] == [_BONUS]
    assert ev.price_events("GMD", d, d + timedelta(days=5)) == []   # after là mở


def test_ledger_dedups_and_prunes_very_old_events():
    old = date.today() - timedelta(days=ev.LEDGER_KEEP_DAYS + 5)
    row = {"ticker": "GMD", "ex_date": "2026-10-07", "title": _BONUS}
    ev._record_ledger([row, dict(row)])
    ev._record_ledger([row, {"ticker": "PET", "ex_date": old.isoformat(),
                             "title": _BONUS}])
    data = json.loads((ev._META / "corp_actions_ledger.json").read_text("utf-8"))
    assert [(e["ticker"], e["ex_date"]) for e in data["events"]] == [
        ("GMD", "2026-10-07")]


# ── Universe sự kiện phải phủ mã đang có lệnh mở ─────────────────────────────

def test_events_universe_adds_extra_tickers(tmp_path):
    from vnstock_brief import VN30_TICKERS, _events_universe
    uni = _events_universe(extra_tickers=["hda", "AAA"],
                           overview_path=tmp_path / "nope.json")
    assert set(uni) == set(VN30_TICKERS) | {"HDA", "AAA"}
    assert set(_events_universe(overview_path=tmp_path / "nope.json")) == set(VN30_TICKERS)


def test_maybe_refresh_events_covers_open_rec_tickers(monkeypatch, tmp_path):
    import sys
    import types

    import vnstock_brief as vb
    import vnstock_memory as vm
    captured = {}
    fake = types.ModuleType("vnstock_events")
    fake.UPCOMING_EVENTS_PATH = tmp_path / "nope.parquet"
    fake.refresh_upcoming = lambda *a, **k: captured.setdefault(
        "tickers", k.get("tickers")) or []
    monkeypatch.setitem(sys.modules, "vnstock_events", fake)
    db = tmp_path / "m.db"
    db.touch()
    monkeypatch.setattr(vm, "DB_PATH", db)
    monkeypatch.setattr(vm, "open_recommendations",
                        lambda: [{"ticker": "HDA"}, {"ticker": "DRI"}])
    vb._maybe_refresh_events()
    assert {"HDA", "DRI"} <= set(captured["tickers"])


def test_open_rec_tickers_never_creates_the_db(monkeypatch, tmp_path):
    import vnstock_brief as vb
    import vnstock_memory as vm
    db = tmp_path / "_meta" / "brief_memory.db"
    monkeypatch.setattr(vm, "DB_PATH", db)
    assert vb._open_rec_tickers() == []
    assert not db.exists() and not db.parent.exists()


def test_telegram_closed_today_does_not_print_zero_pnl_for_unpriced_closes(monkeypatch):
    import vnstock_memory as vm
    import vnstock_telegram as tg
    today = datetime.now().isoformat(timespec="seconds")
    monkeypatch.setattr(vm, "recent_closed_recommendations", lambda limit=20: [
        {"ticker": "GMD", "closed_at": today, "hit_target": "corp_action",
         "pnl_pct": None},
        {"ticker": "FPT", "closed_at": today, "hit_target": "tp", "pnl_pct": 4.2}])
    out = tg._closed_today_block()
    assert "⏸ <b>GMD</b>: không chấm (corp_action)" in out
    assert "<b>FPT</b>: +4.20% (tp)" in out


# ── Mốc HIỂN THỊ (08/10): brief 💡 + footer in "GMD BUY entry=77.6" khi giá 54,2 ──

@pytest.fixture
def display(monkeypatch):
    """Bỏ lưới conftest (lịch sử rỗng) — dùng `_load_history` mà fixture gmd giả."""
    import vnstock_strategy as vs
    import vnstock_train as vt
    monkeypatch.setattr(vt, "_display_history",
                        lambda t, days: vs._load_history(t, days=days))
    return vt


def _all_rebased(d0, days):
    return _hist(days, lambda d: 52.0)          # cả chuỗi đã chia 1.5 (rebase)


def test_display_levels_rebased_are_converted_with_note(gmd, display):
    mem, d0 = gmd(hist_fn=_all_rebased)
    ex = _bdays_after(d0, 5)
    _events(("GMD", ex, _BONUS))
    lv = display.rec_display_levels(mem.recs[0])
    assert lv["mode"] == "rebased" and lv["factor"] == pytest.approx(52 / 78)
    assert (lv["entry"], lv["tp"], lv["sl"]) == pytest.approx((52.0, 85 * 52 / 78, 74 * 52 / 78))
    assert f"GDKHQ {ex.strftime('%d/%m')}" in lv["note"] and "mốc gốc @78" in lv["note"]


def test_display_levels_unrebased_keep_raw_and_warn(gmd, display):
    def h(d0, days):
        ex = _bdays_after(d0, 5)
        return _hist(days, lambda d: 78.0 if d < ex else 52.0)
    mem, d0 = gmd(hist_fn=h)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    lv = display.rec_display_levels(mem.recs[0])
    assert lv["mode"] == "pre_event" and lv["entry"] == 78.0
    assert lv["note"].startswith("⚠️ GDKHQ") and "CHƯA quy đổi" in lv["note"]


def test_display_never_writes_an_anchor(gmd, display):
    mem, _ = gmd(anchors={}, hist_fn=lambda d0, days: _hist(days, lambda d: 78.0))
    lv = display.rec_display_levels(mem.recs[0])
    assert lv["mode"] == "normal" and lv["note"] is None
    assert mem.anchor_writes == 0                  # phép chấm mới được chụp neo


def test_display_levels_fall_back_to_raw(gmd, display, monkeypatch):
    mem, d0 = gmd(hist_fn=_all_rebased)
    _events(("GMD", _bdays_after(d0, 5), _BONUS))
    rec = mem.recs[0]
    assert display.rec_display_levels({**rec, "id": None})["entry"] == 78.0
    monkeypatch.setenv("VNSTOCK_REC_GDKHQ_HOLD", "0")
    assert display.rec_display_levels(rec)["note"] is None


def test_brief_block_and_telegram_footer_print_converted_levels(gmd, display, monkeypatch):
    import vnstock_brief as vb
    import vnstock_telegram as tg
    mem, d0 = gmd(hist_fn=_all_rebased, age_days=6, rec_over={"action": "buy"})
    ex = _bdays_after(d0, 3)
    _events(("GMD", ex, _BONUS))
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: mem.recs)
    monkeypatch.setattr("vnstock_memory.get_active_family", lambda *a, **k: None)
    block = vb._recommendation_block({})
    assert "GMD BUY" in block and "entry=52 " in block and "entry=78" not in block
    assert "đã quy đổi theo GDKHQ" in block and "mốc gốc @78" in block
    foot = tg._open_recs_block()
    assert "@52" in foot and "@78 " not in foot and "mốc gốc @78" in foot
    # TP/SL % không đổi khi cả ba mốc cùng nhân một hệ số
    assert "TP +9.0%" in foot and "SL -5.1%" in foot

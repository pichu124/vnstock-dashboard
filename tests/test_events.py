"""Tests for vnstock_events (upcoming corp-action calendar) + its brief block."""

from __future__ import annotations

from datetime import date

import pandas as pd

import vnstock_events as ev
from vnstock_brief import _upcoming_events_block, _upcoming_window_start, build_prompt


def _write(tmp_path):
    p = tmp_path / "upcoming_events.parquet"
    pd.DataFrame([
        {"ticker": "VIC", "ex_date": "2026-06-12",
         "title": "Trả cổ tức bằng tiền mặt - 1.500đ", "category": "DIVIDEND"},
        {"ticker": "MWG", "ex_date": "2026-06-30",
         "title": "Chia tách cổ phiếu 2:1", "category": "ISSUE"},        # >14d out
        {"ticker": "FPT", "ex_date": "2026-06-01",
         "title": "Cổ tức 1.000đ", "category": "DIVIDEND"},             # past
        {"ticker": "GEX", "ex_date": "2026-06-13",
         "title": "ĐHCĐ thường niên 2026", "category": "MEETING"},
    ]).to_parquet(p, index=False)
    return p


def test_load_upcoming_filters_window(tmp_path):
    out = ev.load_upcoming(within_days=14, path=_write(tmp_path),
                           today=date(2026, 6, 10))
    names = [e["ticker"] for e in out]
    assert names == ["VIC", "GEX"]   # in [10/06, 24/06], sorted; MWG/FPT excluded


def test_load_upcoming_ticker_filter(tmp_path):
    out = ev.load_upcoming(within_days=14, path=_write(tmp_path),
                           today=date(2026, 6, 10), tickers={"VIC"})
    assert [e["ticker"] for e in out] == ["VIC"]


def test_close_brief_window_starts_the_day_after_the_closed_session():
    """Close 08/09/2026: DIG GDKHQ 2026-09-08 nằm trong "Sự kiện sắp tới" của
    chính phiên 08/09, kèm câu "giá tự điều chỉnh ngày GDKHQ" — phiên đã đóng,
    điều chỉnh XONG rồi. Brief chiều phải mở cửa sổ từ ngày KẾ TIẾP; brief
    sáng giữ mặc định (GDKHQ hôm nay còn ở phía trước, đáng nhắc)."""
    assert _upcoming_window_start("morning", "2026-09-08") is None
    assert _upcoming_window_start("afternoon", "2026-09-08") == date(2026, 9, 9)
    assert _upcoming_window_start("allocation", "2026-09-08") == date(2026, 9, 9)
    assert _upcoming_window_start("afternoon", "rác") is None      # không nổ, về mặc định


def test_close_brief_drops_todays_exdate_but_morning_keeps_it(tmp_path):
    p = tmp_path / "upcoming_events.parquet"
    pd.DataFrame([
        {"ticker": "DIG", "ex_date": "2026-09-08",
         "title": "Trả Cổ tức bằng Cổ phiếu tỉ lệ 6.0%", "category": "ISSUE"},
        {"ticker": "VIB", "ex_date": "2026-09-10",
         "title": "Cổ phiếu thưởng tỉ lệ 9.5%", "category": "ISSUE"},
    ]).to_parquet(p, index=False)
    close = ev.load_upcoming(within_days=14, path=p,
                             today=_upcoming_window_start("afternoon", "2026-09-08"))
    assert [e["ticker"] for e in close] == ["VIB"]
    morning = ev.load_upcoming(within_days=14, path=p, today=date(2026, 9, 8))
    assert [e["ticker"] for e in morning] == ["DIG", "VIB"]


def test_collect_context_wires_the_window_start_into_load_upcoming():
    """Lưới nối dây (kiểu test_brief_split): helper đúng mà chỗ gọi quên truyền
    `today=` thì brief chiều vẫn liệt kê GDKHQ hôm nay y như cũ."""
    import inspect
    import vnstock_brief as vb
    src = inspect.getsource(vb.collect_context)
    assert "today=_upcoming_window_start(brief_type, _data_date_str)" in src


def test_load_upcoming_missing_file(tmp_path):
    assert ev.load_upcoming(path=tmp_path / "nope.parquet") == []


def test_extract_upcoming_vci_schema():
    # Mirrors the real VCI company.events() shape: corp action gated on
    # exright_date; insider-trading rows skipped.
    df = pd.DataFrame([
        {"event_title_vi": "Nguyễn X - Đăng kí Mua ACB", "category": "MAJOR_SHAREHOLDER_TRADING",
         "exright_date": None, "start_date": "2026-06-12", "display_date1": "2026-06-12",
         "record_date": None},                                          # insider → skip
        {"event_title_vi": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 700 VND",
         "category": "DIVIDEND", "exright_date": "2026-06-15",
         "record_date": "2026-06-16", "start_date": None, "display_date1": "2026-06-15"},
        {"event_title_vi": "Cổ tức năm 2024", "category": "DIVIDEND",
         "exright_date": "2025-06-15", "record_date": None,
         "start_date": None, "display_date1": "2025-06-15"},            # past GDKHQ → skip
        {"event_title_vi": "ĐHCĐ 2026", "category": "MEETING",
         "exright_date": None, "start_date": "2026-06-20",
         "record_date": None, "display_date1": "2026-06-20"},           # meeting → start_date
    ])
    out = ev._extract_upcoming(df, "ACB", date(2026, 6, 10))
    titles = {e["title"] for e in out}
    assert any("700 VND" in t for t in titles)        # upcoming dividend kept
    assert any("ĐHCĐ 2026" in t for t in titles)      # meeting kept via start_date
    assert not any("Đăng kí Mua" in t for t in titles)  # insider skipped
    assert not any("năm 2024" in t for t in titles)     # past GDKHQ skipped
    div = next(e for e in out if "700 VND" in e["title"])
    assert div["ex_date"] == "2026-06-15"             # uses exright_date


def test_upcoming_events_block_renders():
    block = _upcoming_events_block([
        {"ticker": "VIC", "ex_date": "2026-06-12",
         "title": "Trả cổ tức bằng tiền mặt - 1.500đ", "category": "DIVIDEND"},
        {"ticker": "GEX", "ex_date": "2026-06-13",
         "title": "ĐHCĐ thường niên 2026", "category": "MEETING"},
    ])
    assert "Sự kiện sắp tới" in block
    assert "VIC: Trả cổ tức bằng tiền mặt - 1.500đ — ngày 2026-06-12" in block
    assert "GEX: ĐHCĐ thường niên 2026 — ngày 2026-06-13" in block


def test_upcoming_events_block_empty():
    assert _upcoming_events_block([]) == ""


def test_build_prompt_includes_upcoming_events():
    ctx = {"date": "2026-06-10", "time": "15:00",
           "upcoming_events": [
               {"ticker": "VIC", "ex_date": "2026-06-12",
                "title": "Trả cổ tức tiền mặt", "category": "DIVIDEND"}]}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Sự kiện sắp tới" in prompt and "VIC" in prompt


def test_maybe_refresh_events_noop_when_cache_is_today(monkeypatch, tmp_path):
    import sys
    import types
    import vnstock_brief as vb
    p = tmp_path / "upcoming_events.parquet"
    p.write_text("x")                       # mtime = now → "today"
    called = {}
    fake = types.ModuleType("vnstock_events")
    fake.UPCOMING_EVENTS_PATH = p
    fake.refresh_upcoming = lambda *a, **k: called.setdefault("ran", True) or []
    monkeypatch.setitem(sys.modules, "vnstock_events", fake)
    assert vb._maybe_refresh_events() == 0
    assert "ran" not in called             # fresh → not refetched


def test_maybe_refresh_events_runs_when_missing(monkeypatch, tmp_path):
    import sys
    import types
    import vnstock_brief as vb
    fake = types.ModuleType("vnstock_events")
    fake.UPCOMING_EVENTS_PATH = tmp_path / "nope.parquet"   # missing
    fake.refresh_upcoming = lambda *a, **k: [{"ticker": "ACB"}, {"ticker": "SAB"}]
    monkeypatch.setitem(sys.modules, "vnstock_events", fake)
    assert vb._maybe_refresh_events() == 2


def test_maybe_refresh_events_disabled_by_env(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_EVENTS", "0")
    assert vb._maybe_refresh_events() == 0


def test_events_universe_includes_top_liquid_movers(tmp_path):
    # Auto-refresh universe = VN30 ∪ top movers by GTGD (capped) — previously
    # VN30-only, so watchlist-able mid-caps (e.g. CII) never got their GDKHQ
    # events without a manual --tickers run.
    import json as _json
    from vnstock_brief import VN30_TICKERS, _events_universe
    p = tmp_path / "market_overview.json"
    p.write_text(_json.dumps({"tickers": [
        {"Mã": "CII", "Giá 1T %": 1.0, "Ngành": "Hạ tầng", "last": 17.3,
         "GTGD TB (tỷ)": 120.0},
        {"Mã": "GEX", "Giá 1T %": 2.0, "Ngành": "CN", "last": 30.0,
         "GTGD TB (tỷ)": 300.0},
        {"Mã": "XYZ", "Giá 1T %": 3.0, "Ngành": "X", "last": 8.0,
         "GTGD TB (tỷ)": 2.0},                      # illiquid → excluded
    ]}), encoding="utf-8")
    uni = _events_universe(max_movers=1, overview_path=p)
    assert set(VN30_TICKERS) <= set(uni)
    assert "GEX" in uni                  # top mover by GTGD within the cap
    assert "CII" not in uni              # beyond max_movers=1
    assert "XYZ" not in uni              # below the liquidity floor
    # missing overview → VN30 only (no crash)
    assert set(_events_universe(overview_path=tmp_path / "nope.json")) == set(VN30_TICKERS)


def test_maybe_refresh_events_passes_broadened_universe(monkeypatch, tmp_path):
    import sys
    import types
    import vnstock_brief as vb
    captured = {}
    fake = types.ModuleType("vnstock_events")
    fake.UPCOMING_EVENTS_PATH = tmp_path / "nope.parquet"   # missing → refresh
    fake.refresh_upcoming = lambda *a, **k: captured.setdefault(
        "tickers", k.get("tickers")) or []
    monkeypatch.setitem(sys.modules, "vnstock_events", fake)
    vb._maybe_refresh_events()
    assert captured["tickers"]                              # universe was passed
    assert set(vb.VN30_TICKERS) <= set(captured["tickers"])


def test_refresh_keeps_prior_events_when_fetch_fails(tmp_path, monkeypatch):
    # A flaky re-fetch must NOT drop a known upcoming event (regression: ACB
    # dividend vanished between two same-day runs). ACB's fetch fails (None) →
    # its cached event is retained; SAB's fetch succeeds and refreshes.
    p = tmp_path / "upcoming_events.parquet"
    pd.DataFrame([
        {"ticker": "ACB", "ex_date": "2099-06-15",
         "title": "Trả cổ tức tiền mặt 700 VND", "category": "DIVIDEND"},
    ]).to_parquet(p, index=False)
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", p)
    monkeypatch.setattr(ev, "_fetch_vci_events",
                        lambda t: None if t == "ACB" else pd.DataFrame())
    out = ev.refresh_upcoming(tickers=["ACB", "SAB"])
    assert "ACB" in set(out["ticker"])            # kept despite failed fetch
    saved = ev.load_upcoming(within_days=99999, path=p, today=date(2026, 6, 10))
    assert any(e["ticker"] == "ACB" for e in saved)


def test_refresh_clears_event_on_successful_empty_fetch(tmp_path, monkeypatch):
    # A SUCCESSFUL fetch that returns no upcoming events (cancelled/none) must
    # clear that ticker — distinct from a failed (None) fetch which keeps it.
    p = tmp_path / "upcoming_events.parquet"
    pd.DataFrame([
        {"ticker": "ACB", "ex_date": "2099-06-15", "title": "x", "category": "DIVIDEND"},
    ]).to_parquet(p, index=False)
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", p)
    monkeypatch.setattr(ev, "_fetch_vci_events", lambda t: pd.DataFrame())  # success, empty
    out = ev.refresh_upcoming(tickers=["ACB"])
    assert out.empty


def test_enforce_upcoming_events_rewrites_llm_denial():
    # LLM wrote "Không có sự kiện đáng chú ý" while ctx HAS events (observed at
    # 13:50 — cache intact, prompt had ACB, output denied it) → the guard must
    # splice the real events back in.
    from vnstock_brief import enforce_upcoming_events
    ctx = {"upcoming_events": [
        {"ticker": "ACB", "ex_date": "2026-06-15",
         "title": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 700 VND",
         "category": "DIVIDEND"}]}
    text = "📅 Sự kiện sắp tới\nKhông có sự kiện đáng chú ý.\n💡 Đề xuất giao dịch"
    fixed = enforce_upcoming_events(text, ctx)
    assert "Không có sự kiện đáng chú ý" not in fixed
    assert "ACB: Trả cổ tức bằng tiền mặt" in fixed and "2026-06-15" in fixed
    assert "💡 Đề xuất giao dịch" in fixed          # rest of the brief untouched


def test_enforce_upcoming_events_noop_without_events_or_claim():
    from vnstock_brief import enforce_upcoming_events
    # no events in ctx → text untouched even with the claim
    t1 = "Không có sự kiện đáng chú ý."
    assert enforce_upcoming_events(t1, {}) == t1
    # events present but no section header and no denial → untouched
    ctx = {"upcoming_events": [{"ticker": "ACB", "ex_date": "2026-06-15",
                                "title": "Cổ tức", "category": "DIVIDEND"}]}
    t2 = "ACB: Cổ tức — ngày 2026-06-15"
    assert enforce_upcoming_events(t2, ctx) == t2


def test_enforce_upcoming_events_canonicalizes_partial_section():
    # 14:48/15:20 briefs listed only 1 of the 2 same-day ACB events (dropped the
    # 13% stock dividend — the more price-impactful one). The section is pure
    # data → its body is replaced with the full canonical list + GDKHQ note.
    from vnstock_brief import enforce_upcoming_events
    ctx = {"upcoming_events": [
        {"ticker": "ACB", "ex_date": "2026-06-15",
         "title": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 700 VND",
         "category": "DIVIDEND"},
        {"ticker": "ACB", "ex_date": "2026-06-15",
         "title": "Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 13.0%",
         "category": "ISSUE"}]}
    text = ("📅 Sự kiện sắp tới\n"
            "ACB trả cổ tức bằng tiền mặt vào ngày 2026-06-15.\n"
            "💡 Đề xuất giao dịch\n"
            "Không có khuyến nghị.")
    fixed = enforce_upcoming_events(text, ctx)
    assert "700 VND" in fixed and "13.0%" in fixed          # both events present
    assert "Giá tự điều chỉnh trong ngày GDKHQ" in fixed
    assert "💡 Đề xuất giao dịch" in fixed                   # next section intact
    assert "ACB trả cổ tức bằng tiền mặt vào ngày" not in fixed  # paraphrase gone


def test_templates_have_upcoming_events_output_section():
    # The events block is injected as DATA; the OUTPUT template must also have a
    # "Sự kiện sắp tới" section or the model never surfaces it (observed: block
    # data present but absent from the brief).
    for bt in ("morning", "afternoon"):
        p = build_prompt({"date": "2026-06-10", "time": "15:00"}, brief_type=bt)
        assert "## 📅 Sự kiện sắp tới" in p


# ─── Bão timeout VCI trong refresh_upcoming (22/09: 52 mã × 30s = 28′) ────────

def test_refresh_upcoming_stops_after_consecutive_failures(tmp_path, monkeypatch):
    """Đêm VCI ốm mỗi mã là một timeout 30s: 52 mã = 28′ ngay trong bước
    brief 22/09. Ba mã lỗi liền → dừng, giữ cache cũ, KHÔNG ghi đè file (mtime
    giữ nguyên để lượt sau thử lại rẻ)."""
    import pandas as pd
    import vnstock_events as ev
    p = tmp_path / "upcoming_events.parquet"
    prior = pd.DataFrame([{c: None for c in ev._COLS}]).iloc[0:0]
    prior = pd.DataFrame([{"ticker": "ACB", "ex_date": "2099-01-05", "title": "cũ",
                           **{c: None for c in ev._COLS if c not in ("ticker", "ex_date", "title")}}],
                         columns=ev._COLS)
    prior.to_parquet(p, index=False)
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", p)
    monkeypatch.setattr(ev, "_META", tmp_path)
    mtime0 = p.stat().st_mtime
    calls = []

    def _down(t):
        calls.append(t)
        return None
    monkeypatch.setattr(ev, "_fetch_vci_events", _down)
    out = ev.refresh_upcoming(tickers=[f"T{i:02d}" for i in range(52)])
    assert calls == ["T00", "T01", "T02"]          # dừng sau 3, không gõ 49 mã còn lại
    assert list(out["ticker"]) == ["ACB"]            # cache cũ còn nguyên
    assert p.stat().st_mtime == mtime0               # file không bị ghi đè


def test_refresh_upcoming_failure_streak_resets_on_success(tmp_path, monkeypatch):
    """Lỗi rải rác (mã hủy niêm yết) không phải VCI ngã: xen kẽ OK thì chạy hết."""
    import pandas as pd
    import vnstock_events as ev
    p = tmp_path / "upcoming_events.parquet"
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", p)
    monkeypatch.setattr(ev, "_META", tmp_path)
    monkeypatch.setattr(ev, "_extract_upcoming", lambda df, t, cutoff: [])
    seq = iter([None, None, pd.DataFrame(), None, None, pd.DataFrame(), None])
    calls = []

    def _flaky(t):
        calls.append(t)
        return next(seq)
    monkeypatch.setattr(ev, "_fetch_vci_events", _flaky)
    ev.refresh_upcoming(tickers=list("ABCDEFG"))
    assert calls == list("ABCDEFG")                  # chưa bao giờ 3 lỗi LIỀN → chạy hết


# ─── 30/09: ngân sách tường + backoff (thư viện tự thử lại ~6 lần/mã) ────────

def test_refresh_upcoming_budget_stops_after_first_slow_failure(tmp_path, monkeypatch):
    """`--export-pack` 12:46 30/09: 18 timeout × 30s = 9,8′ dù đã có cửa 3 mã —
    mỗi mã lỗi là ~3′ vì thư viện tự thử lại. Quá ngân sách mà đang lỗi ⇒ dừng
    NGAY sau mã đầu, ghi backoff."""
    import vnstock_events as ev
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", tmp_path / "nope.parquet")
    monkeypatch.setattr(ev, "_META", tmp_path)
    monkeypatch.delenv("VNSTOCK_EVENTS_BACKOFF_MIN", raising=False)
    clock = iter([0.0, 190.0, 380.0, 570.0])          # t_start, rồi sau mỗi mã lỗi
    monkeypatch.setattr(ev.time, "monotonic", lambda: next(clock))
    calls: list = []
    monkeypatch.setattr(ev, "_fetch_vci_events", lambda t: calls.append(t) or None)
    out = ev.refresh_upcoming(tickers=[f"T{i:02d}" for i in range(10)], budget_s=120)
    assert calls == ["T00"] and out.empty                # không gõ 9 mã còn lại
    why = ev.in_backoff()
    assert why and "1 mã lỗi" in why                     # marker backoff đã ghi
    assert ev.in_backoff(now=ev.datetime.now() + ev.timedelta(minutes=95)) is None


def test_refresh_upcoming_budget_zero_keeps_old_rule_and_backoff_env_off(tmp_path, monkeypatch):
    import vnstock_events as ev
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", tmp_path / "nope.parquet")
    monkeypatch.setattr(ev, "_META", tmp_path)
    monkeypatch.setenv("VNSTOCK_EVENTS_BACKOFF_MIN", "0")
    calls: list = []
    monkeypatch.setattr(ev, "_fetch_vci_events", lambda t: calls.append(t) or None)
    ev.refresh_upcoming(tickers=list("ABCDE"), budget_s=0)
    assert calls == ["A", "B", "C"]                      # chỉ còn cửa 3 mã liền
    assert ev.in_backoff() is None                       # env 0 = không ghi marker


def test_refresh_success_clears_backoff(tmp_path, monkeypatch):
    import pandas as pd
    import vnstock_events as ev
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", tmp_path / "up.parquet")
    monkeypatch.setattr(ev, "_META", tmp_path)
    monkeypatch.setattr(ev, "_extract_upcoming", lambda df, t, cutoff: [])
    ev._write_backoff(3)
    assert ev.in_backoff()
    monkeypatch.setattr(ev, "_fetch_vci_events", lambda t: pd.DataFrame())
    ev.refresh_upcoming(tickers=["ACB"])
    assert ev.in_backoff() is None


def test_maybe_refresh_events_skips_while_in_backoff(tmp_path, monkeypatch, capsys):
    import vnstock_brief as vb
    import vnstock_events as ev
    monkeypatch.delenv("VNSTOCK_BRIEF_AUTO_EVENTS", raising=False)
    monkeypatch.setattr(ev, "UPCOMING_EVENTS_PATH", tmp_path / "nope.parquet")   # thiếu → muốn refresh
    monkeypatch.setattr(ev, "_META", tmp_path)
    monkeypatch.setattr(ev, "_fetch_vci_events",
                        lambda t: (_ for _ in ()).throw(AssertionError("gõ VCI trong backoff")))
    ev._write_backoff(3)
    assert vb._maybe_refresh_events() == 0
    assert "bỏ qua auto-refresh sự kiện" in capsys.readouterr().out

"""Tests for vnstock_events (upcoming corp-action calendar) + its brief block."""

from __future__ import annotations

from datetime import date

import pandas as pd

import vnstock_events as ev
from vnstock_brief import _upcoming_events_block, build_prompt


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

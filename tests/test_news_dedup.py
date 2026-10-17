"""Tests for vnstock_news.deduplicate_news()."""

from __future__ import annotations

import pytest

from vnstock_news import deduplicate_news, _norm_title, _news_title


# ─── Title normalisation ──────────────────────────────────────────────────────

def test_norm_title_lowercases():
    assert _norm_title("VCB Tăng Mạnh") == "vcb tăng mạnh"


def test_norm_title_strips_punctuation():
    assert _norm_title("VCB lãi quý 3: +15%!!!") == "vcb lãi quý 3 15"


def test_norm_title_collapses_whitespace():
    assert _norm_title("VCB    lãi\tquý 3\n") == "vcb lãi quý 3"


def test_norm_title_handles_empty():
    assert _norm_title("") == ""
    assert _norm_title(None) == ""  # type: ignore[arg-type]


# ─── Title extraction ─────────────────────────────────────────────────────────

def test_news_title_prefers_news_title():
    item = {"news_title": "A", "title": "B", "head": "C"}
    assert _news_title(item) == "A"


def test_news_title_falls_back_to_title():
    item = {"title": "B", "head": "C"}
    assert _news_title(item) == "B"


def test_news_title_falls_back_to_head():
    assert _news_title({"head": "C"}) == "C"


def test_news_title_returns_empty_when_missing():
    assert _news_title({}) == ""


# ─── Deduplication ────────────────────────────────────────────────────────────

def _mk(title: str, date: str = "2026-05-28", ticker: str = "VCB") -> dict:
    return {"news_title": title, "_date_sort": date, "ticker": ticker}


def test_empty_list_returns_empty():
    out, n = deduplicate_news([])
    assert out == []
    assert n == 0


def test_identical_titles_same_day_deduped():
    items = [
        _mk("VCB lãi quý 3 tăng 15%"),
        _mk("VCB lãi quý 3 tăng 15%"),
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 1
    assert n == 1


def test_near_duplicate_titles_same_day_deduped():
    """Tiny punctuation/whitespace differences should be detected."""
    items = [
        _mk("VCB lãi quý 3 tăng 15%"),
        _mk("VCB lãi quý 3 tăng 15 %"),  # extra space
        _mk("VCB lãi quý 3 tăng 15%!"),  # extra punctuation
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 1
    assert n == 2


def test_different_titles_kept():
    items = [
        _mk("VCB lãi quý 3 tăng 15%"),
        _mk("FPT ký hợp đồng 5000 tỷ"),
        _mk("HPG xuất khẩu thép sang Mỹ"),
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 3
    assert n == 0


def test_same_title_different_days_kept():
    items = [
        _mk("VCB lãi quý 3 tăng 15%", date="2026-05-28"),
        _mk("VCB lãi quý 3 tăng 15%", date="2026-05-27"),
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 2
    assert n == 0


def test_threshold_controls_aggressiveness():
    """Lower threshold catches more, higher catches less."""
    items = [
        _mk("VCB báo lãi quý 3 tăng 15%"),
        _mk("Vietcombank công bố lợi nhuận quý 3 tăng 15%"),  # semantically similar
    ]
    out_loose, n_loose = deduplicate_news(items, similarity_threshold=0.5)
    out_strict, n_strict = deduplicate_news(items, similarity_threshold=0.95)
    assert n_loose >= n_strict


def test_length_filter_skips_unrelated():
    """Titles with very different lengths shouldn't be compared."""
    items = [
        _mk("VCB"),
        _mk("VCB thông báo điều chỉnh giá cổ phiếu và phát hành cổ phiếu thưởng cho cổ đông hiện hữu"),
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 2
    assert n == 0


def test_items_without_title_kept():
    """Items lacking a title field should not be deduped against each other."""
    items = [
        {"_date_sort": "2026-05-28", "ticker": "VCB"},
        {"_date_sort": "2026-05-28", "ticker": "FPT"},
    ]
    out, n = deduplicate_news(items)
    assert len(out) == 2
    assert n == 0


def test_output_sorted_newest_first():
    items = [
        _mk("Title A", date="2026-05-25"),
        _mk("Title B", date="2026-05-28"),
        _mk("Title C", date="2026-05-26"),
    ]
    out, _ = deduplicate_news(items)
    dates = [o["_date_sort"] for o in out]
    assert dates == sorted(dates, reverse=True)


def test_first_occurrence_kept():
    """When duplicates found, the FIRST item in input order is retained."""
    items = [
        {"news_title": "VCB lãi quý 3", "_date_sort": "2026-05-28", "ticker": "VCB", "tag": "first"},
        {"news_title": "VCB lãi quý 3", "_date_sort": "2026-05-28", "ticker": "VCB", "tag": "second"},
    ]
    out, _ = deduplicate_news(items)
    assert len(out) == 1
    assert out[0]["tag"] == "first"


# ─── dashboard/news_tab ───────────────────────────────────────────────────────

def _news_tab_with_fake_st(monkeypatch):
    import importlib
    import sys
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    return st, importlib.reload(importlib.import_module("dashboard.news_tab"))


def test_refresh_with_zero_news_is_not_reported_as_success(monkeypatch):
    """Mạng/nguồn lỗi ⇒ refresh_news trả 0 tin mà UI vẫn "✅ Đã tải **0** tin"."""
    import sys
    import types
    from tests.test_tab_render_smoke import _Ctx

    nn = types.ModuleType("vnstock_news")
    nn.cache_info = lambda: {"exists": False, "count": 0, "age_minutes": None}
    nn.build_universe = lambda **k: ["VCB", "FPT"]
    nn.refresh_news = lambda **k: []
    nn.load_news_cache = lambda: []
    monkeypatch.setitem(sys.modules, "vnstock_news", nn)
    monkeypatch.setitem(sys.modules, "vnstock_sentiment", None)   # ImportError
    st, news_tab = _news_tab_with_fake_st(monkeypatch)
    st.button = lambda *a, key=None, **k: key == "_news_refresh"
    status = _Ctx()
    st.empty = lambda *a, **k: status

    news_tab._render_ticker_news()

    assert not status.success.called
    shown = [str(c.args[0]) for m in (status.error, status.warning, st.error, st.warning)
             for c in m.call_args_list if c.args]
    assert any("Không tải được tin nào" in s for s in shown), shown


def test_failed_refresh_still_shows_old_cache(monkeypatch):
    """Lượt hỏng giữ cache cũ ⇒ tab vẫn báo lỗi nhưng không xoá danh sách đang xem."""
    import sys
    import types
    from tests.test_tab_render_smoke import _Ctx

    old = [{"news_title": "Tin cũ", "ticker": "VCB", "_date_sort": "2026-10-15"}]
    nn = types.ModuleType("vnstock_news")
    nn.cache_info = lambda: {"exists": True, "count": 1, "age_minutes": 60}
    nn.build_universe = lambda **k: ["VCB"]
    nn.refresh_news = lambda **k: []
    nn.load_news_cache = lambda: old
    nn.news_context_block = lambda **k: ""
    monkeypatch.setitem(sys.modules, "vnstock_news", nn)
    monkeypatch.setitem(sys.modules, "vnstock_sentiment", None)
    st, news_tab = _news_tab_with_fake_st(monkeypatch)
    st.button = lambda *a, key=None, **k: key == "_news_refresh"
    status = _Ctx()
    st.empty = lambda *a, **k: status

    news_tab._render_ticker_news()

    assert status.error.called
    assert st.session_state["_news_data"] == old


@pytest.mark.parametrize("raw,expect_prefix,reject_prefix", [
    # 20:00 hôm qua, xem 08:00 sáng: timedelta.days == 0 từng ra "Hôm nay 20:00"
    # trong khi bộ lọc "Hôm nay" (so ngày lịch) loại tin đó.
    ("2026-10-15T20:00:00", "Hôm qua", None),
    ("2026-10-16T07:30:00", "Hôm nay 07:30", None),
    # 2 ngày LỊCH trước nhưng chỉ cách 33 giờ — không phải "Hôm qua".
    ("2026-10-14T23:00:00", "2 ngày trước", "Hôm qua"),
    # Hậu tố Z = UTC: 20:00Z hôm qua là 03:00 sáng nay giờ VN.
    ("2026-10-15T20:00:00Z", "Hôm nay 03:00", None),
])
def test_fmt_age_uses_calendar_days_vn_time(monkeypatch, raw, expect_prefix, reject_prefix):
    from datetime import datetime
    _, news_tab = _news_tab_with_fake_st(monkeypatch)
    out = news_tab._fmt_age(raw, now=datetime(2026, 10, 16, 8, 0))
    assert out.startswith(expect_prefix), out
    if reject_prefix:
        assert not out.startswith(reject_prefix), out


# ─── refresh_news: lượt hỏng không đè cache ──────────────────────────────────

def test_refresh_with_zero_news_keeps_existing_cache(monkeypatch, tmp_path):
    """Mất mạng ⇒ fetch_ticker_news trả [] cho mọi mã; cache cũ (đi Dropbox sang cả
    hai máy) không được bị đè thành rỗng."""
    import json
    import vnstock_news as nn

    path = tmp_path / "news_cache.json"
    old = [{"news_title": f"Tin {i}", "ticker": "VCB", "_date_sort": "2026-10-15"}
           for i in range(5)]
    path.write_text(json.dumps({"fetched_at": "2026-10-15T18:00:00", "items": old}),
                    encoding="utf-8")
    monkeypatch.setattr(nn, "NEWS_CACHE_PATH", path)
    monkeypatch.setattr(nn, "_in_memory", [])
    monkeypatch.setattr(nn, "_cache_loaded_at", None)
    monkeypatch.setattr(nn, "fetch_ticker_news", lambda t, **k: [])

    out = nn.refresh_news(universe=["VCB", "FPT"])

    assert out == []                       # lượt này không tải được gì — caller báo lỗi
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [d["news_title"] for d in data["items"]] == [f"Tin {i}" for i in range(5)]
    assert data["fetched_at"] == "2026-10-15T18:00:00"
    assert len(nn.load_news_cache()) == 5  # bộ nhớ đệm cũng không bị thay bằng []

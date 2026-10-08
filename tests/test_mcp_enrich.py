"""vnstock_mcp_enrich — connector TCBS cho mã đang giữ + lệnh mở, CHẠY BÓNG (U79, 08/10).

Hermetic: `collect` tiêm (không spawn `claude`), `price_events` giả, META về
tmp_path. Số trong ca thử là số THẬT đo 08/10 qua connector:
SHB 5.343,7/4.594,2 · GMD 649,3/432,9 (thưởng 50% GDKHQ 07/10) · FPT 1.885,7/1.714,3."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

import vnstock_mcp_enrich as me

OV, NEWS = me.tool_names("claude.ai TCBS MCP")
_REAL_BONUS_EVENTS = me.bonus_events          # trước khi fixture thay bằng bản giả
NOW = datetime(2026, 10, 8, 21, 0)


def _ov(t, out_m, iss_m):
    return json.dumps({"ticker": t, "exchange": "HOSE", "outstandingShare": out_m,
                       "issueShare": iss_m})


def _news(t, *items):
    return json.dumps({"listActivityNews": [
        {"id": i, "ticker": t, "title": title, "source": "HOSE", "publishDate": pub}
        for i, (title, pub) in enumerate(items)]})


def _ex(name, t, text, is_error=False):
    return {"id": f"{name}-{t}", "name": name, "input": {"ticker": t}, "text": text,
            "is_error": is_error}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (me.ENV_SWITCH, me.ENV_MAX, me.ENV_TIMEOUT, me.ENV_SERVER):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(me, "bonus_events", lambda t, today: (0.0, []))
    monkeypatch.setattr(me, "open_rec_tickers", lambda today: [])


# ── tên tool / prompt ───────────────────────────────────────────────────────
def test_tool_names_follow_desktop_server_naming(monkeypatch):
    assert OV == "mcp__claude_ai_TCBS_MCP__tcinvest-getTickerOverview"
    monkeypatch.setenv(me.ENV_SERVER, "TCBS_MCP")
    assert me.tool_names()[1] == "mcp__TCBS_MCP__tcinvest-getTickerActivityNews"


def test_system_prompt_is_shim_safe_and_names_both_tools():
    system, user = me.build_prompt(["SHB", "GMD"], OV, NEWS)
    assert not set('|<>%"\n') & set(system)
    assert OV in system and NEWS in system and "SHB, GMD" in user


# ── vũ trụ ──────────────────────────────────────────────────────────────────
def test_portfolio_tickers_reads_positive_quantities(tmp_path):
    (tmp_path / "portfolio.json").write_text(json.dumps([
        {"ticker": "shb", "quantity": 1000}, {"ticker": "VCB", "quantity": 0},
        {"ticker": "SHB", "quantity": 5}, {"ticker": "GMD", "quantity": "200"}, "rác"]),
        encoding="utf-8")
    assert me.portfolio_tickers(tmp_path) == ["SHB", "GMD"]
    assert me.portfolio_tickers(tmp_path / "không-có") == []


def test_build_universe_held_first_dedup_and_cap():
    uni = me.build_universe(["SHB", "GMD"], ["GMD", "FPT", "VCB"], max_n=3)
    assert uni == {"SHB": ["held"], "GMD": ["held", "rec"], "FPT": ["rec"]}


# ── đọc kết quả tool ────────────────────────────────────────────────────────
def test_parse_exchanges_reads_numbers_from_tool_results_not_model():
    exs = [_ex(OV, "SHB", _ov("SHB", 5343.7, 4594.2)),
           _ex(NEWS, "SHB", _news("SHB", ("SHB: Nghị quyết HĐQT số 47, 48", "2026-10-06 17:35:50"))),
           _ex(OV, "GMD", _ov("SHB", 1, 1)),                 # trả SAI mã ⇒ từ chối
           _ex(NEWS, "GMD", "401 needs auth", is_error=True),
           _ex(OV, "ZZZ", _ov("ZZZ", 1, 1))]                 # mã ngoài danh sách ⇒ bỏ
    d = me.parse_exchanges(exs, OV, NEWS, ["SHB", "GMD"])
    assert d["SHB"]["overview"] == {"outstanding_m": 5343.7, "issue_m": 4594.2, "exchange": "HOSE"}
    assert d["SHB"]["news"][0]["title"].startswith("SHB: Nghị quyết")
    assert d["GMD"]["overview"] is None and len(d["GMD"]["errors"]) == 2
    assert "ZZZ" not in d


def test_parse_overview_rejects_missing_or_zero():
    assert me.parse_overview(_ov("SHB", 0, 4594.2), "SHB")[0] is None
    assert me.parse_overview("không json", "SHB")[1] == "overview: không phải JSON"


# ── phân loại khoảng lệch ───────────────────────────────────────────────────
def test_shb_gap_is_unlisted_issue():
    g = me.listing_gap(5343.7, 4594.2)
    assert g == {"gap_m": 749.5, "gap_pct": 16.31}
    assert me.classify_gap(g["gap_m"], 4594.2, 0.0)["kind"] == "unlisted"


def test_gmd_gap_matches_bonus_50pct():
    g = me.listing_gap(649.3, 432.9)
    c = me.classify_gap(g["gap_m"], 432.9, 0.5)
    assert c["kind"] == "bonus" and c["expected_bonus_m"] == 216.4 and abs(c["residual_m"]) <= 1


def test_gap_bigger_than_bonus_is_bonus_plus():
    c = me.classify_gap(300.0, 1000.0, 0.10)               # thưởng 10% = 100, dư 200
    assert c["kind"] == "bonus_plus" and c["residual_m"] == 200.0


def test_small_gap_ignored():
    assert me.classify_gap(20.0, 1000.0, 0.0)["kind"] == "none"     # 2% < 5%


def test_bonus_events_sums_stock_ratios_only(monkeypatch):
    import vnstock_events
    monkeypatch.setattr(vnstock_events, "price_events", lambda t, a, b: [
        {"ticker": t, "ex_date": date(2026, 10, 7), "title": "Thưởng cổ phiếu, tỷ lệ 2:1"},
        {"ticker": t, "ex_date": date(2026, 10, 7), "title": "Trả cổ tức bằng tiền mặt 1.000 đồng/cp"}])
    ratio, evs = _REAL_BONUS_EVENTS("GMD", date(2026, 10, 8))
    assert ratio == pytest.approx(0.5) and len(evs) == 1 and evs[0]["ex_date"] == "2026-10-07"


def test_recent_count_window():
    news = [{"published": "2026-10-06 17:35:50"}, {"published": "2026-09-23 14:10:21"},
            {"published": "rác"}]
    assert me.recent_count(news, NOW) == 1


# ── một lượt ────────────────────────────────────────────────────────────────
def _collect_ok(user, system, allowed):
    assert allowed == [OV, NEWS]
    return ([_ex(OV, "SHB", _ov("SHB", 5343.7, 4594.2)),
             _ex(NEWS, "SHB", _news("SHB", ("NQ HĐQT 47, 48", "2026-10-06 17:35:50"))),
             _ex(OV, "GMD", _ov("GMD", 649.3, 432.9)),
             _ex(NEWS, "GMD", _news("GMD"))],
            None, {"model": "claude-sonnet-5-5", "cost_usd": 0.12, "elapsed_s": 21.0})


def test_run_writes_state_and_classifies(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "bonus_events",
                        lambda t, today: (0.5, [{"ex_date": "2026-10-07"}]) if t == "GMD" else (0.0, []))
    res = me.run(tickers=["SHB", "GMD"], meta_dir=tmp_path, now=NOW, collect=_collect_ok)
    st = json.loads((tmp_path / me.OUT_NAME).read_text(encoding="utf-8"))
    assert res["status"] == st["status"] == "ok" and st["run_date"] == "2026-10-08"
    assert st["tickers"]["SHB"]["gap_kind"] == "unlisted" and st["tickers"]["SHB"]["news_recent"] == 1
    assert st["tickers"]["GMD"]["gap_kind"] == "bonus"
    assert st["engine"]["cost_usd"] == 0.12 and st["machine"]
    text = "\n".join(me.summary_lines(st))
    assert "phát hành thêm CHƯA niêm yết" in text and "cp thưởng" in text


def test_run_is_noop_same_day_unless_forced(tmp_path):
    me.run(tickers=["SHB", "GMD"], meta_dir=tmp_path, now=NOW, collect=_collect_ok)
    boom = lambda *a: pytest.fail("không được gọi lại")       # noqa: E731
    assert me.run(tickers=["SHB"], meta_dir=tmp_path, now=NOW, collect=boom)["status"] == "skipped"
    assert me.run(tickers=["SHB", "GMD"], meta_dir=tmp_path, now=NOW,
                  collect=_collect_ok, force=True)["status"] == "ok"


def test_run_partial_and_error_are_written_for_visibility(tmp_path):
    part = me.run(tickers=["SHB", "VCB"], meta_dir=tmp_path, now=NOW, collect=_collect_ok)
    assert part["status"] == "partial" and "gap_m" not in part["tickers"]["VCB"]
    err = me.run(tickers=["SHB"], meta_dir=tmp_path, now=NOW, force=True,
                 collect=lambda *a: ([], "quá 420s", {}))
    assert err["status"] == "error" and err["error"] == "quá 420s"
    assert json.loads((tmp_path / me.OUT_NAME).read_text(encoding="utf-8"))["status"] == "error"


def test_run_skips_without_cli_and_without_tickers(tmp_path):
    no_exe = lambda *a: ([], "không tìm thấy", {"no_exe": True})   # noqa: E731
    assert me.run(tickers=["SHB"], meta_dir=tmp_path, now=NOW, collect=no_exe)["status"] == "skipped"
    assert not (tmp_path / me.OUT_NAME).exists()
    assert me.run(meta_dir=tmp_path, now=NOW, collect=no_exe)["status"] == "skipped"


def test_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv(me.ENV_SWITCH, "0")
    assert me.run(tickers=["SHB"], meta_dir=tmp_path, collect=_collect_ok)["status"] == "disabled"


def test_dry_run_does_not_call_or_write(tmp_path):
    res = me.run(tickers=["SHB"], meta_dir=tmp_path, dry_run=True,
                 collect=lambda *a: pytest.fail("dry-run không gọi"))
    assert res["status"] == "dry-run" and OV in res["system"]
    assert not (tmp_path / me.OUT_NAME).exists()


def test_default_meta_dir_is_redirected_in_tests():
    # Lưới conftest (bài học U17): test quên meta_dir không được ghi vào kho thật.
    assert "data_warehouse" not in str(me.META_DIR)

"""Tests for vnstock_doctor — unified data-source health check (run.py doctor).

Offline checks only (the --net probes hit the network by design and are not
exercised here). Every check reads paths under a monkeypatched _META so tests
are hermetic; freshness thresholds are exercised with real files whose mtimes /
embedded dates are shifted relative to today.
"""
import json
import os
import time
from datetime import date, timedelta

import pandas as pd
import pytest

import vnstock_doctor as doc


@pytest.fixture()
def meta(tmp_path, monkeypatch):
    """Point the doctor at an empty tmp warehouse _meta dir."""
    m = tmp_path / "data_warehouse" / "_meta"
    m.mkdir(parents=True)
    monkeypatch.setattr(doc, "_META", m)
    return m


def _age_file(path, days):
    """Shift a file's mtime `days` into the past."""
    old = time.time() - days * 86400
    os.utime(path, (old, old))


# ── helpers ──────────────────────────────────────────────────────────────────


def test_prev_trading_day_skips_weekends():
    assert doc._prev_trading_day(date(2026, 7, 6)) == date(2026, 7, 3)   # Mon → Fri
    assert doc._prev_trading_day(date(2026, 7, 5)) == date(2026, 7, 3)   # Sun → Fri
    assert doc._prev_trading_day(date(2026, 7, 8)) == date(2026, 7, 7)   # Wed → Tue


def test_age_days_and_fmt():
    assert doc._age_days(date.today().isoformat()) == 0
    assert doc._age_days((date.today() - timedelta(days=3)).isoformat()) == 3
    assert doc._age_days("rác") is None
    assert doc._fmt_age(0) == "hôm nay"
    assert doc._fmt_age(2) == "2 ngày trước"
    assert doc._fmt_age(None) == "?"


# ── offline checks: missing / fresh / stale ──────────────────────────────────


def test_market_overview_missing_fresh_stale(meta):
    r = doc.check_market_overview()
    assert r["status"] == "off" and "screener" in r["fix"]

    p = meta / "market_overview.json"
    p.write_text(json.dumps({"data_date": date.today().isoformat()}),
                 encoding="utf-8")
    assert doc.check_market_overview()["status"] == "ok"

    p.write_text(json.dumps(
        {"data_date": (date.today() - timedelta(days=10)).isoformat()}),
        encoding="utf-8")
    r = doc.check_market_overview()
    assert r["status"] == "warn" and "screener" in r["fix"]


def test_market_overview_falls_back_to_generated_at(meta):
    (meta / "market_overview.json").write_text(json.dumps(
        {"generated_at": f"{date.today().isoformat()} 08:00:00"}),
        encoding="utf-8")
    assert doc.check_market_overview()["status"] == "ok"


def test_warehouse_check_reads_latest_vnindex_bar(meta):
    assert doc.check_warehouse()["status"] == "off"

    vn = meta.parent / "prices" / "ticker=VNINDEX" / "year=2026"
    vn.mkdir(parents=True)
    pd.DataFrame({"time": [pd.Timestamp(date.today())]}).to_parquet(vn / "a.parquet")
    r = doc.check_warehouse()
    assert r["status"] == "ok" and date.today().isoformat() in r["message"]

    # VNINDEX EOD về trễ ~1 phiên qua API (dung sai 2 phiên) → bar đúng tại
    # ngưỡng 2-phiên-trước vẫn là ok, KHÔNG báo động giả ban ngày
    boundary = doc._prev_trading_day(doc._prev_trading_day())
    pd.DataFrame({"time": [pd.Timestamp(boundary)]}).to_parquet(vn / "a.parquet")
    assert doc.check_warehouse()["status"] == "ok"

    pd.DataFrame({"time": [pd.Timestamp(date.today() - timedelta(days=30))]}
                 ).to_parquet(vn / "a.parquet")
    assert doc.check_warehouse()["status"] == "warn"


def test_fundamentals_uses_mtime_age(meta):
    assert doc.check_fundamentals()["status"] == "off"
    p = meta / "fundamentals.parquet"
    p.write_bytes(b"x")
    assert doc.check_fundamentals()["status"] == "ok"
    _age_file(p, 15)
    r = doc.check_fundamentals()
    assert r["status"] == "warn" and "fundamental_updater" in r["fix"]


def test_market_news_counts_recent_and_analyzed(meta):
    assert doc.check_market_news()["status"] == "off"
    today = date.today().isoformat()
    (meta / "market_news_cache.json").write_text(json.dumps({
        "fetched_at": f"{today}T08:00:00",
        "items": [
            {"_date_sort": today, "_impact": "tác động X"},
            {"_date_sort": today, "_impact": ""},
            {"_date_sort": "2020-01-01", "_impact": "cũ"},   # ngoài cửa sổ 3 ngày
        ],
    }, ensure_ascii=False), encoding="utf-8")
    r = doc.check_market_news()
    assert r["status"] == "ok"
    assert "2 tin" in r["message"] and "(1 có tác động LLM)" in r["message"]


def test_market_news_stale_fetch_warns(meta):
    old = (date.today() - timedelta(days=6)).isoformat()
    (meta / "market_news_cache.json").write_text(json.dumps(
        {"fetched_at": f"{old}T08:00:00", "items": []}), encoding="utf-8")
    r = doc.check_market_news()
    assert r["status"] == "warn" and "news" in r["fix"]


def test_foreign_flow_fresh_capped_and_stale(meta):
    assert doc.check_foreign_flow()["status"] == "off"
    p = meta / "foreign_net_daily.json"

    fresh = date.today().isoformat()
    p.write_text(json.dumps({fresh: {"net": -491.0, "n_symbols": 512}}),
                 encoding="utf-8")
    assert doc.check_foreign_flow()["status"] == "ok"

    # ~100 mã = API cap (bug top-100 cũ) → warn dù ngày tươi
    p.write_text(json.dumps({fresh: {"net": -665.0, "n_symbols": 100}}),
                 encoding="utf-8")
    r = doc.check_foreign_flow()
    assert r["status"] == "warn" and "cap" in r["message"]

    stale = (date.today() - timedelta(days=10)).isoformat()
    p.write_text(json.dumps({stale: {"net": -10.0, "n_symbols": 512}}),
                 encoding="utf-8")
    assert doc.check_foreign_flow()["status"] == "warn"


def test_events_uses_mtime(meta):
    assert doc.check_events()["status"] == "off"
    p = meta / "upcoming_events.parquet"
    p.write_bytes(b"x")
    assert doc.check_events()["status"] == "ok"
    _age_file(p, 5)
    assert doc.check_events()["status"] == "warn"


def test_macro_check_flags_stale_indicator(meta, tmp_path, monkeypatch):
    import vnstock_macro as mac
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro.json")
    monkeypatch.setattr(mac, "pmi_reminder", lambda m, today=None: None)

    assert doc.check_macro()["status"] == "off"          # cache rỗng

    fresh = date.today().isoformat()
    (tmp_path / "macro.json").write_text(json.dumps({"indicators": {
        "usdvnd": {"label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
                   "kind": "fx", "history": {fresh: 26191.9}},
    }}), encoding="utf-8")
    assert doc.check_macro()["status"] == "ok"

    old = (date.today() - timedelta(days=30)).isoformat()
    (tmp_path / "macro.json").write_text(json.dumps({"indicators": {
        "usdvnd": {"label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
                   "kind": "fx", "history": {old: 26191.9}},
    }}), encoding="utf-8")
    r = doc.check_macro()
    assert r["status"] == "warn" and "Tỷ giá" in r["message"]


def test_macro_check_surfaces_pmi_reminder(meta, tmp_path, monkeypatch):
    import vnstock_macro as mac
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro.json")
    monkeypatch.setattr(mac, "pmi_reminder",
                        lambda m, today=None: "⏰ PMI tháng 6/2026 chưa được cập nhật")
    fresh = date.today().isoformat()
    (tmp_path / "macro.json").write_text(json.dumps({"indicators": {
        "usdvnd": {"label": "Tỷ giá", "unit": "VND", "kind": "fx",
                   "history": {fresh: 26000.0}},
    }}), encoding="utf-8")
    r = doc.check_macro()
    assert r["status"] == "warn" and "PMI" in r["message"]


def test_llm_keys_provider_and_brief(monkeypatch):
    for k in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY",
              "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY",
              "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert doc.check_llm_keys()["status"] == "off"

    monkeypatch.setenv("GROQ_API_KEY", "x")     # sentiment + brief cùng key
    assert doc.check_llm_keys()["status"] == "ok"

    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")  # brief có, sentiment không
    r = doc.check_llm_keys()
    assert r["status"] == "warn" and "sentiment: ❌" in r["message"]


def test_telegram_env_states(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert doc.check_telegram()["status"] == "off"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    r = doc.check_telegram()
    assert r["status"] == "warn" and "TELEGRAM_CHAT_ID" in r["message"]
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    assert doc.check_telegram()["status"] == "ok"


def test_tests_badge_states(meta):
    assert doc.check_tests()["status"] == "off"
    p = meta / "test_status.json"
    now = f"{date.today().isoformat()}T10:00:00"
    p.write_text(json.dumps({"ran_at": now, "passed": 121, "failed": 0, "errors": 0,
                             "mode": "fast"}), encoding="utf-8")
    assert doc.check_tests()["status"] == "ok"
    p.write_text(json.dumps({"ran_at": now, "passed": 100, "failed": 2, "errors": 0,
                             "mode": "fast"}), encoding="utf-8")
    r = doc.check_tests()
    assert r["status"] == "error" and "2 FAIL" in r["message"]


# ── orchestration ────────────────────────────────────────────────────────────


def test_run_checks_survives_a_crashing_check(meta, monkeypatch):
    def _boom():
        raise RuntimeError("nổ")

    monkeypatch.setattr(doc, "OFFLINE_CHECKS", [doc.check_telegram, _boom])
    results = doc.run_checks()
    assert len(results) == 2
    crashed = results[1]
    assert crashed["status"] == "error" and "nổ" in crashed["message"]


def test_run_checks_offline_skips_net(meta, monkeypatch):
    called = []
    monkeypatch.setattr(doc, "OFFLINE_CHECKS", [doc.check_telegram])
    monkeypatch.setattr(doc, "NET_CHECKS",
                        [lambda: called.append(1) or doc._result("x", "x", "ok", "")])
    doc.run_checks(net=False)
    assert not called
    doc.run_checks(net=True)
    assert called


def test_worst_status_and_report_and_persist(meta):
    results = [
        doc._result("a", "Nguồn A", "ok", "tươi"),
        doc._result("b", "Nguồn B", "warn", "cũ 5 ngày", "python run.py x"),
        doc._result("c", "Nguồn C", "off", "chưa cấu hình"),
    ]
    assert doc.worst_status(results) == "warn"

    report = doc.format_report(results)
    assert "Nguồn B" in report and "↳ sửa: python run.py x" in report
    assert "1 ✅" in report and "1 ⚠️" in report and "1 ⬜" in report

    out = doc.write_status(results, "offline")
    assert out is not None and out.name == "doctor_status.json"
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["worst"] == "warn" and saved["counts"]["ok"] == 1
    assert saved["mode"] == "offline" and len(saved["checks"]) == 3


def test_main_offline_writes_status_and_exit_code(meta, monkeypatch, capsys):
    # KHÔNG dựa vào env thật: main() load .env của repo (override=False) nên
    # trên máy user một key vừa delenv có thể được NẠP LẠI từ .env → check
    # telegram/llm không hermetic. Stub thẳng check list bằng kết quả cố định.
    monkeypatch.setattr(doc, "OFFLINE_CHECKS",
                        [lambda: doc._result("a", "Nguồn A", "ok", "tươi")])
    rc = doc.main([])
    assert rc == 0
    assert (meta / "doctor_status.json").exists()
    assert "Nguồn A" in capsys.readouterr().out

    monkeypatch.setattr(doc, "OFFLINE_CHECKS",
                        [lambda: doc._result("b", "Nguồn B", "warn", "cũ")])
    assert doc.main(["--no-save", "--json"]) == 1   # warn → exit 1

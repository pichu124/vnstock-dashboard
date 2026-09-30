"""Tests for vnstock_doctor — unified data-source health check (run.py doctor).

Offline checks only (the --net probes hit the network by design and are not
exercised here). Every check reads paths under a monkeypatched _META so tests
are hermetic; freshness thresholds are exercised with real files whose mtimes /
embedded dates are shifted relative to today.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

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


def test_pdf_tooling_states(monkeypatch):
    monkeypatch.delenv("VNSTOCK_MACRO_VBMA", raising=False)
    # pdftotext trên PATH → ok, không cần pypdf
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/pdftotext")
    assert doc.check_pdf_tooling()["status"] == "ok"
    # thiếu cả 2 → error + đơn thuốc pip install pypdf (bẫy máy mới 10/07)
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr(doc, "_has_pypdf", lambda: False)
    r = doc.check_pdf_tooling()
    assert r["status"] == "error" and "pypdf" in r["fix"]
    # có pypdf → ok
    monkeypatch.setattr(doc, "_has_pypdf", lambda: True)
    assert doc.check_pdf_tooling()["status"] == "ok"
    # kill-switch VBMA → off (không phải lỗi)
    monkeypatch.setenv("VNSTOCK_MACRO_VBMA", "0")
    assert doc.check_pdf_tooling()["status"] == "off"


def test_llm_keys_provider_and_brief(monkeypatch):
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
              "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
              "MISTRAL_API_KEY", "DEEPSEEK_API_KEY"):
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


def test_tests_badge_states(meta, monkeypatch):
    # Nhánh "code đã đổi sau lần chạy test" có lưới riêng ngay dưới. Ở đây
    # phải TRUNG HOÀ nó: mốc `ran_at` cố định 10:00 + mtime file repo THẬT
    # nghĩa là test đỏ/xanh theo GIỜ TRONG NGÀY — chạy trước 10:00 thì xanh,
    # sau 10:00 mà vừa sửa file nào là đỏ. Đã vấp thật 19/08 lúc 11:51.
    monkeypatch.setattr(doc, "_code_changed_after", lambda _at: None)
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


def test_badge_goes_amber_when_code_changed_after_the_last_test_run(
        meta, monkeypatch, tmp_path):
    """Badge xanh mà code đã đổi sau đó là lời trấn an SAI — ca thật 19/08:
    user merge code mới rồi chạy `pytest` thẳng (không qua run.py nên badge
    không được ghi), badge vẫn khoe con số của hôm trước."""
    p = meta / "test_status.json"
    ran = f"{date.today().isoformat()}T10:00:00"
    p.write_text(json.dumps({"ran_at": ran, "passed": 121, "failed": 0,
                             "errors": 0, "mode": "fast"}), encoding="utf-8")
    monkeypatch.setattr(doc, "_REPO", tmp_path)
    old_py = tmp_path / "cu.py"
    old_py.write_text("x = 1", encoding="utf-8")
    os.utime(old_py, (0, datetime.fromisoformat(ran).timestamp() - 3600))
    assert doc._code_changed_after(ran) is None
    assert doc.check_tests()["status"] == "ok"

    new_py = tmp_path / "moi.py"
    new_py.write_text("x = 2", encoding="utf-8")
    os.utime(new_py, (0, datetime.fromisoformat(ran).timestamp() + 3600))
    assert (doc._code_changed_after(ran) or "").startswith("moi.py")
    r = doc.check_tests()
    assert r["status"] == "warn" and "CODE đã đổi" in r["message"]


# ── orchestration ────────────────────────────────────────────────────────────


def test_run_checks_survives_a_crashing_check(meta, monkeypatch):
    def _boom():
        raise RuntimeError("nổ")

    monkeypatch.setattr(doc, "OFFLINE_CHECKS", [doc.check_telegram, _boom])
    results = doc.run_checks()
    assert len(results) == 2
    crashed = results[1]
    assert crashed["status"] == "error" and "nổ" in crashed["message"]


def test_run_checks_survives_base_exception_but_not_ctrl_c(meta, monkeypatch):
    # pyo3 PanicException (native package hỏng) kế thừa BaseException — doctor
    # phải degrade thành error thay vì sập (thấy thật với pypdf/cryptography 10/07)
    class _Panic(BaseException):
        pass

    def _panic():
        raise _Panic("rust panicked")

    monkeypatch.setattr(doc, "OFFLINE_CHECKS", [_panic, doc.check_telegram])
    results = doc.run_checks()
    assert len(results) == 2
    assert results[0]["status"] == "error" and "_Panic" in results[0]["message"]

    # ...nhưng Ctrl+C của user thì phải thoát thật, không được nuốt
    def _interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(doc, "OFFLINE_CHECKS", [_interrupt])
    with pytest.raises(KeyboardInterrupt):
        doc.run_checks()


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


# ── P5: check_reports + check_allocation ─────────────────────────────────────


def test_check_reports_off_ok_warn(meta):
    assert doc.check_reports()["status"] == "off"

    ok_rec = {"id": "aaa", "kind": "text", "chars": 5000,
              "report_date": "2026-07-10", "source": "SSI",
              "digest": {"has_mismatch": False}}
    (meta / "reports_index.json").write_text(json.dumps(
        {"reports": {"aaa": ok_rec}}), encoding="utf-8")
    r = doc.check_reports()
    assert r["status"] == "ok" and "1 đủ điều kiện" in r["message"]

    # đủ điều kiện nhưng CHƯA digest → warn + đơn thuốc
    no_digest = {**ok_rec, "id": "bbb"}
    no_digest.pop("digest")
    (meta / "reports_index.json").write_text(json.dumps(
        {"reports": {"bbb": no_digest}}), encoding="utf-8")
    r = doc.check_reports()
    assert r["status"] == "warn" and "chưa digest" in r["message"]
    assert "report_digest" in r["fix"]

    # digest có claim lệch registry → warn
    mism = {**ok_rec, "id": "ccc", "digest": {"has_mismatch": True}}
    (meta / "reports_index.json").write_text(json.dumps(
        {"reports": {"ccc": mism}}), encoding="utf-8")
    r = doc.check_reports()
    assert r["status"] == "warn" and "lệch registry" in r["message"]


def test_check_allocation_off_ok_stale(meta, monkeypatch):
    assert doc.check_allocation()["status"] == "off"
    monkeypatch.setattr(doc, "_allocation_brief_reminder", lambda: None)

    p = meta / "allocation_state.json"
    p.write_text(json.dumps({
        "band": "B2", "band_label": "trung tính", "n_inputs": 5,
        "as_of": date.today().isoformat(),
        "history": [{"date": date.today().isoformat()}],
        "report_tilt": {"tilt": 1},
    }), encoding="utf-8")
    r = doc.check_allocation()
    assert r["status"] == "ok"
    assert "band B2" in r["message"] and "tilt +1" in r["message"]

    p.write_text(json.dumps({
        "band": "B3", "as_of": (date.today() - timedelta(days=9)).isoformat(),
        "history": [],
    }), encoding="utf-8")
    r = doc.check_allocation()
    assert r["status"] == "warn" and "run.py allocation" in r["fix"]


def test_check_allocation_monthly_brief_reminder(meta, monkeypatch):
    (meta / "allocation_state.json").write_text(json.dumps({
        "band": "B2", "as_of": date.today().isoformat(), "history": []}),
        encoding="utf-8")
    monkeypatch.setattr(doc, "_allocation_brief_reminder",
                        lambda: "⏰ chưa có brief phân bổ tháng này")
    r = doc.check_allocation()
    assert r["status"] == "warn" and "brief phân bổ" in r["message"]


def test_allocation_brief_reminder_logic(monkeypatch):
    import types, sys
    from datetime import date as _d
    mem = types.ModuleType("vnstock_memory")
    rows = []
    mem.recent_briefs = lambda t, limit=5: rows
    monkeypatch.setitem(sys.modules, "vnstock_memory", mem)
    # mùng 1-2: ân hạn, không nhắc
    assert doc._allocation_brief_reminder(_d(2026, 7, 2)) is None
    # từ mùng 3 chưa có brief tháng này → nhắc
    assert "brief phân bổ" in doc._allocation_brief_reminder(_d(2026, 7, 13))
    # đã có brief trong tháng → im lặng
    rows.append({"created_at": "2026-07-05T10:00:00"})
    assert doc._allocation_brief_reminder(_d(2026, 7, 13)) is None


# ── Phát tối đã tới KHO NÀY chưa (việc #11, 16/09) ───────────────────────────
# Vụ 07/09: desktop tắt sync Dropbox, laptop sáng 08/09 vẫn VNINDEX ✅ (dung sai
# 2 phiên cố ý). Badge này đọc thẳng hai marker trong kho — sync (cuối bước
# updater, có phiên PHỦ) và brief chiều (bước 14/14) — và nói cả hai cách "chưa
# tới": pipeline không chạy HOẶC Dropbox tắt sync. Hàm thuần, `now` cắm được.
# Ba luật rút từ vòng phản biện 16/09: (1) so PHIÊN PHỦ chứ không so ngày lịch
# của marker; (2) cùng đêm không bao giờ kết luận "brief chưa" (doctor bước 13
# luôn trước brief bước 14); (3) hạn phát tối 23:00 vì máy bật muộn xong tới
# 23:15 — sáng hôm sau verdict không đổi.


def _upd(day, at="19:05:12", result="success", machine="PICHU", errors=0, **extra):
    key = "last_success_date" if result == "success" else "last_partial_date"
    return {"last_run_at": f"{day}T{at}", "last_machine": machine,
            "last_result": result, "errors": errors, key: day, **extra}


def _reach(upd, brief, now, **kw):
    return doc.pipeline_reach_verdict(upd, brief, now, **kw)


def test_session_for_matches_run_close_session_date():
    """`_session_for` là bản sao của run._close_session_date — parity 14 ngày
    (import run vào doctor là đảo tầng, nên canh bằng test)."""
    import run as runpy
    import vnstock_rollup as rl
    from datetime import time as _t
    for i in range(14):
        d = date(2026, 9, 14) + timedelta(days=i)
        # run.py từ 29/09 so PHIÊN PHỦ (trước 15:05 = phiên trước) → mốc 16:00 như rollup
        assert doc._session_for(d) == runpy._close_session_date(datetime.combine(d, _t(16)))
        # sau giờ chốt, phiên phủ của rollup phải trùng phiên badge đang xét
        assert doc._session_for(d) == rl.session_covered_at(datetime.combine(d, _t(16)))


def test_brief_kill_switch_spellings_match_cmd_brief():
    import run as runpy
    assert set(runpy._BRIEF_OFF) == doc._OFF_VALUES


def test_reach_before_due_hour_judges_the_previous_session():
    """18:30 thứ 3: phát tối nay chưa tới hạn — chỉ đòi phát hôm qua (cả sync
    lẫn brief của hôm qua)."""
    r = _reach(_upd("2026-09-14"), {"close": "2026-09-14"}, datetime(2026, 9, 15, 18, 30))
    assert r["status"] == "ok" and "2026-09-14 đã tới" in r["message"]
    assert "chưa tới hạn 23:00" in r["message"]


def test_reach_same_night_never_concludes_brief_missing():
    """Doctor bước 13 chạy TRƯỚC brief bước 14 cùng phát — kết luận "brief chưa"
    ghi vào doctor_status.json là sai suốt 24 giờ ở CẢ HAI máy."""
    late = _upd("2026-09-15", "22:08:00")
    for hh, mm in ((22, 30), (23, 45)):
        r = _reach(late, {"close": "2026-09-14"}, datetime(2026, 9, 15, hh, mm))
        assert r["status"] == "ok" and "đang tới kho này" in r["message"], (hh, mm)
        assert "xét lại từ sáng mai" in r["message"]
    r = _reach(late, {"close": "2026-09-14"}, datetime(2026, 9, 16, 8, 0))
    assert r["status"] == "warn" and "brief chiều 2026-09-15 CHƯA" in r["message"]
    # ngày làm việc: brief phiên cũ KHÔNG gửi lại được (telegram close dán nhãn
    # phiên hôm nay và chặn brief tối nay) — fix không được xúi
    assert "run_daily.log" in r["fix"] and "telegram close" not in r["fix"]
    assert "không gửi lại được" in r["fix"]
    # bước 13 lọt qua nửa đêm (sync 23:20, doctor 00:05) — vẫn là đang chạy
    r = _reach(_upd("2026-09-15", "23:20:00"), {"close": "2026-09-14"},
               datetime(2026, 9, 16, 0, 5))
    assert r["status"] == "ok" and "đang chạy" in r["message"]


def test_reach_grace_covers_measured_post_sync_tail_on_a_later_day():
    """Chạy bù T7: sync xong 10:41, doctor 12:15 (94′) — vẫn đang chạy; 13:20
    (159′, quá trần 150′) mới nghi."""
    sat = _upd("2026-09-19", "10:41:00")           # T7 phủ phiên T6 18/09
    assert _reach(sat, {"close": "2026-09-17"},
                  datetime(2026, 9, 19, 12, 15))["status"] == "ok"
    r = _reach(sat, {"close": "2026-09-17"}, datetime(2026, 9, 19, 13, 20))
    assert r["status"] == "warn" and "brief chiều 2026-09-18 CHƯA" in r["message"]
    assert "telegram close" in r["fix"]            # T7 vẫn là phiên T6 ⇒ gửi tay được


def test_reach_marker_from_machine_clock_ahead_is_fresh():
    """Đồng hồ desktop nhanh vài phút: marker "từ tương lai" là bằng chứng
    mạnh nhất rằng phát đang chạy, không phải ngược lại."""
    r = _reach(_upd("2026-09-19", "12:03:00"), {"close": "2026-09-17"},
               datetime(2026, 9, 19, 12, 1))
    assert r["status"] == "ok" and "đang chạy" in r["message"]


def test_reach_all_arrived_is_ok_and_names_machine_and_time():
    r = _reach(_upd("2026-09-15"), {"close": "2026-09-15"}, datetime(2026, 9, 15, 23, 30))
    assert r["status"] == "ok" and r["fix"] == ""
    assert "đã tới kho này" in r["message"] and "PICHU" in r["message"]
    assert "15/09 19:05" in r["message"] and "brief chiều đã đẩy" in r["message"]


def test_reach_partial_sync_counts_as_arrived_but_says_so():
    """Đêm fallback KBS: marker `partial` (việc #12) — data ĐÃ vào kho."""
    r = _reach(_upd("2026-09-15", "19:40:00", "partial", errors=214),
               {"close": "2026-09-15"}, datetime(2026, 9, 15, 23, 30))
    assert r["status"] == "ok" and "partial 214 lỗi" in r["message"]
    # ngày success == ngày partial ⇒ tin trường last_result, không suy từ ngày
    both = {**_upd("2026-09-15"), "last_partial_date": "2026-09-15",
            "last_result": "partial", "errors": 214}
    assert "partial 214 lỗi" in _reach(both, {"close": "2026-09-15"},
                                        datetime(2026, 9, 15, 23, 30))["message"]
    # errors rác không được làm check nổ
    bad = _upd("2026-09-15", result="partial", errors="x")
    msg = _reach(bad, {"close": "2026-09-15"}, datetime(2026, 9, 15, 23, 30))["message"]
    assert "sync partial" in msg and "0 lỗi" not in msg
    # phiên phủ bịa ở tương lai không được tin quá ngày chạy
    fut = _upd("2026-09-15", covered_session="2099-01-01")
    assert "2099" not in _reach(fut, {"close": "2026-09-15"},
                               datetime(2026, 9, 15, 23, 30))["message"]


def test_reach_nothing_arrived_after_due_names_both_causes():
    """Đúng câu của vụ 07/09: pipeline không chạy HOẶC Dropbox tắt sync."""
    r = _reach(_upd("2026-09-14"), {"close": "2026-09-14"}, datetime(2026, 9, 15, 23, 30))
    assert r["status"] == "warn"
    assert "2026-09-15 CHƯA tới kho này" in r["message"]
    assert "pipeline không chạy" in r["message"] and "Dropbox tắt sync" in r["message"]
    assert "HỆ QUẢ" in r["message"]
    assert "⇄ CẢ HAI" in r["fix"] and "🖥️ DESKTOP" in r["fix"]
    assert "Get-ScheduledTaskInfo" in r["fix"] and "Dropbox" in r["fix"]


def test_reach_due_boundary_is_23():
    upd = _upd("2026-09-14")
    assert _reach(upd, {"close": "2026-09-14"}, datetime(2026, 9, 15, 22, 59))["status"] == "ok"
    assert _reach(upd, {"close": "2026-09-14"}, datetime(2026, 9, 15, 23, 0))["status"] == "warn"


def test_reach_morning_after_a_missed_run_warns_about_yesterday():
    """Sáng 08/09 trên laptop (desktop tắt sync từ tối 07/09): marker đứng ở
    04/09 ⇒ phát 07/09 CHƯA tới — badge phải nói ra, không đợi tới hạn."""
    r = _reach(_upd("2026-09-04"), {"close": "2026-09-04"}, datetime(2026, 9, 8, 8, 0))
    assert r["status"] == "warn" and "2026-09-07 CHƯA tới kho này" in r["message"]
    assert "phủ phiên 2026-09-04" in r["message"]


def test_reach_morning_after_missing_brief_still_warns():
    """Sáng hôm sau, sync hôm qua tới mà brief hôm qua không có — đúng lúc
    user nhìn laptop; không được "bốc hơi" chỉ vì đã sang ngày mới."""
    r = _reach(_upd("2026-09-14"), {"close": "2026-09-11"}, datetime(2026, 9, 15, 7, 0))
    assert r["status"] == "warn" and "brief chiều 2026-09-14 CHƯA" in r["message"]
    ok = _reach(_upd("2026-09-14"), {"close": "2026-09-14"}, datetime(2026, 9, 15, 7, 0))
    assert ok["status"] == "ok"
    # cờ tắt ở máy này ⇒ không đòi brief cả ở nhánh phiên trước
    assert _reach(_upd("2026-09-14"), None, datetime(2026, 9, 15, 7, 0),
                  brief_enabled=False)["status"] == "ok"


def test_reach_weekend_and_monday_morning_look_at_friday():
    fri = _upd("2026-09-18")
    assert _reach(fri, {"close": "2026-09-18"}, datetime(2026, 9, 19, 10, 0))["status"] == "ok"
    assert _reach(fri, {"close": "2026-09-18"}, datetime(2026, 9, 20, 20, 0))["status"] == "ok"
    assert _reach(fri, {"close": "2026-09-18"}, datetime(2026, 9, 21, 7, 0))["status"] == "ok"
    r = _reach(_upd("2026-09-17"), {"close": "2026-09-17"}, datetime(2026, 9, 21, 7, 0))
    assert r["status"] == "warn" and "2026-09-18 CHƯA tới" in r["message"]
    # T6 chạy muộn 23:50, doctor T7 00:10: cuối tuần luôn "tới hạn" — cửa sổ
    # 150′ phải đỡ được
    r = _reach(_upd("2026-09-18", "23:50:00"), {"close": "2026-09-17"},
               datetime(2026, 9, 19, 0, 10))
    assert r["status"] == "ok" and "đang chạy" in r["message"]


def test_reach_morning_catchup_only_covers_the_previous_session():
    """Máy tắt 18:00 thứ 2, bật 08:20 thứ 3: chạy bù chỉ lấy được bar tới thứ 2.
    Marker cũ đóng dấu NGÀY LỊCH (thứ 3) — badge phải suy phiên phủ từ GIỜ chạy
    (bất biến "so CẢ GIỜ, không chỉ ngày"), không được khen phát thứ 3 đã tới."""
    legacy = _upd("2026-09-15", "08:20:00")
    r = _reach(legacy, {"close": "2026-09-11"}, datetime(2026, 9, 15, 10, 0))
    # sync thứ 2 tới, brief thứ 2 không có — nhưng đó là THIẾT KẾ của chạy bù
    # sáng (cửa <15:00 không gửi brief cũ), không phải pipeline đứt ⇒ ok + nói rõ
    assert r["status"] == "ok" and "theo thiết kế" in r["message"]
    assert "phủ tới phiên 2026-09-14" in r["message"]
    r = _reach(legacy, {"close": "2026-09-14"}, datetime(2026, 9, 15, 10, 0))
    assert r["status"] == "ok" and "2026-09-14 đã tới" in r["message"]
    r = _reach(legacy, {"close": "2026-09-15"}, datetime(2026, 9, 16, 8, 0))
    assert r["status"] == "warn" and "2026-09-15 CHƯA tới kho này" in r["message"]
    # marker mới có covered_session ⇒ tin nó, không cần suy
    new = _upd("2026-09-15", "08:20:00", covered_session="2026-09-14")
    assert _reach(new, {"close": "2026-09-15"},
                  datetime(2026, 9, 16, 8, 0))["status"] == "warn"
    assert _reach(_upd("2026-09-15", "19:05:12", covered_session="2026-09-15"),
                  {"close": "2026-09-15"}, datetime(2026, 9, 16, 8, 0))["status"] == "ok"


def test_reach_weekend_catchup_without_force_names_the_weekend_updater():
    """Chạy bù T7 bằng code cũ: brief T6 đẩy trên bar T5 (updater bỏ qua cuối
    tuần). Badge phải nói đúng nguyên nhân thay vì đẩy user đi soi Dropbox."""
    r = _reach(_upd("2026-09-17"), {"close": "2026-09-18"}, datetime(2026, 9, 19, 12, 0))
    assert r["status"] == "warn" and "2026-09-18 CHƯA tới" in r["message"]
    assert "cuối tuần" in r["message"] and "--force" in r["message"]
    # ngày thường brief mới hơn sync thì KHÔNG đổ cho cuối tuần
    r = _reach(_upd("2026-09-14"), {"close": "2026-09-15"}, datetime(2026, 9, 15, 23, 30))
    assert r["status"] == "warn" and "cuối tuần" not in r["message"]
    assert "gửi tay từ máy khác" in r["message"]


def test_reach_brief_kill_switch_recorded_in_shared_marker():
    """.env không đồng bộ: desktop tắt brief bằng cờ thì laptop chỉ biết qua
    marker dùng chung — không được réo mỗi đêm."""
    brief = {"close": "2026-09-11",
             "skipped": {"session": "2026-09-14", "reason": "VNSTOCK_PIPELINE_BRIEF=0",
                         "machine": "PICHU", "at": "2026-09-14T19:20:00"}}
    r = _reach(_upd("2026-09-14"), brief, datetime(2026, 9, 15, 8, 0))
    assert r["status"] == "ok" and "VNSTOCK_PIPELINE_BRIEF" in r["message"]
    assert "PICHU" in r["message"]
    r = _reach(_upd("2026-09-15"), None, datetime(2026, 9, 15, 23, 30),
               brief_enabled=False, host="CFA-BINHLD-LT")
    assert r["status"] == "ok" and "trên CFA-BINHLD-LT" in r["message"]


def test_reach_tz_aware_last_run_at_does_not_crash():
    """Mốc có tz quy về giờ VN (mọi mốc trong kho là giờ VN), không phải giờ
    máy đang chạy test: +07:00 giữ 21:05; Z là 04:05 hôm sau — cả hai đều
    "đang tới" tối 15/09, không nổ."""
    for at, hhmm in (("21:05:12+07:00", "15/09 21:05"), ("21:05:12Z", "16/09 04:05")):
        r = _reach(_upd("2026-09-15", at), {"close": "2026-09-14"},
                   datetime(2026, 9, 15, 21, 45))
        assert r["status"] == "ok" and "đang tới" in r["message"], r
        assert hhmm in r["message"]
    from datetime import timezone
    r = _reach(_upd("2026-09-15"), {"close": "2026-09-15"},
               datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc))
    assert r["status"] in ("ok", "warn")


def test_reach_bad_or_missing_marker_is_off_not_crash():
    now = datetime(2026, 9, 15, 23, 30)
    for upd in (None, {}, {"last_success_date": "rác"}, {"last_run_at": "x"}, "not a dict"):
        r = _reach(upd, None, now)
        assert r["status"] == "off" and "chưa có marker sync" in r["message"]
        assert "○ MỘT LẦN" in r["fix"]
    # marker tốt nhưng brief rác / last_run_at rác → vẫn trả verdict
    r = _reach({"last_success_date": "2026-09-15", "last_run_at": "rác"},
               {"close": "rác"}, datetime(2026, 9, 16, 8, 0))
    assert r["status"] == "warn" and "brief_push: chưa có marker" in r["message"]
    r = _reach({"last_success_date": "2026-09-15"}, "rác", datetime(2026, 9, 16, 8, 0))
    assert r["status"] in ("warn", "ok")
    # marker trước 15/09 (không partial/fallback/covered_session) vẫn ra verdict
    old = {"last_success_date": "2026-09-15", "last_run_at": "2026-09-15T19:05:12",
           "last_machine": "PICHU"}
    assert _reach(old, {"close": "2026-09-15"}, datetime(2026, 9, 16, 8, 0))["status"] == "ok"


def test_check_pipeline_reach_reads_the_two_markers_and_env(meta, monkeypatch):
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    assert doc.check_pipeline_reach()["status"] == "off"
    session = doc._session_for(date.today())
    (meta / "pipeline_status.json").write_text(json.dumps(
        {"updater": _upd(session.isoformat(), "19:05:12",
                         covered_session=session.isoformat()),
         "rollup": {"last_success_date": "2026-08-18"}}), encoding="utf-8")
    (meta / "brief_push.json").write_text(json.dumps({"close": session.isoformat()}),
                                           encoding="utf-8")
    r = doc.check_pipeline_reach()
    assert r["status"] == "ok" and "brief chiều đã đẩy" in r["message"]
    (meta / "brief_push.json").write_text("{rác", encoding="utf-8")
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "0")
    r = doc.check_pipeline_reach()
    assert r["status"] == "ok" and "VNSTOCK_PIPELINE_BRIEF" in r["message"]
    assert doc.check_pipeline_reach in doc.OFFLINE_CHECKS
    assert doc.OFFLINE_CHECKS.index(doc.check_pipeline_reach) \
        < doc.OFFLINE_CHECKS.index(doc.check_warehouse)


def test_write_status_records_machine(meta, monkeypatch):
    import vnstock_rollup as rl
    monkeypatch.setattr(rl, "get_hostname", lambda: "CFA-BINHLD-LT")
    out = doc.write_status([doc._result("x", "X", "ok", "m")], "offline")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["machine"] == "CFA-BINHLD-LT"


# ─── Badge engine brief (Claude Code CLI) — 30/09 U62 ────────────────────────

def test_brief_engine_verdict_four_states():
    v = doc.brief_engine_verdict
    assert v({"close": "2026-09-30", "engine": "ladder"}, "ladder", [])["status"] == "ok"
    assert v({"close": "2026-09-30", "engine": "ladder"}, "", [])["status"] == "ok"
    r = v({"close": "2026-09-30", "engine": "claude", "agent": "Claude Code · opus-5-5"},
          "claude", [{"ok": 1, "fail": 0}])
    assert r["status"] == "ok" and "Claude Code · opus-5-5" in r["message"]
    r = v({"close": "2026-09-30", "engine": "ladder", "agent": "Gemini 3.5 Flash",
           "claude_error": "claude CLI quá 600s — bỏ"}, "claude", [{"ok": 0, "fail": 1}])
    assert r["status"] == "warn" and "quá 600s" in r["message"] and "--check" in r["fix"]
    r = v({"close": "2026-09-30", "engine": "ladder", "claude_error": "x"}, "claude",
          [{"ok": 0, "fail": 1}, {"ok": 0, "fail": 2}, {"ok": 0, "fail": 1}])
    assert r["status"] == "error" and "3 ngày" in r["message"]
    r = v({"close": "2026-09-30"}, "claude", [])          # marker cũ, chưa có engine
    assert r["status"] == "ok" and "chưa có brief nào" in r["message"]
    assert v(None, "claude", [])["status"] == "ok"
    assert v("rác", "claude", [{"ok": 0, "fail": 1}])["status"] == "ok"


def test_check_brief_engine_reads_env_dotenv_marker_and_ledger(meta, monkeypatch):
    import vnstock_llm_ledger as _lg
    for k in ("VNSTOCK_BRIEF_ENGINE", "VNSTOCK_LLM_ENGINE"):
        monkeypatch.delenv(k, raising=False)
    assert doc.check_brief_engine()["status"] == "ok"
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    (meta / "brief_push.json").write_text(json.dumps(
        {"close": "2026-09-30", "engine": "ladder", "claude_error": "không thấy claude"}),
        encoding="utf-8")
    monkeypatch.setattr(_lg, "summary", lambda day=None: {
        "day": day, "providers": {"ClaudeCode:claude-opus-5-5": {"ok": 0, "fail": 1}}})
    r = doc.check_brief_engine()
    assert r["status"] == "error" and "không thấy claude" in r["message"]
    monkeypatch.setenv("VNSTOCK_BRIEF_ENGINE", "ladder")   # riêng bước đè công tắc chung
    assert doc.check_brief_engine()["status"] == "ok"
    assert doc.check_brief_engine in doc.OFFLINE_CHECKS
    assert doc.OFFLINE_CHECKS.index(doc.check_brief_engine) \
        > doc.OFFLINE_CHECKS.index(doc.check_pipeline_reach)

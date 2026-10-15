"""U88 (15/10): vị thế ròng khối ngoại HĐTL VN30 — kho + seed + lượt SSI MCP, số vị thế/chuỗi,
mục 📑 trong brief (dòng code + guard qua CẢ chuỗi), badge doctor, bước pipeline.

Kho tạm qua conftest `_futures_foreign_hermetic`; MCP luôn là `collect` giả."""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import vnstock_futures_foreign as ff
import vnstock_futures_foreign_view as fv


@pytest.fixture()
def seeded():
    ff.seed()
    return ff.load()


# ── Mã hợp đồng · lịch đáo hạn · kế hoạch gọi ───────────────────────────────

@pytest.mark.parametrize("y,m,code", [(2024, 10, "41I1EA000"), (2025, 7, "41I1F7000"),
                                      (2026, 10, "41I1GA000"), (2026, 12, "41I1GC000"),
                                      (2027, 3, "41I1H3000")])
def test_krx_codes_match_the_ones_ssi_returned(y, m, code):
    """Mã đo được 15/10 trong phiên cloud (thư mục raw của seed)."""
    assert ff.krx_symbol(y, m) == code
    assert ff.symbol_contract(code) == ff.contract_name(y, m)


def test_old_names_and_junk_symbols():
    assert ff.symbol_contract("vn30f2412") == "VN30F2412"
    assert ff.symbol_contract("SSI") is None and ff.symbol_contract("41I1GA001") is None


def test_third_thursday_and_candidates():
    assert ff.third_thursday(2026, 10) == date(2026, 10, 15)
    assert ff.third_thursday(2026, 2) == date(2026, 2, 19)        # luật; Tết lùi về 13/02 (dữ liệu)
    assert ff.candidates(date(2026, 10, 16), date(2026, 10, 9)) == [
        "VN30F2610", "VN30F2611", "VN30F2612", "VN30F2703", "VN30F2706"]
    # kho hở từ tháng 7 ⇒ thêm các hợp đồng đã đáo hạn sau mốc đó
    assert ff.candidates(date(2026, 10, 16), date(2026, 7, 1))[:3] == ["VN30F2607", "VN30F2608", "VN30F2609"]


def test_plan_daily_is_small_and_gap_plan_pages():
    plan = ff.plan_refresh(date(2026, 10, 16), date(2026, 10, 15), "P__")
    assert len(plan) == 5 and {p["tool"] for p in plan} == {"P__" + ff.T_DAILY}
    assert {p["input"]["range"] for p in plan} == {"3m"}
    assert all(ff.PAGE_MIN <= p["input"]["pageSize"] <= ff.PAGE_MAX for p in plan)
    big = ff.plan_refresh(date(2026, 10, 16), date(2026, 4, 1), "P__")
    assert max(p["input"]["pageIndex"] for p in big) > 1 and big[0]["input"]["range"] == "1y"
    assert all(p["input"]["pageSize"] == ff.PAGE_MAX for p in big)
    system, user = ff.build_prompt(plan)
    assert not any(ch in system for ch in "\n|<>%")              # shim .cmd trên Windows
    assert "41I1GA000" in user and "select:P__" + ff.T_DAILY in user


# ── Đọc kết quả tool ────────────────────────────────────────────────────────

def _row(d, sym="41I1GA000", buy="10", sell="4", close="1840.5", vol="1000", adj="1840.5"):
    r = {"symbol": sym, "trading_date": d, "close": close, "volume": vol, "close_price_adjusted": adj}
    if buy is not None:
        r["foreign_buy_volume_total"] = buy
    if sell is not None:
        r["foreign_sell_volume_total"] = sell
    return r


def _payload(rows):
    return json.dumps({"status": "ok", "data": {"stocks": rows}, "error": None, "meta": {}})


def test_parse_rows_dedupes_flags_and_skips_other_symbols():
    text = _payload([_row("15/10/2026"), _row("15/10/2026", adj="0", buy="999"),
                     _row("14/10/2026", buy=None), _row("13/10/2026", buy=None, sell=None),
                     _row("12/10/2026", sym="41I1GB000")])
    rows, err = ff.parse_rows(text, "41I1GA000")
    assert err is None and [r["date"] for r in rows] == ["2026-10-15", "2026-10-14", "2026-10-13"]
    assert rows[0] == {"date": "2026-10-15", "contract": "VN30F2610", "symbol": "41I1GA000", "buy": 10,
                       "sell": 4, "close": 1840.5, "volume": 1000, "ff": "ok"}
    assert [r["ff"] for r in rows] == ["ok", "partial", "none"]


def test_parse_rows_errors_and_empty():
    assert ff.parse_rows(_payload([]), "41I1GA000") == ([], None)     # chưa niêm yết: không lỗi
    rows, err = ff.parse_rows(json.dumps({"status": "error", "error": "toDate ngoài khoảng"}), "X")
    assert rows == [] and "toDate ngoài khoảng" in err
    rows, err = ff.parse_rows("Error: result exceeds maximum allowed tokens", "X")
    assert rows == [] and err.startswith("không đọc được kết quả")


def test_rows_from_exchanges_matches_plan_by_symbol_and_page():
    plan = ff.plan_refresh(date(2026, 10, 16), date(2026, 10, 15), "P__")
    ex = [{"name": "P__" + ff.T_DAILY, "input": {"symbol": "41I1GA000", "range": "3m", "pageSize": 14,
                                                  "pageIndex": 1},
           "text": _payload([_row("15/10/2026")]), "is_error": False},
          {"name": "P__" + ff.T_DAILY, "input": {"symbol": "41I1GB000", "pageIndex": 1},
           "text": "MCP error -32000", "is_error": True}]
    rows, errors = ff.rows_from_exchanges(plan, ex)
    assert [r["contract"] for r in rows] == ["VN30F2610"]
    assert errors["VN30F2611"] == "MCP error -32000"
    assert errors["VN30F2612"] == "model không gọi tool này"


# ── Kho ─────────────────────────────────────────────────────────────────────

def _r(d, c="VN30F2610", buy=10, sell=4, ff_="ok"):
    return {"date": d, "contract": c, "symbol": "41I1GA000", "buy": buy, "sell": sell,
            "close": 1840.0, "volume": 1000, "ff": ff_}


def test_merge_newer_wins_but_never_drops_foreign_fields():
    df = ff.merge(ff._empty(), [_r("2026-10-15")], source="a", fetched_at="2026-10-15T18:00:00")
    df = ff.merge(df, [_r("2026-10-15", buy=None, sell=None, ff_="none"), _r("2026-10-14", buy=7)],
                  source="b", fetched_at="2026-10-16T18:00:00")
    got = df.set_index("date")
    assert got.at["2026-10-15", "buy"] == 10 and got.at["2026-10-15", "source"] == "a"
    df = ff.merge(df, [_r("2026-10-15", buy=12)], source="c", fetched_at="2026-10-17T18:00:00")
    assert df.set_index("date").at["2026-10-15", "buy"] == 12


def test_load_merges_dropbox_conflicted_copy(tmp_path):
    ff.save(ff.merge(ff._empty(), [_r("2026-10-15")], source="a", fetched_at="2026-10-15T18:00:00"), tmp_path)
    other = ff.merge(ff._empty(), [_r("2026-10-15", buy=50), _r("2026-10-16")], source="b",
                     fetched_at="2026-10-16T18:00:00")
    other.to_parquet(tmp_path / "foreign_contracts (PICHU's conflicted copy).parquet", index=False)
    df = ff.load(tmp_path)
    assert list(df["date"]) == ["2026-10-15", "2026-10-16"] and df["buy"].iloc[0] == 50
    assert ff.conflicted_files(tmp_path) == ["foreign_contracts (PICHU's conflicted copy).parquet"]


def test_seed_file_loads_28_contracts_and_is_idempotent(seeded):
    assert len(seeded) == 2230 and seeded["contract"].nunique() == 28
    assert seeded["date"].max() == "2026-10-15" and set(seeded["source"]) == {"ssi-seed"}
    assert ff.seed()["rows"] == 0


# ── Lượt refresh (MCP giả) ──────────────────────────────────────────────────

def _fake_collect(calls, day="16/10/2026"):
    def collect(user, system, allowed):
        calls.append(user)
        ex = []
        for line in user.splitlines()[2:]:
            tool, _, args = line.split(" ", 1)[1].partition(" ")
            inp = json.loads(args)
            ex.append({"name": tool, "input": inp, "is_error": False,
                       "text": _payload([_row(day, sym=inp["symbol"], buy="100", sell="40")])})
        return ex, None, {"model": "m", "cost_usd": 0.05, "elapsed_s": 30}
    return collect


def test_refresh_seeds_empty_store_then_fetches_the_missing_session():
    calls = []
    res = ff.refresh(datetime(2026, 10, 16, 18, 30), collect=_fake_collect(calls),
                     expect=date(2026, 10, 16))
    assert res["seeded"]["rows"] == 2230 and res["status"] == "ok" and len(calls) == 1
    df = ff.load()
    assert df["date"].max() == "2026-10-16" and len(df[df["date"] == "2026-10-16"]) == 5
    st = ff.read_status()
    assert st["status"] == "ok" and st["last_date"] == "2026-10-16" and st["machine"]
    # đã có phiên phủ ⇒ không gọi lại; --force thì gọi
    assert ff.refresh(datetime(2026, 10, 16, 19), collect=_fake_collect(calls),
                      expect=date(2026, 10, 16))["status"] == "skipped" and len(calls) == 1
    ff.refresh(datetime(2026, 10, 16, 19), collect=_fake_collect(calls), expect=date(2026, 10, 16), force=True)
    assert len(calls) == 2


def test_refresh_no_cli_kill_switch_and_stale_source(monkeypatch):
    def no_exe(u, s, a):
        return [], "không tìm thấy lệnh claude", {"no_exe": True}
    res = ff.refresh(datetime(2026, 10, 16, 18), collect=no_exe, expect=date(2026, 10, 16))
    assert res["status"] == "skipped" and "Claude Code" in res["reason"]
    old = ff.refresh(datetime(2026, 10, 16, 18), collect=_fake_collect([], day="15/10/2026"),
                     expect=date(2026, 10, 16))
    assert old["status"] == "partial"                    # nguồn chưa có phiên 16/10
    monkeypatch.setenv("VNSTOCK_FUTURES_FOREIGN", "0")
    assert ff.refresh(collect=no_exe)["status"] == "disabled"


def test_collect_batches_calls_per_claude_session():
    plan = ff.plan_refresh(date(2026, 10, 16), date(2026, 4, 1), "P__")
    sessions = []
    ff._collect(plan, 10, lambda u, s, a: (sessions.append(u) or ([], None, {"cost_usd": 0.1})))
    assert len(sessions) == -(-len(plan) // ff.CALLS_PER_SESSION)


# ── Số vị thế (khớp số đã soát tay 15/10) ───────────────────────────────────

def test_positions_match_the_hand_checked_numbers(seeded):
    pos = fv.positions(seeded)
    last = pos.loc["2026-10-15"]
    assert (last["after"], last["total"], last["expiring"]) == (-1881, -2411, "VN30F2610")
    assert last["n_live"] == 4 and last["next_front"] == "VN30F2611"
    assert pos.loc["2024-10-15", "after"] == 11004
    valid = pos[pos["complete"]]
    assert valid.index[0] == "2024-09-20"                     # từ đây đủ 4 hợp đồng từ phiên niêm yết
    assert (valid["after"].idxmax(), valid["after"].max()) == ("2025-07-10", 34161)
    assert (valid["after"].idxmin(), valid["after"].min()) == ("2026-07-27", -4570)
    assert int((valid["after"] < 0).sum()) == 37


def test_holiday_shifted_expiry_is_recognised(seeded):
    """VN30F2602 đáo hạn 13/02/2026 (Tết) chứ không phải thứ Năm 19/02."""
    pos = fv.positions(seeded)
    assert pos.at["2026-02-13", "expiring"] == "VN30F2602"
    assert pos.at["2026-02-13", "after"] == 4741 and pos.at["2026-02-13", "total"] == 3879


def test_uncertainty_flags_only_the_krx_switch_week(seeded):
    pos = fv.positions(seeded)
    flagged = list(pos.index[pos["complete"] & pos["uncertain"]])
    assert flagged[0] == "2025-05-05" and flagged[-1] == "2025-05-14" and len(flagged) == 8
    assert pos.at["2026-10-15", "err95"] < 50


def test_summary_and_brief_lines_15_10(seeded):
    s = fv.summary(seeded)
    assert s["streak"]["n"] == 14 and s["streak"]["start"] == "2026-09-28"
    assert s["streak_record"]["ties"] == 2 and s["max_short"]["value"] == -4570
    lines = fv.brief_lines(s, expect="2026-10-15")
    assert lines[0] == ("- Vị thế ròng khối ngoại sau phiên 15/10/2026: short 1,881 HĐ (≈ 347 tỷ đ danh nghĩa)"
                        " · tính cả F2610 đáo hạn phiên này: short 2,411 HĐ")
    assert lines[2] == "- Theo kỳ hạn: F2611 -2,142 · F2612 +280 · F2703 -19 · F2610 đáo hạn phiên này -530 (tất toán)"
    assert "short ròng 14 phiên liên tiếp (từ 28/09) — dài nhất phía short từ 20/09/2024 (bằng 1 chuỗi khác)" in lines[3]
    assert not any("Lưu ý dữ liệu" in l for l in lines)
    for l in lines:                                    # né mẫu guard NN cổ phiếu
        assert "mua ròng" not in l and "bán ròng" not in l and "kỷ lục" not in l


def test_brief_lines_say_when_data_is_stale_uncertain_or_incomplete(seeded):
    stale = fv.brief_lines(fv.summary(seeded), expect="2026-10-16")
    assert stale[-1] == "- Lưu ý dữ liệu: chưa lấy được số phiên 16/10/2026 — đang dùng phiên 15/10/2026"
    may = fv.brief_lines(fv.summary(seeded, as_of="2025-05-09"))
    assert "nguồn không có số khối ngoại phiên này" in may[1] and "CHƯA CHẮC" in may[-1]
    part = seeded[~((seeded["date"] == "2026-10-15") & (seeded["contract"] == "VN30F2703"))]
    part = part[~(part["contract"] == "VN30F2703")]
    lines = fv.brief_lines(fv.summary(part))
    assert len(lines) == 1 and "3/4 hợp đồng" in lines[0] and "chưa đủ" in lines[0]
    assert fv.brief_lines(None) == []


def test_dashboard_tables(seeded):
    pos = fv.positions(seeded)
    me = fv.month_end_table(pos).set_index("Tháng")
    assert me.at["09/2026", "Vị thế ròng (HĐ)"] == -1898 and me.at["07/2025", "Vị thế ròng (HĐ)"] == 19023
    st = fv.streak_table(pos)
    assert list(st["Số phiên"][:2]) == [14, 14] and st["Sâu nhất (HĐ)"].min() == -4570
    q = fv.quality_table(seeded)
    assert q.iloc[0]["Hợp đồng"] == "VN30F2505" and q.iloc[0]["% KL thiếu"] == pytest.approx(16.61)


# ── Mục 📑 trong brief ──────────────────────────────────────────────────────

_CLOSE = ("## 🎯 TLDR\n**Kết quả phiên:** VNINDEX giảm 0.80%, GTGD 20,000 tỷ.\n\n"
          "## 💰 Dòng tiền đáng chú ý\nKhối ngoại bán ròng 1,200 tỷ, tập trung Ngân hàng.\n\n"
          "## ⚠️ Rủi ro cần lưu ý\n- Không có rủi ro mới chạm danh mục hay lệnh đang mở trong phiên này.\n\n"
          "## 🌐 Vĩ mô: lãi suất & tỷ giá\n- Lãi suất ổn định\n")
_MORNING = ("## 🎯 TLDR (2 dòng)\nx\n\n## 🔮 Kịch bản phiên chiều\n- y\n\n"
            "## ⚠️ Rủi ro cần lưu ý (phiên chiều)\n- z\n")


def test_guard_places_section_after_money_flow_or_before_risk(seeded):
    import vnstock_brief_guards as g
    lines = fv.brief_lines(fv.summary(seeded))
    out = g.enforce_futures_foreign_section(_CLOSE, {"futures_foreign_lines": lines})
    assert out.index("## 💰") < out.index("## 📑") < out.index("## ⚠️")
    assert g.enforce_futures_foreign_section(out, {"futures_foreign_lines": lines}) == out
    out = g.enforce_futures_foreign_section(_MORNING, {"futures_foreign_lines": lines})
    assert out.index("## 🔮") < out.index("## 📑") < out.index("## ⚠️")


def test_guard_replaces_model_body_removes_when_empty_noop_without_key():
    import vnstock_brief_guards as g
    model = _CLOSE.replace("## ⚠️", "## 📑 Phái sinh: vị thế khối ngoại (VN30F)\nNN short 9,999 HĐ.\n\n## ⚠️")
    out = g.enforce_futures_foreign_section(model, {"futures_foreign_lines": ["- Vị thế ròng: short 1 HĐ"]})
    assert "9,999" not in out and "- Vị thế ròng: short 1 HĐ" in out
    assert "📑" not in g.enforce_futures_foreign_section(model, {"futures_foreign_lines": []})
    assert g.enforce_futures_foreign_section(model, {}) == model


@pytest.mark.parametrize("bt,text", [("afternoon", _CLOSE), ("morning", _MORNING)])
def test_section_survives_the_full_guard_chain(seeded, bt, text):
    """CẢ chuỗi apply_brief_guards với ctx thật (NN ngành, danh mục, lệnh mở…): dòng 📑 ra
    NGUYÊN VẸN — guard NN cổ phiếu / số / động từ không được chạm — và chạy lại vẫn y nguyên.
    (Cả chuỗi chạy lại chưa idempotent ở mục 📌 — một dòng trống, có từ trước U88 — nên so thân 📑.)"""
    import vnstock_brief_guards as g
    from tests.test_brief_risk_today import _ctx_0510

    def body(out):
        sec = out[out.index("## 📑"):]
        return [l for l in sec.split("\n## ")[0].splitlines()[1:] if l.strip()]
    for as_of in ("2026-10-15", "2025-05-09", "2026-08-03"):
        lines = fv.brief_lines(fv.summary(seeded, as_of=as_of), expect=as_of)
        ctx = _ctx_0510(brief_type=bt, futures_foreign_lines=lines,
                        vnindex_tech={"day_change_pct": -0.8, "close": 1650.0})
        out = g.apply_brief_guards(text, ctx)
        assert body(out) == lines, as_of
        again = g.apply_brief_guards(out, ctx)
        assert body(again) == lines and again.count("## 📑") == 1


@pytest.mark.parametrize("bt", ["morning", "afternoon"])
def test_prompt_carries_block_only_when_present(seeded, bt):
    import vnstock_brief as vb
    from tests.test_brief_risk_today import _ctx_0510
    lines = fv.brief_lines(fv.summary(seeded))
    prompt = vb.build_prompt(_ctx_0510(brief_type=bt, futures_foreign_lines=lines), brief_type=bt)
    assert "## 📑 Phái sinh: vị thế khối ngoại (VN30F)\n- Vị thế ròng khối ngoại" in prompt
    assert "KHÔNG cộng hay so với NN ròng cổ phiếu" in prompt
    assert "## 📑" not in vb.build_prompt(_ctx_0510(brief_type=bt), brief_type=bt)


def test_brief_switch_off(monkeypatch):
    monkeypatch.setenv("VNSTOCK_BRIEF_FUTURES_FOREIGN", "0")
    assert fv.brief_enabled() is False


# ── Doctor · run.py ─────────────────────────────────────────────────────────

@pytest.fixture()
def doc(tmp_path, monkeypatch):
    import vnstock_doctor as d
    (tmp_path / "_meta").mkdir()
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    return d


def test_doctor_badge_states(doc, monkeypatch):
    now = datetime(2026, 10, 15, 20)
    r = doc.check_futures_foreign(now)
    assert r["status"] == "warn" and "kho trống" in r["message"] and "--seed" in r["fix"]
    ff.seed(doc._META.parent / "futures")
    r = doc.check_futures_foreign(now)
    assert r["status"] == "ok" and r["message"].startswith("short 1,881 HĐ sau phiên 2026-10-15")
    r = doc.check_futures_foreign(datetime(2026, 10, 16, 20))
    assert r["status"] == "warn" and "phiên phủ 2026-10-16" in r["message"] and "🖥️ DESKTOP" in r["fix"]
    monkeypatch.setenv("VNSTOCK_FUTURES_FOREIGN", "0")
    assert doc.check_futures_foreign(now)["status"] == "off"
    assert doc.check_futures_foreign in doc.OFFLINE_CHECKS


def test_run_py_step_parser_and_command(monkeypatch):
    import run as runpy
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    assert names.index("assets") < names.index("futures-foreign") < names.index("brief")
    assert runpy._DISPATCH["futures-foreign"] is runpy.cmd_futures_foreign
    assert runpy.build_parser().parse_args(["futures-foreign", "--seed"]).seed is True
    seen = []
    monkeypatch.setattr(runpy, "_run", lambda cmd: seen.append(cmd[2:]) or 1)
    assert runpy.cmd_futures_foreign(SimpleNamespace()) == 1      # lỗi ⇒ cảnh báo, không bao giờ 2
    runpy.cmd_futures_foreign(SimpleNamespace(show=True))
    runpy.cmd_futures_foreign(SimpleNamespace(force=True))
    assert seen == [["--refresh"], ["--show"], ["--force"]]
    assert "tests/test_futures_foreign.py" in open(runpy.__file__, encoding="utf-8").read()


# ── Tab dashboard 📑 Phái sinh NN (Streamlit giả) ───────────────────────────

@pytest.fixture()
def fake_st(monkeypatch):
    import importlib
    import sys
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.download_button = lambda *a, **k: False
    monkeypatch.setitem(sys.modules, "streamlit", st)
    sys.modules.pop("dashboard.futures_foreign_tab", None)
    return st, importlib.import_module("dashboard.futures_foreign_tab")


def test_tab_renders_every_section(fake_st, seeded):
    st, mod = fake_st
    mod.render_futures_foreign_tab()
    warned = [c.args for c in st.error.call_args_list] + [
        c.args for c in st.warning.call_args_list if "lỗi khi vẽ" in str(c.args)]
    assert warned == []                                         # không mục nào rơi vào nhánh lỗi
    assert st.plotly_chart.call_count == 4                      # vị thế · giá · dòng lệnh · theo kỳ hạn
    assert st.dataframe.call_count >= 4                         # kỳ hạn · cuối tháng · 2 bảng chuỗi · chất lượng
    labels = [c.args[0] for c in st.metric.call_args_list]
    assert labels[:4] == ["Vị thế ròng (sau đáo hạn)", "Dòng lệnh khối ngoại phiên", "Chuỗi hiện tại",
                          "Giá trị danh nghĩa"]
    assert st.metric.call_args_list[0].args[1] == "short 1,881 HĐ"


def test_tab_empty_store_tells_how_to_fill(fake_st):
    st, mod = fake_st
    mod.render_futures_foreign_tab()
    assert "futures-foreign --seed" in st.info.call_args.args[0]
    assert st.plotly_chart.call_count == 0


def test_tab_is_wired_into_navigation_and_has_no_math_dollar():
    src = open("vnstock_dashboard.py", encoding="utf-8").read()
    assert '"📑 Phái sinh NN"' in src.split("_TAB_OPTIONS = ")[1].split("]")[0]
    assert 'if _active_tab == "📑 Phái sinh NN":' in src and "render_futures_foreign_tab()" in src
    assert "$" not in open("dashboard/futures_foreign_tab.py", encoding="utf-8").read()


def test_role_frame_rolls_with_expiry(seeded):
    pos = fv.positions(seeded)
    roles = fv.role_frame(pos)
    assert roles.loc["2026-10-15"].tolist() == [-2142, 280, -19, pytest.approx(float("nan"), nan_ok=True)]
    assert roles.loc["2026-10-14"].iloc[0] == pos.at["2026-10-14", "VN30F2610"]
    t = fv.contract_table(fv.summary(seeded, pos=pos))
    assert t.iloc[0]["Mã SSI"] == "41I1GA000" and "(đáo hạn phiên này)" in t.iloc[0]["Hợp đồng"]


def test_collect_context_puts_code_lines_in_ctx(seeded, monkeypatch):
    """Dây nối thật (guard quên nối = code chết): collect_context đọc kho ⇒ khoá ctx có dòng code;
    tắt công tắc brief ⇒ không có khoá (guard no-op)."""
    import vnstock_brief as vb
    ctx = vb.collect_context(brief_type="afternoon", auto_refresh=False)
    lines = ctx["futures_foreign_lines"]
    assert lines and lines[0].startswith("- Vị thế ròng khối ngoại sau phiên ")
    assert "futures_foreign" not in (ctx.get("loader_errors") or {})
    monkeypatch.setenv("VNSTOCK_BRIEF_FUTURES_FOREIGN", "0")
    assert "futures_foreign_lines" not in vb.collect_context(brief_type="afternoon", auto_refresh=False)

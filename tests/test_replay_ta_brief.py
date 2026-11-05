"""scripts/replay_ta_brief.py — chạy lại lịch sử brief chiều có thẻ kỹ thuật (PTKT §14 câu 2).

Lưới canh: chọn đúng phiên/bản, thẻ KHÔNG nhìn trước (bar sau phiên không đổi thẻ), dry-run không
gọi engine, không ghi DB / Telegram / memory / brief_watch, báo cáo đủ khối, lỗi một phiên đi tiếp.
Engine giả lập bằng hàm trả chữ cố định — không gọi model thật.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import needs

_SPEC = importlib.util.spec_from_file_location(
    "replay_ta_brief", Path(__file__).resolve().parent.parent / "scripts" / "replay_ta_brief.py")
rt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rt)


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    import vnstock_brief as vb
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")
    monkeypatch.setenv("VNSTOCK_TA_CARD", "0")     # main() đặt "1" — monkeypatch trả lại sau test
    monkeypatch.setattr(vb, "_ENV_LOADED", True)   # không kéo .env máy thật vào pytest
    # vòng delenv vừa xoá luôn ghim của conftest `_no_claude_cli_anywhere` — ghim lại: quên
    # `engine=` trong một test sau này không được thành lượt gọi Opus thật trên desktop
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_EXE", "/nonexistent/claude-cli-blocked-in-tests")


def _bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _bdays(date(2025, 6, 2), 320)
N_AFTER = 10
D = DAYS[-1 - N_AFTER].isoformat()       # phiên brief: còn 10 phiên SAU nó trong kho


def _bars(base: float, *, after: str = "crash") -> pd.DataFrame:
    """Tăng đều 0,3%/phiên tới hết D (thẻ: xu hướng TĂNG, RSI đà mạnh), sau D: sập 3%/phiên."""
    closes, c = [], base
    for i, d in enumerate(DAYS):
        if i:
            c *= 1.003 if d.isoformat() <= D else (0.97 if after == "crash" else 1.05)
        closes.append(round(c, 2))
    s = pd.Series(closes)
    return pd.DataFrame({"time": pd.to_datetime(DAYS), "open": s.shift(1).fillna(s),
                         "high": (s * 1.005).round(2), "low": (s * 0.995).round(2),
                         "close": s, "volume": 1e6})


def _close_at(df: pd.DataFrame, d: str) -> float:
    return float(df.loc[df["time"] == pd.Timestamp(d), "close"].iloc[0])


BARS = {"VNINDEX": _bars(1000.0), "FPT": _bars(100.0), "HPG": _bars(25.0), "EIB": _bars(16.0)}


def _ctx(d: str = D) -> dict:
    c = _close_at(BARS["VNINDEX"], d)
    fpt, hpg = _close_at(BARS["FPT"], d), _close_at(BARS["HPG"], d)
    return {
        "date": d, "time": "18:30", "brief_type": "afternoon",
        "vnindex_tech": {"close": c, "prev_close": round(c / 1.003, 2), "day_change_pct": 0.3,
                         "support_1": round(c * 0.97, 2), "support_2": round(c * 0.95, 2),
                         "resistance_1": round(c * 1.02, 2), "resistance_2": round(c * 1.04, 2),
                         "ma20": round(c * 0.97, 2), "rsi14": 99.0, "data_date": d,
                         "intraday": False},
        "vn30_gainers": [{"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "Công nghệ", "last": fpt,
                          "GTGD TB (tỷ)": 300.0, "sr_support": round(fpt * 0.96, 2),
                          "sr_resistance": round(fpt * 1.03, 2)}],
        "vn30_losers": [{"Mã": "HPG", "Giá 1T %": 1.5, "Ngành": "Thép", "last": hpg,
                         "GTGD TB (tỷ)": 500.0}],
        "portfolio": [{"ticker": "EIB", "qty": 1000, "buy_price": 20.0,
                       "last_close": _close_at(BARS["EIB"], d), "pnl_pct": -10.0}],
        "mover_universe": {"FPT", "HPG"},
    }


OLD_OUTPUT = """## 🎯 TLDR
**Kết quả phiên:** VNINDEX tăng.

## 📈 Mức kỹ thuật chốt phiên (VNINDEX)
**Đóng cửa:** 1,000.00
**Nhận định:** VN-Index giữ xu hướng giảm ngắn hạn. RSI vùng quá mua, cảnh báo điều chỉnh. Hỗ trợ sẽ giữ quanh S1 nên chắc chắn bật lên. Nếu vượt R1 thì mở đường lên 9,999.00.

## ⚠️ Rủi ro cần lưu ý
- Không có rủi ro đặc biệt.
"""

NEW_RAW = """## 🎯 TLDR
**Kết quả phiên:** VNINDEX tăng.

## 📈 Mức kỹ thuật chốt phiên (VNINDEX)
**Nhận định:** VN-Index giữ xu hướng tăng. Nếu vượt R1 thì mục tiêu 9,999.00. Hỗ trợ sẽ giữ nên chắc chắn bật lên.

## ⚠️ Rủi ro cần lưu ý
- Không có rủi ro đặc biệt.
"""


def _load(tk: str) -> pd.DataFrame:
    return BARS[tk.upper()].copy()


def _brief(d: str = D, **kw) -> dict:
    b = {"id": 1, "created_at": f"{d}T18:40:00", "brief_date": d, "brief_type": "afternoon",
         "agent_name": "Claude Code · opus-5-5", "agent_type": "claude", "output": OLD_OUTPUT,
         "error": None, "context_json": json.dumps(_ctx(d), ensure_ascii=False, default=str),
         "sent": 1}
    b.update(kw)
    return b


# ── Chọn phiên ──────────────────────────────────────────────────────────

def test_select_sessions_prefers_sent_then_claude_and_skips_missing_ctx():
    d1, d2, d3, d4 = (DAYS[-14 + i].isoformat() for i in range(4))
    briefs = [
        _brief(d1, id=1, agent_type="gemini", sent=0),                       # không gửi, không Claude
        _brief(d1, id=2, agent_type="claude", sent=0, created_at=f"{d1}T23:00"),
        _brief(d1, id=3, agent_type="gemini", sent=1),                       # ĐÃ GỬI thắng
        _brief(d2, id=4, agent_type="gemini", sent=0),                       # không đủ điều kiện
        _brief(d3, id=5, agent_type="claude", sent=0, context_json=None),    # thiếu ctx
        _brief(d3, id=6, agent_type="claude", sent=0, context_json="{}"),    # ctx rỗng
        _brief(d4, id=7, agent_type="claude", sent=0),
        _brief(d4, id=8, brief_type="morning"),                              # brief sáng: bỏ
    ]
    got = rt.select_sessions(briefs, limit=20)
    assert [(b["brief_date"], b["id"]) for b in got] == [(d1, 3), (d4, 7)]
    assert [b["id"] for b in rt.select_sessions(briefs, limit=1)] == [7]     # phiên GẦN NHẤT


def test_select_sessions_same_rank_keeps_latest_created():
    briefs = [_brief(D, id=1, created_at=f"{D}T18:00"), _brief(D, id=2, created_at=f"{D}T21:00")]
    assert [b["id"] for b in rt.select_sessions(briefs)] == [2]


def test_stored_ctx_restores_sets_saved_as_repr():
    ctx = rt.stored_ctx(_brief())
    assert ctx["mover_universe"] == {"FPT", "HPG"}
    assert ctx["brief_type"] == "afternoon"


# ── Không nhìn trước ────────────────────────────────────────────────────

@needs("pyarrow")
def test_cards_do_not_change_when_bars_after_session_change():
    """Thêm/đổi bar SAU phiên brief (sập 3%/phiên hay tăng 5%/phiên) ⇒ thẻ y hệt thẻ dựng trên kho
    chỉ có bar tới phiên đó."""
    only_past = {tk: df[df["time"] <= pd.Timestamp(D)] for tk, df in BARS.items()}
    boom = {tk: _bars(float(df["close"].iloc[0]), after="moon") for tk, df in BARS.items()}
    a = rt.attach_cards(_ctx(), BARS["VNINDEX"], _load)
    b = rt.attach_cards(_ctx(), only_past["VNINDEX"], lambda tk: only_past[tk.upper()])
    c = rt.attach_cards(_ctx(), boom["VNINDEX"], lambda tk: boom[tk.upper()])
    assert a["ta_card"] == b["ta_card"] == c["ta_card"]
    assert a["ta_cards"] == b["ta_cards"] == c["ta_cards"]
    assert a["ta_card"]["as_of"] == D
    assert set(a["ta_cards"]) == {"EIB", "FPT", "HPG"}
    assert all(card["as_of"] == D for card in a["ta_cards"].values())
    # Thẻ là của ĐÚNG hàm production: nhãn xu hướng tăng + RSI đà mạnh trên chuỗi tăng đều.
    assert a["ta_card"]["short"] == "TĂNG" and a["ta_card"]["rsi_label"] == "đà mạnh"
    assert a["ta_card"]["s1"] == _ctx()["vnindex_tech"]["support_1"]   # mức = ctx đã lưu


@needs("pyarrow")
def test_attach_cards_does_not_mutate_input_ctx():
    ctx = _ctx()
    rt.attach_cards(ctx, BARS["VNINDEX"], _load)
    assert "ta_card" not in ctx and "ta_levels" not in ctx["vnindex_tech"]


@needs("pyarrow")
def test_vnindex_mismatch_is_a_session_error_not_a_crash():
    """Kho VN-Index lệch `vnindex_tech.close` đã lưu ⇒ lỗi phiên (như production), không ném."""
    b = _brief()
    ctx = json.loads(b["context_json"])
    ctx["vnindex_tech"]["close"] += 50
    b["context_json"] = json.dumps(ctx)
    row = rt.prepare_session(b, BARS["VNINDEX"], _load)
    assert row["error"] and "lệch" in row["error"]
    assert "prompt" not in row


# ── Vi phạm, guard, kết cục ─────────────────────────────────────────────

@needs("pyarrow")
def test_old_section_violations_counted_per_rule():
    row = rt.prepare_session(_brief(), BARS["VNINDEX"], _load)
    assert row["error"] is None
    v = row["old_violations"]
    assert v["xu_huong"] == ["VN-Index giữ xu hướng giảm ngắn hạn."]
    assert v["rsi"] == ["RSI vùng quá mua, cảnh báo điều chỉnh."]
    assert v["hua_hen"] == ["Hỗ trợ sẽ giữ quanh S1 nên chắc chắn bật lên."]
    assert v["so_bia"] == ["Nếu vượt R1 thì mở đường lên 9,999.00."]
    assert v["kl"] == ["Nếu vượt R1 thì mở đường lên 9,999.00."]
    assert rt.n_violations(v) == 5


@needs("pyarrow")
def test_prompt_carries_card_from_cut_bars():
    row = rt.prepare_session(_brief(), BARS["VNINDEX"], _load)
    assert "Thẻ kỹ thuật VN-Index" in row["prompt"]
    for line in row["ta_card"]["lines"]:
        assert line in row["prompt"]
    assert f"Phiên {D}" in row["prompt"]


@needs("pyarrow")
def test_forward_outcome_reads_sessions_after_brief():
    vt = _ctx()["vnindex_tech"]
    o = rt.forward_outcome(BARS["VNINDEX"], D, vt)
    assert o["available"] and o["sessions_after"] == 5
    assert o["t1_pct"] == pytest.approx(-3.0, abs=0.01)
    assert o["t5_pct"] == pytest.approx((0.97 ** 5 - 1) * 100, abs=0.02)
    assert o["touch"]["S1"]["first_session"] == 1          # low T+1 = 0,97×0,995×close < S1
    assert o["touch"]["S2"]["first_session"] == 2
    assert o["touch"]["R1"]["first_session"] is None
    assert o["vol_t1_ratio"] == 1.0
    assert rt.forward_outcome(BARS["VNINDEX"], "2030-01-02", vt)["available"] is False


@needs("pyarrow")
def test_run_engine_applies_guards_and_counts_dropped_sentences():
    row = rt.prepare_session(_brief(), BARS["VNINDEX"], _load)
    calls = []
    rt.run_engine(row, lambda p: (calls.append(p) or ("```\n" + NEW_RAW + "\n```", None, {})))
    assert calls == [row["prompt"]]
    assert row["error"] is None
    g = row["guard"]
    assert g["raw_sentences"] == 3 and g["final_sentences"] == 1 and g["kept"] == 1
    assert g["dropped"] == ["Nếu vượt R1 thì mục tiêu 9,999.00.",
                            "Hỗ trợ sẽ giữ nên chắc chắn bật lên."]
    assert g["card_lines_ok"]                             # code chèn đủ dòng thẻ vào mục 📈
    assert rt.n_violations(row["new_raw_violations"]) == 3   # số bịa + KL (câu 2) + hứa hẹn
    assert rt.n_violations(row["new_final_violations"]) == 0
    for line in row["ta_card"]["lines"]:
        assert line in row["new_section"]


@needs("pyarrow")
def test_guard_crash_keeps_paid_text_and_marks_session_error(monkeypatch):
    import vnstock_brief as vb
    row = rt.prepare_session(_brief(), BARS["VNINDEX"], _load)

    def _crash(text, ctx):
        raise KeyError("khoá ctx cũ")
    monkeypatch.setattr(vb, "apply_brief_guards", _crash)
    rt.run_engine(row, lambda p: (NEW_RAW, None, {}))
    assert row["error"].startswith("guard: KeyError")
    assert row["new_raw"] == NEW_RAW.strip() and "new_final" not in row

# ── CLI end-to-end: không ghi DB / Telegram / memory ────────────────────

def _make_db(path: Path, briefs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE briefs (id INTEGER PRIMARY KEY, created_at TEXT, brief_date TEXT, "
              "brief_type TEXT, agent_name TEXT, agent_type TEXT, model TEXT, prompt TEXT, "
              "output TEXT, error TEXT, context_json TEXT, auto_score REAL, sent INTEGER)")
    for b in briefs:
        c.execute("INSERT INTO briefs (id, created_at, brief_date, brief_type, agent_name, "
                  "agent_type, output, error, context_json, sent) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  tuple(b[k] for k in ("id", "created_at", "brief_date", "brief_type",
                                       "agent_name", "agent_type", "output", "error",
                                       "context_json", "sent")))
    c.commit()
    c.close()


def _write_prices(prices: Path) -> None:
    for tk, df in BARS.items():
        for y, g in df.groupby(df["time"].dt.year):
            d = prices / f"ticker={tk}" / f"year={y}"
            d.mkdir(parents=True, exist_ok=True)
            g.to_parquet(d / "data.parquet")


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """Kho tạm: prices + brief_memory.db 2 phiên; mọi đường ghi bị cấm đều nổ nếu bị gọi."""
    import vnstock_brief as vb
    import vnstock_brief_pack as vbp
    import vnstock_brief_watch as bw
    import vnstock_memory as mem
    import vnstock_telegram as tg
    wh = tmp_path / "wh"
    _write_prices(wh / "prices")
    d0 = DAYS[-1 - N_AFTER - 1].isoformat()
    _make_db(wh / "_meta" / "brief_memory.db",
             [_brief(d0, id=1), _brief(D, id=2, agent_type="gemini", sent=1)])
    monkeypatch.setattr(vb, "_VNINDEX_PRICES_DIR", wh / "prices")

    def _forbidden(*a, **k):
        raise AssertionError("replay không được ghi memory / gửi Telegram / brief_watch")
    for mod, name in ((mem, "save_brief"), (tg, "send_message"), (tg, "push_close_brief"),
                      (vbp, "finalize_brief"), (vbp, "write_final"), (vbp, "write_raw"),
                      (vbp, "write_pack"), (bw, "observe_brief")):
        monkeypatch.setattr(mod, name, _forbidden)
    return wh


def _args(wh: Path, out: Path, *extra: str) -> list[str]:
    return ["--db", str(wh / "_meta" / "brief_memory.db"), "--out", str(out), *extra]


@needs("pyarrow")
def test_dry_run_never_calls_engine_and_writes_only_out_dir(warehouse, tmp_path):
    before = _snapshot(warehouse)

    def _boom(prompt):
        raise AssertionError("dry-run gọi engine")
    out = tmp_path / "out"
    assert rt.main(_args(warehouse, out), engine=_boom, ask=_boom) == 0
    assert _snapshot(warehouse) == before                 # DB + kho y nguyên từng byte
    md = (out / "report.md").read_text(encoding="utf-8")
    for needle in ("DRY-RUN", f"## Phiên {D}", "### Thẻ kỹ thuật dựng lại", "### 📈 brief CŨ",
                   "### 📈 brief MỚI (sau guard)", "dry-run — chưa gọi model",
                   "DỮ LIỆU TƯƠNG LAI", "## Bảng tổng", "Vi phạm theo 5 luật mới: 5"):
        assert needle in md, needle
    assert sorted(p.name for p in (out / "prompts").iterdir()) == [
        f"{DAYS[-1 - N_AFTER - 1].isoformat()}.md", f"{D}.md"]
    assert not (out / "new").exists()
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["meta"]["dry_run"] is True
    assert rep["summary"]["old_violations"]["xu_huong"] == 2
    assert all("ctx" not in s and "prompt" not in s for s in rep["sessions"])


@needs("pyarrow")
def test_run_calls_engine_per_session_and_never_writes_db(warehouse, tmp_path):
    before = _snapshot(warehouse)
    calls = []

    def _engine(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "", "claude CLI quá 600s — bỏ", {"elapsed_s": 600.0}
        return NEW_RAW, None, {"model": "claude-opus-5-5", "cost_usd": 0.3}
    out = tmp_path / "out"
    assert rt.main(_args(warehouse, out, "--run", "--yes"), engine=_engine) == 0
    assert len(calls) == 2                                # lỗi phiên đầu ⇒ vẫn chạy phiên sau
    assert _snapshot(warehouse) == before
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    s = rep["summary"]
    assert s["ran"] == 1 and len(s["errors"]) == 1 and "600s" in s["errors"][0]["error"]
    assert s["dropped_sentences"] == 2
    assert sum(s["new_final_violations"].values()) == 0
    assert rep["meta"]["estimate"]["calls"] == 2
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Guard: 3 câu model → 1 câu · bỏ 2" in md
    assert "Câu guard bỏ ở bản mới: 2" in md
    assert (out / "new" / f"{D}.raw.md").read_text(encoding="utf-8") == NEW_RAW.strip()


@needs("pyarrow")
def test_run_without_yes_asks_and_declining_calls_nothing(warehouse, tmp_path):
    asked = []

    def _boom(prompt):
        raise AssertionError("đã từ chối mà vẫn gọi engine")
    rc = rt.main(_args(warehouse, tmp_path / "out", "--run"), engine=_boom,
                 ask=lambda q: asked.append(q) or "n")
    assert rc == 1 and asked == ["Gọi 2 lượt? [y/N] "]
    assert not (tmp_path / "out").exists()


def test_estimate_uses_ledger_price_table():
    rows = [{"prompt": "x" * 30_000}, {"prompt": "x" * 30_000}, {"error": "hỏng"}]
    est = rt.estimate(rows, "claude-opus-5-5")
    assert est["calls"] == 2
    assert est["usd_measured"] == pytest.approx(2 * rt.MEASURED_USD_PER_CALL)
    assert est["usd_tokens"] > 0                          # opus có trong bảng giá sổ LLM
    assert rt.estimate(rows, "model-la")["usd_tokens"] == 0


# ── Sau review: không mất bản đã trả tiền, không đè report, memo timeout ─────

@needs("pyarrow")
def test_interrupt_mid_run_keeps_paid_text_and_rerun_reuses_it(warehouse, tmp_path):
    calls = []

    def _dies_on_second(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise KeyboardInterrupt                   # Ctrl+C / máy ngủ giữa lượt 2
        return NEW_RAW, None, {"model": "claude-opus-5-5"}
    out = tmp_path / "out"
    with pytest.raises(KeyboardInterrupt):
        rt.main(_args(warehouse, out, "--run", "--yes"), engine=_dies_on_second)
    raws = sorted(p.name for p in (out / "new").glob("*.raw.md"))
    assert len(raws) == 1                             # bản đã trả tiền nằm trên đĩa
    assert (out / "report.md").is_file()              # finally vẫn ghi report phần đã chạy

    again = []

    def _count(prompt):
        again.append(prompt)
        return NEW_RAW, None, {"model": "claude-opus-5-5"}
    assert rt.main(_args(warehouse, out, "--run", "--yes"), engine=_count) == 0
    assert len(again) == 1                            # phiên đã có raw KHÔNG gọi lại
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["summary"]["ran"] == 2
    assert [s["engine_info"].get("reused") for s in rep["sessions"]].count(True) == 1


@needs("pyarrow")
def test_engine_fail_streak_stops_early(warehouse, tmp_path):
    calls = []

    def _always_fail(prompt):
        calls.append(prompt)
        return "", "claude CLI quá 600s — bỏ", {}
    out = tmp_path / "out"
    assert rt.main(_args(warehouse, out, "--run", "--yes"), engine=_always_fail) == 0
    assert len(calls) == rt.ENGINE_FAIL_STREAK_MAX
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["meta"]["stopped_early"]


def test_dry_run_default_dir_never_overwrites_paid_run_dir():
    assert rt._default_out(True).name.endswith("-dry")
    assert not rt._default_out(False).name.endswith("-dry")
    assert rt._default_out(True).parent == rt._default_out(False).parent


def test_timeout_memo_is_reset_but_missing_exe_memo_is_kept(monkeypatch):
    import vnstock_claude_cli as vcc
    monkeypatch.setattr(vcc, "_DEAD_REASON", "claude CLI quá 600s — bỏ")
    rt._reset_timeout_memo()
    assert vcc._DEAD_REASON is None
    monkeypatch.setattr(vcc, "_DEAD_REASON", "không tìm thấy lệnh `claude` (Claude Code CLI)")
    rt._reset_timeout_memo()
    assert vcc._DEAD_REASON is not None


def test_stored_ctx_pins_today_to_session_date():
    ctx = rt.stored_ctx({"context_json": json.dumps({"date": "2026-10-15"})})
    assert ctx["today"] == "2026-10-15"               # guard GDKHQ so với NGÀY PHIÊN, không hôm nay


def test_hermetic_cli_pin_survives_env_wipe():
    import vnstock_brief_pack as vbp
    assert vbp.cli_executable() is None

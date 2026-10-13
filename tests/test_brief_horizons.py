"""P1b-3 (#21) — khối 🔭 + TLDR dòng 3 trong brief chiều (sau công tắc
`VNSTOCK_HORIZONS`, mặc định TẮT tới #26). Đặc tả `docs/THIET-KE-BRIEF-3-KHUNG.md`
§3.12, §4 (B), §3.10. Số mẫu = trạng thái THẬT 🖥️ 13/10 (`run.py horizons --show`).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

TANG, DI_NGANG, GIAM = 1, 0, -1
HOI, CHUA_RO, CHINH = 1, 0, -1


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)


def _snap(as_of="2026-10-13", **over) -> dict:
    s = {"as_of": as_of, "short": CHINH, "short_since": "2026-09-24", "score": -7, "n": 7,
         "medium": GIAM, "medium_since": "2026-10-02", "pending": 0, "week_closed": False,
         "medium_provisional": None,
         "levels": [{"kind": "leave_giam", "price": 1802.4, "reachable": True}],
         "alert": {"tier": 1, "anchor": 1853.08, "since": "2026-10-01"},
         "protect": "cứng", "stance": {"forced": "GIẢM", "allowed": ["GIẢM"]},
         "ma_w": {"short": 1781.99, "long": 1801.32}}
    s.update(over)
    return s


def _view(**over) -> dict:
    v = {"stale": False, "snap": _snap(), "prev": _snap(as_of="2026-10-12"),
         "short_sessions": 14, "medium_weeks": 2, "breadth_pct": 9.0, "breadth_pct_4w": 11.0}
    v.update(over)
    return v


def _ctx(view=None, **over) -> dict:
    c = {"brief_type": "afternoon", "horizons": view if view is not None else _view(),
         "market_sentiment": {"mood": "❄️ Sợ hãi", "momentum": -67},
         "allocation": {"band": "B4", "band_label": "Căng thẳng",
                        "allocation": {"Cổ phiếu": 15, "Trái phiếu": 25, "Tiền gửi": 40,
                                       "Vàng": 12, "USD": 8}}}
    c.update(over)
    return c


# ── Canon: 🔭 + TLDR dòng 3 (số từ state, mức in làm tròn "~") ─────────────────

def test_horizon_lines_for_the_real_13_10_state():
    from vnstock_brief import _horizon_body_lines, _horizon_tldr_line
    assert _horizon_body_lines(_ctx()) == [
        "- Ngắn hạn (vài phiên): nhịp chỉnh, phiên thứ 14 (từ 24/09); điểm kỹ thuật ngày -7/7; "
        "tâm lý ❄️ Sợ hãi. Hết nhịp chỉnh khi điểm về ≥ 0.",
        "- Trung hạn (xu hướng tuần): GIẢM, tuần 2 (từ 02/10); 9% mã trên MA200 "
        "(4 tuần trước 11%).",
        "- Dài hạn (6–12 tháng): đang thu thập — chỉ đọc theo trung hạn.",
        "- 🚨 Rủi ro ngắn hạn: BẬT mức 1 từ 01/10, neo đỉnh ~1,853; lên mức 2 nếu đóng < ~1,668 "
        "(90% neo) hoặc thêm 1 phiên ≤ -2.5%. Không đổi xu hướng.",
        "- 💼 Cổ phiếu 15% (band B4). Nên (đồng pha giảm): giữ tỷ trọng thấp; không bắt đáy.",
    ]
    assert _horizon_tldr_line(_ctx()) == (
        "**Trung hạn:** GIẢM từ 02/10 → không mua đuổi nhịp hồi; chỉ rời GIẢM khi 2 tuần liền "
        "đóng trên ~1,802 (mức tuần này, tính lại mỗi tuần).")


def test_change_line_appears_only_when_a_layer_moved():
    from vnstock_brief import _horizon_body_lines
    moved = _view(snap=_snap(as_of="2026-10-02", medium_since="2026-10-02"),
                  prev=_snap(as_of="2026-10-01", medium=DI_NGANG, medium_since="2026-07-24"),
                  medium_weeks=1)
    first = _horizon_body_lines(_ctx(moved))[0]
    assert first == ("- 🔁 Thay đổi: trung hạn ĐI NGANG → GIẢM (02/10). "
                     "Ngắn hạn và 🚨 không đổi.")
    assert not _horizon_body_lines(_ctx())[0].startswith("- 🔁")


def test_flat_trend_line_points_to_the_down_level_and_alert_off():
    from vnstock_brief import _horizon_body_lines, _horizon_tldr_line
    flat = _view(snap=_snap(medium=DI_NGANG, medium_since="2026-07-24", short=HOI,
                            short_since="2026-10-09", score=4,
                            alert={"tier": 0, "anchor": None, "since": None},
                            levels=[{"kind": "to_giam", "price": 1766.2, "reachable": True},
                                    {"kind": "to_tang", "price": 2020.0, "reachable": False}]),
                 prev=None, short_sessions=3, medium_weeks=12)
    lines = _horizon_body_lines(_ctx(flat))
    assert "- 🚨 Rủi ro ngắn hạn: tắt." in lines
    assert lines[-1] == ("- 💼 Cổ phiếu 15% (band B4). Nên (nhịp hồi trong xu hướng đi ngang): "
                         "không nâng tỷ trọng; nếu chốt lời thì chốt phần vượt tỷ trọng.")
    assert _horizon_tldr_line(_ctx(flat)) == (
        "**Trung hạn:** ĐI NGANG từ 24/07 → không nâng tỷ trọng theo nhịp hồi; chuyển GIẢM nếu "
        "đóng tuần < ~1,766; lên TĂNG cần 2 tuần đọc > ~2,020 (chưa thể trong tuần này).")


def test_cap_note_rides_on_the_portfolio_line():
    from vnstock_brief import _horizon_body_lines
    ctx = _ctx()
    ctx["allocation"]["capped_by"] = {"by": "horizons", "why": "trung hạn GIẢM",
                                      "proposed_band": "B3", "proposed_pct": 30}
    assert _horizon_body_lines(ctx)[-1].startswith(
        "- 💼 Cổ phiếu 15% (band B4; band dữ liệu đề xuất B3 30% — giữ vì trung hạn GIẢM).")


def test_stale_state_prints_not_updated_and_no_tldr_line():
    from vnstock_brief import _horizon_body_lines, _horizon_tldr_line
    stale = {"stale": True, "as_of": "2026-10-09", "reason": "cũ: …"}
    assert _horizon_body_lines(_ctx(stale)) == ["- 🔭 chưa cập nhật (as_of 09/10)."]
    assert _horizon_tldr_line(_ctx(stale)) is None


# ── Guard enforce_horizon_view ──────────────────────────────────────────────────

_AGENT = """## 🎯 TLDR
**Kết quả phiên:** VNINDEX 1,737.71 (-0.66%), phiên giảm thứ 5 liên tiếp.
**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,720.50 → mục tiêu S2=1,700.10; hủy nếu vượt lại R1=1,760.20.

## 📊 Tổng kết phiên
Phiên giảm trên diện rộng.
"""


def test_guard_inserts_tldr_line_and_section_right_after_tldr():
    from vnstock_brief import _HORIZON_TITLE, _horizon_body_lines, _horizon_tldr_line, \
        enforce_horizon_view
    out = enforce_horizon_view(_AGENT, _ctx())
    lines = out.splitlines()
    i = lines.index(_HORIZON_TITLE)
    assert lines[3] == _horizon_tldr_line(_ctx())
    assert lines[i + 1:i + 1 + 5] == _horizon_body_lines(_ctx())
    assert lines.index("## 📊 Tổng kết phiên") > i
    assert enforce_horizon_view(out, _ctx()) == out                  # idempotent


def test_guard_keeps_one_agent_sentence_without_numbers():
    from vnstock_brief import _HORIZON_TITLE, enforce_horizon_view
    base = enforce_horizon_view(_AGENT, _ctx())
    edited = (base
              .replace("Hết nhịp chỉnh khi điểm về ≥ 0.",
                       "Hết nhịp chỉnh khi điểm về ≥ 0. → Lực bán chưa cạn. Câu hai bị bỏ.")
              .replace("(4 tuần trước 11%).",
                       "(4 tuần trước 11%). → Đáy có thể quanh 1,650."))
    out = enforce_horizon_view(edited, _ctx())
    sec = out.split(_HORIZON_TITLE)[1]
    assert "→ Lực bán chưa cạn." in sec and "Câu hai" not in sec
    assert "1,650" not in sec                                        # câu có số ⇒ bỏ
    assert enforce_horizon_view(out, _ctx()) == out


def test_guard_rewrites_a_section_the_agent_garbled():
    from vnstock_brief import _HORIZON_TITLE, _horizon_body_lines, enforce_horizon_view
    garbled = _AGENT.replace("## 📊 Tổng kết phiên",
                             f"{_HORIZON_TITLE}\n- Trung hạn: TĂNG mạnh, mục tiêu 2,000\n\n"
                             "## 📊 Tổng kết phiên")
    out = enforce_horizon_view(garbled, _ctx())
    body = out.split(_HORIZON_TITLE)[1].split("## 📊")[0].strip().splitlines()
    assert body == _horizon_body_lines(_ctx())


@pytest.mark.parametrize("ctx", [
    {"brief_type": "afternoon"},                       # công tắc tắt ⇒ không có khoá
    _ctx(brief_type="morning"),                        # brief sáng: dòng 🔭 riêng ở #24
])
def test_guard_is_a_noop_without_horizons_or_for_the_morning_brief(ctx):
    from vnstock_brief import enforce_horizon_view
    assert enforce_horizon_view(_AGENT, ctx) == _AGENT


# ── Vòng tròn: khối chuẩn qua TOÀN BỘ chuỗi guard ra giống từng byte ──────────

def _five_real_sessions():
    """5 phiên chạy bóng THẬT 07–13/10 (🖥️ `horizons --show`): trung hạn GIẢM từ
    02/10, ngắn hạn nhịp chỉnh, 🚨 mức 1 từ 01/10; độ rộng/điểm theo phiên."""
    days = ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    for k, d in enumerate(days):
        snap = _snap(as_of=d, score=-6 if k < 2 else -7, n=7)
        yield _ctx(_view(snap=snap, prev=_snap(as_of=days[k - 1]) if k else None,
                         short_sessions=10 + k, breadth_pct=9.0 + (k % 2),
                         breadth_pct_4w=11.0))


@pytest.mark.parametrize("ctx", list(_five_real_sessions()))
def test_canonical_section_survives_the_whole_guard_chain(ctx):
    """Bản xuất bản (qua TOÀN BỘ chuỗi guard) mang đúng khối canon từng byte, và
    chạy lại chuỗi guard không đổi gì (guard khác không gặm 🔭)."""
    from vnstock_brief import (_HORIZON_TITLE, _horizon_body_lines, _horizon_tldr_line,
                               apply_brief_guards)
    out = apply_brief_guards(_AGENT, ctx)
    lines = out.split("\n")
    i = lines.index(_HORIZON_TITLE)
    body = _horizon_body_lines(ctx)
    assert lines[i + 1:i + 1 + len(body)] == body and lines[i + 1 + len(body)] == ""
    assert _horizon_tldr_line(ctx) in lines
    assert apply_brief_guards(out, ctx) == out


# ── Ăn khớp với phần còn lại ────────────────────────────────────────────────────

def test_detect_stance_ignores_the_trend_line():
    from vnstock_brief import _detect_stance
    tldr = ("**Kết quả phiên:** VNINDEX giảm.\n**Stance ngày mai:** TRUNG TÍNH — chờ.\n"
            "**Trung hạn:** GIẢM từ 02/10 → không mua đuổi nhịp hồi.")
    assert _detect_stance(tldr) == "neutral"
    # "ĐI NGANG" của dòng 3 là từ khoá TRUNG TÍNH của fallback ⇒ phải bị bỏ trước khi đếm
    no_label = "Phiên chờ tín hiệu.\n**Trung hạn:** ĐI NGANG từ 24/07 → không nâng tỷ trọng."
    assert _detect_stance(no_label) == "unknown"
    assert _detect_stance(no_label.replace("**Trung hạn:**", "")) == "neutral"


def test_known_levels_include_horizon_levels():
    from vnstock_brief import _known_index_levels
    vt = {"close": 1737.71, "ma20": 1790.0, "horizon_levels": [1802.4, 1853.08, 2600.0]}
    assert 1802.4 in _known_index_levels(vt) and 1853.08 in _known_index_levels(vt)
    assert 2600.0 not in _known_index_levels(vt)      # ngoài dải chỉ số ⇒ lọc


def test_switch_off_keeps_ctx_free_of_horizons(monkeypatch):
    import vnstock_brief
    assert vnstock_brief.horizons_enabled() is False
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    assert vnstock_brief.horizons_enabled() is True


def test_prompt_with_horizons_carries_the_section_and_the_rule(monkeypatch):
    from vnstock_brief import _horizon_body_lines, build_prompt
    p = build_prompt({"date": "2026-10-13", "time": "15:30", **_ctx()}, brief_type="afternoon")
    assert "## 🔭 Góc nhìn theo khung thời gian" in p
    assert _horizon_body_lines(_ctx())[0] in p
    assert "TỐI ĐA 1 câu" in p and "## 🎯 TLDR (3 dòng)" in p
    assert "## 🎯 TLDR (3 dòng)" not in build_prompt(
        {"date": "2026-10-13", "time": "15:30"}, brief_type="afternoon")


def test_finalize_guard_delta_ignores_the_code_inserted_section():
    from vnstock_brief_pack import _guard_delta
    from vnstock_brief import enforce_horizon_view
    fixed = enforce_horizon_view(_AGENT, _ctx())
    assert _guard_delta(_AGENT, fixed) == 0
    assert _guard_delta(_AGENT, fixed + "\nthêm") == len("\nthêm")


# ── brief_view: ctx["horizons"] từ state đã lưu ────────────────────────────────

def test_brief_view_counts_sessions_weeks_and_breadth_from_saved_inputs():
    import vnstock_horizons_state as hs
    days, d = [], date(2026, 8, 3)
    while len(days) < 60:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    inputs = {x.isoformat(): {"close": 1700.0 + i, "breadth_pct": float(i % 30)}
              for i, x in enumerate(days)}
    last, prev = days[-1].isoformat(), days[-2].isoformat()
    snap = _snap(as_of=last, short_since=days[-5].isoformat(), medium_since=days[-12].isoformat())
    st = {"inputs": inputs, "published": [_snap(as_of=prev), snap]}
    lp = hs.Latest(state=st, snap=snap, missing=None, expect=days[-1])
    v = hs.brief_view(lp)
    assert v["stale"] is False and v["snap"] is snap and v["prev"]["as_of"] == prev
    assert v["short_sessions"] == 5
    assert v["medium_weeks"] == len({x.isocalendar()[:2] for x in days[-12:]})
    assert v["breadth_pct"] == float(59 % 30) and v["breadth_pct_4w"] == float(39 % 30)
    assert 1802.4 in v["known_levels"] and 1853.08 in v["known_levels"]
    assert round(1853.08 * 0.9, 2) in v["known_levels"]

    stale = hs.Latest(state=st, snap=_snap(as_of=prev), missing=None, expect=days[-1])
    assert hs.brief_view(stale) == {"stale": True, "as_of": prev, "reason": stale.reason}


# ── Sau review #21: ctx giàu, idempotent, chỗ đặt khi thiếu TLDR, mức S/R ──────

def _rich_ctx(**over) -> dict:
    """ctx gần thật: tâm lý đúng nhãn hệ thống, vnindex_tech có S/R, vĩ mô 3 dòng."""
    c = _ctx(market_sentiment={"mood": "❄️ Sợ hãi", "momentum": -35},
             vnindex_tech={"close": 1737.71, "ma20": 1790.12, "ma50": 1801.5,
                           "ma200": 1650.44, "support_1": 1720.5, "resistance_1": 1760.2,
                           "resistance_2": 1790.12, "day_change_pct": -0.66,
                           "horizon_levels": [1802.4, 1853.08, 1667.77, 1781.99, 1801.32]},
             breadth={"pct_above_ma200": 9.0},
             macro=[{"key": "pmi", "label": "PMI sản xuất", "value": 51.9, "unit": "điểm",
                     "as_of": "2026-10-01", "prev_as_of": "2026-09-01",
                     "change": {"dir": -1, "delta": -1.4}},
                    {"key": "usdvnd", "label": "Tỷ giá USD/VND", "value": 26219.0,
                     "unit": "VND", "as_of": "2026-10-13", "prev_as_of": "2026-10-10",
                     "change": {"dir": 1, "delta": 80.0, "pct": 0.3}},
                    {"key": "interbank_1w", "label": "Lãi suất LNH 1 tuần", "value": 4.5,
                     "unit": "%/năm", "as_of": "2026-10-13", "prev_as_of": "2026-10-10",
                     "change": {"dir": 1, "delta": 0.2}}])
    c.update(over)
    return c


_AGENT_UP = _AGENT.replace("**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,720.50 → "
                           "mục tiêu S2=1,700.10; hủy nếu vượt lại R1=1,760.20.",
                           "**Stance ngày mai:** TĂNG — canh mua nếu vượt R1=1,760.20 → mục "
                           "tiêu R2=1,790.12; hủy nếu thủng S1=1,720.50.")


_UPTREND = _view(snap=_snap(short=CHUA_RO, score=1, medium=TANG, medium_since="2026-09-04",
                           alert={"tier": 0, "anchor": None, "since": None},
                           stance={"forced": None, "allowed": ["TĂNG", "TRUNG TÍNH", "GIẢM"]},
                           levels=[{"kind": "leave_tang", "price": 1700.3, "reachable": True}]),
                 prev=None)


@pytest.mark.parametrize("text,view", [(_AGENT, None), (_AGENT_UP, _UPTREND)])
def test_rich_ctx_chain_is_idempotent_even_with_the_stance_caveat(text, view):
    """Review #21: caveat "⚠️ Stance nghiêng TĂNG…" (momentum -35) chèn dưới dòng
    Stance từng làm lượt 2 nhân đôi dòng "**Trung hạn:**" (gửi lại --from-file)."""
    from vnstock_brief import _HORIZON_TITLE, _horizon_body_lines, apply_brief_guards
    ctx = _rich_ctx(**({"horizons": view} if view else {}))
    once = apply_brief_guards(text, ctx)
    if view:
        assert "tâm lý thị trường đang TIÊU CỰC" in once      # caveat ⚠️ thật sự được chèn
    assert apply_brief_guards(once, ctx) == once
    assert once.count("**Trung hạn:**") == 1 and once.count(_HORIZON_TITLE) == 1
    i = once.split("\n").index(_HORIZON_TITLE)
    body = _horizon_body_lines(ctx)
    assert once.split("\n")[i + 1:i + 1 + len(body)] == body
    assert any("tâm lý ❄️ Sợ hãi" in ln for ln in body)
    assert any("Vĩ mô (chưa chấm): PMI 51.9 ▼ · USD/VND 26,219 ▲ · LNH 1 tuần 4.5% ▲."
               in ln for ln in body)


def test_macro_snippet_kill_switch_is_captured_in_ctx(monkeypatch):
    import vnstock_horizons_state as hs
    from vnstock_brief import _horizon_body_lines, _load_horizons
    monkeypatch.setattr(hs, "latest_published", lambda *a, **k: "LP")
    monkeypatch.setattr(hs, "brief_view", lambda lp: _view())
    monkeypatch.setenv("VNSTOCK_HORIZON_MACRO", "0")
    ctx = _rich_ctx()
    _load_horizons(ctx)
    monkeypatch.delenv("VNSTOCK_HORIZON_MACRO")      # pack --from-file: env đổi cũng không sao
    assert ctx["horizons"]["macro"] is False
    assert not any("Vĩ mô" in ln for ln in _horizon_body_lines(ctx))


def test_no_two_decimal_number_outside_the_known_levels():
    import re
    from vnstock_brief import _horizon_body_lines, _horizon_tldr_line
    ctx = _rich_ctx()
    ctx["macro"][2]["value"] = 6.2
    text = "\n".join(_horizon_body_lines(ctx) + [_horizon_tldr_line(ctx)])
    assert re.findall(r"\d\.\d{2}\b", text) == []


@pytest.mark.parametrize("text,first_heading", [
    (_AGENT.replace("## 🎯 TLDR", "## TLDR"), "## TLDR"),
    (_AGENT.replace("## 🎯 TLDR\n", ""), None),
])
def test_without_the_emoji_heading_the_section_still_follows_the_tldr(text, first_heading):
    from vnstock_brief import _HORIZON_TITLE, _detect_stance, _horizon_tldr_line, \
        apply_brief_guards
    ctx = _rich_ctx()
    out = apply_brief_guards(text, ctx)
    lines = out.split("\n")
    assert lines.index(_HORIZON_TITLE) > lines.index(_horizon_tldr_line(ctx))
    assert "**Kết quả phiên:**" in out and "**Stance ngày mai:**" in out
    assert apply_brief_guards(out, ctx) == out
    if first_heading:
        assert lines[0] == first_heading


def test_no_tldr_at_all_puts_the_section_at_the_end():
    from vnstock_brief import _HORIZON_TITLE, enforce_horizon_view
    out = enforce_horizon_view("## 📊 Tổng kết phiên\nx\n", _ctx())
    assert out.startswith("## 📊 Tổng kết phiên") and _HORIZON_TITLE in out


def test_every_agent_written_section_is_replaced():
    from vnstock_brief import _HORIZON_TITLE, enforce_horizon_view
    dup = _AGENT + f"\n{_HORIZON_TITLE}\n- Trung hạn: TĂNG mạnh\n"
    out = enforce_horizon_view(dup, _ctx())
    assert out.count(_HORIZON_TITLE) == 1 and "TĂNG mạnh" not in out


def test_sr_guard_never_pins_a_support_to_an_alert_threshold():
    """Review #21: thiếu support_2 ⇒ S2 đúng (MA200) từng bị ghim về 1,667.77 (90% neo 🚨)."""
    from vnstock_brief import enforce_sr_direction
    ctx = _rich_ctx()
    text = "**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,745.00 → mục tiêu S2=1,650.44."
    out = enforce_sr_direction(text, ctx)
    assert "1,667.77" not in out


def test_malformed_snapshot_degrades_to_not_updated():
    from vnstock_brief import _horizon_render
    bad = _view(snap={"as_of": "2026-10-13", "short": "?", "score": "x"})
    body, tldr = _horizon_render(_ctx(bad))
    assert body == ["- 🔭 chưa cập nhật (as_of 13/10)."] and tldr is None


def test_template_swap_needs_every_anchor():
    from vnstock_brief import _swap_horizon_template
    tmpl = "## 🎯 TLDR (2 dòng)\n**Kết quả phiên:** x\n## 📊 Tổng kết phiên\n"
    assert _swap_horizon_template(tmpl) == tmpl


def test_load_horizons_fills_ctx_and_known_levels(monkeypatch):
    import vnstock_horizons_state as hs
    from vnstock_brief import _load_horizons
    monkeypatch.setattr(hs, "latest_published", lambda *a, **k: "LP")
    monkeypatch.setattr(hs, "brief_view", lambda lp: _view(known_levels=[1802.4, 1853.08]))
    ctx = {"vnindex_tech": {"close": 1737.71}}
    _load_horizons(ctx)
    assert ctx["horizons"]["snap"]["medium"] == GIAM
    assert ctx["vnindex_tech"]["horizon_levels"] == [1802.4, 1853.08]
    monkeypatch.setattr(hs, "brief_view", lambda lp: {"stale": True, "as_of": "2026-10-09"})
    ctx = {"vnindex_tech": {"close": 1737.71}}
    _load_horizons(ctx)
    assert ctx["horizons"]["stale"] and "horizon_levels" not in ctx["vnindex_tech"]
    monkeypatch.setattr(hs, "latest_published", lambda *a, **k: 1 / 0)
    ctx = {}
    _load_horizons(ctx)                    # đọc hỏng ⇒ "chưa cập nhật", không im như công tắc tắt
    assert ctx["horizons"]["stale"] is True and ctx["horizons"]["as_of"] is None
    from vnstock_brief import _horizon_body_lines
    assert _horizon_body_lines(ctx) == ["- 🔭 chưa cập nhật (chưa đọc được state 3 khung)."]


@pytest.mark.parametrize("pending,closed,expect", [
    (0, False, "chỉ rời GIẢM khi 2 tuần liền đóng trên ~1,802 (mức tuần này, tính lại mỗi tuần)"),
    (0, True, "chỉ rời GIẢM khi 2 tuần liền đóng trên ~1,802 (mức tuần tới, tính lại mỗi tuần)"),
    (1, True, "rời GIẢM nếu tuần tới đóng trên ~1,802 (đã có 1/2 tuần)"),
])
def test_tldr_counts_pending_weeks_and_names_next_week_on_friday(pending, closed, expect):
    from vnstock_brief import _horizon_tldr_line
    view = _view(snap=_snap(pending=pending, week_closed=closed))
    assert _horizon_tldr_line(_ctx(view)).endswith(expect + ".")


def test_tier_two_alert_reads_as_escalated_not_started():
    from vnstock_brief import _horizon_body_lines
    view = _view(snap=_snap(alert={"tier": 2, "anchor": 1853.08, "since": "2026-10-01"}))
    line = next(ln for ln in _horizon_body_lines(_ctx(view)) if ln.startswith("- 🚨"))
    assert line.startswith("- 🚨 Rủi ro ngắn hạn: BẬT từ 01/10, đã lên mức 2, neo đỉnh ~1,853")


@pytest.mark.parametrize("as_of,since,closed,weeks", [
    ("2026-10-02", "2026-10-02", True, 1),       # thứ Sáu đổi trạng thái = tuần 1
    ("2026-10-05", "2026-10-02", False, 1),
    ("2026-10-13", "2026-10-02", False, 2),
    ("2026-10-01", "2026-07-24", False, 10),     # mẫu §4(A): "từ 24/07, 10 tuần"
    ("2026-10-13", "2026-10-05", False, 2),      # thứ Sáu nghỉ ⇒ hiệu lực thứ Hai
])
def test_medium_weeks_count_closed_weeks(as_of, since, closed, weeks):
    import vnstock_horizons_state as hs
    snap = _snap(as_of=as_of, medium_since=since, short_since=since, week_closed=closed)
    st = {"inputs": {as_of: {"close": 1700.0, "breadth_pct": 9.0}}, "published": [snap]}
    v = hs.brief_view(hs.Latest(state=st, snap=snap, missing=None,
                                expect=date.fromisoformat(as_of)))
    assert v["medium_weeks"] == weeks


def test_agent_written_trend_line_variants_are_replaced():
    from vnstock_brief import _detect_stance, enforce_horizon_view
    text = _AGENT.replace("\n\n## 📊", "\n- **Trung hạn:** TĂNG mạnh\n\n## 📊")
    out = enforce_horizon_view(text, _ctx())
    assert "TĂNG mạnh" not in out and out.count("Trung hạn:**") == 1
    assert _detect_stance("**Stance ngày mai:** — x\n- **Trung hạn:** TĂNG giá") == "unknown"


def test_pack_round_trip_keeps_horizons(tmp_path):
    from vnstock_brief_pack import read_pack, write_pack
    pack = {"version": 2, "brief_type": "afternoon", "session": "2026-10-13",
            "prompt": "p", "ctx": _rich_ctx()}
    back = read_pack(write_pack(pack, tmp_path / "brief_pack.json"))
    assert back["ctx"]["horizons"] == pack["ctx"]["horizons"]


_STATES = {
    "giam_alert1": _view(),
    "flat_pending": _view(snap=_snap(medium=DI_NGANG, medium_since="2026-07-24", pending=1,
                                     short=CHUA_RO, score=1,
                                     stance={"forced": None, "allowed": ["TRUNG TÍNH", "GIẢM"]},
                                     alert={"tier": 0, "anchor": None, "since": None},
                                     levels=[{"kind": "to_giam", "price": 1766.2, "reachable": True},
                                             {"kind": "to_tang", "price": 1890.5,
                                              "reachable": False}])),
    "uptrend": _UPTREND,
    "alert2": _view(snap=_snap(alert={"tier": 2, "anchor": 1853.08, "since": "2026-10-01"})),
    "stale": {"stale": True, "as_of": "2026-10-09", "reason": "cũ"},
}


@pytest.mark.parametrize("name", list(_STATES))
@pytest.mark.parametrize("text", [_AGENT, _AGENT_UP])
def test_every_state_is_byte_stable_through_the_whole_chain(name, text):
    from vnstock_brief import _HORIZON_TITLE, _horizon_render, apply_brief_guards
    ctx = _rich_ctx(horizons=_STATES[name])
    ctx["allocation"]["capped_by"] = {"by": "horizons", "why": "trung hạn GIẢM",
                                      "proposed_band": "B3", "proposed_pct": 30}
    once = apply_brief_guards(text, ctx)
    assert apply_brief_guards(once, dict(ctx)) == once
    body, tldr = _horizon_render(ctx)
    lines = once.split("\n")
    i = lines.index(_HORIZON_TITLE)
    assert lines[i + 1:i + 1 + len(body)] == body
    assert (tldr in lines) if tldr else "**Trung hạn:**" not in once

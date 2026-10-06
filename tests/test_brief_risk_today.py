"""Mục '⚠️ Rủi ro cần lưu ý' theo PHƠI NHIỄM danh mục (risk_today, 06/10).

Đặc tả: docs/THIET-KE-MUC-RUI-RO.md. Khối cũ "Đòn bẩy cao nhất VTZ/VJC/PET ·
Op.CF thấp nhất KBC/NVL" lặp y hệt nhiều tháng vì số BCTC năm đứng yên và phép
chọn là xếp hạng cực trị trên một nhóm ổn định — nó không nối với gì của NGÀY.
Mục mới do code dựng từ thứ user đang phơi nhiễm hôm nay: danh mục 📌, lệnh mở
ở footer, ngành của chúng, GDKHQ, tiền tệ/khối ngoại biến động mạnh. User chốt
06/10: bỏ khối cực trị khỏi brief ngày (câu 1 = b — in lại khi có kỳ BCTC mới
là pha 2), CÓ tính 16 lệnh footer là phơi nhiễm (câu 2).

Lưới canh: golden 05/10 ở CẢ HAI chế độ (công tắc tắt phải ra y hệt brief cũ),
idempotent toàn chuỗi, đơn vị NGHÌN ↔ ĐỒNG của giá quy đổi, từ vựng cấm, và
dòng model không được lén mang số/đòn bẩy trở lại.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pytest

import vnstock_brief as vb
from vnstock_brief_canon import (
    _RISK_FALLBACK_LINE,
    _RISK_FORBIDDEN_VOCAB,
    _RISK_LINE_PREFIXES,
    _RISK_TODAY_RULES,
    _fmt_footer_price,
)
from vnstock_brief_guards_common import _is_section_start
from vnstock_brief_guards_sections import (
    _risk_agent_line_ok,
    _risk_exposure,
    _risk_today_lines,
    enforce_risk_today,
)

_BONUS = "Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%"

GOLD_P1 = (
    "- Danh mục tập trung 100% vào nhóm tài chính: SSI 55% · EIB 45% giá trị đang giữ "
    "(theo giá hiện tại); vốn ngoại đang rút khỏi nhóm này: Ngân hàng bán ròng -2,783 tỷ "
    "(1 tuần), mạnh nhất thị trường; SSB cùng ngành Ngân hàng với EIB giảm 7.4% sau 5 "
    "phiên. Theo dõi: khối ngoại còn bán ròng nhóm Ngân hàng ở phiên kế tiếp."
)
GOLD_R = (
    "- GDKHQ chạm lệnh mở GMD (MUA @78): Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ "
    "50.0% ngày 2026-10-07; mốc @78 tương đương ≈52 sau quy đổi quyền, entry/TP/SL "
    "trong sổ CHƯA quy đổi. Theo dõi: phiên 2026-10-07 giá về quanh mức quy đổi là "
    "điều chỉnh cơ học, không phải tín hiệu chạm SL."
)
LEGACY_05_10 = [
    "- Vốn ngoại: VN10Y−US10Y = -0.75 điểm %, chênh lệch âm vẫn gây áp lực lên tỷ giá.",
    "- Tin ngành: EVN điều chỉnh giá điện, nhóm sản xuất chịu thêm chi phí.",
    "Đòn bẩy cao nhất (phi tài chính): VTZ D/E=2.81, VJC D/E=2.74, PET D/E=2.41 — "
    "VTZ cao nhất trong nhóm theo dõi.",
    "Lưu chuyển tiền HĐKD thấp nhất: KBC Op.CF=-17,344 tỷ (BĐS), NVL Op.CF=-6,145 tỷ (BĐS).",
    "(Lưu ý: Op.CF âm của mã (BĐS) chủ yếu do tích lũy quỹ đất/hàng tồn kho dự án — vốn "
    "lưu động, KHÔNG phải lỗ HĐKD; soi thêm D/E và nợ vay.)",
]

RAW_0510 = """## 🎯 TLDR
- VNINDEX giảm về 1,753.20, khối ngoại bán ròng mạnh nhóm Ngân hàng.
- Stance ngày mai: GIẢM.

## 📋 Watchlist sáng mai
1. **SSB** (Giá 18,950) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 18,500
2. **DCM** (Giá 36,100) — canh MUA NẾU vượt 37,000

## ⚠️ Rủi ro cần lưu ý
- Vốn ngoại: VN10Y−US10Y = -0.75 điểm %, chênh lệch âm vẫn gây áp lực lên tỷ giá.
- Tin ngành: EVN điều chỉnh giá điện, nhóm sản xuất chịu thêm chi phí.
- Đòn bẩy cao nhất (phi tài chính): VTZ D/E=2.81 — VTZ cao nhất trong nhóm theo dõi.
- KBC Op.CF=-17,344 tỷ (BĐS) là rủi ro dòng tiền.

## 📅 Sự kiện sắp tới
- KDH: Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0% — ngày 2026-10-07

## 📌 Danh mục đang giữ
- EIB: 20,000 cp | vốn 20.50 | hiện 16.40 | lỗ -20.0% → GIỮ, chờ nhóm ngân hàng ổn định

## 💡 Đề xuất giao dịch
- DRI MUA @12.5, chốt lời 13.6, cắt lỗ 11.9 (chiến lược #69)
"""


def _macro(key, label, value, unit, kind, as_of, *, pct=None, delta=None,
           prev_as_of="2026-10-02"):
    """Đúng hình dạng một dòng `vnstock_macro.load_macro`."""
    return {"key": key, "label": label, "value": value, "unit": unit, "kind": kind,
            "source": "test", "as_of": as_of, "prev_as_of": prev_as_of,
            "prev_value": value - (delta or 0),
            "change": {"pct": pct, "delta": delta,
                       "dir": 1 if (delta or 0) > 0 else (-1 if (delta or 0) < 0 else 0)}}


def _recs_0510():
    base = datetime(2026, 10, 5, 19, 0)
    rows = [("GMD", 78.0, 11)] + [(t, 20.0, 0) for t in ("DRI", "BFC", "DGW", "HDA", "DXP")]
    rows += [(t, 30.0, 4) for t in ("FPT", "MWG2", "HPG", "VNM", "PNJ", "REE", "GAS", "MSN",
                                     "VHC", "CTR")]
    return [{"ticker": t, "action": "BUY", "entry": px, "tp": px * 1.1, "sl": px * 0.95,
             "horizon_days": 20, "created_at": (base - timedelta(days=a)).isoformat(),
             "age_days": a} for t, px, a in rows]


def _ctx_0510(**over) -> dict:
    ctx = {
        "date": "2026-10-05", "time": "15:30", "brief_type": "afternoon", "risk_today": True,
        "portfolio": [
            {"ticker": "EIB", "qty": 20000, "buy_price": 20.5, "last_close": 16.4,
             "pnl_pct": -20.0},
            {"ticker": "SSI", "qty": 20000, "buy_price": 23.4, "last_close": 19.65,
             "pnl_pct": -16.0},
        ],
        "financial_tickers": {"EIB", "SSI", "SSB", "NAB", "HDB"},
        "realestate_tickers": {"KBC", "NVL", "KDH"},
        "tickers": [
            {"Mã": "EIB", "Ngành": "Ngân hàng", "NN 1T (tỷ)": -10, "Giá 1T %": -2},
            {"Mã": "SSI", "Ngành": "Chứng khoán", "NN 1T (tỷ)": -20, "Giá 1T %": -1},
            {"Mã": "SSB", "Ngành": "Ngân hàng", "Giá 1T %": -7.4, "GTGD TB (tỷ)": 40},
            {"Mã": "GMD", "Ngành": "Vận tải", "Giá 1T %": 1.0},
            {"Mã": "VTZ", "Ngành": "Nhựa"}, {"Mã": "KBC", "Ngành": "Bất động sản"},
        ],
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -2783},
            {"Ngành": "Bán lẻ & Thương mại", "NN 1T (tỷ)": -1277},
            {"Ngành": "Họ VIN", "NN 1T (tỷ)": -801},
            {"Ngành": "Họ M", "NN 1T (tỷ)": -120},
            {"Ngành": "Chứng khoán", "NN 1T (tỷ)": -90},
            {"Ngành": "Bảo hiểm", "NN 1T (tỷ)": 20},
            {"Ngành": "Khai khoáng & Tài nguyên", "NN 1T (tỷ)": 3249},
        ],
        "vn30_losers": [
            {"Mã": "SSB", "Giá 1T %": -7.4, "Ngành": "Ngân hàng", "GTGD TB (tỷ)": 40,
             "last": 18.95},
            {"Mã": "DCM", "Giá 1T %": -5.5, "Ngành": "Hoá chất", "GTGD TB (tỷ)": 60,
             "last": 36.1},
            {"Mã": "VPI", "Giá 1T %": -5.1, "Ngành": "Bất động sản", "GTGD TB (tỷ)": 35,
             "last": 60.2},
        ],
        "open_recs": _recs_0510(),
        "upcoming_events": [
            {"ticker": "KDH", "ex_date": "2026-10-07",
             "title": "Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%"},
            {"ticker": "MWG", "ex_date": "2026-10-07",
             "title": "Trả cổ tức bằng tiền mặt - Đợt 2 2025 - 1,000 VND"},
            {"ticker": "GMD", "ex_date": "2026-10-07", "title": _BONUS},
        ],
        "vn30_fundamentals": {
            "VTZ": {"de": 2.81}, "VJC": {"de": 2.74}, "PET": {"de": 2.41},
            "KBC": {"de": 1.1, "ocf": -17344}, "NVL": {"ocf": -6145},
            "EIB": {"de": 9.0}, "SSI": {"de": 2.0},
        },
        "macro": [
            _macro("usdvnd", "Tỷ giá USD/VND", 26219.0, "VND", "fx", "2026-10-05",
                   pct=0.03, delta=8.0),
            _macro("interbank_on", "LNH qua đêm", 3.64, "%/năm", "rate", "2026-10-05",
                   pct=-30.0, delta=-1.56),
            _macro("govt_bond_yield_10y", "Lợi suất TPCP 10Y", 3.98, "%/năm", "rate",
                   "2026-10-03", pct=-0.3, delta=-0.01),
        ],
        "market_sentiment": {"mood": "Tiêu cực", "momentum": -40,
                             "signals": [{"name": "NN ròng 1D", "value": "-284 tỷ",
                                          "dir": -1}]},
        "bias_floor": {"dir": "GIẢM"},
        "vnindex_tech": {"close": 1753.2},
    }
    ctx.update(over)
    return ctx


def _section(text: str) -> list:
    lines = text.splitlines()
    s = next(i for i, l in enumerate(lines)
             if _is_section_start(l) and "rủi ro cần lưu ý" in l.lower())
    e = next((i for i in range(s + 1, len(lines)) if _is_section_start(lines[i])),
             len(lines))
    return [l for l in lines[s + 1:e] if l.strip()]


def _chain(ctx, raw=RAW_0510):
    return vb.apply_brief_guards(raw, ctx)


# ── Golden 05/10 ────────────────────────────────────────────────────────────

def test_new_mode_golden_0510():
    out = _chain(_ctx_0510())
    sec = _section(out)
    assert sec == [GOLD_P1, GOLD_R]
    body = "\n".join(sec)
    for gone in ("VTZ", "KBC", "D/E", "Op.CF", "VN10Y", "KDH", "MWG", "EVN"):
        assert gone not in body, gone


@pytest.mark.parametrize("mode", ["missing", False])
def test_legacy_mode_golden_0510(mode):
    """Công tắc tắt (hoặc pack cũ thiếu khoá) ⇒ mục ra Y HỆT brief cũ."""
    ctx = _ctx_0510()
    if mode == "missing":
        ctx.pop("risk_today")
    else:
        ctx["risk_today"] = False
    raw = RAW_0510.replace(
        "- Đòn bẩy cao nhất (phi tài chính): VTZ D/E=2.81 — VTZ cao nhất trong nhóm theo dõi.\n"
        "- KBC Op.CF=-17,344 tỷ (BĐS) là rủi ro dòng tiền.\n", "")
    assert _section(_chain(ctx, raw)) == LEGACY_05_10


@pytest.mark.parametrize("mode", [True, False])
def test_full_chain_idempotent_both_modes(mode):
    ctx = _ctx_0510(risk_today=mode)
    once = _chain(ctx)
    assert _chain(ctx, once) == once


def test_chain_position():
    import inspect

    import vnstock_brief_guards as g
    src = inspect.getsource(g.apply_brief_guards)
    pos = {n: src.index(f"{n}(") for n in (
        "enforce_exdate_levels", "enforce_reference_band_wording", "enforce_risk_today",
        "enforce_number_format")}
    assert (pos["enforce_exdate_levels"] < pos["enforce_reference_band_wording"]
            < pos["enforce_risk_today"] < pos["enforce_number_format"])


# ── Biến thể: dòng code đi qua toàn chuỗi phải nguyên byte ──────────────────

def _variant(name):
    c = _ctx_0510()
    if name == "a_no_portfolio":
        c.pop("portfolio")
    elif name == "b_held_move":
        c["portfolio"] = [{"ticker": "HPG", "qty": 1000, "buy_price": 30.0,
                           "last_close": 27.0, "pnl_pct": -10.0, "chg_1d_pct": -3.5,
                           "last_bar": "2026-10-05", "sr_support": 25.1}]
        c["tickers"] = c["tickers"] + [{"Mã": "HPG", "Ngành": "Thép", "NN 1T (tỷ)": -80,
                                         "Giá 1T %": -9}]
    elif name == "c_new_rec_realestate":
        c["open_recs"] = c["open_recs"] + [{"ticker": "KDH", "action": "BUY", "entry": 30.0,
                                             "age_days": 0}]
        c["vn30_fundamentals"] = {**c["vn30_fundamentals"], "KDH": {"de": 0.5, "ocf": -1234}}
    elif name == "d_held_cash_dividend":
        c["portfolio"] = [{"ticker": "FPT", "qty": 100, "buy_price": 24.0,
                           "last_close": 25.0, "pnl_pct": 4.2}]
        c["upcoming_events"] = c["upcoming_events"] + [
            {"ticker": "FPT", "ex_date": "2026-10-06",
             "title": "Trả cổ tức bằng tiền, 1.500 đồng/cổ phiếu"}]
    elif name == "e_fx":
        c["macro"] = [_macro("usdvnd", "Tỷ giá USD/VND", 26330.0, "VND", "fx", "2026-10-05",
                             pct=0.45, delta=118.0)]
    elif name == "f_foreign_1d":
        c.pop("portfolio")
        c["market_sentiment"] = {"signals": [{"name": "NN ròng 1D", "value": "-1,500 tỷ"}]}
    return c


_VARIANTS = ["a_no_portfolio", "b_held_move", "c_new_rec_realestate",
             "d_held_cash_dividend", "e_fx", "f_foreign_1d"]
_EXPECT_PREFIX = {"b_held_move": "- Mã đang giữ HPG", "c_new_rec_realestate": "- Cơ bản lệnh mới KDH",
                  "d_held_cash_dividend": "- GDKHQ chạm mã đang giữ FPT",
                  "e_fx": "- Tiền tệ xấu đi", "f_foreign_1d": "- Khối ngoại bán ròng mạnh"}


@pytest.mark.parametrize("name", _VARIANTS)
def test_roundtrip_variants(name):
    ctx = _variant(name)
    code = _risk_today_lines(ctx, RAW_0510)
    out = _chain(ctx)
    sec = _section(out)
    assert sec[:len(code)] == code, "dòng code bị guard phía sau sửa"
    assert _chain(ctx, out) == out
    if name in _EXPECT_PREFIX:
        assert any(l.startswith(_EXPECT_PREFIX[name]) for l in code), code
    if name == "c_new_rec_realestate":
        assert any("tích lũy quỹ đất" in l for l in code)


def test_variant_texts_are_exact():
    b = _risk_today_lines(_variant("b_held_move"))
    assert b[0] == ("- Mã đang giữ HPG: khối ngoại bán ròng chính mã này -80 tỷ (1 tuần); "
                    "giảm 9.0% sau 5 phiên; giảm 3.5% trong ngày 2026-10-05. Theo dõi: "
                    "HPG thủng 25.10 (hỗ trợ pivot 60 phiên).")
    d = _risk_today_lines(_variant("d_held_cash_dividend"))
    assert d[0].startswith("- GDKHQ chạm mã đang giữ FPT: Trả cổ tức bằng tiền, 1.500 "
                           "đồng/cổ phiếu ngày 2026-10-06; giá tham chiếu ≈23.5 sau quy đổi "
                           "quyền (giá hiện tại 25.00).")


@pytest.mark.parametrize("name", _VARIANTS)
def test_code_lines_forbidden_vocabulary_and_en_numbers(name):
    for line in _risk_today_lines(_variant(name)):
        assert line.startswith(_RISK_LINE_PREFIXES)
        assert not _is_section_start(line)
        for w in _RISK_FORBIDDEN_VOCAB:
            assert w not in line, (w, line)
        assert not re.search(r"\d{1,3}(\.\d{3})+,\d", line), line


# ── Tầng P ──────────────────────────────────────────────────────────────────

def test_p1_custom_group_mapping():
    """EIB thuộc 'Họ M' — số NN của Ngân hàng KHÔNG được gán cho EIB (R10)."""
    line = _risk_today_lines(_ctx_0510())[0]
    for clause in re.split(r"[;:]", line):
        assert not ("EIB" in clause and "-2,783" in clause), clause
    assert "nhóm tài chính" in line and "SSB cùng ngành Ngân hàng với EIB" in line


def test_p1_needs_adverse_flow_and_two_positions():
    calm = _ctx_0510(sectors=[{"Ngành": "Ngân hàng", "NN 1T (tỷ)": 300},
                              {"Ngành": "Bán lẻ", "NN 1T (tỷ)": -900},
                              {"Ngành": "Thép", "NN 1T (tỷ)": -700},
                              {"Ngành": "Dầu khí", "NN 1T (tỷ)": -600}])
    assert not any(l.startswith("- Danh mục tập trung") for l in _risk_today_lines(calm))
    one = _ctx_0510(portfolio=[_ctx_0510()["portfolio"][0]])
    lines = _risk_today_lines(one)
    assert not any(l.startswith("- Danh mục tập trung") for l in lines)
    assert any(l.startswith("- Mã đang giữ EIB") and "Ngân hàng bán ròng -2,783" in l
               for l in lines), lines


def test_p_triggers_are_dynamic():
    c = _variant("b_held_move")
    c["portfolio"][0]["last_bar"] = "2026-10-02"          # bar cũ ⇒ không dùng % ngày
    line = _risk_today_lines(c)[0]
    assert "trong ngày" not in line
    many = _ctx_0510(portfolio=[
        {"ticker": t, "qty": q, "last_close": 10.0} for t, q in
        (("HPG", 100), ("HSG", 300), ("NKG", 200))],
        tickers=[{"Mã": t, "Ngành": "Thép", "Giá 1T %": -9} for t in ("HPG", "HSG", "NKG")],
        sectors=[{"Ngành": "Thép", "NN 1T (tỷ)": 50}], open_recs=[])
    held = [l for l in _risk_today_lines(many) if l.startswith("- Mã đang giữ")]
    assert [l.split()[4] for l in held] == ["HSG:", "NKG:"]   # theo trọng số, trần P = 2


# ── Tầng R / P4: GDKHQ ──────────────────────────────────────────────────────

def test_r_exdate_units_and_anchor():
    c = _ctx_0510(open_recs=[{"ticker": "AAA", "action": "BUY", "entry": 25.0, "age_days": 3}],
                  upcoming_events=[{"ticker": "AAA", "ex_date": "2026-10-06",
                                    "title": "Trả cổ tức bằng tiền, 1.500 đồng/cổ phiếu"}],
                  portfolio=[])
    line = _risk_today_lines(c)[0]
    assert "≈23.5" in line and "@25" in line and "CHƯA quy đổi" in line   # quên ×1000 ⇒ ≈23.5 mất
    meet = _ctx_0510(open_recs=c["open_recs"], portfolio=[],
                     upcoming_events=[{"ticker": "AAA", "ex_date": "2026-10-06",
                                       "title": "Đại hội cổ đông thường niên 2026"}])
    assert _risk_today_lines(meet) == []
    far = _ctx_0510(open_recs=c["open_recs"], portfolio=[],
                    upcoming_events=[{"ticker": "AAA", "ex_date": "2026-10-12",
                                      "title": _BONUS}])
    assert _risk_today_lines(far) == []
    unread = _ctx_0510(open_recs=c["open_recs"], portfolio=[],
                       upcoming_events=[{"ticker": "AAA", "ex_date": "2026-10-06",
                                         "title": "Quyền mua cổ phiếu, tỷ lệ 5:1"}])
    assert "tự điều chỉnh" in _risk_today_lines(unread)[0]


def test_r_anchor_is_the_session_date_not_the_wall_clock():
    """Neo theo ctx['date']: brief phiên 06/01/2025 vẫn thấy sự kiện 08/01/2025
    dù đồng hồ máy đã ở 2026."""
    c = _ctx_0510(date="2025-01-06", portfolio=[],
                  open_recs=[{"ticker": "GMD", "action": "BUY", "entry": 78.0, "age_days": 2}],
                  upcoming_events=[{"ticker": "GMD", "ex_date": "2025-01-08", "title": _BONUS}])
    assert "≈52" in _risk_today_lines(c)[0]


def test_r_skips_ticker_already_flagged_elsewhere():
    raw = RAW_0510.replace("- DRI MUA @12.5", "- GMD MUA @78 · ⚠️ GDKHQ 2026-10-07 (x)\n- DRI MUA @12.5")
    assert not any("GMD" in l for l in _risk_today_lines(_ctx_0510(), raw))


# ── Tầng F: cơ bản cho lệnh MỚI ──────────────────────────────────────────────

def _f_ctx(recs, funds, **over):
    return _ctx_0510(open_recs=recs, vn30_fundamentals=funds, upcoming_events=[],
                     **over)


def test_f_new_recs_only_nonfinancial():
    new = {"ticker": "DRI", "action": "BUY", "entry": 12.5, "age_days": 0}
    lines = _risk_today_lines(_f_ctx([new], {"DRI": {"de": 2.10}}))
    f = [l for l in lines if l.startswith("- Cơ bản lệnh mới")]
    assert f and "D/E=2.10 (BCTC gần nhất)" in f[0]
    old = {**new, "age_days": 5}
    assert not any(l.startswith("- Cơ bản") for l in _risk_today_lines(
        _f_ctx([old], {"DRI": {"de": 2.10}})))
    bank = {"ticker": "NAB", "action": "BUY", "entry": 14.0, "age_days": 0}
    assert not any(l.startswith("- Cơ bản") for l in _risk_today_lines(
        _f_ctx([bank], {"NAB": {"de": 9.0}})))
    held = {"ticker": "HPG", "action": "BUY", "entry": 27.0, "age_days": 0}
    c = _f_ctx([held], {"HPG": {"de": 3.0}},
               portfolio=[{"ticker": "HPG", "qty": 100, "last_close": 27.0}])
    assert not any(l.startswith("- Cơ bản") for l in _risk_today_lines(c))
    for l in lines:
        assert "cao nhất" not in l


def test_f_line_survives_realestate_ocf_guard():
    from vnstock_brief_guards_sections import enforce_realestate_ocf_context
    c = _variant("c_new_rec_realestate")
    out = _chain(c)
    assert enforce_realestate_ocf_context(out, c) == out


# ── Tầng M ──────────────────────────────────────────────────────────────────

def test_m3_m4_and_level_gauges_never_print():
    c = _ctx_0510(portfolio=[])
    c["macro"] = c["macro"] + [_macro("vn10y_us10y_spread", "VN10Y−US10Y", -0.75, "điểm %",
                                      "spread", "2026-10-05", delta=0.4)]
    assert not any("VN10Y" in l for l in _risk_today_lines(c))
    stale = _ctx_0510(portfolio=[], macro=[_macro("usdvnd", "Tỷ giá USD/VND", 26500.0,
                                                  "VND", "fx", "2026-09-28", pct=0.9,
                                                  delta=236.0)])
    assert not any(l.startswith("- Tiền tệ") for l in _risk_today_lines(stale))
    with_p1 = _ctx_0510(market_sentiment={"signals": [{"name": "NN ròng 1D",
                                                       "value": "-1,500 tỷ"}]})
    lines = _risk_today_lines(with_p1)
    assert any(l.startswith("- Danh mục tập trung") for l in lines)
    assert not any(l.startswith("- Khối ngoại bán ròng mạnh") for l in lines)


# ── Dòng của model (R9) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("line", [
    "- EIB lỗ 20% cần cắt sớm.",
    "- Danh mục dùng đòn bẩy margin cao.",
    "- EIB D/E cao, rủi ro nợ.",
    "- VTZ có nợ vay lớn, tránh.",
    "- EVN tăng giá điện làm khó nhóm sản xuất.",
])
def test_agent_line_filter_drops(line):
    c = _ctx_0510()
    assert not _risk_agent_line_ok(line, c, _risk_exposure(c))


def test_agent_line_filter_keeps_one_portfolio_line_last():
    keep = "- Danh mục EIB, SSI cùng nhóm, dễ chịu áp lực tin ngành."
    raw = RAW_0510.replace("- Tin ngành: EVN", keep + "\n- Khối ngoại bán ròng nhóm tài "
                           "chính kéo dài.\n- Danh mục còn thêm rủi ro khác.\n- Tin ngành: EVN")
    sec = _section(_chain(_ctx_0510(), raw))
    assert sec == [GOLD_P1, GOLD_R, keep]


def test_agent_line_dropped_when_it_repeats_a_code_kind():
    c = _ctx_0510()
    raw = RAW_0510.replace("- Tin ngành: EVN", "- Khối ngoại bán ròng nhóm tài chính.\n"
                                               "- Tin ngành: EVN")
    assert _section(_chain(c, raw)) == [GOLD_P1, GOLD_R]


# ── Dự phòng, chèn mục, parity sáng ─────────────────────────────────────────

def test_fallback_and_insert():
    quiet = _ctx_0510(portfolio=[], open_recs=[], upcoming_events=[])
    assert _section(_chain(quiet)) == [_RISK_FALLBACK_LINE]
    no_sec = RAW_0510.split("## ⚠️ Rủi ro cần lưu ý")[0] + "## 📅 Sự kiện sắp tới\n- x\n"
    out = enforce_risk_today(no_sec, _ctx_0510())
    lines = out.splitlines()
    i = lines.index("## ⚠️ Rủi ro cần lưu ý")
    assert lines[i + 1] == GOLD_P1 and "📅" in out.split("## ⚠️ Rủi ro cần lưu ý")[1]
    morning = enforce_risk_today(no_sec, _ctx_0510(brief_type="morning"))
    assert "## ⚠️ Rủi ro cần lưu ý (phiên chiều)" in morning
    assert enforce_risk_today(no_sec, quiet) == no_sec
    assert enforce_risk_today(RAW_0510, _ctx_0510(brief_type="allocation")) == RAW_0510


def test_morning_parity():
    raw = RAW_0510.replace("## ⚠️ Rủi ro cần lưu ý", "## ⚠️ Rủi ro cần lưu ý (phiên chiều)")
    assert _section(_chain(_ctx_0510(brief_type="morning"), raw)) == [GOLD_P1, GOLD_R]


# ── Prompt ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bt", ["morning", "afternoon"])
def test_prompt_new_mode(bt):
    c = _ctx_0510(brief_type=bt)
    p = vb.build_prompt(c, brief_type=bt)
    assert _RISK_TODAY_RULES in p
    for line in _risk_today_lines(c):
        assert line in p
    assert "CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng" not in p
    assert "(số BCTC gần nhất; lấy" in vb._vn30_fund_block(
        {"VTZ": {"de": 2.81, "updated": "2026-10-04"}}, risk_today=True)
    old = dict(c)
    old.pop("risk_today")
    p_old = vb.build_prompt(old, brief_type=bt)
    assert "CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng" in p_old
    assert "Dữ kiện rủi ro hôm nay" not in p_old


@pytest.mark.parametrize("tmpl", ["_MORNING_TEMPLATE", "_AFTERNOON_TEMPLATE"])
def test_swap_replaces_exactly_one_block(tmpl):
    t = getattr(vb, tmpl)
    out = vb._swap_risk_rules(t)
    assert out.count(_RISK_TODAY_RULES) == 1
    assert out.count("## ") == t.count("## ")
    out.format(system="s", data="d")                 # template vẫn .format được


def test_fund_block_legacy_header_unchanged():
    assert "(cập nhật 2026-10-04)" in vb._vn30_fund_block(
        {"VTZ": {"de": 2.81, "updated": "2026-10-04"}})


# ── Công tắc + loader ───────────────────────────────────────────────────────

def test_risk_today_enabled_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_BRIEF_RISK"):
            monkeypatch.delenv(k)
    monkeypatch.setattr(vb, "_ENV_LOADED", True)
    assert vb._risk_today_enabled("afternoon") is True
    for v in ("0", "false", "off", "no"):
        monkeypatch.setenv("VNSTOCK_BRIEF_RISK_TODAY", v)
        assert vb._risk_today_enabled("morning") is False
    monkeypatch.delenv("VNSTOCK_BRIEF_RISK_TODAY")
    assert vb._risk_today_enabled("allocation") is False
    import inspect
    src = inspect.getsource(vb.collect_context)
    for needle in ("'risk_today': _risk_today_enabled(brief_type)".replace("'", '"'),
                   "_attach_portfolio_levels(", "_load_open_recs("):
        assert needle in src


def test_open_recs_match_telegram_footer(monkeypatch, tmp_path):
    import vnstock_memory as vm
    import vnstock_telegram as tg
    now = datetime.now()
    opens = [{"ticker": t, "action": "BUY", "entry_price": 20.0, "take_profit": 22.0,
              "cut_loss": 19.0, "horizon_days": 5, "strategy_id": sid,
              "created_at": (now - timedelta(days=1)).isoformat()}
             for t, sid in (("AAA", 1), ("BBB", 2), ("CCC", 1))]
    monkeypatch.setattr(vm, "open_recommendations", lambda: opens)
    monkeypatch.setattr(vb, "_validation_of_strategy",
                        lambda sid: {"known": True, "passed": sid == 1, "p": 0.5,
                                     "reasons": []})
    monkeypatch.setattr(vb, "_active_strategy_validation",
                        lambda ctx=None: {"known": False, "passed": False, "p": None,
                                          "reasons": []})
    mine = {r["ticker"] for r in vb._load_open_recs(now.date().isoformat(), opens)}
    footer = set(re.findall(r"<b>([A-Z]{3})</b>", tg._open_recs_block()))
    assert mine == footer == {"AAA", "CCC"}
    db = tmp_path / "_meta" / "brief_memory.db"
    monkeypatch.setattr(vm, "DB_PATH", db)
    assert vb._load_open_recs("2026-10-05") == [] and not db.exists()


def test_pack_roundtrip_carries_mode(tmp_path):
    from vnstock_brief_pack import PACK_VERSION, read_pack, write_pack
    ctx = _ctx_0510()
    p = write_pack({"version": PACK_VERSION, "prompt": "x", "ctx": ctx}, tmp_path / "p.json")
    back = read_pack(p)["ctx"]
    assert back["risk_today"] is True
    assert vb.apply_brief_guards(RAW_0510, back) == vb.apply_brief_guards(RAW_0510, ctx)


def test_risk_numbers_no_bank_leak():
    from vnstock_brief_guards_numbers import enforce_risk_numbers
    c = _ctx_0510()
    txt = "## ⚠️ Rủi ro cần lưu ý\n- EIB, SSI lỗ nặng giữa lúc NN bán ròng ngân hàng.\n"
    assert enforce_risk_numbers(txt, c) == txt
    wrong = "## ⚠️ Rủi ro cần lưu ý\n- VJC D/E=9.99 là rủi ro đòn bẩy.\n"
    assert "VJC D/E=2.74" in enforce_risk_numbers(wrong, c)       # (b) vẫn sửa số sai


@pytest.mark.parametrize("p", [0, 0.5, 9.21, 78, 139.4])
def test_footer_price_format_is_one_source(p):
    import vnstock_telegram as tg
    assert _fmt_footer_price(p) == tg._fmt_price(p)


# ── Sổ brief_watch: mục Rủi ro lặp y hệt ────────────────────────────────────

def test_scan_risk_repeat():
    import vnstock_brief_watch as w
    assert w.scan_risk_repeat("## 🎯 TLDR\n- x\n") == []
    a = w.scan_risk_repeat(f"## ⚠️ Rủi ro cần lưu ý\n{GOLD_P1}\n\n## 📅 X\n")
    b = w.scan_risk_repeat(f"## ⚠️ Rủi ro cần lưu ý\n{GOLD_P1}\n## 📌 Y\n- khác\n")
    assert a[0]["digest"] == b[0]["digest"] and a[0]["codes"] == ["- Danh mục tập trung"]


def _write_watch(root, events):
    (root / "_meta").mkdir(parents=True, exist_ok=True)
    (root / "_meta" / "brief_watch.json").write_text(json.dumps({"events": events}),
                                                     encoding="utf-8")


def test_summarize_counts_risk_pairs_without_touching_old_counters(tmp_path):
    import vnstock_brief_watch as w
    ev = [{"kind": "risk_section", "digest": d, "at": f"2026-10-0{i}", "host": "h"}
          for i, d in enumerate(["a", "a", "b", "b", "b"], start=1)]
    _write_watch(tmp_path, ev)
    st = w.summarize(tmp_path)
    assert (st["risk_pairs"], st["risk_repeats"]) == (4, 3)
    assert st["n_days"] == 0 and st["enough"] is False


def test_doctor_badge_risk_repeat(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path / "_meta")
    few = [{"kind": "risk_section", "digest": "a", "at": f"2026-10-0{i}"} for i in (1, 2, 3)]
    _write_watch(tmp_path, few)
    r = doc.check_brief_watch()
    assert r["status"] == "ok" and "n=2" in r["message"]
    many = [{"kind": "risk_section", "digest": "a", "at": f"2026-09-{d:02d}"}
            for d in range(20, 28)]
    _write_watch(tmp_path, many)
    r = doc.check_brief_watch()
    assert r["status"] == "warn" and "VNSTOCK_BRIEF_RISK_TODAY" in r["fix"]

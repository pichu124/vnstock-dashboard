"""PTKT P2c+P3 — thẻ kỹ thuật vào brief + guard chữ kỹ thuật (`VNSTOCK_TA_CARD`).

Đặc tả: `docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §10d (code nói dữ kiện, model ≤3 câu nhận định,
guard giữ ranh giới), §6, §16 (RSI > 70 = đà mạnh), §17–§18 (S/R là MỐC THAM CHIẾU, biên 1 ATR).

Lưới canh: golden chụp TRƯỚC khi nối (công tắc tắt ⇒ prompt + output guard giống từng byte),
bản mẫu prompt khi bật, brief giả lập cố tình sai ra đúng sau chuỗi guard, idempotent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_GOLDEN = Path(__file__).parent / "golden" / "brief_ta_card_off.json"


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")


def _vt() -> dict:
    return {
        "close": 1733.2, "prev_close": 1720.0, "day_change_pct": 0.77,
        "day_high": 1740.1, "day_low": 1718.3, "week_high": 1745.6, "week_low": 1700.4,
        "month_high": 1760.9, "month_low": 1680.2, "high_52w": 1800.5, "low_52w": 1200.7,
        "ma20": 1712.5, "ma50": 1690.1, "ma200": 1600.3, "ma20_slope_pct": 0.5,
        "rsi14": 75.3, "chop14": 45.2, "candle_patterns": ["Bullish Engulfing"],
        "ha_streak": 3, "support_1": 1705.5, "support_2": 1690.25,
        "resistance_1": 1748.8, "resistance_2": 1765.4, "data_date": "2026-11-04",
        "intraday": False,
    }


def _ctx_off(brief_type: str = "afternoon") -> dict:
    return {
        "date": "2026-11-04", "time": "15:30" if brief_type == "afternoon" else "11:30",
        "brief_type": brief_type,
        "vnindex_tech": _vt(),
        "vn30_gainers": [
            {"Mã": "FPT", "Giá 1T %": 4.2, "Ngành": "Công nghệ", "last": 112.5,
             "GTGD TB (tỷ)": 300.0, "sr_support": 108.3, "sr_resistance": 118.0},
            {"Mã": "DGC", "Giá 1T %": 6.1, "Ngành": "Hoá chất", "last": 95.4,
             "GTGD TB (tỷ)": 15.0},
        ],
        "vn30_losers": [
            {"Mã": "HPG", "Giá 1T %": -3.1, "Ngành": "Thép", "last": 25.35,
             "GTGD TB (tỷ)": 500.0, "sr_support": 24.8, "sr_resistance": 26.9},
        ],
        "portfolio": [{"ticker": "EIB", "qty": 20000, "buy_price": 20.5, "last_close": 16.4,
                       "pnl_pct": -20.0}],
    }


# Chữ model CỐ TÌNH sai ở mục 📈: số bịa (1,812.00), xu hướng ngược thẻ ("giảm" khi thẻ TĂNG),
# "hỗ trợ sẽ giữ", "vượt R1" không kèm KL, RSI 75 gọi "quá mua", 5 câu (quá 3).
RAW = """## 🎯 TLDR (2 dòng)
**Kết quả phiên:** VNINDEX đóng cửa 1,733.20 (+0.77%), GTGD vừa phải.
**Stance ngày mai:** TĂNG — canh mua nếu vượt R1=1,748.80 → mục tiêu R2=1,765.40; hủy nếu thủng S1=1,705.50

## 📊 Tổng kết phiên
VNINDEX tăng 0.77% hôm nay.

## 📈 Mức kỹ thuật chốt phiên (VNINDEX)
**Đóng cửa:** 1,733.20 (+0.77%)
- Xu hướng MA20: GIẢM — dưới MA20 -9.99%
**Nhận định:** VN-Index giữ xu hướng giảm ngắn hạn dù đóng trên MA20. RSI 75.3 vùng quá mua, cảnh báo điều chỉnh. Hỗ trợ sẽ giữ quanh S1 1,705.50 nên chắc chắn bật lên. Nếu vượt R1 1,748.80 thì mở đường lên 1,812.00. Thủng S1 1,705.50 là về S2 1,690.25.

## 📋 Watchlist sáng mai
1. **FPT** (Giá 112,500) — canh MUA NẾU vượt 118,000 · chốt lời 124,000 · cắt lỗ 108,000

## ⚠️ Rủi ro cần lưu ý
- Không có rủi ro đặc biệt.
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _off_outputs() -> dict:
    """Prompt sáng/chiều + output chuỗi guard với ctx KHÔNG có khoá thẻ (công tắc tắt)."""
    import vnstock_brief as vb
    out = {}
    for bt in ("morning", "afternoon"):
        ctx = _ctx_off(bt)
        out[f"prompt|{bt}"] = _sha(vb.build_prompt(ctx, brief_type=bt))
        out[f"guards|{bt}"] = _sha(vb.apply_brief_guards(RAW, _ctx_off(bt)))
    return out


def _golden() -> dict:
    g = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    return {k: v for k, v in g.items() if not k.startswith("_")}


def test_off_prompt_and_guards_are_byte_identical_to_pre_change_golden():
    """Công tắc tắt ⇒ ctx không có khoá thẻ ⇒ prompt sáng/chiều + output chuỗi guard y hệt bản
    chụp TRƯỚC khi nối (751bdd3)."""
    assert _off_outputs() == _golden()


def test_env_on_but_ctx_without_card_is_still_identical(monkeypatch):
    """Env bật nhưng ctx thiếu khoá (pack cũ / loader hỏng) ⇒ y nguyên: prompt + guard chỉ đọc ctx."""
    monkeypatch.setenv("VNSTOCK_TA_CARD", "1")
    assert _off_outputs() == _golden()


# ── Thẻ giả lập (hàm thuần `brief_lines`/`brief_facts`/`card_labels` trên dict thẻ) ──────────

def _card(close, *, short, medium, long_, rsi, vol, ma20=None, slope=None, sma200_pct=None,
          atr=None, sr=None, as_of="2026-11-04", conflicts=()):
    import vnstock_ta_card as tc
    lv = None
    if sr:
        lv = {"support_1": sr.get("s1"), "support_2": sr.get("s2"),
              "resistance_1": sr.get("r1"), "resistance_2": sr.get("r2")}
        lv["s1_atr"] = (close - lv["support_1"]) / atr if lv["support_1"] else None
        lv["r1_atr"] = (lv["resistance_1"] - close) / atr if lv["resistance_1"] else None
    return {
        "label": "", "as_of": as_of, "close": close, "n_bars": 400,
        "short": {"label": short, "ma20": ma20, "ma20_slope_pct": slope,
                  "rsi": rsi, "rsi_label": tc.rsi_label(rsi),
                  "vol_ratio": vol, "vol_confirmed": None if vol is None else vol >= tc.VOL_MULT},
        "medium": {"label": medium},
        "long": {"label": long_, "sma200_dist_pct": sma200_pct},
        "volatility": {"atr": atr, "atr_pct": atr / close * 100 if atr else None},
        "levels": lv, "broke_support": False, "conflicts": list(conflicts),
    }


def _ta_ctx(brief_type: str = "afternoon") -> dict:
    """ctx như `collect_context` dựng khi `VNSTOCK_TA_CARD=1` (thẻ VN-Index khớp `vnindex_tech`)."""
    import vnstock_ta_card as tc
    vni = _card(1733.2, short="TĂNG", medium="GIẢM", long_="TĂNG", rsi=75.3, vol=1.3,
                ma20=1712.5, slope=0.5, atr=25.0,
                sr={"s1": 1705.5, "s2": 1690.25, "r1": 1748.8, "r2": 1765.4},
                conflicts=[tc.CONFLICT_SHORT_UP_MEDIUM_DOWN, tc.CONFLICT_MACD_DOWN_ABOVE_MA20])
    fpt = _card(112.5, short="TĂNG", medium="ĐI NGANG", long_="TĂNG", rsi=64.0, vol=1.4,
                sma200_pct=8.0, atr=3.0, sr={"s1": 108.3, "r1": 118.0})
    eib = _card(16.4, short="GIẢM", medium="GIẢM", long_="GIẢM", rsi=35.2, vol=0.8,
                sma200_pct=-12.5, as_of="2026-10-28")
    ctx = _ctx_off(brief_type)
    ctx["vnindex_tech"]["ta_levels"] = [1708.2, 1758.2]
    ctx["ta_card"] = {**tc.card_labels(vni), "label": "VN-Index",
                      "day_change_pct": ctx["vnindex_tech"]["day_change_pct"],
                      "lines": tc.brief_lines(vni, "2026-11-04")}
    ctx["ta_cards"] = {tk: {**tc.card_labels(c), "label": tk,
                            "line": tc.brief_facts(c, "2026-11-04", price_scale=1000)}
                       for tk, c in (("EIB", eib), ("FPT", fpt))}
    return ctx


CARD_LINES = [
    "- Phiên 2026-11-04 · đóng cửa 1,733.20",
    "- Xu hướng MA20: TĂNG — trên MA20 +1.21% (MA20 dốc +0.50%/5 phiên) · RSI 75.3 đà mạnh · "
    "KL 1.30× TB20 xác nhận",
    "- Mức tham chiếu: S1 1,705.50 (1.11 ATR) · R1 1,748.80 (0.62 ATR) · kế tiếp S2 1,690.25 / "
    "R2 1,765.40 · biên 1 ATR: 1,708.20–1,758.20",
    "- Tín hiệu lệch nhau: ngắn hạn tăng mà trung hạn giảm",
]


def test_brief_lines_vnindex_variant_exact():
    """VN-Index trong brief: không trung/dài hạn, không MACD (kể cả tín hiệu lệch suy từ MACD),
    không ATR%; có biên 1 ATR và S2/R2 kế tiếp."""
    assert _ta_ctx()["ta_card"]["lines"] == CARD_LINES


def test_brief_facts_ticker_variant_exact():
    cards = _ta_ctx()["ta_cards"]
    assert cards["FPT"]["line"] == (
        "xu hướng MA20 TĂNG · tuần ĐI NGANG · dài TĂNG (SMA200 +8.00%) · RSI 64.0 mạnh · "
        "KL 1.40× TB20 xác nhận · S1 108,300 (1.40 ATR) / R1 118,000 (1.83 ATR)")
    assert cards["EIB"]["line"].startswith(
        "⚠️ Dữ liệu dừng từ 2026-10-28 (số dưới đây là của phiên đó) · xu hướng MA20 GIẢM")
    for line in (cards["FPT"]["line"], cards["EIB"]["line"]):
        assert "MACD" not in line and "52 tuần" not in line and "ATR(" not in line


def test_card_labels_are_json_compact():
    lab = _ta_ctx()["ta_card"]
    json.dumps(lab)                                   # không DataFrame / numpy
    assert (lab["short"], lab["medium"], lab["rsi_label"], lab["vol_confirmed"]) == (
        "TĂNG", "GIẢM", "đà mạnh", True)
    assert (lab["band_lo"], lab["band_hi"], lab["s1"], lab["r1"]) == (1708.2, 1758.2, 1705.5, 1748.8)
    assert lab["conflicts"] == ["ngắn hạn tăng mà trung hạn giảm"]


# Brief giả lập khi BẬT: model chép sai dòng thẻ, 4 câu nhận định cố tình sai — xu hướng ngược thẻ,
# RSI 75.3 "quá mua, cảnh báo", số bịa 1,812.00, "hỗ trợ sẽ giữ", "vượt/thủng" không kèm KL,
# "thủng là về S2".
RAW_ON = RAW.replace(
    "**Nhận định:** VN-Index giữ xu hướng giảm ngắn hạn dù đóng trên MA20. RSI 75.3 vùng quá mua, "
    "cảnh báo điều chỉnh. Hỗ trợ sẽ giữ quanh S1 1,705.50 nên chắc chắn bật lên. Nếu vượt R1 "
    "1,748.80 thì mở đường lên 1,812.00. Thủng S1 1,705.50 là về S2 1,690.25.",
    "**Nhận định:** VN-Index giữ xu hướng giảm dù đóng trên MA20, RSI 75.3 vùng quá mua, cảnh "
    "báo điều chỉnh. Nếu vượt R1 1,748.80 thì mở đường lên 1,812.00. Hỗ trợ sẽ giữ quanh S1 "
    "1,705.50; vượt R1 1,748.80 thì mức kế tiếp R2 1,765.40, thủng S1 1,705.50 là về S2 "
    "1,690.25. Mức huỷ là đóng cửa dưới S2 1,690.25.")

GUARDED_SECTION = [
    "## 📈 Mức kỹ thuật chốt phiên (VNINDEX)",
    *CARD_LINES,
    # câu 1 (xu hướng + RSI ngược thẻ) và câu 2 (số bịa) bị BỎ; câu 3 mất hai mệnh đề hứa hẹn;
    # câu 4 = MỨC HUỶ được GIỮ (trần 3 câu chọn theo vai — replay 05/10→04/11: cắt theo vị trí làm
    # mất mức huỷ 17/20 phiên)
    "**Nhận định:** Vượt R1 1,748.80 (cần KL ≥ 1.2× TB20) thì mức kế tiếp R2 1,765.40. "
    "Mức huỷ là đóng cửa dưới S2 1,690.25.",
]


def _ta_section(text: str) -> list[str]:
    from vnstock_brief_guards_common import _is_section_start, is_ta_heading
    lines = text.splitlines()
    s = next(i for i, l in enumerate(lines) if is_ta_heading(l))
    e = next((j for j in range(s + 1, len(lines)) if _is_section_start(lines[j])), len(lines))
    return [l for l in lines[s:e] if l.strip()]


def test_simulated_brief_comes_out_right_after_full_chain():
    import vnstock_brief as vb
    out = vb.apply_brief_guards(RAW_ON, _ta_ctx())
    assert _ta_section(out) == GUARDED_SECTION
    assert "1,812" not in out and "1,800.50" not in out      # câu số bịa bị bỏ (không ghim số khác)
    assert "Mức huỷ là đóng cửa dưới S2 1,690.25." in out   # vai "mức huỷ" giữ dù là câu thứ 4


@pytest.mark.parametrize("bt", ["afternoon", "morning"])
def test_full_chain_idempotent_when_on(bt):
    import vnstock_brief as vb
    ctx = _ta_ctx(bt)
    once = vb.apply_brief_guards(RAW_ON, ctx)
    assert vb.apply_brief_guards(once, _ta_ctx(bt)) == once


def test_chain_position_after_number_guards_before_number_format():
    import inspect

    import vnstock_brief_guards as g
    src = inspect.getsource(g.apply_brief_guards)
    # bỏ mệnh đề hứa hẹn TRƯỚC guard số/chữ: chúng phán phần còn lại (idempotent ở lượt 2)
    order = ["enforce_scenario_levels", "enforce_range_position", "enforce_ta_card_block",
             "enforce_ta_no_level_promise", "enforce_ta_numbers", "enforce_ta_trend_words",
             "enforce_ta_rsi_words", "enforce_ta_breakout_volume", "enforce_number_format"]
    pos = [src.index(f"{n}(") for n in order]
    assert pos == sorted(pos)


# ── Từng guard ───────────────────────────────────────────────────────────

_TA_GUARDS = ["enforce_ta_card_block", "enforce_ta_numbers", "enforce_ta_trend_words",
              "enforce_ta_rsi_words", "enforce_ta_no_level_promise", "enforce_ta_breakout_volume"]


def _guard(name):
    import vnstock_brief_guards as g
    return getattr(g, name)


def _sec(insight: str) -> str:
    return ("## 📊 Tổng kết phiên\nx.\n\n## 📈 Mức kỹ thuật chốt phiên (VNINDEX)\n"
            + "\n".join(CARD_LINES) + f"\n**Nhận định:** {insight}\n\n## 📋 Watchlist sáng mai\n1. A\n")


def _insight(text: str) -> str:
    return next(l for l in text.splitlines() if l.startswith("**Nhận định:**"))[len("**Nhận định:** "):]


@pytest.mark.parametrize("name", _TA_GUARDS)
@pytest.mark.parametrize("variant", ["no_key", "allocation", "empty_lines"])
def test_every_ta_guard_is_noop_without_card(name, variant):
    ctx = _ta_ctx()
    if variant == "no_key":
        ctx.pop("ta_card")
    elif variant == "allocation":
        ctx["brief_type"] = "allocation"
    else:
        ctx["ta_card"]["lines"] = []
    assert _guard(name)(RAW_ON, ctx) == RAW_ON


def test_card_block_rebuilds_edited_card_and_cuts_to_three_sentences():
    raw = _sec("A một. B hai. C ba. D bốn.").replace(CARD_LINES[1], "- Xu hướng MA20: GIẢM")
    out = _guard("enforce_ta_card_block")(raw, _ta_ctx())
    assert _ta_section(out)[1:5] == CARD_LINES
    assert _insight(out) == "A một. B hai. C ba."


def test_card_block_inserted_after_overview_when_model_drops_the_section():
    raw = "## 🎯 TLDR\nt.\n\n## 📊 Tổng kết phiên\nx.\n\n## 📋 Watchlist sáng mai\n1. A\n"
    out = _guard("enforce_ta_card_block")(raw, _ta_ctx())
    assert out == ("## 🎯 TLDR\nt.\n\n## 📊 Tổng kết phiên\nx.\n\n"
                   "## 📈 Mức kỹ thuật chốt phiên (VNINDEX)\n" + "\n".join(CARD_LINES)
                   + "\n\n## 📋 Watchlist sáng mai\n1. A\n")
    morning = _ta_ctx("morning")
    assert "## 📈 Mức kỹ thuật quan trọng (VNINDEX)" in _guard("enforce_ta_card_block")(raw, morning)


def test_card_block_merges_duplicate_sections_and_old_template_lines():
    raw = ("## 📊 Tổng kết phiên\nx.\n\n## Mức kỹ thuật chốt phiên\n**Đóng cửa:** 1,733.20\n"
           "**Hỗ trợ gần:** S1 1,705.50\n**Trigger ngày mai:** vượt R1 1,748.80 có KL\n\n"
           "## 📈 Mức kỹ thuật chốt phiên (VNINDEX)\n- Mức tham chiếu: S1 9\nÝ phụ.\n")
    out = _guard("enforce_ta_card_block")(raw, _ta_ctx())
    sec = _ta_section(out)
    assert sec[0] == "## Mức kỹ thuật chốt phiên" and sec[1:5] == CARD_LINES
    assert _insight(out) == "vượt R1 1,748.80 có KL. Ý phụ."
    assert out.count("Mức tham chiếu") == 1


@pytest.mark.parametrize("line, want", [
    ("## 📈 Mức kỹ thuật chốt phiên (VNINDEX)", True),
    ("## 📈 Mức kỹ thuật quan trọng (VNINDEX)", True),
    ("## Mức kỹ thuật chốt phiên", True),                       # model bỏ emoji / đuôi
    ("## 📈 **Mức kỹ thuật quan trọng (VN-Index)**", True),
    ("## 📈 Mức kỹ thuật", True),
    ("## 📋 Watchlist — mức kỹ thuật cần canh", False),          # mục khác có cụm "mức kỹ thuật"
    ("## ⚠️ Rủi ro: thủng mức kỹ thuật", False),
    ("## 📈 Thẻ kỹ thuật VN-Index", False),
    ("Mức kỹ thuật chốt phiên", False),                          # không phải dòng tiêu đề
])
def test_ta_heading_is_only_the_section_title(line, want):
    from vnstock_brief_guards_common import is_ta_heading
    assert is_ta_heading(line) is want


def test_ta_heading_recognises_every_canon_title():
    from vnstock_brief_canon import TA_SECTION_TITLES
    from vnstock_brief_guards_common import is_ta_heading
    assert all(is_ta_heading(t) for t in TA_SECTION_TITLES.values())


def test_card_block_leaves_other_sections_mentioning_levels_alone():
    raw = _sec("Ý một.") + "\n## ⚠️ Rủi ro: thủng mức kỹ thuật\n- Thủng S1.\n"
    out = _guard("enforce_ta_card_block")(raw, _ta_ctx())
    assert "## ⚠️ Rủi ro: thủng mức kỹ thuật\n- Thủng S1." in out
    assert _insight(out) == "Ý một."


@pytest.mark.parametrize("line, want", [
    ("Phiên chiều mai cần KL.", ["Phiên chiều mai cần KL."]),      # không phải dòng "Phiên <ngày>"
    ("- Phiên 2026-11-04 · đóng cửa 9", []),                       # bản chép dòng thẻ
    ("* **Vị trí so với MA:** trên cả ba", []),                    # khung template cũ
    ("Nếu vượt R1 1,748.80: mục tiêu R2", ["Nếu vượt R1 1,748.80: mục tiêu R2."]),  # không phải nhãn
    ("**Kịch bản:** vượt R1", ["vượt R1."]),
])
def test_card_block_agent_line_rules(line, want):
    from vnstock_brief_guards_sections import _ta_agent_sentences
    assert _ta_agent_sentences([line], CARD_LINES) == want


@pytest.mark.parametrize("insight, kept", [
    ("Đóng cửa quanh 1,733 trên MA20.", True),               # làm tròn
    ("S1 ở 1.705,5 theo cách viết VN.", True),               # định dạng VN
    ("RSI 75.3, trên ngưỡng 70.", True),                      # ngưỡng canon
    ("Biên 1 ATR 1,708.20–1,758.20.", True),
    ("Mục tiêu 1,812.00 nếu bùng nổ.", False),                # số bịa
    ("MA50 1,690.10 là mức kế tiếp.", False),                 # có ở prompt, KHÔNG có ở thẻ
    ("Giá cách R1 0.9%.", False),                             # tự tính
    ("FPT có S1 108.3 nghìn.", True),                         # số của thẻ mã câu nhắc tới
    ("Phiên 04/11 giữ nhịp, MA20 TB20 S1.", True),            # ngày + số dính chữ bỏ qua
])
def test_numbers_guard(insight, kept):
    raw = _sec(insight)
    out = _guard("enforce_ta_numbers")(raw, _ta_ctx())
    assert (out == raw) is kept
    if not kept:
        assert "**Nhận định:**" not in out                     # hết câu ⇒ bỏ cả dòng


def test_numbers_guard_drops_only_the_bad_sentence():
    out = _guard("enforce_ta_numbers")(_sec("Ý đúng 1,733.20. Ý sai 1,812.00. Ý cuối."), _ta_ctx())
    assert _insight(out) == "Ý đúng 1,733.20. Ý cuối."


def _guarded_insight(name: str, insight: str) -> "str | None":
    """Dòng nhận định sau MỘT guard; None = guard bỏ hết câu (dòng thẻ vẫn còn)."""
    out = _guard(name)(_sec(insight), _ta_ctx())
    assert _ta_section(out)[1:5] == CARD_LINES
    return _insight(out) if "**Nhận định:**" in out else None


# Chữ ngược thẻ ⇒ BỎ câu, KHÔNG thay từ (thay từ biến câu đúng thành sai — review 05/11).
@pytest.mark.parametrize("insight, want", [
    ("VN-Index trong xu hướng giảm.", None),
    ("Xu hướng MA20 đi ngang.", None),
    ("Thị trường xu hướng GIẢM.", None),
    ("Ý đúng. VN-Index xu hướng giảm. Ý cuối.", "Ý đúng. Ý cuối."),
    ("EIB xu hướng tăng.", None),                                            # thẻ của mã
    ("VN-Index xu hướng tăng.", "VN-Index xu hướng tăng."),
    ("Xu hướng giảm trung hạn còn đó.", "Xu hướng giảm trung hạn còn đó."),   # khung khác
    ("Không xu hướng giảm nào xuất hiện.", "Không xu hướng giảm nào xuất hiện."),  # phủ định
    ("VN-Index chưa có xu hướng giảm.", "VN-Index chưa có xu hướng giảm."),
    ("FPT xu hướng tăng còn EIB xu hướng giảm.", "FPT xu hướng tăng còn EIB xu hướng giảm."),
    ("HPG xu hướng giảm.", "HPG xu hướng giảm."),                            # mã không có thẻ
    ("HNX-Index xu hướng giảm.", "HNX-Index xu hướng giảm."),                # chỉ số khác
    ("UPCoM xu hướng giảm.", "UPCoM xu hướng giảm."),
    ("RSI cao, xu hướng tăng.", "RSI cao, xu hướng tăng."),                  # RSI không phải mã
])
def test_trend_words_against_the_card(insight, want):
    assert _guarded_insight("enforce_ta_trend_words", insight) == want


@pytest.mark.parametrize("insight, want", [
    ("RSI 75.3 vùng quá mua, cảnh báo điều chỉnh.", None),
    ("RSI 75.3 quá mua.", None),
    ("RSI 75.3 quá mua, chưa có tín hiệu đảo chiều.", None),       # phủ định KHÔNG nhắm vùng
    ("Giá quá mua.", "Giá quá mua."),                               # câu không nói RSI
    ("Tín hiệu quá mua có thể dẫn tới điều chỉnh.", None),          # §16: không cần chữ RSI
    ("EIB RSI 35.2 quá bán.", None),                                # thẻ của mã: yếu
    ("RSI 75.3 là đà mạnh chứ không phải quá mua.", "RSI 75.3 là đà mạnh chứ không phải quá mua."),
    ("Không có tín hiệu quá mua theo RSI.", "Không có tín hiệu quá mua theo RSI."),
    ("RSI 75.3 đà mạnh.", "RSI 75.3 đà mạnh."),
])
def test_rsi_words_against_the_card(insight, want):
    assert _guarded_insight("enforce_ta_rsi_words", insight) == want


def test_rsi_negated_zone_that_is_the_card_label_is_dropped():
    """Thẻ quá bán mà câu nói "không phải quá bán" ⇒ phủ định đúng nhãn thẻ ⇒ sai ⇒ bỏ."""
    ctx = _ta_ctx()
    ctx["ta_card"]["rsi_label"] = "quá bán"
    raw = _sec("RSI không phải quá bán. RSI quá bán.")
    assert _insight(_guard("enforce_ta_rsi_words")(raw, ctx)) == "RSI quá bán."


@pytest.mark.parametrize("insight, want", [
    ("Hỗ trợ sẽ giữ quanh S1.", None),
    ("Hỗ trợ S1 1,705.50 sẽ giữ vững nếu dòng tiền không rút.", None),   # tên mức + số chen giữa
    ("Hỗ trợ gần S1 sẽ đỡ giá, kháng cự R1 sẽ cản.", None),
    ("Kháng cự R1 1,748.80 chắc chắn sẽ chặn đà tăng.", None),
    ("Chắc chắn bật lên.", None),
    ("Thủng S1 là về S2.", None),
    ("Đảm bảo giữ được.", None),
    ("Giá giữ trên MA20, chắc chắn sẽ hồi.", "Giá giữ trên MA20."),       # bỏ MỆNH ĐỀ
    ("Thủng S1 thì chắc chắn sẽ rơi về S2, cần cẩn trọng.", "Cần cẩn trọng."),
    ("Vượt R1 thì mức kế tiếp R2; thủng S1 1,705.50 sẽ về S2 1,690.25.",
     "Vượt R1 thì mức kế tiếp R2."),
    ("RSI đà mạnh nhưng hỗ trợ S1 sẽ giữ.", "RSI đà mạnh."),
    ("Vượt R1 thì lên R2.", "Vượt R1 thì lên R2."),                       # kịch bản nếu–thì
    ("Có thể sẽ về S2 nếu thủng S1.", "Có thể sẽ về S2 nếu thủng S1."),
    ("Chưa chắc chắn S1 giữ được.", "Chưa chắc chắn S1 giữ được."),
    ("Đảm bảo an toàn bằng cách chờ vượt R1.", "Đảm bảo an toàn bằng cách chờ vượt R1."),
    ("Hỗ trợ S1 sẽ giữ, cần theo dõi (S1, MA20).", "Cần theo dõi (S1, MA20)."),  # ngoặc nguyên
])
def test_no_level_promise_drops_the_clause(insight, want):
    assert _guarded_insight("enforce_ta_no_level_promise", insight) == want


def test_promise_clause_drop_then_number_check_is_idempotent():
    """Mã nằm ở mệnh đề bị bỏ, số của mã ở mệnh đề còn lại ⇒ câu mất chủ thể: guard số phán SAU
    khi bỏ mệnh đề (bỏ luôn ở lượt 1, không phải lượt 2)."""
    import vnstock_brief as vb
    raw = _sec("FPT có hỗ trợ sẽ giữ, cách S1 108.3 nghìn. Ý cuối.")
    once = vb.apply_brief_guards(raw, _ta_ctx())
    assert _insight(once) == "Ý cuối."
    assert vb.apply_brief_guards(once, _ta_ctx()) == once


@pytest.mark.parametrize("sentence, want", [
    ("; chắc chắn S2 là về S2 nhưng giá giữ.", "giá giữ."),     # mệnh đề rỗng đầu câu không giữ
    ("; chắc chắn S2.", None),                                  # chỉ còn dấu câu ⇒ bỏ câu
])
def test_drop_clauses_ignores_empty_clauses(sentence, want):
    from vnstock_brief_guards_common import ta_drop_clauses
    from vnstock_brief_guards_text import _ta_promises
    assert ta_drop_clauses(sentence, _ta_promises) == want


def test_level_promise_examples_are_all_caught():
    """Mọi cụm prompt cấm đều có mẫu guard bắt — danh sách là HẰNG dùng chung prompt + guard."""
    import re

    from vnstock_brief_canon import TA_LEVEL_PROMISE_EXAMPLES, TA_LEVEL_PROMISE_PHRASES
    for ex in TA_LEVEL_PROMISE_EXAMPLES:
        assert any(re.search(p, f"thủng S1 {ex}", re.IGNORECASE)
                   for p in TA_LEVEL_PROMISE_PHRASES), ex


@pytest.mark.parametrize("insight, want", [
    ("Vượt R1 1,748.80 thì mức kế tiếp R2.",
     "Vượt R1 1,748.80 (cần KL ≥ 1.2× TB20) thì mức kế tiếp R2."),
    ("Vượt lên trên R1 1,748.80 sẽ xác nhận đà tăng.",
     "Vượt lên trên R1 1,748.80 (cần KL ≥ 1.2× TB20) sẽ xác nhận đà tăng."),
    ("Thủng xuống dưới S1 1,705.50 thì dừng.",
     "Thủng xuống dưới S1 1,705.50 (cần KL ≥ 1.2× TB20) thì dừng."),
    ("Vượt R1 thì R2, thủng S1 thì S2.",                                   # MỘT lần mỗi câu
     "Vượt R1 (cần KL ≥ 1.2× TB20) thì R2, thủng S1 thì S2."),
    ("Thủng hỗ trợ 1,705.50 với KL lớn là tín hiệu xấu.",
     "Thủng hỗ trợ 1,705.50 với KL lớn là tín hiệu xấu."),
    ("Vượt MA20 khi khối lượng tăng.", "Vượt MA20 khi khối lượng tăng."),
    ("Thanh khoản cần cải thiện; vượt R1 mới xác nhận.",
     "Thanh khoản cần cải thiện; vượt R1 mới xác nhận."),
    ("Chỉ số đã vượt MA20.", "Chỉ số đã vượt MA20."),                     # việc đã xảy ra
    ("Giữ trên MA20.", "Giữ trên MA20."),
])
def test_breakout_needs_volume(insight, want):
    assert _guarded_insight("enforce_ta_breakout_volume", insight) == want


def test_breakout_note_uses_card_threshold_without_session_volume():
    ctx = _ta_ctx()
    ctx["ta_card"]["vol_ratio"] = None
    ctx["ta_card"]["vol_mult"] = 1.25
    out = _guard("enforce_ta_breakout_volume")(_sec("Thủng S1 thì dừng."), ctx)
    assert _insight(out) == "Thủng S1 (cần KL ≥ 1.25× TB20) thì dừng."


@pytest.mark.parametrize("insight", [
    "Mức huỷ: đóng cửa dưới S1 1,705.50 2 phiên liên tiếp.",       # số phiên ≤ 10
    "Đóng cửa dưới S1 trong 10 phiên.",
    "Chỉ số tăng 0.77% và giữ trên MA20 1,712.50.",                # day_change_pct + ma20
    "Đóng cửa 1,733.2 điểm.",
])
def test_numbers_guard_allows_sessions_ma20_close_change(insight):
    raw = _sec(insight)
    assert _guard("enforce_ta_numbers")(raw, _ta_ctx()) == raw


@pytest.mark.parametrize("insight", [
    "Đóng cửa dưới S1 trong 11 phiên.",                            # > 10 phiên: không miễn
    "Đóng cửa dưới S1 2.5 phiên.",
    "Chỉ số tăng 1.5% hôm nay.",
])
def test_numbers_guard_still_drops_unknown(insight):
    assert "**Nhận định:**" not in _guard("enforce_ta_numbers")(_sec(insight), _ta_ctx())


# ── Bộ câu của review đối kháng (05/11) qua CẢ chuỗi guard: câu → kỳ vọng ──────────
# None = câu bị bỏ (mục chỉ còn dòng thẻ). Sai ⇒ bỏ câu/mệnh đề; đúng ⇒ giữ nguyên từng chữ.
REVIEW_SENTENCES = [
    # s1.txt
    ("VN-Index duy trì xu hướng giảm dù đóng cửa trên MA20, RSI 75.3 vùng quá mua.", None),
    ("Chỉ số vượt MA50 1,690.10 và MA200 1,600.30, xu hướng tăng được củng cố.", None),  # MA50 ∉ thẻ
    ("VN-Index tăng 0.77% lên 1,733.20 với GTGD 25,000 tỷ.", None),                      # GTGD ∉ thẻ
    ("Nếu vượt R1 1,748.80 và giữ được trên mốc này, chỉ số có thể hướng tới R2 1,765.40; "
     "ngược lại thủng S1 1,705.50 sẽ về S2 1,690.25.",
     "Nếu vượt R1 1,748.80 (cần KL ≥ 1.2× TB20) và giữ được trên mốc này, chỉ số có thể hướng "
     "tới R2 1,765.40."),
    ("Kháng cự R1 1,748.80 chắc chắn sẽ chặn đà tăng trong phiên tới.", None),
    ("Không xu hướng giảm nào xuất hiện khi chỉ số còn trên MA20.", "="),
    ("RSI 75.3 cho thấy đà mạnh, nhưng tín hiệu quá mua có thể dẫn tới điều chỉnh ngắn.", None),
    ("Đảm bảo an toàn bằng cách chờ vượt R1 1,748.80 kèm thanh khoản cải thiện.", "="),
    ("Hỗ trợ S1 1,705.50 sẽ giữ vững nếu dòng tiền không rút.", None),
    ("Ngắn hạn xu hướng tăng nhưng trung hạn xu hướng giảm — tín hiệu lệch nhau.", "="),
    ("Chỉ số cách R1 khoảng 15 điểm, cách S1 khoảng 28 điểm.", None),                     # tự tính
    ("FPT đang trong xu hướng giảm, RSI 64 quá mua.", None),
    ("Phá vỡ 1,750 sẽ mở ra nhịp tăng mới.", None),                                      # số bịa
    ("Giá đóng trên MA20 1,712.50 ba phiên liên tiếp, vượt đỉnh tuần 1,745.60 thì xác nhận.",
     None),                                                                             # đỉnh tuần ∉ thẻ
    ("Mức huỷ: đóng cửa dưới S1 1,705.50 hai phiên liên tiếp với KL ≥ 1.2× TB20.", "="),
    ("Thủng S1 thì chắc chắn sẽ rơi về S2, cần cẩn trọng.", "Cần cẩn trọng."),
    ("VN-Index giữ xu hướng tăng; vượt R1 1,748.80 thì lên R2 1,765.40, thủng S1 1,705.50 thì "
     "xuống S2 1,690.25.",
     "VN-Index giữ xu hướng tăng; vượt R1 1,748.80 (cần KL ≥ 1.2× TB20) thì lên R2 1,765.40, "
     "thủng S1 1,705.50 thì xuống S2 1,690.25."),
    # s2.txt
    ("Mức huỷ: đóng cửa dưới S1 1,705.50 2 phiên liên tiếp.", "="),
    ("Mức huỷ là đóng cửa dưới S1 trong 3 phiên.", "="),
    ("Chỉ số quanh 1.733 điểm, trên MA20.", "="),
    ("Đóng cửa 1.733,20 điểm, cao hơn MA20.", "Đóng cửa 1,733.20 điểm, cao hơn MA20."),  # định dạng EN
    ("Chỉ số tăng 0.77% và giữ trên MA20 1,712.50.", "="),
    ("Xu hướng MA20 tăng với độ dốc +0.5%, KL 1.3 lần TB20.", "="),
    ("VN-Index tăng nhưng HPG xu hướng giảm kéo nhóm thép.", "="),
    ("FPT xu hướng tăng còn EIB xu hướng giảm.", "="),
    ("Dài hạn xu hướng tăng, khung tuần xu hướng giảm.", "="),
    ("Vượt lên trên R1 1,748.80 sẽ xác nhận đà tăng.",
     "Vượt lên trên R1 1,748.80 (cần KL ≥ 1.2× TB20) sẽ xác nhận đà tăng."),
    ("Nếu vượt 1,748.80 thì R2 1,765.40 là đích; nếu thủng 1,705.50 thì S2 1,690.25.",
     "Nếu vượt 1,748.80 (cần KL ≥ 1.2× TB20) thì R2 1,765.40 là đích; nếu thủng 1,705.50 thì "
     "S2 1,690.25."),
    ("Hỗ trợ gần S1 sẽ đỡ giá, kháng cự R1 sẽ cản.", None),
    ("Thanh khoản cần cải thiện; vượt R1 mới xác nhận.", "="),
    ("Chỉ số đã vượt MA20, RSI trên 70 là đà mạnh chứ không phải quá mua.", "="),
    ("Không có tín hiệu quá mua theo RSI.", "="),
    # thêm
    ("EIB xu hướng tăng, RSI 35.2 yếu.", None),
    ("HNX-Index xu hướng giảm, chưa theo VN-Index.", "="),
    ("RSI 75.3 quá mua, chưa có tín hiệu đảo chiều.", None),
    ("Thủng xuống dưới S1 1,705.50 thì mức kế tiếp S2 1,690.25.",
     "Thủng xuống dưới S1 1,705.50 (cần KL ≥ 1.2× TB20) thì mức kế tiếp S2 1,690.25."),
]


def _chain_insight(sentence: str, bt: str = "afternoon") -> "tuple[str | None, str]":
    import vnstock_brief as vb
    start = RAW.index("**Nhận định:**")
    raw = RAW[:start] + "**Nhận định:** " + sentence + RAW[RAW.index("\n", start):]
    out = vb.apply_brief_guards(raw, _ta_ctx(bt))
    sec = _ta_section(out)
    assert sec[1:5] == CARD_LINES                       # mục không bao giờ trống: thẻ của code
    ins = [l for l in sec if l.startswith("**Nhận định:**")]
    return (ins[0][len("**Nhận định:** "):] if ins else None), out


@pytest.mark.parametrize("bt", ["afternoon", "morning"])
@pytest.mark.parametrize("sentence, want", REVIEW_SENTENCES)
def test_review_sentences_through_full_chain(sentence, want, bt):
    import vnstock_brief as vb
    got, out = _chain_insight(sentence, bt)
    assert got == (sentence if want == "=" else want)
    assert vb.apply_brief_guards(out, _ta_ctx(bt)) == out          # idempotent


# ── Prompt khi bật ───────────────────────────────────────────────────────

@pytest.mark.parametrize("bt", ["afternoon", "morning"])
def test_prompt_on_has_card_block_and_section_frame(bt):
    import vnstock_brief as vb
    p = vb.build_prompt(_ta_ctx(bt), brief_type=bt)
    data, tmpl = p.split("\n---\n", 1)
    i = data.index("\n## VNINDEX kỹ thuật (")
    vt_block = data[i:data.index("\n## ", i + 5)]
    for line in CARD_LINES:
        assert line in vt_block
    # thẻ THAY các dòng tự đọc chỉ báo; giữ giá/range/MA/pivot cho guard cũ + TLDR
    for gone in ("MA20 slope", "RSI(14)", "quá mua", "CHOP(14)", "Mẫu nến", "Heikin-Ashi"):
        assert gone not in vt_block, gone
    for kept in ("Giá đóng cửa: **1,733.20**", "Vị trí range tuần", "MA50=1,690.10",
                 "S2=1,690.25 | S1=1,705.50 | R1=1,748.80 | R2=1,765.40"):
        assert kept in vt_block, kept
    # mốc ⭐ của mã có thẻ ⇒ thẻ; mã không có thẻ giữ khối mốc cũ; danh mục ⇒ khối riêng
    assert ("Giá 112,500 ⭐ [thẻ: xu hướng MA20 TĂNG · tuần ĐI NGANG · dài TĂNG (SMA200 +8.00%) · "
            "RSI 64.0 mạnh · KL 1.40× TB20 xác nhận · S1 108,300 (1.40 ATR) / R1 118,000 (1.83 ATR) "
            "— S1/R1 = hỗ trợ/kháng cự pivot 60 phiên, mốc THAM CHIẾU]") in data
    assert "Giá 25,350 ⭐ [hỗ trợ 24,800 / kháng cự 26,900 — pivot 60 phiên]" in data
    assert "\n## Thẻ kỹ thuật mã đang giữ" in data and "- EIB: ⚠️ Dữ liệu dừng từ 2026-10-28" in data
    # khung mục 📈: thẻ do hệ thống chèn, model ≤3 câu nhận định
    j = tmpl.index("## 📈 Mức kỹ thuật")
    sec = tmpl[j:tmpl.index("\n## ", j)]
    assert "**Nhận định:** [TỐI ĐA 3 câu" in sec and '"hỗ trợ sẽ giữ"' in sec and "1.20× TB20" in sec
    for gone in ("Trigger", "Vs MA", "Vị trí so với MA", "Hỗ trợ gần"):
        assert gone not in sec, gone


# ── Dựng ctx (collect_context bước 6b) ───────────────────────────────────

def _bars(closes, start="2025-01-06", volume=1000.0):
    c = np.asarray(closes, dtype=float)
    t = pd.bdate_range(start, periods=len(c))
    return pd.DataFrame({"time": t, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": np.full(len(c), volume)})


def _uptrend(n, start):
    steps = np.full(n, 0.002) + np.where(np.arange(n) % 2, -0.004, 0.004)
    return start * np.exp(np.cumsum(steps))


def _wire(monkeypatch, idx, hist):
    import vnstock_brief as vb
    import vnstock_strategy as vs
    monkeypatch.setattr(vb, "_load_vnindex_df", lambda augment=True: idx)
    monkeypatch.setattr(vs, "_load_history_from_parquet",
                        lambda tk, days, prices_dir=None: hist.get(tk, pd.DataFrame()))


def _built_ctx(idx):
    ctx = _ctx_off()
    vt = ctx["vnindex_tech"]
    vt["close"] = float(idx["close"].iloc[-1])
    ctx["date"] = idx["time"].iloc[-1].date().isoformat()
    vt["support_1"], vt["resistance_1"] = vt["close"] * 0.98, vt["close"] * 1.02
    return ctx


def test_attach_ta_cards_builds_labels_lines_and_ticker_priority(monkeypatch):
    import vnstock_brief as vb
    idx = _bars(_uptrend(320, 1500.0))
    fpt = _uptrend(320, 1.0)
    hist = {"EIB": _bars(_uptrend(300, 15.0)), "FPT": _bars(fpt / fpt[-1] * 112.5),
            "DGC": _bars(_uptrend(320, 90.0))}
    _wire(monkeypatch, idx, hist)
    ctx = _built_ctx(idx)
    vb._attach_ta_cards(ctx)
    ta = ctx["ta_card"]
    json.dumps({"ta_card": ta, "ta_cards": ctx["ta_cards"]})
    assert ta["label"] == "VN-Index" and ta["short"] == "TĂNG" and ta["lines"][0].startswith("- Phiên ")
    assert ta["s1"] == pytest.approx(ctx["vnindex_tech"]["support_1"], abs=1e-3)
    assert not any("đã vượt" in l or "đã thủng" in l for l in ta["lines"])  # mức từ bar cuối
    assert list(ctx["ta_cards"]) == ["EIB", "FPT", "DGC"]   # danh mục → ⭐ → mover; HPG không có kho
    assert ctx["vnindex_tech"]["ta_levels"] == [ta["band_lo"], ta["band_hi"]]
    fpt_line = ctx["ta_cards"]["FPT"]["line"]
    assert "S1 108,300 (" in fpt_line and "R1 118,000 (" in fpt_line   # mức pivot của mover (ctx)
    assert "Dữ liệu dừng" not in fpt_line
    assert ctx["ta_cards"]["EIB"]["line"].startswith("⚠️ Dữ liệu dừng từ")  # bar cuối cũ hơn VN-Index
    assert ctx["ta_cards"]["EIB"]["s1"] is None                         # danh mục: không có mức
    assert "loader_errors" not in ctx


def test_attach_ta_cards_ticker_limit_and_one_bad_ticker(monkeypatch):
    import vnstock_brief as vb
    idx = _bars(_uptrend(320, 1500.0))
    _wire(monkeypatch, idx, {})
    ctx = _built_ctx(idx)
    ctx["vn30_gainers"] = [{"Mã": f"A{i:02d}", "GTGD TB (tỷ)": 100.0} for i in range(20)]
    assert len(vb._ta_card_tickers(ctx)) == vb._TA_CARD_MAX_TICKERS

    import vnstock_strategy as vs

    def _boom(tk, days, prices_dir=None):
        if tk == "FPT":
            raise OSError("parquet hỏng")
        return _bars(_uptrend(300, 20.0))
    monkeypatch.setattr(vs, "_load_history_from_parquet", _boom)
    ctx = _built_ctx(idx)
    vb._attach_ta_cards(ctx)
    assert "FPT" not in ctx["ta_cards"] and "EIB" in ctx["ta_cards"]
    assert "FPT" in ctx["loader_errors"]["ta_cards"]


def test_attach_ta_cards_blanks_live_volume_intraday(monkeypatch):
    import vnstock_brief as vb
    idx = _bars(_uptrend(320, 1500.0))
    _wire(monkeypatch, idx, {})
    ctx = _built_ctx(idx)
    ctx["vnindex_tech"]["intraday"] = True
    vb._attach_ta_cards(ctx)
    assert ctx["ta_card"]["vol_ratio"] is None
    assert any("giá hiện tại" in l for l in ctx["ta_card"]["lines"])
    assert any("KL chưa đủ dữ liệu" in l for l in ctx["ta_card"]["lines"])


def test_collect_context_card_shares_the_vnindex_read_with_vnindex_tech(monkeypatch, tmp_path):
    """Brief sáng có live: WSS ghi file giữa hai lần đọc ⇒ lần đọc thứ hai ra close khác. Thẻ phải
    dựng trên CÙNG bản đọc với ``vnindex_tech`` — không thì ValueError và brief mất thẻ."""
    import vnstock_brief as vb
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VNSTOCK_TA_CARD", "1")
    base = _bars(_uptrend(320, 1500.0))
    reads = []

    def _live_read(augment=True):
        df = base.copy()
        df.loc[df.index[-1], "close"] += len(reads)       # mỗi lần đọc: tick live mới
        reads.append(augment)
        return df
    monkeypatch.setattr(vb, "_load_vnindex_df", _live_read)
    ctx = vb.collect_context("morning")
    assert "ta_card" not in (ctx.get("loader_errors") or {})
    assert ctx["ta_card"]["close"] == pytest.approx(ctx["vnindex_tech"]["close"], abs=1e-3)


def test_star_line_keeps_one_sided_note_when_card_replaces_levels():
    import vnstock_brief as vb
    import vnstock_ta_card as tc
    ctx = _ta_ctx()
    ctx["vn30_gainers"][0]["sr_resistance"] = None
    fpt = _card(112.5, short="TĂNG", medium="ĐI NGANG", long_="TĂNG", rsi=64.0, vol=1.4,
                sma200_pct=8.0, atr=3.0, sr={"s1": 108.3})
    ctx["ta_cards"]["FPT"] = {**tc.card_labels(fpt), "label": "FPT",
                              "line": tc.brief_facts(fpt, "2026-11-04", price_scale=1000)}
    data = vb.build_prompt(ctx, brief_type="afternoon").split("\n---\n", 1)[0]
    fpt_line = next(l for l in data.splitlines() if l.startswith("- FPT "))
    assert fpt_line.endswith("mốc THAM CHIẾU, CHƯA có mốc còn lại trong tầm]")


def test_collect_context_switch(monkeypatch, tmp_path):
    """Tắt ⇒ không gọi bước 6b; bật mà bước 6b ném ⇒ ghi `loader_errors`, ctx không có thẻ."""
    import vnstock_brief as vb
    monkeypatch.chdir(tmp_path)                    # collect_context đọc/ghi `data_warehouse/` tương đối
    calls = []

    def _boom(ctx, idx=None):
        calls.append(1)
        raise RuntimeError("kho lỗi")
    monkeypatch.setattr(vb, "_vnindex_technicals", lambda df=None: {})
    monkeypatch.setattr(vb, "_attach_ta_cards", _boom)
    ctx = vb.collect_context("afternoon")
    assert not calls and "ta_card" not in ctx
    monkeypatch.setenv("VNSTOCK_TA_CARD", "1")
    ctx = vb.collect_context("afternoon")
    assert calls == [1] and "ta_card" not in ctx
    assert ctx["loader_errors"]["ta_card"] == "RuntimeError: kho lỗi"


@pytest.mark.parametrize("val, on", [("1", True), ("true", True), ("on", True), ("0", False),
                                     ("", False), ("no", False)])
def test_switch_values(monkeypatch, val, on):
    import vnstock_ta_card as tc
    monkeypatch.setenv("VNSTOCK_TA_CARD", val)
    assert tc.ta_card_enabled() is on


# ── Trần 3 câu chọn theo VAI (replay 20 phiên 05/10→04/11) ────────────────────

def test_pick_insight_keeps_both_sides_and_invalidation_from_replay_1006():
    from vnstock_brief_guards_sections import ta_pick_insight
    sents = ["Chỉ số dưới MA20 và RSI yếu, xu hướng ngắn hạn giảm.",
             "Chiều giảm: thủng S1 1,744.31 với KL ≥ 1.20× TB20 thì về vùng S2.",
             "Biên 1 ATR là mốc tham chiếu.",
             "Chiều tăng: đóng trên R1 1,768.05 với KL ≥ 1.20× TB20 thì nhịp hồi mở rộng.",
             "Nhận định giảm sai nếu chỉ số đứng vững trên R1 1,768.05 kèm KL xác nhận."]
    out = ta_pick_insight(sents)
    assert out == [sents[0],
                   "Chiều giảm: thủng S1 1,744.31 với KL ≥ 1.20× TB20 thì về vùng S2; chiều tăng: "
                   "đóng trên R1 1,768.05 với KL ≥ 1.20× TB20 thì nhịp hồi mở rộng.",
                   sents[4]]


def test_pick_insight_four_sentences_keeps_invalidation_not_cut_by_position():
    from vnstock_brief_guards_sections import ta_pick_insight
    sents = ["Ý chính.", "Thủng S1 1,675.19 kèm KL thì giảm tiếp.",
             "Vượt R1 1,734.39 kèm KL thì hồi.",
             "Nhận định giảm sai nếu chỉ số đóng cửa trên R1 1,734.39 kèm KL xác nhận."]
    out = ta_pick_insight(sents)
    assert len(out) == 3 and out[-1] == sents[3]
    assert out[1] == "Thủng S1 1,675.19 kèm KL thì giảm tiếp; vượt R1 1,734.39 kèm KL thì hồi."


def test_pick_insight_without_roles_falls_back_to_order():
    from vnstock_brief_guards_sections import ta_pick_insight
    assert ta_pick_insight(["A.", "B.", "C.", "D."]) == ["A.", "B.", "C."]
    three = ["Vượt R1 thì hồi.", "Ý.", "Sai nếu thủng S1."]
    assert ta_pick_insight(three) == three                 # ≤3 câu: không đảo chữ model


def test_card_block_drops_numbered_list_fragments():
    raw = _sec("1. Ý chính rõ. 2. Thủng S1 kèm KL thì giảm. 3. Sai nếu vượt R1.")
    out = _guard("enforce_ta_card_block")(raw, _ta_ctx())
    assert _insight(out) == "Ý chính rõ. Thủng S1 kèm KL thì giảm. Sai nếu vượt R1."

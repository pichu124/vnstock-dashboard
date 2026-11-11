"""Guard số NN ngành nhận KHUNG THÁNG (11/11): `enforce_sector_nn_figures` /
`enforce_money_flow_two_sides` / `enforce_net_flow_label` từng so MỌI số NN ngành với NN 1 TUẦN —
số NN 1 THÁNG đúng ("Ngân hàng bán ròng 2,536 tỷ (1M)") bị ghim thành số tuần ("-1,032 tỷ (1 tuần)
(1 tháng)"). Nay khung xác định bằng nhãn NGAY SAU số / tên ngành ("(1M)", "(1 tháng)", "trong
tháng", "20 phiên"): khung tháng ⇒ so độ lớn + CHIỀU với NN 1M thật, sai thì ghim về NN 1M;
không nhãn tháng ⇒ như cũ (NN 1T).
"""
from __future__ import annotations

import pytest

import vnstock_brief as vb

_CTX = {"sectors": [
    {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1032.4, "NN 1M (tỷ)": -2536.0, "GTGD TB (tỷ)": 4000.0},
    {"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": 120.0, "NN 1M (tỷ)": 300.0, "GTGD TB (tỷ)": 900.0},
]}


def _run(t: str) -> str:
    once = vb.apply_brief_guards(t, _CTX)
    assert vb.apply_brief_guards(once, _CTX) == once, once            # idempotent (`--from-file`)
    return once.splitlines()[0]


@pytest.mark.parametrize("text, want", [
    # số 1 tháng ĐÚNG có nhãn tháng ⇒ giữ nguyên
    ("Ngân hàng bán ròng 2,536 tỷ (1M).", "Ngân hàng bán ròng 2,536 tỷ (1"),
    ("Ngân hàng bán ròng 2,536 tỷ trong tháng.", "Ngân hàng bán ròng 2,536 tỷ trong tháng"),
    ("- Dòng tiền ngoại: Thép & Kim loại mua ròng 300 tỷ (1M).", "Thép & Kim loại mua ròng 300 tỷ (1 tháng)"),
    # sai CHIỀU / sai dấu / sai độ lớn với nhãn tháng ⇒ ghim về NN 1M thật (có dấu, động từ đúng)
    ("Ngân hàng mua ròng 2,536 tỷ (1M).", "Ngân hàng bán ròng -2,536 tỷ (1"),
    ("Ngân hàng bán ròng +2,536 tỷ (1M).", "Ngân hàng bán ròng -2,536 tỷ (1"),
    ("Ngân hàng bán ròng 5,000 tỷ (1M).", "Ngân hàng bán ròng -2,536 tỷ (1"),
])
def test_month_framed_sector_figure(text, want):
    out = _run(text)
    assert want in out, out
    assert "1,032" not in out and "(1 tuần)" not in out, out


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 2,536 tỷ (1T), đỉnh 1 tháng.",                 # nhãn TUẦN ngay sau số
    "Tuần này Ngân hàng bán ròng 2,536 tỷ, cao nhất trong tháng.",     # chữ tháng ở mệnh đề khác
    "Ngân hàng bán ròng 2,536 tỷ (1 tuần), trong tháng NN bán ròng mạnh.",
    "Ngân hàng bán ròng 2,536 tỷ trong 11 tháng.",                      # "11 tháng" không phải khung 1M
    "Ngân hàng bán ròng 2,536 tỷ, áp lực lớn.",                         # không nhãn ⇒ khung tuần như cũ
    # review 11/11: chữ "tháng"/"20 phiên" của mệnh đề khác không phải khung 1M
    "Ngân hàng bán ròng 1,032 tỷ, 1 tháng trước còn mua ròng 400 tỷ.",
    "Ngân hàng bán ròng 1,032 tỷ (1 tháng trước: mua ròng).",
    "Ngân hàng bán ròng 1,032 tỷ, tháng thứ ba liên tiếp.",
    "Ngân hàng bán ròng 1,032 tỷ tháng trước.",
    "Ngân hàng bán ròng 1,032 tỷ tháng Mười.",
    "Ngân hàng bán ròng 1,032 tỷ trong 20 phiên trước đó.",
])
def test_without_month_frame_behaves_as_before(text):
    assert "-1,032" in _run(text)


def test_number_before_name_forms_on_money_flow_line():
    out = _run("**Dòng tiền ngành:** NN bán ròng 2,536 tỷ trong ngành Ngân hàng (1M).")
    assert "bán ròng 2,536 tỷ trong ngành Ngân hàng" in out and "1,032 tỷ trong ngành" not in out
    out2 = _run("**Dòng tiền ngành:** NN mua ròng 2,536 tỷ trong ngành Ngân hàng (1M).")
    assert "bán ròng 2,536 tỷ trong ngành Ngân hàng" in out2              # động từ theo chiều NN 1M
    out3 = _run("**Dòng tiền ngành:** Ngân hàng (NN -2,536 tỷ, 1 tháng) chịu áp lực.")
    assert "Ngân hàng (NN -2,536 tỷ" in out3
    out4 = _run("**Dòng tiền ngành:** Ngân hàng (NN +900 tỷ, 1 tháng) chịu áp lực.")
    assert "Ngân hàng (NN -2,536 tỷ" in out4                              # sai ⇒ ghim NN 1M có dấu



def test_month_framed_wrong_direction_outside_money_flow_region():
    """Review 11/11: ngoài vùng dòng tiền (TLDR, Danh mục) không guard nào ghim độ lớn — số tuần với
    nhãn tháng + động từ SAI CHIỀU từng lọt ("NN mua ròng 1,032 tỷ trong ngành Ngân hàng (1M)")."""
    t = ("🎯 TLDR\nNN mua ròng 1,032 tỷ trong ngành Ngân hàng (1M), áp lực giảm.\n"
         "💰 Dòng tiền\nNgân hàng bị bán ròng.")
    once = vb.apply_brief_guards(t, _CTX)
    assert vb.apply_brief_guards(once, _CTX) == once, once
    line = once.splitlines()[1]
    assert "bán ròng 2,536 tỷ trong ngành Ngân hàng" in line and "mua ròng" not in line, line


def test_week_figure_with_month_label_is_idempotent():
    """Review 11/11: số TUẦN của ngành top kèm nhãn tháng — two_sides từng coi là "đã có số" ở lượt 1
    rồi chèn dòng chuẩn ở lượt 2 (bản gửi lại `--from-file` khác bản đầu)."""
    for t in ("Ngân hàng bán ròng 1,032 tỷ (1M).", "Ngân hàng bán ròng 1,032 tỷ trong tháng."):
        out = _run(t)
        assert "-2,536 tỷ" in out, out



def test_parenthetical_liquidity_figure_is_not_pinned():
    out = _run("**Dòng tiền ngành:** Thép & Kim loại (+1,500 tỷ GTGD) sôi động.")
    assert "(+1,500 tỷ GTGD)" in out, out

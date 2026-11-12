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
    # review 11/11: "trong (1) tháng trước/sau …" vẫn là khung tháng
    ("Ngân hàng bán ròng 2,536 tỷ trong 1 tháng trước kỳ review.", "2,536 tỷ trong 1 tháng trước kỳ review"),
    ("Ngân hàng bán ròng 2,536 tỷ trong tháng sau khi FTSE công bố.", "2,536 tỷ trong tháng sau khi"),
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



def test_week_figure_next_to_signed_month_figure_is_kept():
    """Review 11/11: "(NN -1,032 tỷ, 1 tháng -2,536 tỷ)" — số sau "1 tháng" là số THÁNG riêng, số trước
    là số tuần đúng: không được ghi đè số tuần thành bản sao số tháng."""
    out = _run("**Dòng tiền ngành:** Ngân hàng (NN -1,032 tỷ, 1 tháng -2,536 tỷ) chịu áp lực.")
    assert "(NN -1,032 tỷ, 1 tháng -2,536 tỷ)" in out, out
    for t, want in (("🎯 TLDR\nNgân hàng bán ròng 1,032 tỷ, 1 tháng -2,536 tỷ.", "1,032"),
                    ("🎯 TLDR\nNN bán ròng 1,032 tỷ trong ngành Ngân hàng, 1 tháng qua ngành giảm 5%.",
                     "1,032 tỷ trong ngành Ngân hàng")):
        once = vb.apply_brief_guards(t, _CTX)
        assert vb.apply_brief_guards(once, _CTX) == once, once
        assert want in once.splitlines()[1], once


def test_name_to_verb_gap_does_not_cross_into_another_sector():
    """Lỗi cũ (trước 11/11): khoảng tên→động từ 40 ký tự vượt sang NGÀNH KHÁC — "Thép & Kim loại tăng
    mạnh, Ngân hàng bán ròng 2,536 tỷ (1M)" từng thành "Ngân hàng mua ròng +300 tỷ (1M)" (số + chiều
    của Thép gán cho Ngân hàng)."""
    out = _run("Thép & Kim loại tăng mạnh, Ngân hàng bán ròng 2,536 tỷ (1M).")
    assert "Ngân hàng bán ròng 2,536 tỷ (1" in out and "+300" not in out, out
    out2 = _run("Thép & Kim loại tăng mạnh, Ngân hàng bán ròng 1,032 tỷ.")
    assert "Ngân hàng bán ròng -1,032 tỷ" in out2 and "+120" not in out2, out2
    # chính ngành đó vẫn được soát như cũ
    assert "+120" in _run("Thép & Kim loại tăng mạnh, NN mua ròng 999 tỷ.")


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 2,536 tỷ trong một tháng.",
    "Ngân hàng bán ròng 2,536 tỷ (một tháng).",
])
def test_month_written_out_in_words_is_a_month_frame(text):
    """Lỗi cũ: "trong một tháng" (chữ) không được nhận là khung tháng ⇒ số NN 1M đúng bị ghim về tuần."""
    out = _run(text)
    assert "2,536 tỷ" in out and "1,032" not in out, out


def test_month_name_january_is_not_a_frame():
    assert "-1,032" in _run("Ngân hàng bán ròng 2,536 tỷ tháng một.")


def test_lowercase_other_sector_name_also_stops_the_gap():
    """"Thép & Kim loại tăng mạnh, nhóm ngân hàng bán ròng 999 tỷ" — tên ngành khác viết THƯỜNG cũng
    chặn khoảng tên→động từ (trước: số của Thép +120 gán cho câu về ngân hàng)."""
    out = _run("Thép & Kim loại tăng mạnh, nhóm ngân hàng bán ròng 999 tỷ.")
    assert "+120" not in out, out
    # tên trùng chữ phổ thông ("khác hẳn") KHÔNG chặn: số bịa của Ngân hàng vẫn bị ghim như cũ
    assert "-1,032" in _run("Ngân hàng khác hẳn tuần trước, NN bán ròng 999 tỷ.")


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 3,800 tỷ trong một tháng rưỡi.",
    "Ngân hàng bán ròng 3,800 tỷ trong 1 tháng rưỡi.",
    "Ngân hàng bán ròng 3,800 tỷ trong 3 tháng.",
    "Ngân hàng bán ròng 3,800 tỷ (2 tháng).",
    "Ngân hàng bán ròng 3,800 tỷ trong quý.",
    "Ngân hàng bán ròng 3,800 tỷ trong 11 tháng.",                     # "11 tháng" không phải khung 1M
])
def test_span_without_data_is_left_untouched(text):
    """Khoảng thời gian KHÔNG có trong dữ liệu (tháng rưỡi, N≥2 tháng, quý): không phải khung 1M, cũng
    không phải tuần ⇒ guard không ghim số (ghim về số tuần/tháng đều sai khung)."""
    out = _run(text)
    assert "3,800 tỷ" in out and "1,032" not in out and "2,536" not in out, out


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 3,800 tỷ, 2 tháng trước còn mua ròng 400 tỷ.",
    "Ngân hàng bán ròng 3,800 tỷ, quý trước còn mua ròng.",
    "Ngân hàng bán ròng 3,800 tỷ, quý III lợi nhuận tăng.",
    "Ngân hàng bán ròng 3,800 tỷ, quý IV thường hồi phục.",
    "Ngân hàng bán ròng 3,800 tỷ trong 3 tháng tới sẽ giảm.",
    "Ngân hàng bán ròng 3,800 tỷ, ba tháng cuối năm thường yếu.",
])
def test_other_clause_after_span_words_still_pins(text):
    """Review: "2 tháng trước", "quý III", "3 tháng tới"… là MỆNH ĐỀ KHÁC, không phải khoảng thời gian của
    số ⇒ số bịa vẫn bị ghim như cũ (về NN 1T)."""
    assert "-1,032" in _run(text)


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 1,032 tỷ (3 tháng).",
    "Ngân hàng bán ròng 1,032 tỷ trong quý.",
    "Ngân hàng bán ròng 1,032 tỷ trong một tháng rưỡi.",
])
def test_week_value_with_other_span_gets_no_week_label_and_is_idempotent(text):
    """Review: số TRÙNG số tuần kèm "(3 tháng)" từng bị nhãn khung chèn "(1 tuần)" — tự mâu thuẫn và lượt
    chạy lại (`--from-file`) đổi chữ."""
    out = _run(text)
    assert "(1 tuần)" not in out, out


def test_lowercase_name_only_stops_after_group_word():
    """Tên viết thường chỉ chặn sau "nhóm/ngành/cổ phiếu" — "tín dụng bất động sản" là chữ thường của
    văn, không phải nhắc ngành khác ⇒ số bịa của Ngân hàng vẫn bị ghim."""
    assert "-1,032" in _run("Ngân hàng: tín dụng bất động sản siết, NN bán ròng 999 tỷ.")
    assert "+120" not in _run("Thép & Kim loại tăng mạnh, cổ phiếu ngân hàng bán ròng 999 tỷ.")


def test_parenthetical_with_other_span_left_untouched():
    out = _run("**Dòng tiền ngành:** Ngân hàng (NN -3,800 tỷ, 3 tháng) chịu áp lực.")
    assert "(NN -3,800 tỷ, 3 tháng)" in out, out


@pytest.mark.parametrize("text, wrong", [
    ("Thép & Kim loại tăng mạnh, ngân hàng bán ròng 999 tỷ.", "+120"),
    ("Bất động sản giảm sâu, ngân hàng bị NN bán ròng 999 tỷ.", "-500"),
    ("Thép & Kim loại tăng mạnh, NGÂN HÀNG bán ròng 999 tỷ.", "+120"),
])
def test_lowercase_other_sector_right_before_verb_stops_gap(text, wrong):
    """Review 12/11: tên ngành khác viết thường/HOA đứng NGAY TRƯỚC động từ dòng tiền vẫn chặn — không
    thì số của ngành đứng trước bị gán cho câu về ngành sau."""
    ctx = {"sectors": _CTX["sectors"] + [{"Ngành": "Bất động sản", "NN 1T (tỷ)": -500.0}]}
    once = vb.apply_brief_guards(text, ctx)
    assert vb.apply_brief_guards(once, ctx) == once
    first = once.splitlines()[0]               # các dòng sau là dòng chuẩn two_sides tự thêm
    assert wrong not in first and "999 tỷ" in first, once


@pytest.mark.parametrize("text", [
    "Ngân hàng bị NN bán ròng 3,800 tỷ trong 10 tháng đầu năm.",
    "Ngân hàng bán ròng 3,800 tỷ (9 tháng đầu năm).",
    "Ngân hàng bán ròng 3,800 tỷ trong quý III.",
    "Ngân hàng bán ròng 3,800 tỷ (quý III).",
    "Ngân hàng bán ròng 3,800 tỷ trong 3 tháng trước kỳ review.",
])
def test_valid_span_of_the_figure_is_left_untouched(text):
    """Review 12/11: "trong 10 tháng đầu năm", "(quý III)"… là khoảng của CHÍNH số ⇒ để nguyên."""
    out = _run(text)
    assert "3,800 tỷ" in out and "(1 tuần)" not in out, out


def test_coverage_label_skips_figure_with_other_span():
    """Review 12/11: ngày thiếu phiên NN 1T, nhãn "NN 1 tuần thiếu…" từng gắn lên số "(3 tháng)" và lượt
    chạy lại đổi chữ."""
    ctx = {**_CTX, "nn_coverage": {"sessions": 19, "asked": 20, "missing_1t": 1, "missing_1m": 1}}
    for t in ("Ngân hàng bán ròng 1,032 tỷ (3 tháng).", "Ngân hàng bán ròng 1,032 tỷ trong quý.",
              "NN bán ròng 1,032 tỷ trong ngành Ngân hàng trong quý."):
        once = vb.apply_brief_guards(t, ctx)
        assert vb.apply_brief_guards(once, ctx) == once, once
        assert "NN 1 tuần thiếu" not in once.splitlines()[0], once


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 999 tỷ (3 tháng trước: mua ròng 400 tỷ).",
    "Ngân hàng bán ròng 999 tỷ (quý trước mua ròng 400 tỷ).",
    "Ngân hàng bán ròng 999 tỷ (quý III: mua ròng 200 tỷ).",
    "Ngân hàng bán ròng 999 tỷ trong quý III: mua ròng 200 tỷ.",
    "Ngân hàng bán ròng 999 tỷ (quý IV dự kiến mua lại).",
    "Ngân hàng bán ròng 999 tỷ (3 tháng cuối năm dự báo mua ròng).",
])
def test_other_clause_inside_parentheses_still_pins(text):
    """Review 12/11: mệnh đề KHÁC trong ngoặc / sau ":" không phải khoảng của số ⇒ số bịa vẫn bị ghim."""
    assert "-1,032" in _run(text)


@pytest.mark.parametrize("text", [
    "Ngân hàng bán ròng 3,800 tỷ trong 9 tháng năm 2025.",
    "Ngân hàng bán ròng 3,800 tỷ trong quý 3 năm 2025.",
    "Ngân hàng bán ròng 3,800 tỷ (quý III/2025).",
])
def test_span_with_year_is_left_untouched(text):
    out = _run(text)
    assert "3,800 tỷ" in out and "1,032" not in out, out

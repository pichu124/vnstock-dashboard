"""P5 đa tài sản (U86): mục 🪙 trong brief (số do code dựng) + cảnh báo Telegram biến động.

Kho tạm (conftest `_assets_hermetic_anywhere`), ngày cố định qua `_FixedDate`."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

import vnstock_assets as va
import vnstock_assets_alerts as aa
import vnstock_assets_brief as ab
import vnstock_assets_view as av

TODAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 21, 5)
T = "2026-10-09T21:00:00"


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setenv("VNSTOCK_ASSETS_ALERTS", "1")              # conftest tắt mặc định; ở đây gửi qua `send` giả
    monkeypatch.setattr(av, "date", _FixedDate)
    monkeypatch.setattr(ab, "date", _FixedDate)
    monkeypatch.setattr(aa, "date", _FixedDate)
    monkeypatch.setattr(va, "date", _FixedDate)


def _w(key, pairs, **kw):
    va.write(key, [va._row(d, v, kw.get("src", "yahoo"), **({"bid": kw["bid"], "ask": v} if "bid" in kw else {}))
                   for d, v in pairs], today=TODAY, fetched_at=T)


def _seed(brent_today=105.0, vcb_today=26090.0):
    _w("XAU", [("2026-10-08", 4150.0), ("2026-10-09", 4182.09)], src="finhay")
    _w("USDVND", [("2026-10-08", 25870.0), ("2026-10-09", 25881.0)])
    _w("GOLD_SJC_BAR", [("2026-10-08", 144_300_000), ("2026-10-09", 144_800_000)], src="finhay", bid=141_800_000)
    _w("BRENT", [("2026-10-08", 100.0), ("2026-10-09", brent_today)])
    _w("WTI", [("2026-10-08", 90.0), ("2026-10-09", 91.0)])
    _w("DXY", [("2026-10-08", 102.0), ("2026-10-09", 102.3)])
    _w("USDVND_VCB", [("2026-10-08", 26070.0), ("2026-10-09", vcb_today)], src="vcb", bid=25700.0)
    _w("USD_CENTRAL", [("2026-10-08", 25634.0), ("2026-10-09", 25629.0)], src="mbk")
    va.write("CURVE_BRENT", [va._row("2026-10-09", 104.0 - j, "yahoo", contract=c)
                             for j, c in enumerate(("BZZ26", "BZF27", "BZG27"))], today=TODAY, fetched_at=T)
    va.update_status("estimates", {"USD_BROAD_EST": {"value": 121.23, "band_pct": 0.3, "date": "2026-10-08",
                                                     "anchor": 121.38, "anchor_date": "2026-10-02", "h": 4}})


# ── mục 🪙 trong brief ──────────────────────────────────────────────────────
def test_brief_lines_are_code_built_and_complete():
    _seed()
    lines = ab.brief_lines()
    assert lines[0].startswith("- Vàng: vàng TG 4,182.09 USD/oz (+0.77% 1 phiên, 09/10)")
    assert "SJC miếng bán 144.80 triệu đ/lượng (+0.35% 1 phiên)" in lines[0] and "đắt hơn vàng TG quy đổi +" in lines[0]
    assert lines[1].startswith("- Dầu (hợp đồng tháng gần): Brent 105.00 USD/thùng (+5.00% 1 phiên, 09/10)")
    assert "đường cong Brent backwardation (tháng gần − tháng kế +1.00 USD)" in lines[1]
    assert "DXY 102.30 (+0.29% 1 phiên)" in lines[2] and "chỉ số USD rộng ước tính 121.23 ±0.3%" in lines[2]
    assert "VCB bán 26,090 (+0.08% 1 phiên), còn cách trần 3.14% (trần 26,910)" in lines[2]
    assert "$" not in "\n".join(lines)
    block = ab.prompt_block(lines)
    assert block.startswith("\n## 🪙 Hàng hoá & Tiền tệ\n- Vàng:") and "KHÔNG tự viết số" in block


def test_brief_lines_drop_stale_series_and_kill_switch(monkeypatch):
    _seed()
    old = date(2026, 10, 15)                                       # 6 ngày sau: dầu/USD/vàng TG đều cũ
    assert ab.brief_lines(today=old) == []
    monkeypatch.setenv("VNSTOCK_BRIEF_ASSETS", "0")
    assert ab.brief_lines() == [] and ab.prompt_block([]) == ""


def test_brief_lines_include_significant_links():
    _seed()
    (va.META_DIR / "assets_links.json").write_text(json.dumps({"rows": [
        {"ticker": "PVD", "driver_label": "Dầu Brent (HĐTL)", "verdict": "có, đúng chiều",
         "w60": {"beta": 0.45, "t": 4.2}},
        {"ticker": "VHC", "driver_label": "DXY", "verdict": "không thấy", "w60": {"beta": 0.1, "t": 0.5}},
        {"ticker": "HVN", "driver_label": "Dầu Brent (HĐTL)", "verdict": "có, đúng chiều",
         "w60": {"beta": -0.3, "t": -5.0}}]}), encoding="utf-8")
    last = ab.brief_lines()[-1]
    assert last == ("- Độ nhạy 60 phiên (đã trừ nhịp chung thị trường): HVN -0.30% khi Dầu Brent (HĐTL) đổi 1% · "
                    "PVD +0.45% khi Dầu Brent (HĐTL) đổi 1%")


# ── cảnh báo Telegram ───────────────────────────────────────────────────────
def test_alerts_detect_levels_and_send_once():
    _seed(brent_today=107.0)                                       # Brent +7% ⇒ bậc 2 (ngưỡng 3%)
    sent = []
    res = aa.run(NOW, send=lambda t: sent.append(t) or True)
    assert res["status"] == "sent" and res["ids"] == ["BRENT:2026-10-09:L2"]
    assert "Dầu Brent (HĐTL tháng gần) 107.00 USD/thùng ▲ +7.00% so phiên trước" in sent[0]
    assert aa.run(NOW, send=lambda t: sent.append(t) or True)["status"] == "quiet"   # đã gửi, không lặp
    _w("BRENT", [("2026-10-09", 110.0)])                           # +10% ⇒ lên bậc 3 ⇒ báo thêm
    assert aa.run(NOW, send=lambda t: sent.append(t) or True)["ids"] == ["BRENT:2026-10-09:L3"]
    assert len(sent) == 2


def test_alerts_ceiling_room_and_quiet_and_errors(monkeypatch):
    _seed(vcb_today=26_850.0)                                      # +2.99% ⇒ tín hiệu đổi + còn 0.23% tới trần
    res = aa.run(NOW, dry_run=True)
    assert res["status"] == "dry-run" and "chỉ còn 0.23% tới trần biên độ 26,910" in res["text"]
    assert "USD/VND Vietcombank (bán) 26,850 đ ▲ +2.99%" in res["text"]
    assert not (va.META_DIR / aa.LEDGER_NAME).exists()             # dry-run không ghi sổ
    assert aa.run(NOW, send=lambda t: False)["status"] == "error"  # Telegram từ chối ⇒ chưa đánh dấu
    assert aa.run(NOW, send=lambda t: True)["status"] == "sent"
    monkeypatch.setenv("VNSTOCK_ASSETS_ALERTS", "0")
    assert aa.run(NOW, send=lambda t: True) == {"status": "disabled"}


def test_alerts_quiet_when_nothing_moves():
    _seed(brent_today=101.0)
    assert aa.run(NOW, send=lambda t: pytest.fail("không được gửi"))["status"] == "quiet"


# ── guard mục 🪙 trong chuỗi guard brief ────────────────────────────────────
_BRIEF = ("## 🎯 TLDR\nVNINDEX giảm 0.80% so với phiên trước, chỉ số đóng cửa 1,650.\n\n"
          "## 🌐 Vĩ mô: lãi suất & tỷ giá\n- Tỷ giá USD/VND (tham chiếu): 26,190\n\n"
          "## 📰 Tin kinh tế/chính trị nổi bật\n- Tin A\n")


def _ctx(lines):
    return {"assets_lines": lines, "brief_type": "afternoon",
            "vnindex_tech": {"day_change_pct": -0.8, "close": 1650.0}}


def test_guard_inserts_after_macro_and_survives_full_chain():
    """Chạy CẢ chuỗi apply_brief_guards: dòng code của mục 🪙 phải ra NGUYÊN VẸN (guard số VNINDEX,
    USD/VND, động từ tăng/giảm… không được chạm), đúng vị trí, và chạy lại không đổi."""
    import vnstock_brief_guards as g
    _seed(brent_today=104.0)
    lines = ab.brief_lines()
    out = g.apply_brief_guards(_BRIEF, _ctx(lines))
    sec = out[out.index("## 🪙 Hàng hoá & Tiền tệ"):]
    body = sec.split("\n## ")[0].splitlines()[1:]
    assert [l for l in body if l.strip()] == lines                 # từng dòng nguyên vẹn
    assert out.index("## 🌐") < out.index("## 🪙") < out.index("## 📰")
    assert g.apply_brief_guards(out, _ctx(lines)) == out           # idempotent qua cả chuỗi


def test_guard_replaces_model_body_removes_when_empty_and_noop_without_key():
    import vnstock_brief_guards as g
    model = _BRIEF.replace("## 📰", "## 🪙 Hàng hoá & Tiền tệ\nVàng tăng mạnh 5% lên 4,500 USD/oz.\n\n## 📰")
    out = g.enforce_assets_section(model, {"assets_lines": ["- Vàng: vàng TG 4,182.09 USD/oz"]})
    assert "4,500" not in out and "- Vàng: vàng TG 4,182.09 USD/oz" in out
    assert "🪙" not in g.enforce_assets_section(model, {"assets_lines": []})   # chuỗi đều cũ ⇒ gỡ mục
    assert g.enforce_assets_section(model, {}) == model                         # pack cũ / tắt ⇒ no-op
    no_macro = "## 🎯 TLDR\nx\n\n## 📌 Danh mục đang giữ\n- y\n"
    out = g.enforce_assets_section(no_macro, {"assets_lines": ["- USD: DXY 102.30"]})
    assert out.index("## 🪙") < out.index("## 📌")


@pytest.mark.parametrize("bt", ["morning", "afternoon"])
def test_prompt_carries_assets_block_only_when_present(bt):
    import vnstock_brief as vb
    from tests.test_brief_risk_today import _ctx_0510
    _seed()
    lines = ab.brief_lines()
    prompt = vb.build_prompt(_ctx_0510(brief_type=bt, assets_lines=lines), brief_type=bt)
    assert "## 🪙 Hàng hoá & Tiền tệ\n- Vàng:" in prompt and "KHÔNG tự viết số vàng/dầu/USD" in prompt
    assert prompt.index("## 🪙 Hàng hoá") > prompt.index("Ngày:")
    assert "## 🪙" not in vb.build_prompt(_ctx_0510(brief_type=bt), brief_type=bt).split("## 🎯")[0]

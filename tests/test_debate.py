"""Tests for vnstock_debate — 1 vòng phản biện band phân bổ (devil's advocate).

Hermetic: cache trỏ tmp_path, LLM call monkeypatch.
"""
import json

import pytest

import vnstock_debate as db


_STATE = {
    "band": "B4", "band_label": "căng thẳng", "band_data": "B4",
    "score": -0.739, "as_of": "2026-07-13",
    "report_tilt": {"tilt": 1, "n_reports": 1},
    "inputs": [{"label": "Regime thị trường", "value": "score -3",
                "score": -0.6, "detail": "Tiêu cực", "as_of": "2026-07-13"}],
    "allocation": {"Cổ phiếu": 15, "Trái phiếu": 25, "Tiền gửi": 40,
                   "Vàng": 12, "USD": 8},
}

_RAW = """Đây là phản biện:
- Độ rộng 13% trên MA200 là vùng quá bán lịch sử, xác suất hồi kỹ thuật cao hơn giảm tiếp. 🎯
- Thanh khoản CĂNG +1.17 điểm % thường đảo chiều nhanh khi KBNN gửi tiền trở lại.
- ## Consensus chỉ dựa 1 báo cáo — mẫu quá mỏng để tilt phòng thủ thêm.
- Điều kiện đảo ngược: VNINDEX vượt lại MA20 kèm độ rộng > 40% thì band B4 là sai.
Dòng không phải luận điểm này phải bị bỏ."""


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_CACHE", tmp_path / "allocation_debate.json")


def test_run_debate_parses_points_and_sanitizes(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "_debate_call",
                        lambda s, u: seen.update(s=s, u=u) or _RAW)
    d = db.run_debate(_STATE, {"n_reports": 1, "stance": {"Cổ phiếu": -2.0}})
    assert d["band"] == "B4" and d["as_of"] == "2026-07-13"
    assert len(d["points"]) == 4
    assert d["points"][3].startswith("Điều kiện đảo ngược:")
    # sanitize: emoji/## bị strip, không phá section parser khi vào prompt
    assert "🎯" not in d["points"][0] and "#" not in d["points"][2]
    # dữ kiện cho người phản biện = số thật từ state + consensus
    assert "Band hiện tại: B4" in seen["u"]
    assert "Regime thị trường" in seen["u"] and "-2.00" in seen["u"]
    assert "PHẢN BIỆN" in seen["s"]
    # đã ghi cache
    on_disk = json.loads(db._CACHE.read_text(encoding="utf-8"))
    assert on_disk["points"] == d["points"]


def test_run_debate_cached_per_asof_band(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "_debate_call",
                        lambda s, u: calls.append(1) or _RAW)
    db.run_debate(_STATE)
    assert len(calls) == 1
    # cùng (as_of, band) → đọc cache, KHÔNG call lại
    d2 = db.run_debate(_STATE)
    assert len(calls) == 1 and len(d2["points"]) == 4
    # --force → call lại
    db.run_debate(_STATE, force=True)
    assert len(calls) == 2
    # kỳ mới (as_of khác) → call mới
    db.run_debate({**_STATE, "as_of": "2026-08-01"})
    assert len(calls) == 3


def test_run_debate_llm_dead_keeps_old_cache(monkeypatch):
    monkeypatch.setattr(db, "_debate_call", lambda s, u: _RAW)
    db.run_debate(_STATE)
    monkeypatch.setattr(db, "_debate_call", lambda s, u: None)
    # kỳ mới nhưng LLM chết → trả cache cũ (còn hơn không), không ghi đè
    d = db.run_debate({**_STATE, "as_of": "2026-08-01"})
    assert d["as_of"] == "2026-07-13"
    # không có cache cũ + LLM chết → None
    db._CACHE.unlink()
    assert db.run_debate({**_STATE, "as_of": "2026-08-01"}) is None


def test_run_debate_guards_inputs(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "_debate_call",
                        lambda s, u: calls.append(1) or _RAW)
    assert db.run_debate({}) is None                    # thiếu state
    assert db.run_debate({"band": "B9"}) is None        # band rác
    monkeypatch.setenv("VNSTOCK_ALLOC_DEBATE", "0")     # kill switch
    assert db.run_debate(_STATE) is None
    assert calls == []


def test_load_debate_and_cli(monkeypatch, capsys):
    assert db.load_debate() is None
    assert db.main(["--show"]) == 1
    monkeypatch.setattr(db, "_debate_call", lambda s, u: _RAW)
    db.run_debate(_STATE)
    assert db.load_debate()["band"] == "B4"
    assert db.main(["--show"]) == 0
    assert "Phản biện band B4" in capsys.readouterr().out

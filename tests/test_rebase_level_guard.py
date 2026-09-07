"""
Lưới cho bế tắc CỬA GÁC ⇄ CÔNG CỤ CHỮA (phát hiện + phản biện 26/08).

**Hai bên hỏi hai câu khác nhau, nên mù/sáng ngược nhau:**

| ai | đo gì | công thức |
|---|---|---|
| `vnstock_basis_guard.check_basis` — CỬA GÁC | **MỨC** | trung vị `wh/src`, rồi `\\|r − 1\\| > TOL` |
| `probe_price_basis.find_basis_step` — bộ dò | **ĐẠO HÀM** | `jumps = \\|r[1:]/r[:-1] − 1\\|` |
| `probe_price_basis._find_break` — bộ dò | **ĐẠO HÀM**, chỉ trên chuỗi KHO | vách giá ≥30% |

Nguồn back-adjust TRỌN lịch sử ⇒ `wh/src` lệch **ĐỒNG ĐỀU** ⇒ đạo hàm = 0 ở
mọi điểm ⇒ **cả hai bộ dò trả None**, còn cửa gác thì chặn. Trước bản vá,
`_rebase_one` rơi vào nhánh đó và in **"✅ không còn vách nghi vấn"** rồi
**exit 0** — báo thành công trong khi không chữa gì.

Và nó **tự khoá**: `update_ticker` đặt `fetch_from = last_date` rồi `return`
ngay khi gác phán `basis_changed`, TRƯỚC mọi lệnh ghi ⇒ `last_date` đóng băng
⇒ đêm sau cửa sổ đối chiếu vẫn nằm trọn trong phần cơ sở CŨ ⇒ lại chặn. Vòng
lặp tự nuôi.

Đo trên máy user 26/08: `probe_price_basis --ticker SDK` in *"không tìm thấy
vách nghi vấn trong 365 ngày"* trong khi sổ cách ly ghi **SDK 1.4857×**.

Điều mỉa mai: `last_divergent_day` — đo đúng MỨC từng bar — vốn đã nằm sẵn
trong chính `rebase_ticker_history.py`, chỉ là nó đứng SAU hai cửa mù nên
không bao giờ được chạm tới.
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebase_ticker_history.py"
_spec = importlib.util.spec_from_file_location("rebase_ticker_history_lvl", _SCRIPT)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _series(n=60, ratio=1.0, start=date(2026, 6, 1)):
    """(kho, nguồn) — kho = nguồn × ratio ở MỌI bar (lệch đồng đều)."""
    days = [start + timedelta(days=i) for i in range(n)]
    src = pd.DataFrame({"time": days, "close": [100.0 + i for i in range(n)]})
    wh = pd.DataFrame({"time": days,
                       "close": [(100.0 + i) * ratio for i in range(n)]})
    return wh, src


class TestUniformOffsetIsInvisibleToStepDetectors:
    """Nền của cả bế tắc — chứng minh bằng chính hàm thật, không phải suy diễn."""

    def test_a_uniform_offset_has_no_step_at_all(self):
        from probe_price_basis import find_basis_step
        wh, src = _series(ratio=1.4857)
        assert find_basis_step(wh, src) is None

    def test_but_the_level_detector_sees_it_immediately(self):
        wh, src = _series(ratio=1.4857)
        assert R.last_divergent_day(wh, src, today=date(2027, 1, 1)) is not None

    def test_and_the_guard_sees_it_too(self):
        from vnstock_basis_guard import check_basis
        wh, src = _series(ratio=1.4857)
        wh_c = {r["time"]: r["close"] for _, r in wh.iterrows()}
        src_c = {r["time"]: r["close"] for _, r in src.iterrows()}
        out = check_basis(wh_c, src_c, last_date=date(2027, 1, 1))
        assert out["verdict"] == "basis_changed"
        assert round(out["ratio"], 4) == 1.4857

    def test_an_aligned_series_stays_clean_in_every_detector(self):
        """Bản vá không được biến mã sạch thành báo động giả."""
        from probe_price_basis import find_basis_step
        wh, src = _series(ratio=1.0)
        assert find_basis_step(wh, src) is None
        assert R.last_divergent_day(wh, src, today=date(2027, 1, 1)) is None


class TestLevelDivergence:
    def test_it_returns_none_when_the_warehouse_is_missing(self, tmp_path):
        assert R._level_divergence("KHONGCO", tmp_path) is None

    def test_a_broken_source_never_raises(self, tmp_path, monkeypatch):
        """Bộ dò hỏng mà ném thì `_rebase_one` chết giữa chừng — mất luôn cả
        đường chữa lẫn đường từ chối."""
        import probe_price_basis as ppb
        monkeypatch.setattr(ppb, "load_wh",
                            lambda *a, **k: (_ for _ in ()).throw(IOError("hỏng")))
        assert R._level_divergence("VCB", tmp_path) is None


class TestDriftLedgerLookup:
    def test_a_quarantined_ticker_is_recognised(self, tmp_path, monkeypatch):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "load_pending", lambda wh: {"SDK": {}})
        assert R._in_drift_ledger("sdk", tmp_path) is True

    def test_an_absent_ticker_is_not(self, tmp_path, monkeypatch):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "load_pending", lambda wh: {"SDK": {}})
        assert R._in_drift_ledger("VCB", tmp_path) is False

    def test_an_unreadable_ledger_is_not_an_error(self, tmp_path, monkeypatch):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "load_pending",
                            lambda wh: (_ for _ in ()).throw(IOError("hỏng")))
        assert R._in_drift_ledger("SDK", tmp_path) is False


class TestNoMoreFalseGreen:
    """Bất biến chính: **không bao giờ in ✅ + exit 0 cho một mã vẫn đang lệch.**

    Báo thành công sai còn tệ hơn báo lỗi: badge doctor thì đỏ mãi, mà công cụ
    chữa in ✅ — người dùng học cách bỏ qua badge.
    """

    def _stub(self, monkeypatch, tmp_path, tk="SDK", level=None, pending=False):
        (tmp_path / "prices" / f"ticker={tk}").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(R, "_find_break", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(R, "_basis_break_of", lambda *a, **k: None)
        monkeypatch.setattr(R, "_level_divergence", lambda *a, **k: level)
        monkeypatch.setattr(R, "_in_drift_ledger", lambda *a, **k: pending)
        import check_unit_continuity as cuc
        monkeypatch.setattr(cuc, "load_bars", lambda *a, **k: [], raising=False)
        import probe_price_basis as ppb
        monkeypatch.setattr(ppb, "_find_break", lambda *a, **k: None)

    def test_level_divergence_alone_blocks_the_false_green(
            self, tmp_path, monkeypatch, capsys):
        self._stub(monkeypatch, tmp_path, level=date(2026, 8, 20))
        rc = R._rebase_one("SDK", tmp_path, apply=False)
        out = capsys.readouterr().out
        assert rc == 1
        assert "✅" not in out and "KHÔNG có bậc nhảy" in out

    def test_being_in_the_ledger_alone_blocks_it_too(
            self, tmp_path, monkeypatch, capsys):
        """Kể cả khi bộ dò mức im: cửa gác đã chặn mã này, và gác đo MỨC —
        nó biết thứ bộ dò bậc không biết."""
        self._stub(monkeypatch, tmp_path, level=None, pending=True)
        rc = R._rebase_one("SDK", tmp_path, apply=False)
        out = capsys.readouterr().out
        assert rc == 1 and "sổ cách ly" in out

    def test_the_refusal_says_WHY_the_usual_fix_does_not_apply(
            self, tmp_path, monkeypatch, capsys):
        """"Không chữa được" mà không nói vì sao thì người đọc sẽ thử lại
        chính lệnh đó."""
        self._stub(monkeypatch, tmp_path, level=date(2026, 8, 20))
        R._rebase_one("SDK", tmp_path, apply=False)
        out = capsys.readouterr().out
        assert "ĐỒNG ĐỀU" in out and "không có vách nào để làm mốc" in out

    def test_a_genuinely_clean_ticker_still_passes(
            self, tmp_path, monkeypatch, capsys):
        """Bản vá không được biến mọi mã thành từ chối — thế thì công cụ vô
        dụng theo hướng ngược lại."""
        self._stub(monkeypatch, tmp_path, level=None, pending=False)
        rc = R._rebase_one("SDK", tmp_path, apply=False)
        out = capsys.readouterr().out
        assert rc == 0 and "✅" in out

    def test_the_clean_message_says_the_level_detector_also_ran(
            self, tmp_path, monkeypatch, capsys):
        """Trước bản vá, dòng ✅ có nghĩa 'không có bậc nhảy' mà đọc thành
        'sạch'. Nay nó phải nói rõ đã hỏi cả hai loại bộ dò."""
        self._stub(monkeypatch, tmp_path, level=None, pending=False)
        R._rebase_one("SDK", tmp_path, apply=False)
        assert "MỨC" in capsys.readouterr().out

    def test_the_refusal_never_writes_anything(self, tmp_path, monkeypatch):
        """Đường từ chối phải rẽ TRƯỚC mọi lệnh ghi."""
        self._stub(monkeypatch, tmp_path, level=date(2026, 8, 20))
        monkeypatch.setattr(R, "_read_all",
                            lambda *a, **k: pytest.fail("không được đọc/ghi file kho"))
        assert R._rebase_one("SDK", tmp_path, apply=True) == 1


class TestTheIronyIsFixed:
    def test_the_level_detector_is_now_reachable_from_the_clean_branch(self):
        """`last_divergent_day` đã có sẵn trong chính file này từ trước, kèm
        test — nó chỉ nằm SAU hai cửa mù nên không bao giờ chạy tới."""
        import inspect
        src = inspect.getsource(R._rebase_one)
        assert "_level_divergence" in src
        assert src.index("_level_divergence") < src.index("không còn vách nghi vấn")

    def test_level_divergence_reuses_the_existing_pure_helper(self):
        import inspect
        assert "last_divergent_day" in inspect.getsource(R._level_divergence)

    def test_the_tolerance_matches_the_guard(self):
        """Hai bên lệch ngưỡng thì lại đẻ ra một cặp mù/sáng ngược nhau mới."""
        import inspect
        from vnstock_basis_guard import TOL
        sig = inspect.signature(R._level_divergence)
        assert sig.parameters["tol"].default == pytest.approx(TOL)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

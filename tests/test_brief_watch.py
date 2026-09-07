"""
Lưới cho `vnstock_brief_watch` — sổ ĐẾM TRƯỚC, QUYẾT SAU.

Hai nghi ngờ từ đợt soi brief close 21/08 (U22) không đủ căn cứ để viết guard
ngay, và ghi vào `docs/CLAUDE-NOTES.md` thì KHÔNG bao giờ nổi lên lại — file
đó tự nhận là kho lưu. Nên máy tự đếm, doctor réo khi đủ mẫu.

Ca nguy hiểm nhất ở đây thuộc họ bug quen của repo: **trình bày "chưa đo được"
thành "đo ra kết quả xấu"** (vết 13/08: n=2 vẽ thành "0%"). Dưới sàn mẫu, badge
PHẢI là ok kèm n=…, tuyệt đối không warn.
"""
from __future__ import annotations

import json

import vnstock_brief_watch as w

_CTX = {
    "vn30_fundamentals": {"KBC": {"ocf": -17344.0}, "FPT": {"ocf": 5000.0},
                          "NVL": {"ocf": -6145.0}},
    "tickers": [{"Mã": "KBC", "Vốn hoá (tỷ)": 21000.0},
                {"Mã": "FPT", "Vốn hoá (tỷ)": 200000.0},
                {"Mã": "NVL", "Vốn hoá (tỷ)": 30000.0}],
    "sectors": [{"Ngành": "Chứng khoán & Đầu tư tài chính", "NN 1T (tỷ)": 340.0},
                {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1276.0},
                {"Ngành": "Họ VIN", "NN 1T (tỷ)": -1513.0}],
}

_SSI_LINE = ("- SSI: 20,000 cp | vốn 23.40 | hiện 20.75 | lỗ -11.3% → CANH BÁN "
             "cơ cấu danh mục do khối ngoại liên tục bán ròng mạnh nhóm "
             "Chứng khoán & Đầu tư tài chính.")


class TestOcfScaleDetector:
    def test_the_real_kbc_case_is_recorded(self):
        got = w.scan_ocf_scale(_CTX)
        assert [e["ticker"] for e in got] == ["KBC"]
        assert got[0]["ratio"] == 0.826          # |−17,344| / 21,000

    def test_a_healthy_ticker_is_not_recorded(self):
        assert all(e["ticker"] != "FPT" for e in w.scan_ocf_scale(_CTX))

    def test_a_ticker_without_market_cap_is_skipped_not_guessed(self):
        ctx = {"vn30_fundamentals": {"XYZ": {"ocf": -99999.0}}, "tickers": []}
        assert w.scan_ocf_scale(ctx) == []

    def test_nan_and_missing_ocf_are_ignored(self):
        ctx = {"vn30_fundamentals": {"A": {"ocf": float("nan")}, "B": {}},
               "tickers": [{"Mã": "A", "Vốn hoá (tỷ)": 100.0},
                           {"Mã": "B", "Vốn hoá (tỷ)": 100.0}]}
        assert w.scan_ocf_scale(ctx) == []

    def test_sorted_worst_first(self):
        got = w.scan_ocf_scale(_CTX, threshold=0.1)
        assert [e["ticker"] for e in got] == ["KBC", "NVL"]

    def test_empty_ctx_is_safe(self):
        assert w.scan_ocf_scale(None) == [] and w.scan_ocf_scale({}) == []


class TestFlowClaimDetector:
    def test_the_real_ssi_claim_is_caught(self):
        got = w.scan_flow_claims(_SSI_LINE, _CTX)
        assert len(got) == 1
        assert got[0]["sector"] == "Chứng khoán & Đầu tư tài chính"
        assert got[0]["claimed"] == "bán ròng"
        assert got[0]["actual_nn_1t_ty"] == 340.0

    def test_a_true_claim_stays_silent(self):
        assert w.scan_flow_claims("khối ngoại bán ròng mạnh nhóm Ngân hàng.", _CTX) == []

    def test_a_true_buy_claim_stays_silent(self):
        ctx = {"sectors": [{"Ngành": "Bán lẻ", "NN 1T (tỷ)": 169.0}]}
        assert w.scan_flow_claims("khối ngoại mua ròng nhóm Bán lẻ.", ctx) == []

    def test_a_wrong_buy_claim_is_caught(self):
        assert w.scan_flow_claims("khối ngoại mua ròng nhóm Họ VIN.", _CTX)

    def test_an_unmatched_sector_name_is_ignored_not_guessed(self):
        # Khớp mờ là tự tạo báo động giả — không khớp CHÍNH XÁC thì im lặng
        assert w.scan_flow_claims("khối ngoại bán ròng nhóm Thép Hoà Phát.", _CTX) == []

    def test_no_sectors_in_ctx_is_a_noop(self):
        assert w.scan_flow_claims(_SSI_LINE, {"sectors": []}) == []

    def test_detector_never_mutates_the_text(self):
        before = _SSI_LINE
        w.scan_flow_claims(_SSI_LINE, _CTX)
        assert _SSI_LINE == before


class TestLedgerIO:
    def test_record_and_load_roundtrip(self, tmp_path):
        assert w.record(tmp_path, [{"kind": "ocf_scale", "ticker": "KBC"}],
                        today="2026-08-21")
        data = w.load(tmp_path)
        assert data["events"][0]["ticker"] == "KBC"
        assert data["events"][0]["at"] == "2026-08-21"
        assert data["events"][0]["host"]        # phải có trường MÁY

    def test_same_day_rerun_replaces_instead_of_double_counting(self, tmp_path):
        # Chạy lại `run.py brief` ba lần một tối KHÔNG được thành ba bằng chứng
        for _ in range(3):
            w.record(tmp_path, [{"kind": "flow_claim", "sector": "X"}],
                     today="2026-08-21")
        assert len(w.load(tmp_path)["events"]) == 1

    def test_a_different_day_accumulates(self, tmp_path):
        w.record(tmp_path, [{"kind": "flow_claim", "sector": "X"}], today="2026-08-21")
        w.record(tmp_path, [{"kind": "flow_claim", "sector": "X"}], today="2026-08-22")
        assert len(w.load(tmp_path)["events"]) == 2

    def test_log_is_capped(self, tmp_path):
        for i in range(w.MAX_EVENTS + 50):
            w.record(tmp_path, [{"kind": "flow_claim", "sector": f"S{i}"}],
                     today=f"day-{i}")
        assert len(w.load(tmp_path)["events"]) == w.MAX_EVENTS

    def test_record_is_a_noop_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VNSTOCK_BRIEF_WATCH", "0")
        assert w.record(tmp_path, [{"kind": "ocf_scale"}]) is False
        assert not w.watch_path(tmp_path).exists()

    def test_record_never_raises_when_the_write_fails(self, tmp_path, monkeypatch):
        r"""Sổ hỏng KHÔNG được kéo brief theo.

        ⚠️ Bản đầu của test này dựng "đường dẫn không ghi được" bằng chuỗi
        POSIX `/proc/...`. Trên Windows chuỗi đó là `C:\proc\...` và
        `mkdir(parents=True)` THÀNH CÔNG ⇒ test xanh trong container, ĐỎ trên
        máy thật, và `run.py test` exit 2 = dừng cứng pipeline trước bước
        brief (đúng cách đã mất brief đêm 19/08). Nay chặn ở tầng hành vi:
        bắt chính bước ghi ném lỗi, không giả định gì về hệ tệp.
        """
        import vnstock_parquet_io as pio

        def _boom(*a, **k):
            raise OSError("đĩa đầy")

        monkeypatch.setattr(pio, "write_json_atomic", _boom)
        assert w.record(tmp_path, [{"kind": "ocf_scale"}]) is False

    def test_observe_brief_never_raises_when_the_write_fails(self, tmp_path,
                                                             monkeypatch):
        import vnstock_parquet_io as pio
        monkeypatch.setattr(pio, "write_json_atomic",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        # Vẫn trả danh sách quan sát, chỉ là không ghi được — brief đi tiếp
        assert w.observe_brief(tmp_path, _SSI_LINE, _CTX, today="2026-08-21")

    def test_load_on_corrupt_file_returns_empty(self, tmp_path):
        p = w.watch_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        assert w.load(tmp_path) == {}

    def test_observe_brief_writes_both_kinds(self, tmp_path):
        got = w.observe_brief(tmp_path, _SSI_LINE, _CTX, today="2026-08-21")
        kinds = {e["kind"] for e in got}
        assert kinds == {"ocf_scale", "flow_claim"}
        assert json.loads(w.watch_path(tmp_path).read_text(encoding="utf-8"))["events"]


class TestBadgeNeverCriesTooEarly:
    def _fill(self, tmp_path, days):
        for i in range(days):
            w.record(tmp_path, [{"kind": "flow_claim", "sector": "Chứng khoán"}],
                     today=f"2026-08-{i + 1:02d}")

    def test_below_the_floor_is_not_enough(self, tmp_path):
        self._fill(tmp_path, w.MIN_SAMPLES - 1)
        assert w.summarize(tmp_path)["enough"] is False

    def test_at_the_floor_is_enough(self, tmp_path):
        self._fill(tmp_path, w.MIN_SAMPLES)
        assert w.summarize(tmp_path)["enough"] is True

    def test_doctor_stays_ok_below_the_floor(self, tmp_path, monkeypatch):
        import vnstock_doctor as d
        self._fill(tmp_path, w.MIN_SAMPLES - 1)
        monkeypatch.setattr(d, "_META", tmp_path / "_meta")
        r = d.check_brief_watch()
        assert r["status"] == "ok"           # KHÔNG được warn khi thiếu mẫu
        assert "CHƯA đủ mẫu" in r["message"]

    def test_doctor_warns_once_there_is_enough(self, tmp_path, monkeypatch):
        import vnstock_doctor as d
        self._fill(tmp_path, w.MIN_SAMPLES)
        monkeypatch.setattr(d, "_META", tmp_path / "_meta")
        r = d.check_brief_watch()
        assert r["status"] == "warn"
        assert r["fix"]                       # phải nói làm gì tiếp

    def test_doctor_is_ok_on_an_empty_ledger(self, tmp_path, monkeypatch):
        import vnstock_doctor as d
        monkeypatch.setattr(d, "_META", tmp_path / "_meta")
        assert d.check_brief_watch()["status"] == "ok"

    def test_summarize_names_the_worst_offender(self, tmp_path):
        w.record(tmp_path, [{"kind": "ocf_scale", "ticker": "KBC", "ratio": 0.83},
                            {"kind": "ocf_scale", "ticker": "NVL", "ratio": 0.20}],
                 today="2026-08-21")
        assert w.summarize(tmp_path)["worst_ocf"]["ticker"] == "KBC"


class TestFinancialsAreNotSuspicious:
    """Vết 07/09 — sổ đếm 83 mã Op.CF/vốn hoá bất thường qua 6 phiên, đậm nhất
    **NAB 6.118×**, và đầu bảng là **BID · BSI · DSE · HDB · NAB**: năm trên
    sáu mã là NGÂN HÀNG / CHỨNG KHOÁN.

    Với định chế tài chính, "lưu chuyển tiền HĐKD" theo VAS gồm cả biến động
    **tiền gửi, cho vay, liên ngân hàng** — dòng BẢNG CÂN ĐỐI, không phải dòng
    tiền hoạt động theo nghĩa doanh nghiệp thường. Op.CF vài trăm nghìn tỷ ở
    đó là **số THẬT**, không phải lệch đơn vị.

    Và `_FINANCIAL_TICKERS` đã ghi đúng điều đó từ trước — xếp hạng rủi ro của
    brief ĐÃ loại nhóm này ra. Nên sổ đang đếm những mã **không bao giờ tới
    được mục Rủi ro**: đếm bao nhiêu phiên cũng không ra quyết định nào, mà
    badge thì cứ vàng.
    """

    def _ctx(self, tickers):
        return {
            "tickers": [{"Mã": t, "Vốn hoá (tỷ)": 20_000.0} for t in tickers],
            "vn30_fundamentals": {t: {"ocf": -122_000.0} for t in tickers},
        }

    def test_a_bank_is_not_recorded(self):
        import vnstock_brief_watch as W
        assert W.scan_ocf_scale(self._ctx(["NAB"])) == []

    def test_a_securities_firm_is_not_recorded(self):
        import vnstock_brief_watch as W
        assert W.scan_ocf_scale(self._ctx(["BSI"])) == []

    def test_a_financial_known_only_BY_INDUSTRY_is_not_recorded(self):
        """DSE không nằm trong danh sách tĩnh — nó chỉ lộ ra qua phân loại
        NGÀNH mà runner bơm vào `ctx["financial_tickers"]`. Bỏ vế đó là sổ vẫn
        đếm nhầm đúng những mã mới niêm yết."""
        import vnstock_brief_watch as W
        ctx = self._ctx(["DSE"])
        ctx["financial_tickers"] = {"DSE"}
        assert W.scan_ocf_scale(ctx) == []

    def test_a_NON_financial_is_STILL_recorded(self):
        """Không được vơ đũa cả nắm: KBC (BĐS) Op.CF âm nặng là tín hiệu THẬT
        mà mục Rủi ro sinh ra để nói — sổ phải giữ nó."""
        import vnstock_brief_watch as W
        got = W.scan_ocf_scale(self._ctx(["KBC"]))
        assert [e["ticker"] for e in got] == ["KBC"]

    def test_it_shares_ONE_list_with_the_risk_ranking(self):
        """Hai bên tự giữ danh sách riêng là chắc chắn lệch nhau — và lệch ở
        đây nghĩa là sổ lại đếm thứ brief không bao giờ in."""
        import inspect

        import vnstock_brief_watch as W
        assert "_FINANCIAL_TICKERS" in inspect.getsource(W._excluded_financials)
        assert "financial_tickers" in inspect.getsource(W._excluded_financials)

    def test_a_missing_canon_never_breaks_the_ledger(self, monkeypatch):
        """Sổ là best-effort tuyệt đối — brief KHÔNG được hỏng vì cái sổ."""
        import builtins

        import vnstock_brief_watch as W
        _real = builtins.__import__

        def boom(name, *a, **k):
            if name == "vnstock_brief_canon":
                raise ImportError("hỏng")
            return _real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", boom)
        assert W._excluded_financials({"financial_tickers": {"NAB"}}) == {"NAB"}

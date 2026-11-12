"""Tests for the corp-action events layer (vnstock_adjust)."""

from __future__ import annotations

import importlib.util
import pandas as pd
import pytest



# ── Gộp nguồn thay vì first-wins (14/08 — vá vùng mù 12 mã của div_check) ──


def _div_company(rows):
    """Company giả chỉ có dividends() — đủ cho đường _extract_dividends."""
    class _C:
        def dividends(self):
            return pd.DataFrame(rows)
    return _C()


def _sources(monkeypatch, *companies):
    """Thay chuỗi nguồn bằng danh sách company giả (giữ nguyên thứ tự)."""
    import vnstock_adjust as va
    pairs = [(f"fake{i}", (lambda c: (lambda _t: c))(c))
             for i, c in enumerate(companies)]
    monkeypatch.setattr(va, "_company_sources", lambda: iter(pairs))


class TestMergedSources:
    def test_all_sources_consulted_not_first_wins(self, monkeypatch):
        """Nguồn 1 chỉ có sự kiện CŨ — sự kiện MỚI của nguồn 2 vẫn phải vào.
        (Trước 14/08: nguồn 1 có gì đó là break — đúng hình vùng mù VNM/SAB.)"""
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2018-05-10",
                                "cash_dividend": 1000.0}]),
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 2
        assert str(max(df["ex_date"])) == "2026-04-15"

    def test_exact_duplicate_prefers_earlier_source(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]),
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1400.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        assert df.loc[0, "cash_amount"] == 1500.0

    def test_near_duplicate_two_dates_same_event_collapsed(self, monkeypatch):
        """Nguồn B ghi record-date lệch 2 ngày → vẫn là MỘT sự kiện, giữ bản
        nguồn ưu tiên — không được đẻ ra 'sự kiện ma' cho div_check chấm."""
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]),
                 _div_company([{"exercise_date": "2026-04-17",
                                "cash_dividend": 1500.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        assert str(df.loc[0, "ex_date"]) == "2026-04-15"

    def test_distinct_events_far_apart_both_kept(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-01-10",
                                "cash_dividend": 800.0},
                               {"exercise_date": "2026-06-10",
                                "cash_dividend": 700.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 2

    def test_broken_first_source_falls_through(self, monkeypatch):
        import vnstock_adjust as va
        from vnstock_adjust import _fetch_events

        def _boom(_t):
            raise RuntimeError("nguồn chết")
        ok = _div_company([{"exercise_date": "2026-04-15",
                            "cash_dividend": 1500.0}])
        monkeypatch.setattr(va, "_company_sources",
                            lambda: iter([("dead", _boom),
                                          ("ok", lambda _t: ok)]))
        df = _fetch_events("VNM")
        assert len(df) == 1


def _vci_events_company(rows):
    """Company giả chỉ có events() — hình dạng VCI thật (dump 14/08)."""
    class _C:
        def events(self):
            return pd.DataFrame(rows)
    return _C()


class TestVciEventShape:
    """Hình dạng THẬT chép từ dump VNM/SAB/GVR 14/08 — extractor từng mù
    trọn nhóm trả cổ tức TIỀN MẶT vì: chỉ bắt chia tách/thưởng, dò cột
    ex_date (VCI: exright_date), đọc nhãn event_name (VCI: event_name_vi)."""

    _DIV_ROW = {
        "event_name_vi": "Trả cổ tức bằng tiền mặt", "ticker": "VNM",
        "event_code": "DIV", "category": "DIVIDEND",
        "exright_date": "2026-06-26", "record_date": "2026-06-29",
        "value_per_share": 1850.0, "exercise_ratio": 0.185,
    }
    _MEETING_ROW = {
        "event_name_vi": "Đại hội Đồng Cổ đông", "ticker": "VNM",
        "event_code": "AGME", "category": "SHAREHOLDER_MEETING",
        "exright_date": "2026-05-14", "value_per_share": float("nan"),
        "exercise_ratio": float("nan"),
    }
    _INSIDER_ROW = {
        "event_name_vi": "Giao dịch nội bộ: Giao dịch tổ chức", "ticker": "VNM",
        "event_code": "DDINS", "category": "MAJOR_SHAREHOLDER_TRADING",
        "exright_date": float("nan"), "value_per_share": float("nan"),
        "exercise_ratio": float("nan"),
    }

    def test_cash_dividend_parsed_meetings_and_insiders_skipped(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch, _vci_events_company(
            [self._DIV_ROW, self._MEETING_ROW, self._INSIDER_ROW]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["type"] == "cash"
        assert row["cash_amount"] == 1850.0          # value_per_share, VND/cp
        assert str(row["ex_date"]) == "2026-06-26"   # exright_date, không phải record

    def test_stock_dividend_bonus_parsed_via_exercise_ratio(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        bonus = {**self._DIV_ROW,
                 "event_name_vi": "Trả cổ tức bằng cổ phiếu",
                 "event_code": "ISS", "category": "ISSUE",
                 "value_per_share": float("nan"), "exercise_ratio": 0.15,
                 "exright_date": "2026-03-05"}
        _sources(monkeypatch, _vci_events_company([bonus]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        assert df.iloc[0]["type"] == "bonus"
        assert df.iloc[0]["ratio"] == 0.15

    def test_div_missing_exright_date_skipped_not_crash(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        broken = {**self._DIV_ROW, "exright_date": float("nan")}
        _sources(monkeypatch, _vci_events_company([broken]))
        assert _fetch_events("VNM").empty

    def test_old_flat_shape_still_parsed(self, monkeypatch):
        # Hình dạng cũ (ex_date/event_name/ratio) không được vỡ khi thêm VCI
        from vnstock_adjust import _fetch_events
        old = {"event_name": "Stock split 2:1", "ex_date": "2026-02-10",
               "ratio": 2.0}
        _sources(monkeypatch, _vci_events_company([old]))
        df = _fetch_events("VNM")
        assert len(df) == 1 and df.iloc[0]["type"] == "split"


_needs_vnstock = pytest.mark.skipif(importlib.util.find_spec("vnstock") is None,
                                    reason="cần vnstock thế hệ 6 (CI cài tối thiểu, không có vnstock)")


@_needs_vnstock
class TestGen6EventShape:
    """`Reference().company(t).events()` thế hệ 6 (hồ sơ v5): event_title / event_type /
    ex_right_date / value / ratio. Thế hệ 6 KHÔNG có capital_history ⇒ dòng phát hành có tỷ
    lệ phải ra `bonus` (loại mà bản capital_history cũ ghi cho máy dò bất thường)."""

    # `event_type` = enum thật của hợp đồng vnstock 6.0.0 (chữ thường). Tiêu đề cố ý KHÔNG chứa
    # cụm "cổ tức bằng tiền" liền nhau: phân loại phải theo enum, không dò chữ.
    _ROWS = [
        {"symbol": "FPT", "event_title": "Trả cổ tức đợt 1/2026 bằng tiền, 2.000 đồng/cổ phiếu",
         "event_type": "cash_dividend", "ex_right_date": "2026-06-15", "record_date": "2026-06-16",
         "value": 2000.0, "ratio": None, "ratio_text": None},
        {"symbol": "FPT", "event_title": "Trả cổ tức năm 2025 bằng cổ phiếu, tỷ lệ 20:3",
         "event_type": "stock_dividend", "ex_right_date": "2026-07-01", "record_date": "2026-07-02",
         "value": None, "ratio": 0.15, "ratio_text": "20:3"},
        {"symbol": "FPT", "event_title": "Phát hành cổ phiếu theo chương trình ESOP",
         "event_type": "esop", "ex_right_date": "2026-08-01", "value": None, "ratio": 0.01},
        {"symbol": "FPT", "event_title": "Phát hành riêng lẻ cho nhà đầu tư chiến lược",
         "event_type": "private_placement", "ex_right_date": "2026-08-20", "value": None,
         "ratio": 0.05},
        {"symbol": "FPT", "event_title": "Phát hành thêm cổ phiếu cho cổ đông hiện hữu",
         "event_type": "rights_issue", "ex_right_date": "2026-09-10", "record_date": "2026-09-11",
         "value": None, "ratio": 0.1, "ratio_text": "10:1", "exercise_price": 10000.0},
        {"symbol": "FPT", "event_title": "Chia tách cổ phiếu 2:1", "event_type": "stock_split",
         "ex_right_date": "2026-11-02", "value": None, "ratio": 2.0},
    ]

    def test_reference_company_events_parsed(self, monkeypatch):
        import vnstock
        from vnstock_adjust import _fetch_events

        rows = self._ROWS

        class _Company:
            def events(self, start=None, end=None):
                return pd.DataFrame(rows)

        class _Reference:
            def __init__(self, *_a, **_k):
                pass

            def company(self, symbol):
                assert symbol == "FPT"
                return _Company()
        monkeypatch.setattr(vnstock, "Reference", _Reference)
        df = _fetch_events("FPT")
        def _v(x):
            return None if pd.isna(x) else x
        got = [(str(r.ex_date), r.type, _v(r.cash_amount), _v(r.ratio))
               for r in df.itertuples()]
        assert got[0] == ("2026-06-15", "cash", 2000.0, None)
        assert got[1:] == [("2026-07-01", "bonus", None, 0.15),
                           ("2026-09-10", "bonus", None, 0.1),
                           ("2026-11-02", "split", None, 2.0)]

    def test_source_error_skips_ticker(self, monkeypatch):
        import vnstock
        from vnstock.errors import InputError
        from vnstock_adjust import _fetch_events

        class _Reference:
            def __init__(self, *_a, **_k):
                pass

            def company(self, symbol):
                class _C:
                    def events(self, start=None, end=None):
                        raise InputError("Chưa chọn nguồn")
                return _C()
        monkeypatch.setattr(vnstock, "Reference", _Reference)
        assert _fetch_events("FPT").empty


def test_refresh_events_keeps_legacy_cache_rows(tmp_path, monkeypatch):
    """Nguồn thế hệ 6 nghèo sử liệu hơn nguồn cũ ⇒ refresh GỘP, không xoá sự kiện cũ khỏi kho."""
    import vnstock_adjust as va
    old = pd.DataFrame([
        {"ticker": "VNM", "ex_date": "2019-07-01", "type": "cash", "cash_amount": 2000.0,
         "ratio": None, "raw": "DIV/VCI"},
        {"ticker": "VNM", "ex_date": "2026-06-15", "type": "cash", "cash_amount": 1400.0,
         "ratio": None, "raw": "cũ"},
    ])
    path = va._events_path("VNM", tmp_path)
    path.parent.mkdir(parents=True)
    old.to_parquet(path, index=False)
    new = pd.DataFrame([{"ticker": "VNM", "ex_date": pd.Timestamp("2026-06-16").date(),
                         "type": "cash", "cash_amount": 1500.0, "ratio": None, "raw": "gen6"}])
    monkeypatch.setattr(va, "_fetch_events_detail", lambda t, verbose=False: (new, []))

    out = va.refresh_events("VNM", tmp_path)

    got = [(str(r.ex_date), r.cash_amount) for r in out.itertuples()]
    assert got == [("2019-07-01", 2000.0), ("2026-06-16", 1500.0)]   # trùng gần ⇒ bản mới thắng
    assert len(va.load_events("VNM", tmp_path)) == 2



def _seed_cache(va, tmp_path, ticker, rows):
    path = va._events_path(ticker, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_refresh_events_keeps_old_rows_the_new_source_simply_omits(tmp_path, monkeypatch):
    """Nguồn mới trả sự kiện CŨ HƠN dòng kho mà thiếu một dòng ⇒ dòng kho vẫn giữ (nguồn cũ đã chết)."""
    import vnstock_adjust as va
    _seed_cache(va, tmp_path, "HPG", [
        {"ticker": "HPG", "ex_date": "2020-07-01", "type": "cash", "cash_amount": 1000.0,
         "ratio": None, "raw": "DIV/VCI"},
        {"ticker": "HPG", "ex_date": "2022-06-10", "type": "bonus", "cash_amount": None,
         "ratio": 0.3, "raw": "capital_history"},
    ])
    new = pd.DataFrame([
        {"ticker": "HPG", "ex_date": pd.Timestamp(d).date(), "type": "cash", "cash_amount": 500.0,
         "ratio": None, "raw": "gen6"} for d in ("2019-05-01", "2025-06-01")])
    monkeypatch.setattr(va, "_fetch_events_detail", lambda t, verbose=False: (new, []))

    out = va.refresh_events("HPG", tmp_path)

    assert [(str(r.ex_date), r.type) for r in out.itertuples()] == [
        ("2019-05-01", "cash"), ("2020-07-01", "cash"), ("2022-06-10", "bonus"), ("2025-06-01", "cash")]


def test_refresh_events_drops_old_bonus_only_when_source_says_non_price_event(tmp_path, monkeypatch):
    """Dòng "bonus" cũ (ESOP ghi nhầm) bỏ CHỈ khi nguồn mới ghi ngày đó là enum không đổi giá."""
    import vnstock_adjust as va
    _seed_cache(va, tmp_path, "FPT", [
        {"ticker": "FPT", "ex_date": "2018-05-02", "type": "bonus", "cash_amount": None,
         "ratio": 0.15, "raw": "capital_history"},
        {"ticker": "FPT", "ex_date": "2026-08-01", "type": "bonus", "cash_amount": None,
         "ratio": 0.01, "raw": "ESOP ghi nhầm"},
    ])
    new = pd.DataFrame([{"ticker": "FPT", "ex_date": pd.Timestamp("2025-06-15").date(),
                         "type": "cash", "cash_amount": 2000.0, "ratio": None, "raw": "gen6"}])
    monkeypatch.setattr(va, "_fetch_events_detail",
                        lambda t, verbose=False: (new, ["2026-08-03"]))   # esop, lệch 2 ngày

    out = va.refresh_events("FPT", tmp_path)

    assert [(str(r.ex_date), r.type) for r in out.itertuples()] == [("2018-05-02", "bonus"),
                                                                     ("2025-06-15", "cash")]


def test_extract_events_reports_non_price_enum_dates():
    import vnstock_adjust as va

    class _Co:
        def events(self, start=None, end=None):
            return pd.DataFrame([
                {"event_title": "ESOP", "event_type": "esop", "ex_right_date": "2026-08-01", "ratio": 0.01},
                {"event_title": "Cổ tức", "event_type": "cash_dividend", "ex_right_date": "2026-06-15",
                 "value": 2000.0},
            ])
    skipped: list = []
    rows = va._extract_events(_Co(), "FPT", skipped=skipped)
    assert [r["type"] for r in rows] == ["cash"] and skipped == ["2026-08-01"]


def test_refresh_events_handles_tz_aware_gen6_dates_and_ignores_meetings(tmp_path, monkeypatch):
    """Ngày thế hệ 6 có múi giờ VN (hợp đồng `timezones`) ⇒ không TypeError khi so với kho không
    múi; họp/lấy ý kiến cổ đông CÙNG NGÀY không bao giờ xoá đợt thưởng thật trong kho."""
    import vnstock_adjust as va
    _seed_cache(va, tmp_path, "HPG", [
        {"ticker": "HPG", "ex_date": "2022-06-10", "type": "bonus", "cash_amount": None,
         "ratio": 0.3, "raw": "capital_history"},
        {"ticker": "HPG", "ex_date": "2024-03-04", "type": "bonus", "cash_amount": None,
         "ratio": 0.01, "raw": "ESOP ghi nhầm"},
    ])
    tz = "Asia/Ho_Chi_Minh"

    class _Co:
        def events(self, start=None, end=None):
            return pd.DataFrame({
                "event_title": ["Lấy ý kiến cổ đông", "ESOP", "Cổ tức"],
                "event_type": ["shareholder_poll", "esop", "cash_dividend"],
                "ex_right_date": pd.to_datetime(["2022-06-10", "2024-03-05", "2025-06-02"]).tz_localize(tz),
                "value": [None, None, 500.0], "ratio": [None, 0.01, None],
            })
    monkeypatch.setattr(va, "_company_sources", lambda: iter([("gen6", lambda t: _Co())]))

    out = va.refresh_events("HPG", tmp_path)

    assert [(str(r.ex_date), r.type) for r in out.itertuples()] == [("2022-06-10", "bonus"),
                                                                     ("2025-06-02", "cash")]


def test_every_gen6_event_type_enum_is_classified():
    """Đủ 23 enum `event_type` của vnstock 6.0.0 — enum đã biết không bao giờ rơi về dò tiêu đề."""
    import vnstock_adjust as va
    enum = {"additional_listing", "bond_conversion", "bond_interest", "bonus_share", "buyback",
            "cash_dividend", "delisting", "esop", "exchange_transfer", "info_update", "other",
            "private_placement", "rights_issue", "shareholder_meeting", "shareholder_poll",
            "stock_conversion", "stock_dividend", "stock_merge", "stock_split",
            "trading_suspension", "treasury_share_sale", "voting_right", "warrant_settlement"}
    assert set(va._GEN6_EVENT_KIND) == enum

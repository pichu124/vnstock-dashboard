"""
Soi hai báo cáo của `run.py weekend` ngày 22/08/2026.

① **Model watch in 3 dòng ❌ trông y hệt nhau nhưng đòi hai hành động khác
   hẳn.** Cerebras trả `HTTP 402 "Payment required … Visit your billing"` —
   đó là hỏng **TÀI KHOẢN**, MỌI model Cerebras sẽ 402 y như vậy, nên đi thay
   slug là mất công vô ích. OpenRouter trả `HTTP 404 "unavailable for free"`
   kèm "biến mất khỏi danh mục" — đó mới là **model chết**, đúng ca dùng quy
   trình `_MODEL_MIGRATIONS` + `_DEAD_SLUGS`.

② **Báo cáo TUẦN in con số đổi của MỘT PHIÊN mà không ghi mốc.**
   `• Lãi suất liên ngân hàng ON: 3.01%/năm ▼ -1.01 điểm %` và câu
   "giảm 1.01 điểm % **so với kỳ trước**" — trong bản mang tên "Báo cáo tuần"
   thì "kỳ trước" đọc ra là TUẦN trước. Mốc thật là lần đọc liền trước
   (`vnstock_macro._pick` lấy `dates[idx-1]`), tức phiên trước: 2026-08-19.
   Cùng họ bất biến với "Giá 1T %" trong CLAUDE.md — mọi nhãn phải ghi rõ
   khung thời gian.
"""
from __future__ import annotations

import vnstock_model_watch as mw
import vnstock_rates_report as rr

_DEAD = [
    {"provider": "Cerebras", "model": "gemma-4-31b",
     "tag": "[1] sentiment + [7] fallback",
     "detail": 'HTTP 402: {"message":"Payment required to access this resource."}'},
    {"provider": "Cerebras", "model": "gpt-oss-120b",
     "tag": "[3-6] digest b1 + [7] brief",
     "detail": 'HTTP 402: {"message":"Payment required to access this resource."}'},
    {"provider": "OpenRouter", "model": "openai/gpt-oss-20b:free",
     "tag": "[1] sentiment + [3-6] digest b2",
     "detail": 'HTTP 404: {"error":{"message":"This model is unavailable for free."}}'},
]


class TestAccountFailuresAreNotModelFailures:
    def test_two_cerebras_rows_collapse_into_one_account_line(self):
        lines = mw.build_dead_alerts(_DEAD)
        acct = [l for l in lines if l.startswith("🏦")]
        assert len(acct) == 1
        assert "Cerebras" in acct[0] and "402" in acct[0]

    def test_the_account_line_says_swapping_the_slug_will_not_help(self):
        acct = [l for l in mw.build_dead_alerts(_DEAD) if l.startswith("🏦")][0]
        assert "ĐỔI SLUG KHÔNG CỨU ĐƯỢC" in acct

    def test_the_account_line_still_names_every_affected_point(self):
        acct = [l for l in mw.build_dead_alerts(_DEAD) if l.startswith("🏦")][0]
        assert "gemma-4-31b" in acct and "gpt-oss-120b" in acct
        assert "[1] sentiment" in acct and "[3-6] digest b1" in acct

    def test_a_genuine_dead_model_stays_a_model_level_alert(self):
        lines = mw.build_dead_alerts(_DEAD)
        model_lines = [l for l in lines if l.startswith("❌")]
        assert len(model_lines) == 1
        assert "openai/gpt-oss-20b:free" in model_lines[0]

    def test_401_and_403_are_account_level_too(self):
        assert mw.account_level_code("HTTP 401: bad key") == "401"
        assert mw.account_level_code("HTTP 403: forbidden") == "403"

    def test_404_and_429_are_not_account_level(self):
        # 429 là nghẽn tạm thời, KHÔNG được gộp thành "tài khoản chết"
        assert mw.account_level_code("HTTP 404: gone") is None
        assert mw.account_level_code("HTTP 429: rate limited") is None

    def test_no_http_code_is_not_account_level(self):
        assert mw.account_level_code("timeout") is None
        assert mw.account_level_code("") is None
        assert mw.account_level_code(None) is None

    def test_empty_input_gives_no_lines(self):
        assert mw.build_dead_alerts([]) == []
        assert mw.build_dead_alerts(None) == []

    def test_two_providers_failing_on_account_give_two_lines(self):
        rows = [{"provider": "A", "model": "m1", "tag": "t", "detail": "HTTP 402: x"},
                {"provider": "B", "model": "m2", "tag": "t", "detail": "HTTP 401: y"}]
        assert len([l for l in mw.build_dead_alerts(rows) if l.startswith("🏦")]) == 2

    def test_the_dead_openrouter_slug_is_gone_from_every_ladder(self):
        import vnstock_report_digest as dg
        import vnstock_sentiment as snt
        dead = "openai/gpt-oss-20b:free"
        assert all(p["model"] != dead for p in snt._PROVIDERS)
        assert all(m != dead for _, m in dg._FREE_TIER2)
        assert dead not in dg._FREE_MODELS.values()

    def test_no_migration_points_at_the_dead_slug(self):
        # Migration trỏ vào model chết thì vô dụng — đúng ca 22/08
        from vnstock_brief import _MODEL_MIGRATIONS
        assert "openai/gpt-oss-20b:free" not in _MODEL_MIGRATIONS.values()


class TestWeeklyReportLabelsItsComparisonDate:
    def _data(self, prev="2026-08-19"):
        return {"week_label": "Tuần 34/2026", "as_of": "2026-08-21", "gauges": [],
                "rates": [{"label": "Lãi suất liên ngân hàng ON",
                           "value": "3.01%/năm", "change": "▼ -1.01 điểm %",
                           "prev_as_of": prev, "dir": -1,
                           "as_of": "2026-08-20", "source": "SBV"},
                          {"label": "Lãi suất tái cấp vốn (SBV)",
                           "value": "4.50%/năm", "change": "",
                           "prev_as_of": None, "dir": 0,
                           "as_of": "2023-06-19", "source": "SBV"}],
                "narrative": []}

    def test_telegram_bullet_names_the_comparison_date(self):
        out = rr.render_telegram(self._data())
        assert "▼ -1.01 điểm %" in out and "(so 2026-08-19)" in out

    def test_html_row_names_the_comparison_date(self):
        assert "(so 2026-08-19)" in rr.render_html(self._data())

    def test_a_rate_without_a_change_gets_no_dangling_label(self):
        out = rr.render_telegram(self._data())
        assert out.count("(so ") == 1
        assert "4.50%/năm</b>\n" in out or out.rstrip().endswith("4.50%/năm</b>")

    def test_missing_prev_date_does_not_crash_or_invent_one(self):
        out = rr.render_telegram(self._data(prev=None))
        assert "(so " not in out and "▼ -1.01 điểm %" in out

    def test_narrative_says_the_real_date_not_ky_truoc(self):
        by_key = {"interbank_on": {"change": {"delta": -1.01},
                                   "prev_as_of": "2026-08-19"}}
        out = rr._narrative({"gauges": []}, by_key, None)
        joined = " ".join(out)
        assert "so với 2026-08-19" in joined
        assert "kỳ trước" not in joined

    def test_narrative_falls_back_without_inventing_a_week(self):
        by_key = {"interbank_on": {"change": {"delta": -1.01}}}
        joined = " ".join(rr._narrative({"gauges": []}, by_key, None))
        assert "lần đọc trước" in joined and "tuần" not in joined.lower()

    def test_a_small_move_still_says_nothing(self):
        by_key = {"interbank_on": {"change": {"delta": -0.02},
                                   "prev_as_of": "2026-08-19"}}
        assert rr._narrative({"gauges": []}, by_key, None) == []

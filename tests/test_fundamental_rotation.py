"""Updater cơ bản XOAY VÒNG theo "mã lâu chưa kiểm nhất trước" (14/11).

Vết thật: thứ Bảy 14/11 là lượt Weekend đầu tiên trên vnstock thế hệ 6. Bước
`fundamentals --force` chạy ~5,8 mã/phút (đo 🖥️: 939 mã / 2h42) ⇒ một lượt đủ
1.754 mã cần ~5 giờ, mà trần task là 180′ ⇒ bị cắt ở mã thứ ~850. Danh sách
mã xếp theo bảng chữ cái nên tuần nào cũng cắt ĐÚNG chỗ đó: nửa sau bảng chữ
cái không bao giờ được cập nhật, và không có gì báo lỗi (doctor chỉ nhìn mtime
của file, mà file được ghi theo lô nên luôn "tươi").

Sửa: sổ `fundamentals_checked.json` ghi ngày mỗi mã được NGUỒN TRẢ LỜI lần cuối
(có số HOẶC rỗng); thứ tự chạy = chưa kiểm bao giờ → cũ nhất → mới nhất. Bị cắt
giữa chừng thì lượt sau tự chạy phần còn lại.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import vnstock_fund_checked as fc

TODAY = date(2026, 11, 14)


def _iso(d: date) -> str:
    return d.isoformat()


# ── hàm thuần ────────────────────────────────────────────────────────────────

def test_fetch_order_never_checked_first_then_oldest_then_alphabetical():
    last = {"AAA": "2026-11-14", "BBB": "2026-11-07", "CCC": "2026-11-14"}
    assert fc.fetch_order(["CCC", "AAA", "DDD", "BBB"], last) == ["DDD", "BBB", "AAA", "CCC"]


def test_fetch_order_without_any_history_is_plain_alphabetical():
    # Kho mới / sổ chưa có: hành vi y như trước khi sửa.
    assert fc.fetch_order(["VCB", "FPT", "ACB"], {}) == ["ACB", "FPT", "VCB"]


def test_last_checked_takes_the_newer_of_ledger_and_updated_at():
    existing = pd.DataFrame({
        "ticker":     ["AAA", "BBB", "CCC", "DDD"],
        "updated_at": ["2026-11-14", "2026-11-07", None, float("nan")],
    })
    checked = {"BBB": "2026-11-14", "AAA": "2026-10-01", "EEE": "2026-11-10"}
    assert fc.last_checked(existing, checked) == {
        "AAA": "2026-11-14",     # parquet mới hơn sổ
        "BBB": "2026-11-14",     # sổ mới hơn parquet (mã "giữ data cũ")
        "EEE": "2026-11-10",     # chỉ có trong sổ
    }                            # CCC/DDD: không có ngày nào ⇒ coi như chưa kiểm


def test_last_checked_survives_frame_without_updated_at_column():
    assert fc.last_checked(pd.DataFrame({"ticker": ["AAA"]}), {}) == {}
    assert fc.last_checked(pd.DataFrame(), {"AAA": "2026-11-14"}) == {"AAA": "2026-11-14"}


@pytest.mark.parametrize("min_age, expect", [
    (0, []),                               # tắt: không bỏ mã nào
    (1, ["AAA"]),                          # kiểm HÔM NAY ⇒ bỏ
    (8, ["AAA", "BBB"]),                   # 7 ngày trước < 8 ⇒ bỏ
])
def test_checked_within_skips_only_recent_ones(min_age, expect):
    last = {"AAA": _iso(TODAY), "BBB": _iso(TODAY - timedelta(days=7)), "ZZZ": "rác"}
    got = fc.checked_within(["AAA", "BBB", "CCC", "ZZZ"], last, min_age, TODAY)
    assert sorted(got) == expect           # CCC chưa kiểm + ZZZ ngày hỏng: không bao giờ bỏ


def test_stale_count_counts_old_and_never_checked():
    last = {"AAA": _iso(TODAY), "BBB": _iso(TODAY - timedelta(days=22)),
            "CCC": _iso(TODAY - timedelta(days=21))}
    # > 21 ngày: BBB (22) và DDD (chưa kiểm). CCC đúng 21 ngày chưa tính.
    assert fc.stale_count(["AAA", "BBB", "CCC", "DDD"], last, 21, TODAY) == 2


# ── sổ trên đĩa ──────────────────────────────────────────────────────────────

def test_ledger_roundtrip_and_tolerates_garbage(tmp_path):
    p = tmp_path / fc.LEDGER_NAME
    assert fc.load(p) == {}                                   # chưa có file
    fc.save({"VCB": "2026-11-14"}, p)
    assert fc.load(p) == {"VCB": "2026-11-14"}
    p.write_text("{ cụt giữa chừng", encoding="utf-8")
    assert fc.load(p) == {}                                   # hỏng ⇒ coi như chưa có
    p.write_text(json.dumps(["không", "phải", "dict"]), encoding="utf-8")
    assert fc.load(p) == {}
    p.write_text(json.dumps({"VCB": "2026-11-14", "BAD": 5, "": "x"}), encoding="utf-8")
    assert fc.load(p) == {"VCB": "2026-11-14"}                # lọc mục sai kiểu


# ── update() thật, nguồn giả ─────────────────────────────────────────────────

@pytest.fixture
def fu(tmp_path, monkeypatch):
    """Updater trỏ vào tmp: parquet, ảnh tháng và sổ đều đi theo FUND_PATH."""
    import vnstock_fundamental_updater as mod
    monkeypatch.setattr(mod, "FUND_PATH", tmp_path / "fundamentals.parquet")
    monkeypatch.setattr(mod, "FUND_HISTORY_DIR", tmp_path / "hist")
    monkeypatch.setattr(mod, "_fetch_cash_flow", lambda t: {})
    monkeypatch.setattr(mod, "_fetch_debt_to_equity", lambda t: None)
    mod.seen = []                                             # thứ tự nguồn bị hỏi

    def _ratios(t):
        mod.seen.append(t)
        if t.startswith("EMPTY"):
            return {}
        if t.startswith("BAD"):
            raise RuntimeError("nguồn nổ")
        return {"pe": 10.0, "roe": 15.0}

    monkeypatch.setattr(mod, "_fetch_ratios", _ratios)
    yield mod
    del mod.seen


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ledger(fu) -> dict:
    return fc.load(fu.FUND_PATH.parent / fc.LEDGER_NAME)


def test_update_asks_the_stalest_tickers_first(fu):
    fu._save(pd.DataFrame({
        "ticker":     ["AAA", "BBB", "CCC"],
        "pe":         [1.0, 2.0, 3.0],
        "updated_at": [_today(), "2026-01-07", _today()],
    }))
    fu.update(tickers=["CCC", "AAA", "DDD", "BBB"], force=True, delay=0.0, workers=1)
    assert fu.seen == ["DDD", "BBB", "AAA", "CCC"]


def test_every_answered_ticker_is_stamped_but_errors_are_not(fu):
    # KEEP: đã có số, lần này nguồn trả rỗng ⇒ "giữ data cũ" — dòng parquet KHÔNG đổi,
    # nên chỉ có sổ mới biết nó vừa được hỏi.
    fu._save(pd.DataFrame({"ticker": ["EMPTYKEEP"], "pe": [9.0], "updated_at": ["2026-01-07"]}))
    df = fu.update(tickers=["AAA", "EMPTYKEEP", "EMPTYNEW", "BADX"], force=True,
                   delay=0.0, workers=1)
    led = _ledger(fu)
    assert led == {"AAA": _today(), "EMPTYKEEP": _today(), "EMPTYNEW": _today()}
    assert "BADX" not in led                                   # lỗi ⇒ tuần sau thử lại SỚM
    keep = df.loc[df["ticker"] == "EMPTYKEEP"].iloc[0]
    assert keep["pe"] == 9.0 and keep["updated_at"] == "2026-01-07"   # số cũ giữ nguyên


def test_kept_tickers_do_not_jump_the_queue_next_run(fu):
    """160 mã 'giữ data cũ' ngày 14/11 mang `updated_at` cũ mãi mãi. Không có sổ thì
    tuần nào chúng cũng chen lên đầu hàng, ăn ~28′ của trần 180′."""
    fu._save(pd.DataFrame({"ticker": ["EMPTYKEEP", "OLD"], "pe": [9.0, 5.0],
                           "updated_at": ["2026-01-07", "2026-02-01"]}))
    fu.update(tickers=["EMPTYKEEP"], force=True, delay=0.0, workers=1)   # hỏi rồi, vẫn rỗng
    fu.seen.clear()
    fu.update(tickers=["EMPTYKEEP", "OLD"], force=True, delay=0.0, workers=1)
    assert fu.seen == ["OLD", "EMPTYKEEP"]


class _Killed(BaseException):
    """Task Scheduler giết tiến trình: không phải Exception nên `_fetch_one` không nuốt."""


def test_a_run_cut_short_is_finished_by_the_next_one(fu, monkeypatch):
    tickers = [f"T{i:02d}" for i in range(10)]
    real = fu._fetch_ratios

    def _dies_at_seven(t):
        if len(fu.seen) >= 7:
            raise _Killed()
        return real(t)

    monkeypatch.setattr(fu, "_fetch_ratios", _dies_at_seven)
    with pytest.raises(_Killed):
        fu.update(tickers=tickers, force=True, delay=0.0, workers=1, batch_save=3)
    first = set(_ledger(fu))                # chỉ những lô ĐÃ LƯU mới được tính là xong
    assert first == {"T00", "T01", "T02", "T03", "T04", "T05"}

    monkeypatch.setattr(fu, "_fetch_ratios", real)
    fu.seen.clear()
    fu.update(tickers=tickers, force=True, delay=0.0, workers=1, batch_save=3)
    assert fu.seen[:4] == ["T06", "T07", "T08", "T09"]         # phần bị bỏ dở đi TRƯỚC
    assert set(_ledger(fu)) == set(tickers)


def test_a_run_cut_short_still_records_reporting_periods(fu, monkeypatch):
    """Sổ kỳ BCTC (`fundamentals_periods.json`) từng chỉ được gấp ở lần lưu CUỐI.
    Lượt T7 nay bị cắt MỖI tuần ⇒ lần lưu cuối không bao giờ tới ⇒ dòng "Kỳ BCTC mới"
    của brief lặng lẽ biến mất. Phải gấp ở MỖI lô đã lưu."""
    from vnstock_fund_periods import LEDGER_NAME, read_ledger

    def _ratios(t):
        fu.seen.append(t)
        if len(fu.seen) > 7:
            raise _Killed()
        return {"pe": 10.0, "debt_to_equity": 1.2, "de_period": "2026-Q3"}

    monkeypatch.setattr(fu, "_fetch_ratios", _ratios)
    with pytest.raises(_Killed):
        fu.update(tickers=[f"T{i:02d}" for i in range(10)], force=True, delay=0.0,
                  workers=1, batch_save=3)
    periods = read_ledger(fu.FUND_PATH.parent / LEDGER_NAME).get("tickers") or {}
    assert set(periods) == {"T00", "T01", "T02", "T03", "T04", "T05"}   # 2 lô đã lưu
    assert periods["T00"]["de"]["period"] == "2026-Q3"


def test_min_age_days_fetches_only_what_today_missed(fu):
    fu.update(tickers=["AAA", "BBB"], force=True, delay=0.0, workers=1)
    fu.seen.clear()
    df = fu.update(tickers=["AAA", "BBB", "CCC", "DDD"], force=True, delay=0.0,
                   workers=1, min_age_days=1)
    assert fu.seen == ["CCC", "DDD"]
    assert sorted(df["ticker"]) == ["AAA", "BBB", "CCC", "DDD"]   # dòng cũ không bị rơi


def test_min_age_days_with_nothing_left_is_a_clean_noop(fu, capsys):
    fu.update(tickers=["AAA"], force=True, delay=0.0, workers=1)
    fu.seen.clear()
    assert fu.update(tickers=["AAA"], force=True, delay=0.0, workers=1, min_age_days=1) is None
    assert fu.seen == []
    assert "--min-age-days" in capsys.readouterr().out


def test_corrupt_ledger_does_not_stop_the_update(fu):
    (fu.FUND_PATH.parent / fc.LEDGER_NAME).write_text("{ cụt", encoding="utf-8")
    fu.update(tickers=["AAA"], force=True, delay=0.0, workers=1)
    assert _ledger(fu) == {"AAA": _today()}


def test_parallel_run_stamps_the_same_tickers_as_sequential(fu):
    fu.update(tickers=["AAA", "BBB", "EMPTYX", "BADX", "CCC"], force=True,
              delay=0.0, workers=4, batch_save=2)
    assert set(_ledger(fu)) == {"AAA", "BBB", "EMPTYX", "CCC"}


def test_weekend_step_keeps_force_and_needs_no_new_flag():
    """Xoay vòng nằm trong thứ tự chạy, không nằm ở cờ: lệnh của task T7 không đổi."""
    import run
    import argparse
    cmds = dict(run._weekend_steps(argparse.Namespace(warehouse="data_warehouse")))
    assert "--force" in cmds["fundamentals"] and "--min-age-days" not in cmds["fundamentals"]

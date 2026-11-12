"""
Corp-action events layer — fetch & cache per-ticker corporate actions.

Events (cash dividends, splits, bonus issues, share issuances) are fetched per
ticker from vnstock thế hệ 6 (`Reference().company(t).events()`) and cached to
`data_warehouse/_meta/corp_actions/{TICKER}.parquet`. If the fetch fails
or vnstock lacks the endpoint, the ticker is silently skipped.

Thế hệ 6 không có `capital_history()` (UnsupportedError): tăng vốn (phát hành thêm,
quyền mua…) nay đọc từ chính `events()` — dòng phát hành có tỷ lệ ⇒ `type="bonus"`,
đúng loại mà bản `capital_history` cũ ghi để máy dò bất thường bỏ qua vách giá.

Consumers: vnstock_events (upcoming-events brief block), vnstock_anomaly
(corp-action-aware anomaly suppression), vnstock_corp_registry.

Data contract
-------------
The cached events parquet has the schema:

    ticker: str
    ex_date: date
    type: "cash" | "stock" | "split" | "bonus"
    cash_amount: float (VND, nullable)
    ratio: float (nullable)  # e.g. 10:1 split → ratio=10
    raw: str (original description, for debugging)

Public API
----------
    load_events(ticker, meta_dir) -> DataFrame
        Read cached corp-action events (empty DF if cache miss).

    refresh_events(ticker) -> DataFrame
        Fetch from vnstock and write cache. Best-effort only.

(A back-adjusted-price layer — apply_adjustments()/close_adj — used to live
here but was never wired into production; see git history if needed.)

This module is **read-only** with respect to the raw OHLCV warehouse.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
CORP_ACTIONS_SUBDIR = "_meta/corp_actions"

EVENT_SCHEMA_COLS = ["ticker", "ex_date", "type", "cash_amount", "ratio", "raw"]


# ─────────────────────────────────────────────────────────────────────────────
# Loading / caching
# ─────────────────────────────────────────────────────────────────────────────


def _events_path(ticker: str, warehouse: Path) -> Path:
    return warehouse / CORP_ACTIONS_SUBDIR / f"{ticker}.parquet"


def load_events(ticker: str, warehouse: Path = DEFAULT_WAREHOUSE) -> pd.DataFrame:
    """Read cached corp-action events. Returns an empty DF on miss."""
    path = _events_path(ticker, warehouse)
    if not path.exists():
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    if df.empty:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
    return df


def refresh_events(
    ticker: str,
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    verbose: bool = False,
) -> pd.DataFrame:
    """Best-effort fetch of corp-action events from vnstock and cache to parquet.

    GỘP với cache cũ: nguồn dòng cũ (DIV/VCI, capital_history) đã chết từ 10/11, thứ nó
    ghi không lấy lại được ⇒ dòng cũ CHỈ bị bỏ khi có BẰNG CHỨNG DƯƠNG từ nguồn mới:
      • nguồn mới có dòng cùng loại lệch ≤ `_NEAR_DUP_DAYS` ngày (bản mới thắng), hoặc
      • dòng cũ là "bonus" mà nguồn mới ghi ngày đó (±`_NEAR_DUP_DAYS`) là sự kiện KHÔNG đổi
        giá theo enum (ESOP, phát hành riêng lẻ… từng bị dò tiêu đề ghi thành "bonus").
    Nguồn mới KHÔNG trả một sự kiện không phải là bằng chứng nó không có thật.
    """
    events, non_price_dates = _fetch_events_detail(ticker, verbose=verbose)
    if events.empty:
        return events
    old = load_events(ticker, warehouse)
    np_days = [d for d in map(_as_local_date, non_price_dates) if d is not None]
    if not old.empty and np_days:
        def _refuted(row) -> bool:
            d = _as_local_date(row["ex_date"])
            return (row["type"] == "bonus" and d is not None
                    and any(abs((d - n).days) <= _NEAR_DUP_DAYS for n in np_days))
        old = old[~old.apply(_refuted, axis=1)]
    if not old.empty:
        merged = pd.concat([events, old[EVENT_SCHEMA_COLS]], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ticker", "ex_date", "type"], keep="first")
        events = _drop_near_duplicates(merged).sort_values("ex_date").reset_index(drop=True)
    path = _events_path(ticker, warehouse)
    path.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(path, index=False)
    return events


def _as_local_date(v):
    """str / date / Timestamp (có hoặc không múi giờ — thế hệ 6 trả ngày có múi giờ VN) →
    `datetime.date` theo giờ VN; rỗng / không đọc được ⇒ None."""
    try:
        t = pd.Timestamp(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Ho_Chi_Minh")
    return t.date()


def _fetch_events(ticker: str, *, verbose: bool = False) -> pd.DataFrame:
    """Query vnstock for corp actions. Returns empty DF on any failure."""
    return _fetch_events_detail(ticker, verbose=verbose)[0]


def _fetch_events_detail(ticker: str, *, verbose: bool = False) -> tuple[pd.DataFrame, list]:
    """Như `_fetch_events`, kèm danh sách ex_date mà nguồn ghi là sự kiện KHÔNG đổi giá
    (enum thế hệ 6) — bằng chứng để `refresh_events` bỏ dòng "bonus" cũ ghi nhầm.

    GỘP kết quả của MỌI nguồn trong `_company_sources()` (đổi 14/08 — trước đó
    "nguồn đầu có gì đó là dừng", và đó chính là vùng mù 12 mã của div_check).
    Trùng lặp khử ở dưới, dòng của nguồn ĐỨNG TRƯỚC thắng. Thế hệ 6 chỉ còn MỘT
    lối (`Reference().company(t)`); thứ tự nguồn dữ liệu do luật `VNSTOCK_SOURCE`
    quyết, không do code.
    """
    rows: list[dict] = []
    non_price: list = []

    for source_name, resolve in _company_sources():
        try:
            company = resolve(ticker)
        except Exception as e:
            if verbose:
                print(f"  [{ticker}] {source_name}: resolve failed — {e}")
            continue
        if company is None:
            continue
        dividends = _extract_dividends(company, ticker)
        events = _extract_events(company, ticker, skipped=non_price)
        found = dividends + events
        rows.extend(found)
        if verbose:
            if found:
                print(f"  [{ticker}] {source_name}: "
                      f"{len(dividends)} div, {len(events)} event")
            else:
                print(f"  [{ticker}] {source_name}: no data")

    if not rows:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS), non_price

    df = pd.DataFrame(rows)
    for col in EVENT_SCHEMA_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[EVENT_SCHEMA_COLS]
    df["ex_date"] = pd.to_datetime(df["ex_date"], errors="coerce").dt.date
    df = df.dropna(subset=["ex_date", "ticker"])
    # keep="first": rows đang theo THỨ TỰ ƯU TIÊN nguồn (giàu sử liệu trước),
    # và trong mỗi nguồn extractor dividends (đủ cash_amount) chạy trước —
    # bản "đến trước" luôn là bản giàu thông tin hơn.
    df = df.drop_duplicates(subset=["ticker", "ex_date", "type"], keep="first")
    df = _drop_near_duplicates(df)
    return df.sort_values("ex_date").reset_index(drop=True), non_price


# Hai nguồn ghi cùng một sự kiện bằng hai mốc ngày lệch nhau (ex-date vs
# record-date thường cách 1-2 ngày làm việc) → nếu giữ cả hai, div_check sẽ
# chấm một "sự kiện" không có thật ngay cạnh sự kiện thật.
_NEAR_DUP_DAYS = 5


def _drop_near_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Khử sự kiện TRÙNG GẦN giữa các nguồn: cùng (ticker, type) mà ex_date
    lệch ≤ ``_NEAR_DUP_DAYS`` ngày = một sự kiện thật bị hai nguồn ghi hai
    mốc. Giữ dòng đến TRƯỚC (nguồn ưu tiên hơn). Đánh đổi ghi rõ: hai sự
    kiện CÙNG LOẠI cách nhau ≤5 ngày lịch gần như không tồn tại ở corp
    action VN — chấp nhận gộp nhầm ca đó để đổi lấy không chấm sự kiện ma.
    """
    if df.empty:
        return df
    keep_rows = []
    kept_dates: dict[tuple, list] = {}
    for _, row in df.iterrows():
        key = (row["ticker"], row["type"])
        ex = pd.Timestamp(row["ex_date"])
        if any(abs((ex - d).days) <= _NEAR_DUP_DAYS
               for d in kept_dates.get(key, [])):
            continue
        kept_dates.setdefault(key, []).append(ex)
        keep_rows.append(row)
    return pd.DataFrame(keep_rows).reset_index(drop=True)


def _company_sources():
    """Yield (name, resolver) pairs. Resolver: str -> company-like object.

    Thế hệ 6: một lối duy nhất `Reference().company(t)` qua mặt tiền `vnstock_auth`
    (nguồn chọn ở `.env`, không ghi tên nguồn vào lệnh gọi).
    """

    def via_reference(ticker: str):
        from vnstock_auth import get_vnstock
        return get_vnstock(ticker).company

    yield "vnstock:Reference.company", via_reference


_DIVIDEND_METHOD_NAMES = (
    "dividends",
    "dividend",
    "dividend_history",
    "cash_dividend",
    "cash_dividend_history",
    "corporate_action_dividends",
)


def _call_first_working(obj, method_names):
    """Call the first attribute/method on ``obj`` that returns a non-empty DataFrame."""
    for name in method_names:
        try:
            attr = getattr(obj, name)
        except AttributeError:
            continue
        try:
            val = attr() if callable(attr) else attr
        except Exception:
            continue
        if val is None:
            continue
        try:
            if hasattr(val, "empty") and val.empty:
                continue
        except Exception:
            pass
        return name, val
    return None, None


def _extract_dividends(company, ticker: str) -> list[dict]:
    name, div = _call_first_working(company, _DIVIDEND_METHOD_NAMES)
    if div is None:
        return []
    div = div.copy()
    div.columns = [c.lower() for c in div.columns]
    out: list[dict] = []
    for _, r in div.iterrows():
        ex = (r.get("exercise_date") or r.get("ex_date")
              or r.get("ex_rights_date") or r.get("record_date"))
        cash = (r.get("cash_dividend") or r.get("cash_value")
                or r.get("value") or r.get("amount")
                or r.get("dividend_value"))
        try:
            cash_val = float(cash) if cash not in (None, "") else None
        except (TypeError, ValueError):
            cash_val = None
        if ex is None or cash_val is None:
            continue
        out.append({
            "ticker": ticker,
            "ex_date": ex,
            "type": "cash",
            "cash_amount": cash_val,
            "ratio": None,
            "raw": str(r.to_dict()),
        })
    return out


_EVENT_METHOD_NAMES = (
    "events",
    "event_history",
    "corporate_events",
    "corp_events",
    "company_events",
    "events_schedule",
)


# Category VCI không phải corp-action giá — bỏ qua thẳng (họp ĐHĐCĐ, giao
# dịch nội bộ, đổi địa chỉ… không làm giá tham chiếu bị điều chỉnh).
_EVENT_SKIP_CATEGORIES = {"MAJOR_SHAREHOLDER_TRADING", "SHAREHOLDER_MEETING",
                          "OTHER"}

# Thế hệ 6: `event_type` là enum chữ thường của hợp đồng vnstock — ĐỦ 23 giá trị của
# `reference.company.events` bản 6.0.0. Loại KHÔNG đổi giá tham chiếu ⇒ None (bỏ). Phát hành
# quyền mua giữ kiểu "bonus" như `capital_history()` dòng cũ (vốn điều lệ tăng ⇒ "bonus");
# gộp cổ phiếu (stock_merge) đổi giá như chia tách ⇒ "split". Chỉ enum THẬT SỰ lạ (bản
# vnstock mới thêm) mới rơi về dò tiêu đề.
_GEN6_EVENT_KIND = {
    "cash_dividend": "cash",
    "stock_dividend": "bonus",
    "bonus_share": "bonus",
    "rights_issue": "bonus",
    "stock_split": "split",
    "stock_merge": "split",
    "additional_listing": None, "bond_conversion": None, "bond_interest": None,
    "buyback": None, "delisting": None, "esop": None, "exchange_transfer": None,
    "info_update": None, "other": None, "private_placement": None,
    "shareholder_meeting": None, "shareholder_poll": None, "stock_conversion": None,
    "trading_suspension": None, "treasury_share_sale": None, "voting_right": None,
    "warrant_settlement": None,
}
# Loại PHÁT HÀNH không đổi giá — thứ mà dò tiêu đề ("phát hành"…) từng ghi nhầm thành "bonus".
# Chỉ chúng mới là bằng chứng để bỏ dòng "bonus" cũ; họp/lấy ý kiến cổ đông, cập nhật thông
# tin, đình chỉ… hay CHỐT CÙNG NGÀY với đợt thưởng thật ⇒ không bao giờ là bằng chứng.
_GEN6_ISSUANCE_NO_PRICE = frozenset({
    "esop", "private_placement", "treasury_share_sale", "bond_conversion",
    "stock_conversion", "warrant_settlement", "additional_listing",
})


def _first_val(r, *names):
    """Giá trị đầu tiên khác rỗng/NaN trong các cột ứng viên."""
    for n in names:
        v = r.get(n)
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
            continue
        return v
    return None


def _extract_events(company, ticker: str, skipped: list | None = None) -> list[dict]:
    """Đọc events() về CHUẨN schema — hiểu mọi hình dạng dữ liệu đã gặp.

    Bài học 14/08 (dump VNM/SAB/GVR): extractor cũ chỉ bắt chia tách/thưởng
    và dò cột `ex_date`/`event_name` — trong khi VCI trả cổ tức TIỀN MẶT
    nằm ngay trong events() (event_code=DIV, `value_per_share` VND/cp) với
    cột tên `exright_date`/`event_name_vi`. Kết quả: nhóm trả tiền mặt
    (VNM/SAB/PLX/GVR…) trắng sự kiện oan suốt — "extractor mù, nguồn sáng".

    Thế hệ 6 (hồ sơ v5): `event_title`, `event_type`, `ex_right_date`, `value`
    (tiền/cp), `ratio`. Dòng PHÁT HÀNH (thêm, quyền mua…) có tỷ lệ ⇒ `bonus` — thay
    cho `capital_history()` mà thế hệ 6 không có.
    """
    name, evt = _call_first_working(company, _EVENT_METHOD_NAMES)
    if evt is None:
        return []
    evt = evt.copy()
    evt.columns = [c.lower() for c in evt.columns]
    out: list[dict] = []
    for _, r in evt.iterrows():
        etype = str(r.get("event_type") or "").strip().lower()
        kind = _GEN6_EVENT_KIND.get(etype, "") if etype else ""
        if kind is None:                       # enum thế hệ 6 không đổi giá tham chiếu
            if skipped is not None and etype in _GEN6_ISSUANCE_NO_PRICE:
                skipped.append(_first_val(r, "ex_date", "exercise_date", "ex_rights_date",
                                          "exright_date", "ex_right_date"))
            continue
        cat = str(_first_val(r, "category", "event_type") or "").upper()
        if not kind and cat in _EVENT_SKIP_CATEGORIES:
            continue
        ex = _first_val(r, "ex_date", "exercise_date", "ex_rights_date",
                        "exright_date", "ex_right_date")
        label = str(_first_val(r, "event_name_vi", "event_name",
                               "event_title_vi", "event_title", "title",
                               "event") or "").lower()
        code = str(r.get("event_code") or "").upper()

        def _num(*names):
            v = _first_val(r, *names)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        if ex is None:
            continue
        if kind:                               # thế hệ 6: enum quyết, không dò chữ
            is_cash, is_split, is_bonus = kind == "cash", kind == "split", kind == "bonus"
        else:                                  # bảng không có enum: dò tiêu đề như dòng cũ
            is_cash = ((code == "DIV" or cat == "DIVIDEND" or "cổ tức bằng tiền" in label
                        or "cash dividend" in label) and "cổ tức bằng cổ phiếu" not in label)
            is_split = "split" in label or "chia tách" in label or "tách cổ phiếu" in label
            is_bonus = ("bonus" in label or "thưởng" in label or "stock dividend" in label
                        or "cổ tức bằng cổ phiếu" in label or "phát hành" in label
                        or "quyền mua" in label or "rights" in label)
        if is_cash:
            cash_val = _num("value_per_share", "cash_per_share", "cash_dividend", "cash_value",
                            "value", "amount")
            if cash_val is None or not cash_val > 0:
                continue
            out.append({
                "ticker": ticker, "ex_date": ex, "type": "cash",
                "cash_amount": cash_val, "ratio": None,
                "raw": str(r.to_dict()),
            })
        elif is_split:
            ratio_val = _num("ratio", "split_ratio", "exercise_ratio")
            if ratio_val is None:
                continue
            out.append({
                "ticker": ticker, "ex_date": ex, "type": "split",
                "cash_amount": None, "ratio": ratio_val,
                "raw": str(r.to_dict()),
            })
        elif is_bonus:
            ratio_val = _num("ratio", "exercise_ratio")
            if ratio_val is None:
                continue
            out.append({
                "ticker": ticker, "ex_date": ex, "type": "bonus",
                "cash_amount": None, "ratio": ratio_val,
                "raw": str(r.to_dict()),
            })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic probe — for debugging API changes
# ─────────────────────────────────────────────────────────────────────────────


def probe_company(ticker: str) -> dict:
    """Introspect what each data source exposes for ``ticker``.

    Returns a dict with source name → method/attr lists + sample data.
    Useful when the vnstock API changes and _extract_* stop matching.

    CLI: ``python vnstock_adjust.py --probe VCB``
    """
    out: dict = {"ticker": ticker, "sources": {}}
    for source_name, resolve in _company_sources():
        info: dict = {"resolved": False, "error": None,
                      "methods": [], "attrs": [], "samples": {}}
        try:
            company = resolve(ticker)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            out["sources"][source_name] = info
            continue
        if company is None:
            info["error"] = "resolver returned None"
            out["sources"][source_name] = info
            continue

        info["resolved"] = True
        for attr_name in sorted(dir(company)):
            if attr_name.startswith("_"):
                continue
            try:
                val = getattr(company, attr_name)
            except Exception:
                continue
            if callable(val):
                info["methods"].append(attr_name)
            else:
                info["attrs"].append(attr_name)

        # Probe every public method — not just our guesses. For each, try
        # calling with no args, then with common (start, end) date range args.
        # This catches methods that require parameters (like KBS dividends).
        for candidate in info["methods"]:
            sample_key = candidate
            attempts = [
                ("()", lambda a=getattr(company, candidate): a()),
                ("(start, end)",
                 lambda a=getattr(company, candidate):
                 a(start="2020-01-01", end="2026-12-31")),
            ]
            for label, call in attempts:
                try:
                    val = call()
                except Exception as e:
                    info["samples"][f"{sample_key}{label}"] = \
                        f"<error: {type(e).__name__}: {str(e)[:60]}>"
                    continue
                if val is None:
                    info["samples"][f"{sample_key}{label}"] = "<None>"
                elif hasattr(val, "empty") and val.empty:
                    info["samples"][f"{sample_key}{label}"] = "<empty DataFrame>"
                elif hasattr(val, "columns"):
                    info["samples"][f"{sample_key}{label}"] = {
                        "shape": list(val.shape),
                        "columns": list(val.columns),
                        "head": val.head(2).to_dict(orient="records"),
                    }
                    break  # stop trying variants once we got data
                else:
                    info["samples"][f"{sample_key}{label}"] = \
                        f"<{type(val).__name__}>"
                    break
        out["sources"][source_name] = info
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Core adjustment
# ─────────────────────────────────────────────────────────────────────────────






# ─────────────────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────────────────




__all__ = [
    "EVENT_SCHEMA_COLS",
    "load_events",
    "probe_company",
    "refresh_events",
]


def _main():
    import argparse
    import json as _json
    import sys as _sys

    # Force UTF-8 on stdout (Windows console defaults to cp1252 which can't
    # encode Vietnamese characters in probe output)
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Corporate-action probe/refresh")
    ap.add_argument("--probe", metavar="TICKER",
                    help="Introspect what corp-action methods a ticker exposes")
    ap.add_argument("--refresh", metavar="TICKER",
                    help="Fetch and cache corp-action events for a ticker")
    ap.add_argument("--out", metavar="PATH",
                    help="Write probe output to this file (UTF-8) instead of stdout")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.probe:
        info = probe_company(args.probe)
        text = _json.dumps(info, indent=2, default=str, ensure_ascii=False)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"[probe] wrote {args.out} ({len(text):,} chars)")
        else:
            print(text)
    elif args.refresh:
        ev = refresh_events(args.refresh, verbose=args.verbose)
        print(f"[refresh] {args.refresh}: {len(ev)} event(s)")
        if not ev.empty:
            print(ev.head(10).to_string(index=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()

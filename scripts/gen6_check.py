"""Kiểm nhanh vnstock thế hệ 6 trên MÁY THẬT (có khoá nguồn): mỗi loại dữ liệu dự án dùng —
nguồn nào trả lời, cột nào, đơn vị/múi giờ, có khớp kho giá không. Không ghi kho giá, không in khoá;
thứ DUY NHẤT được ghi là đệm NN ròng theo ngày `_meta/nn_screener/<ngày>.parquet` (phiên đã chốt —
chính đệm pipeline dùng, ghi trước càng đỡ thời gian cho lượt tối). Kết quả in ra màn hình + `gen6_check_report.txt` (gốc repo, đã gitignore) để dán cho Claude.

    python scripts/gen6_check.py            # mặc định FPT, VCB, HPG
    python scripts/gen6_check.py --tickers FPT,SHS,BSR

Mục "LỖI NGUỒN" với nguồn chưa khai/chưa có khoá là bình thường (vd thống kê lệnh chỉ SSI có).
Cảnh báo `SchemaChangeWarning` (nếu có) được GHI LẠI, không tắt.
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

# Loại dữ liệu → route vnstock thế hệ 6 (để in nguồn được chọn)
ROUTES = {
    "Giá ngày/phút cổ phiếu": "market.equity.ohlcv",
    "Giá chỉ số": "market.index.ohlcv",
    "Bảng giá live": "market.equity.quote",
    "Chỉ số trong phiên": "market.index.quote",
    "HĐTL live": "market.futures.quote",
    "Volume profile": "market.equity.volume_profile",
    "NN ròng theo mã (screener)": "market.equity.screener",
    "Thống kê lệnh (Lệnh lớn, GTGD chỉ số)": "market.equity.daily_stats",
    "Rổ VN30": "reference.index.members",
    "Danh sách mã theo sàn": "reference.equity.list",
    "Niêm yết / cổ đông / free-float": "reference.company.listing",
    "Sự kiện quyền": "reference.company.events",
    "BCTC + chỉ số tài chính": "fundamental.equity.ratio",
}


def ratio_summary(wh: pd.DataFrame, src: pd.DataFrame) -> dict:
    """Hàm THUẦN: so `close` kho vs nguồn theo ngày (`time` là date). Trả n, trung vị tỉ lệ kho/nguồn,
    lệch % tối đa, ngày cuối mỗi bên. Tỉ lệ ≈1 = cùng đơn vị + cùng cơ sở; ≈1000 = lệch đơn vị."""
    out = {"n": 0, "wh_last": None, "src_last": None}
    if not wh.empty:
        out["wh_last"] = str(max(wh["time"]))
    if not src.empty:
        out["src_last"] = str(max(src["time"]))
    m = wh.merge(src, on="time", suffixes=("_wh", "_src"))
    m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
    if m.empty:
        return out
    r = m["close_wh"] / m["close_src"]
    out.update(n=int(len(m)), ratio_median=round(float(r.median()), 4),
               max_dev_pct=round(float((r / r.median() - 1).abs().max() * 100), 2))
    return out


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, s: str = "") -> None:
        print(s)
        self.lines.append(s)

    def run(self, title: str, fn) -> None:
        t0 = time.time()
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            try:
                msg = fn()
                status = "OK  "
            except Exception as e:  # noqa: BLE001 — công cụ kiểm: mọi lỗi là một kết quả
                code = getattr(e, "code", "") or ""
                msg = f"{type(e).__name__} {code}: {str(e)[:220]}"
                status = "LỖI "
        schema = [w for w in rec if "SchemaChange" in type(w.message).__name__
                  or "SchemaChange" in w.category.__name__]
        self.add(f"[{status}] {title} ({time.time() - t0:.1f}s): {msg}")
        for w in schema[:3]:
            self.add(f"        ⚠ SchemaChangeWarning: {str(w.message)[:200]}")


def _cols(df) -> str:
    if df is None:
        return "None"
    if isinstance(df, pd.Series):
        return f"Series {len(df)} dòng"
    return f"{len(df)} dòng; cột: {', '.join(map(str, list(df.columns)[:18]))}"


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tickers", default="FPT,VCB,HPG")
    ap.add_argument("--warehouse", default=str(REPO / "data_warehouse"))
    args = ap.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    prices = Path(args.warehouse) / "prices"
    rep = Report()

    import vnstock
    import vnstock_auth as va
    from vnstock import Fundamental, Market, Reference
    from scripts.probe_price_basis import load_wh

    summary = va.configure_sources(force=True)
    va.keep_schema_warnings()
    rep.add(f"vnstock {getattr(vnstock, '__version__', '?')} · nguồn khai: {summary['default'] or '(trống)'}"
            f" · luật theo nhóm: {summary['routes'] or '(không)'}")
    rep.add("")
    rep.add("== Nguồn được chọn cho từng loại dữ liệu ==")
    for label, route in ROUTES.items():
        try:
            w = vnstock.sources.which(route)
            got = (f"dùng: {', '.join(w.get('sources') or []) or '(CHƯA có nguồn khai đọc được)'}"
                   f" · đọc được: {', '.join(w.get('readers') or []) or '-'}")
        except Exception as e:  # noqa: BLE001
            got = f"{type(e).__name__} {getattr(e, 'code', '')}"
        rep.add(f"  {label:<40} → {got}")
    rep.add("")

    today = date.today()
    d0 = today - timedelta(days=60)
    rep.add("== Giá ngày: nguồn vs kho (tỉ lệ ≈1 là khớp; ≈1000 là lệch đơn vị) ==")
    for tk in tickers:
        def _price(tk=tk):
            src = va.get_vnstock(tk).quote.history(start=d0.isoformat(), end=today.isoformat(), interval="1D")
            s = src[["time", "close"]].copy()
            s["time"] = pd.to_datetime(s["time"]).dt.date
            wh = load_wh(prices, tk, d0, today)
            return f"{ratio_summary(wh, s)} · múi giờ cột time: {getattr(src['time'].dt, 'tz', None)}"
        rep.run(f"{tk} ohlcv 1D", _price)

    def _intraday():
        df = va.get_vnstock(tickers[0]).quote.history(
            start=(today - timedelta(days=5)).isoformat(), end=today.isoformat(), interval="1m")
        return f"{len(df)} nến 1m; {df['time'].min()} → {df['time'].max()}" if len(df) else "rỗng"
    rep.run(f"{tickers[0]} ohlcv 1m", _intraday)

    def _index():
        df = va.get_vnstock("VNINDEX").quote.history(
            start=(today - timedelta(days=10)).isoformat(), end=today.isoformat(), interval="1D")
        return f"{len(df)} phiên; close cuối {df['close'].iloc[-1] if len(df) else '-'}"
    rep.run("VNINDEX ohlcv 1D", _index)

    def _quote():
        df = Market().equity.quote(tickers)
        wh_last = {tk: load_wh(prices, tk, today - timedelta(days=10), today)["close"].tail(1).tolist()
                   for tk in tickers}
        cp = df.set_index("symbol")["close_price"].to_dict() if {"symbol", "close_price"} <= set(df.columns) else {}
        return f"{_cols(df)} · close_price nguồn {cp} vs close kho {wh_last}"
    rep.run("Bảng giá live (equity.quote)", _quote)

    def _index_quote():
        df = Market().index("VNINDEX").quote()
        keep = [c for c in ("time", "close_price", "total_volume", "accumulated_volume",
                            "accumulated_value") if c in df.columns]
        return (f"{_cols(df)}\n        2 dòng đầu: {df[keep].head(2).to_dict(orient='records')}"
                f"\n        2 dòng cuối: {df[keep].tail(2).to_dict(orient='records')}")
    rep.run("Chỉ số trong phiên (index.quote) — cột nào là KL luỹ kế?", _index_quote)
    rep.run("HĐTL VN30F1M quote", lambda: _cols(Market().futures("VN30F1M").quote()))
    rep.run(f"{tickers[0]} volume_profile", lambda: _cols(Market().equity(tickers[0]).volume_profile()))

    def _screener():
        days = [d for d in (today - timedelta(days=i) for i in range(1, 8)) if d.weekday() < 5][:2]
        out = []
        for d in days:
            from vnstock_foreign_flow import foreign_net_for_date
            df = foreign_net_for_date(d.isoformat())          # có đệm theo ngày (lần 2 nhanh)
            v = pd.to_numeric(df.get("foreign_net_value"), errors="coerce").dropna()
            out.append(f"{d}: {len(df)} mã, NN ròng |max|={v.abs().max():,.0f}, Σ={v.sum():,.0f}"
                       if len(v) else f"{d}: {len(df)} mã, không có foreign_net_value")
        return " | ".join(out) + " (hai ngày khác nhau ⇒ date= lấy đúng ngày lịch sử)"
    rep.run("Screener NN ròng theo ngày (lần 2 đọc đệm theo ngày ⇒ nhanh)", _screener)

    def _ratio():
        df = Fundamental().equity(tickers[0]).ratio(period="year")
        keep = [c for c in ("year", "quarter", "pe", "pb", "roe", "roa", "net_margin", "debt_to_assets",
                            "liabilities_to_equity", "market_cap") if c in df.columns]
        return f"{_cols(df)}\n        3 dòng cuối: {df[keep].tail(3).to_dict(orient='records')}"
    rep.run(f"{tickers[0]} ratio năm (ROE nên là điểm %, vd 25 chứ không 0.25)", _ratio)

    def _bs():
        df = Fundamental().equity(tickers[0]).balance_sheet(period="quarter")
        per = sorted(pd.unique(df["period"]))[-4:] if "period" in df.columns else []
        return f"{_cols(df)} · kỳ gần nhất: {per}"
    rep.run(f"{tickers[0]} balance_sheet quý", _bs)

    rep.run(f"{tickers[0]} company.listing", lambda: (lambda d: f"{_cols(d)} · {d.head(1).to_dict(orient='records')}")(
        Reference().company(tickers[0]).listing()))
    rep.run(f"{tickers[0]} company.shareholders (rate là phân số?)", lambda: (
        lambda d: f"{_cols(d)} · rate đầu: {d['rate'].head(3).tolist() if 'rate' in d.columns else '-'}")(
        Reference().company(tickers[0]).shareholders()))
    rep.run(f"{tickers[0]} company.events", lambda: (
        lambda d: f"{_cols(d)} · event_type: {sorted(pd.unique(d['event_type'].astype(str)))[:10] if 'event_type' in d.columns else '-'}")(
        Reference().company(tickers[0]).events(start=(today - timedelta(days=730)).isoformat())))
    rep.run("Danh sách mã HOSE", lambda: _cols(Reference().equity.list(exchange="HOSE")))
    rep.run(f"{tickers[0]} trade_history (chỉ SSI)", lambda: _cols(
        Market().equity(tickers[0]).trade_history(start=(today - timedelta(days=30)).isoformat(),
                                                  end=today.isoformat())))
    rep.run("Rổ VN30 (chỉ SSI)", lambda: _cols(Reference().index("VN30").members()))

    out = REPO / "gen6_check_report.txt"
    out.write_text("\n".join(rep.lines) + "\n", encoding="utf-8")
    print(f"\n→ Đã lưu {out} — dán nội dung này cho Claude.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""P0 brief 3 khung — replay trên KHO THẬT, CHỈ ĐỌC (docs/THIET-KE-BRIEF-3-KHUNG.md §6).

Dựng lại từng phiên bằng chính code repo: điểm 7 phiếu (`classify_regime`),
momentum (`compute_market_sentiment`), floor cũ (`_bias_floor_dir`) và các tầng
mới (`vnstock_horizons`). Breadth (% mã trên EMA200) và A/D tái dựng THEO NGÀY
từ parquet đúng cách `vnstock_runner.compute_market_overview` đếm; NN từ
`foreign_net_daily.json`; brief đã gửi thật từ `brief_memory.db` (mode=ro).

Không ghi gì vào kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop
đang chạy (18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi.

    python scripts/replay_horizons.py --from 2026-06-01 --summary
    python scripts/replay_horizons.py --from 2026-08-15 --to 2026-10-03 --table
    python scripts/replay_horizons.py --csv horizons_replay.csv

Giới hạn: momentum thật còn gồm tin tức/vĩ mô (replay không có) ⇒ floor cũ
replay có thể lệch floor đã in; khối "Đã in thật" cho biết lệch bao nhiêu.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import vnstock_horizons as hz  # noqa: E402

_EMA_ALPHA = 2 / (200 + 1)
_RUNNER_LOOKBACK_DAYS = 400          # vnstock_runner: cutoff = hôm nay − 400 ngày
_EPISODE = ("2026-08-15", "2026-09-30")
_CRASHES = [("2018-04-09", "2018-07-05"), ("2020-01-20", "2020-03-24"),
            ("2022-04-05", "2022-11-15"), ("2025-03-25", "2025-04-09"),
            ("2026-01-13", "2026-03-23")]


# ── Đọc kho ──────────────────────────────────────────────────────────────

def _read_ticker(td: Path, min_year: int | None = None) -> pd.DataFrame:
    frames = []
    for yd in sorted(td.glob("year=*")):
        try:
            if min_year and int(yd.name.split("=")[1]) < min_year:
                continue
        except ValueError:
            continue
        for pf in yd.glob("*.parquet"):          # kể cả "(conflicted copy)"
            try:
                frames.append(pd.read_parquet(pf))
            except Exception:
                continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df.columns = [str(c).lower() for c in df.columns]
    for col in ("time", "trading_date", "date"):
        if col in df.columns:
            df = df.rename(columns={col: "time"})
            break
    if "time" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    df["time"] = pd.to_datetime(df["time"]).dt.normalize()
    return (df.sort_values("time").drop_duplicates("time", keep="last")
              .reset_index(drop=True))


def load_vnindex(warehouse: Path) -> tuple[list[date], list[float]]:
    for sym in ("VNINDEX", "VN-INDEX", "^VNINDEX"):
        df = _read_ticker(warehouse / "prices" / f"ticker={sym}")
        if df.empty:
            continue
        c = df["close"].astype(float)
        if c.iloc[-1] > 5000:                    # như vnstock_brief._load_vnindex_df
            c = c / 1000
        return hz.dedupe_daily([t.date() for t in df["time"]], c.tolist())
    return [], []


def tech_frame(dates: list[date], closes: list[float]) -> pd.DataFrame:
    """Kỹ thuật VNINDEX từng phiên — cùng công thức `_vnindex_technicals`."""
    c = pd.Series(closes, index=pd.to_datetime(dates), dtype=float)
    d = c.diff(1)
    up = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(com=13, adjust=False).mean()
    return pd.DataFrame({
        "close": c, "ma20": c.rolling(20).mean(), "ma50": c.rolling(50).mean(),
        "ma200": c.rolling(200).mean(),
        "rsi14": 100.0 - 100.0 / (1.0 + up / dn.replace(0, np.nan)),
        "chg": (c / c.shift(1) - 1.0) * 100,
    })


def load_nn(warehouse: Path) -> dict[str, float]:
    p = warehouse / "_meta" / "foreign_net_daily.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for d, rec in raw.items():
        try:
            out[str(d)[:10]] = float(rec["net"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def breadth_history(warehouse: Path, targets: list[date]) -> dict[date, dict]:
    """% mã trên EMA200 + A/D cho TỪNG phiên, đếm như `compute_market_overview`:
    mã ≥5 bar trong 400 ngày lùi vào mẫu số; EMA200 (adjust=False) bắt đầu ở bar
    đầu cửa sổ, chỉ tính khi ≥200 bar; A/D = bar cuối so bar liền trước.
    EMA cửa sổ = EMA toàn chuỗi − (1−α)^k·(F[lo] − x[lo]) — O(1) mỗi phiên."""
    if not targets:
        return {}
    tgt = np.array([np.datetime64(d) for d in targets])
    cut = tgt - np.timedelta64(_RUNNER_LOOKBACK_DAYS, "D")
    n_t = len(tgt)
    total = np.zeros(n_t, int); above = np.zeros(n_t, int)
    adv = np.zeros(n_t, int); dec = np.zeros(n_t, int)
    min_year = targets[0].year - 2
    for td in sorted((warehouse / "prices").glob("ticker=*")):
        tk = td.name.split("=", 1)[1]
        if len(tk) > 5 or not tk.isalpha():
            continue
        df = _read_ticker(td, min_year)
        if len(df) < 5:
            continue
        x = df["close"].astype(float).to_numpy()
        x = np.where(x > 500, x / 1000, x)       # vnstock_runner._normalize_prices
        t = df["time"].to_numpy().astype("datetime64[D]")
        f = pd.Series(x).ewm(alpha=_EMA_ALPHA, adjust=False).mean().to_numpy()
        hi = np.searchsorted(t, tgt, side="right") - 1
        lo = np.searchsorted(t, cut, side="left")
        n = hi - lo + 1
        ok = (hi >= 0) & (n >= 5)
        total += ok
        has200 = ok & (n >= 200)
        if has200.any():
            h, l_ = hi[has200], lo[has200]
            ema = f[h] - (1 - _EMA_ALPHA) ** (h - l_) * (f[l_] - x[l_])
            above[np.where(has200)[0][x[h] > ema]] += 1
        two = ok & (n >= 2)
        if two.any():
            h = hi[two]
            diff = x[h] - x[h - 1]
            idx = np.where(two)[0]
            adv[idx[diff > 0]] += 1
            dec[idx[diff < 0]] += 1
    out = {}
    for i, d in enumerate(targets):
        if total[i]:
            out[d] = {"total": int(total[i]),
                      "above_ma200_pct": round(above[i] / total[i] * 100, 1),
                      "advances": int(adv[i]), "declines": int(dec[i]),
                      "ad_ratio": round(adv[i] / max(dec[i], 1), 2)}
    return out


def printed_briefs(warehouse: Path) -> dict[str, dict]:
    """Brief chiều đã gửi thật: mỗi ngày lấy bản HỢP LỆ mới nhất (mode=ro)."""
    db = warehouse / "_meta" / "brief_memory.db"
    if not db.exists():
        return {}
    from vnstock_brief import _detect_stance, _extract_section
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT brief_date, agent_name, output, context_json FROM briefs "
            "WHERE brief_type='afternoon' AND (error IS NULL OR error='') "
            "AND output IS NOT NULL AND output != '' ORDER BY created_at").fetchall()
    finally:
        con.close()
    lab = {"bullish": "TĂNG", "bearish": "GIẢM", "neutral": "TRUNG TÍNH"}
    out: dict[str, dict] = {}
    for bdate, agent, text, ctx_json in rows:
        try:
            ctx = json.loads(ctx_json or "{}")
        except Exception:
            ctx = {}
        tldr = _extract_section(text, "TLDR") or text[:600]
        b = ctx.get("breadth") or {}
        out[str(bdate)[:10]] = {
            "stance": lab.get(_detect_stance(tldr), "?"), "agent": agent,
            "floor": (ctx.get("bias_floor") or {}).get("dir") or "-",
            "breadth_pct": b.get("above_ma200_pct"), "ad_ratio": b.get("ad_ratio"),
            "momentum": (ctx.get("market_sentiment") or {}).get("momentum"),
        }
    return out


# ── Replay ───────────────────────────────────────────────────────────────

def replay(dates, closes, breadth: dict, nn: dict, params: hz.MediumParams,
           rows_from: date | None = None) -> pd.DataFrame:
    """Điểm cũ chấm từ `rows_from`; tầng trung hạn/🚨 gấp từ ĐẦU lịch sử."""
    from vnstock_brief import _bias_floor_dir
    from vnstock_market_sentiment import compute_market_sentiment
    from vnstock_regime import classify_regime

    tf = tech_frame(dates, closes)
    rows = []
    for d, r in zip(dates, tf.itertuples()):
        if not np.isfinite(r.ma200) or (rows_from and d < rows_from):
            continue
        tech = {"close": r.close, "ma20": r.ma20, "ma50": r.ma50, "ma200": r.ma200,
                "rsi14": round(float(r.rsi14), 1),
                "day_change_pct": round(float(r.chg), 2)}
        b = breadth.get(d, {})
        nn_d = nn.get(d.isoformat())
        reg = classify_regime(tech, b, round(nn_d, 1) if nn_d is not None else 0.0)
        mom = compute_market_sentiment(b, nn_d, tech).get("momentum")
        rows.append({"date": d, "close": r.close, "chg": round(float(r.chg), 2),
                     "score": reg["score"], "n": reg["n_signals"],
                     "label_old": reg["label"], "momentum": mom,
                     "floor_old": _bias_floor_dir(mom, reg["score"]) or "-",
                     "breadth_pct": b.get("above_ma200_pct"),
                     "ad_ratio": b.get("ad_ratio"), "nn": nn_d})
    df = pd.DataFrame(rows).set_index("date")
    df["short"] = hz.short_series(df.score.tolist(), df.n.tolist())
    weeks = hz.medium_series(dates, closes, params)
    med = dict(zip(dates, hz.medium_daily(dates, weeks)))
    alerts = dict(zip(dates, hz.alert_series(closes)))
    df["medium"] = [med[d] for d in df.index]
    df["alert"] = [alerts[d].tier for d in df.index]
    floors = [None if f == "-" else f for f in df.floor_old]
    df["protect"] = [hz.protection_level(f, s, m, a) or "-" for f, s, m, a
                     in zip(floors, df.short, df.medium, df.alert)]
    rules = [hz.stance_rule(s, m, a) for s, m, a in zip(df.short, df.medium, df.alert)]
    df["stance_forced"] = [r.forced or "-" for r in rules]
    df["stance_allowed"] = ["/".join(r.allowed) for r in rules]
    return df


def _changes(s: pd.Series) -> int:
    return int((s != s.shift(1)).iloc[1:].sum())


def _reversals(s: pd.Series, up: str, down: str) -> int:
    seq = [v for v in s if v in (up, down)]
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def summary(df: pd.DataFrame, printed: dict, dates, closes, params) -> None:
    n = len(df)
    print(f"\n== Cửa sổ {df.index[0]} → {df.index[-1]} ({n} phiên) ==")
    print(f"  CŨ  nhãn header đổi {_changes(df.label_old)} lần · floor đổi "
          f"{_changes(df.floor_old)} · đảo TĂNG↔GIẢM {_reversals(df.floor_old, 'TĂNG', 'GIẢM')}")
    fz = df.stance_forced
    print(f"  MỚI ngắn hạn đổi {_changes(df.short)} · trung hạn đổi {_changes(df.medium)} · "
          f"Stance ép đổi {_changes(fz)} · đảo {_reversals(fz, 'TĂNG', 'GIẢM')} · "
          f"ngày được TĂNG {int(df.stance_allowed.str.contains('TĂNG').sum())}")
    print(f"  bảo vệ cứng {(df.protect == 'cứng').mean()*100:.0f}% · mềm "
          f"{(df.protect == 'mềm').mean()*100:.0f}% · 🚨 bật {(df.alert > 0).mean()*100:.0f}% phiên")
    pr = [(d, printed[d.isoformat()]) for d in df.index if d.isoformat() in printed]
    if pr:
        st = pd.Series([p["stance"] for _, p in pr])
        fl = pd.Series([p["floor"] for _, p in pr])
        same = sum(1 for d, p in pr if p["floor"] == df.at[d, "floor_old"])
        print(f"  ĐÃ IN THẬT ({len(pr)} brief): Stance đổi {_changes(st)} · đảo "
              f"{_reversals(st, 'TĂNG', 'GIẢM')} · floor đổi {_changes(fl)} · floor replay "
              f"khớp floor đã in {same}/{len(pr)}")
        bx = [(df.at[d, "breadth_pct"], p["breadth_pct"]) for d, p in pr
              if p["breadth_pct"] is not None and df.at[d, "breadth_pct"] is not None]
        if bx:
            err = np.mean([abs(a - b) for a, b in bx])
            print(f"  breadth tái dựng vs ctx đã in: lệch TB {err:.1f} điểm % trên {len(bx)} phiên")
    else:
        print("  ĐÃ IN THẬT: không đọc được brief_memory.db trong cửa sổ này")

    # Trạng thái hiện tại + mức tuần tới
    last = df.iloc[-1]
    weeks = hz.medium_series(dates, closes, params)
    w = weeks[-1] if weeks else None
    print(f"\n== Hôm nay {df.index[-1]} ==")
    print(f"  Trung hạn: {hz.MEDIUM_LABEL[int(last.medium)]}"
          + (f" (⏳ {w.pending}/{params.up_weeks})" if w and w.pending else "")
          + f" · Ngắn hạn: {hz.SHORT_LABEL[int(last.short)]} (điểm {int(last.score)}/{int(last.n)})"
          + f" · 🚨 {'mức ' + str(int(last.alert)) if last.alert else 'tắt'}"
          + f" · bảo vệ {last.protect}")
    if w:
        prior = [x.close for x in weeks]
        hi52 = max(closes[-252:])
        for lv in hz.trigger_levels(prior, w.state, closes[-1], hi52, params):
            txt = f"{lv.price:,.0f}" if lv.reachable else f"~{lv.price:,.0f} → chưa thể trong tuần này"
            print(f"  mức tuần tới — {lv.kind}: {txt}")


def grid(dates, closes, episode=_EPISODE) -> None:
    """Vùng phẳng tham số trung hạn trên toàn lịch sử VNINDEX trong kho."""
    c = pd.Series(closes, index=pd.to_datetime(dates))
    yrs = len(c) / 250
    print(f"\n== Vùng phẳng trung hạn ({dates[0]} → {dates[-1]}, {yrs:.1f} năm) ==")
    print("  biến thể                           đổi/năm  đảo≤4t  | rời TĂNG lúc đã giảm (2018·2020·2022·04/25·Q1/26) | TĂNG trong "
          f"{episode[0][5:]}–{episode[1][5:]}?")
    for ms, ml in ((8, 30), (10, 40), (12, 50)):
        for band in (0.01, 0.02, 0.03):
            for fuse in (None, 0.08):
                p = hz.MediumParams(ma_short=ms, ma_long=ml, band=band, fuse=fuse)
                md = pd.Series(hz.medium_daily(dates, hz.medium_series(dates, closes, p)),
                               index=c.index)
                ch = md[md.diff().fillna(0) != 0]
                dd, dirs = list(ch.index), list(np.sign(md.diff()[ch.index]))
                q = sum(1 for k in range(1, len(dd))
                        if dirs[k] != dirs[k - 1] and (dd[k] - dd[k - 1]).days <= 28)
                cr = []
                for a, b in _CRASHES:
                    seg = md.loc[a:b]
                    if seg.empty:
                        cr.append("  n/a"); continue
                    fd = seg.index[seg.diff().fillna(0) < 0]
                    cr.append(f"{(c[fd[0]] / c[a] - 1) * 100:5.1f}%" if len(fd) else "   - ")
                ep = md.loc[episode[0]:episode[1]]
                tag = "CÓ" if (ep == hz.TANG).any() else ("không" if len(ep) else "n/a")
                mark = " ◀ chốt" if (ms, ml, band, fuse) == (10, 40, 0.02, 0.08) else ""
                print(f"  MA{ms}w/MA{ml}w ±{band*100:.0f}% cầu chì {'8%' if fuse else 'tắt':4s}"
                      f"   {len(dd)/yrs:5.1f}  {q:3d}/{len(dd):<3d} | {' '.join(cr)} | {tag}{mark}")


def macro_depth(warehouse: Path) -> None:
    p = warehouse / "_meta" / "macro_indicators.json"
    try:
        reg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        print("\n== Vĩ mô: không đọc được macro_indicators.json =="); return
    print("\n== Độ sâu registry vĩ mô (số lần đọc · đầu → cuối) ==")
    try:
        from vnstock_macro import dense_history
    except Exception:
        dense_history = None
    for key, ind in sorted(reg.items()):
        if not isinstance(ind, dict):
            continue
        h = ind.get("history") or {}
        dh = dense_history(key) if dense_history else {}
        src = dh if len(dh) > len(h) else h
        if src:
            ks = sorted(src)
            print(f"  {key:24s} {len(src):4d} · {ks[0]} → {ks[-1]}"
                  + (" (cache ngày)" if src is dh else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="start", default="2026-06-01")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--summary", action="store_true", help="(mặc định) tóm tắt")
    ap.add_argument("--table", action="store_true", help="in bảng từng phiên")
    ap.add_argument("--csv", default=None, help="ghi CSV ra đường dẫn này")
    ap.add_argument("--no-breadth", action="store_true",
                    help="bỏ tái dựng breadth/A-D (nhanh, điểm thiếu 2 phiếu)")
    ap.add_argument("--no-grid", action="store_true")
    ap.add_argument("--warehouse", default=str(_REPO / "data_warehouse"))
    a = ap.parse_args(argv)

    wh = Path(a.warehouse)
    dates, closes = load_vnindex(wh)
    if len(dates) < 260:
        print(f"❌ VNINDEX trong kho chỉ có {len(dates)} phiên — cần ≥260"); return 2
    print(f"VNINDEX: {len(dates)} phiên {dates[0]} → {dates[-1]}")
    start = date.fromisoformat(a.start)
    end = date.fromisoformat(a.end) if a.end else dates[-1]
    nn = load_nn(wh)
    print(f"NN: {len(nn)} phiên trong cache"
          + (f" ({min(nn)} → {max(nn)})" if nn else " — phiếu NN bị bỏ"))
    # tầng mới gấp từ đầu lịch sử; điểm cũ chỉ cần từ (start − 30 phiên) để
    # máy trạng thái ngắn hạn ấm lên trước cửa sổ
    warm = max(0, next((i for i, d in enumerate(dates) if d >= start), len(dates)) - 30)
    targets = [d for d in dates[warm:] if d <= end]
    breadth = {} if a.no_breadth else breadth_history(wh, targets)
    if breadth:
        lb = breadth[max(breadth)]
        print(f"Breadth tái dựng: {len(breadth)} phiên, mẫu số {lb['total']} mã "
              f"(phiên cuối {lb['above_ma200_pct']}% trên EMA200)")
    params = hz.MediumParams()
    df = replay(dates, closes, breadth, nn, params, rows_from=targets[0])
    df = df[df.index <= end]
    printed = printed_briefs(wh)
    win = df[df.index >= start]
    if win.empty:
        print("❌ Không có phiên nào trong cửa sổ"); return 2
    summary(win, printed, [d for d in dates if d <= end],
            [c for d, c in zip(dates, closes) if d <= end], params)
    if a.table:
        print("\n  ngày        đóng    điểm  floor cũ | ngắn hạn     trung hạn  🚨 bảo vệ | Stance ép  | đã in")
        for d, r in win.iterrows():
            p = printed.get(d.isoformat(), {})
            print(f"  {d} {r.close:8,.2f} {int(r.score):+3d}/{int(r.n)} {r.floor_old:5s} | "
                  f"{hz.SHORT_LABEL[int(r.short)]:11s} {hz.MEDIUM_LABEL[int(r.medium)]:9s} "
                  f"{int(r.alert)}  {r.protect:4s} | {r.stance_forced:9s} | "
                  f"{p.get('stance', ''):10s} {p.get('floor', '')}")
    if not a.no_grid:
        grid([d for d in dates if d <= end], [c for d, c in zip(dates, closes) if d <= end])
    macro_depth(wh)
    if a.csv:
        out = win.copy()
        out["printed_stance"] = [printed.get(d.isoformat(), {}).get("stance") for d in out.index]
        out["printed_floor"] = [printed.get(d.isoformat(), {}).get("floor") for d in out.index]
        out.to_csv(a.csv, encoding="utf-8-sig")
        print(f"\n💾 CSV: {a.csv} ({len(out)} dòng)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

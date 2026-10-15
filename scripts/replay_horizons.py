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

from vnstock_horizons_state import (breadth_history, load_nn,  # noqa: E402,F401
                                    load_vnindex, read_ticker, tech_frame)

_read_ticker = read_ticker            # tên cũ (test + P0 đã dùng)
_EPISODE = ("2026-08-15", "2026-09-30")
_CRASHES = [("2018-04-09", "2018-07-05"), ("2020-01-20", "2020-03-24"),
            ("2022-04-05", "2022-11-15"), ("2025-03-25", "2025-04-09"),
            ("2026-01-13", "2026-03-23")]


# ── Đọc kho ──────────────────────────────────────────────────────────────

def printed_briefs(warehouse: Path) -> dict[str, dict]:
    """Brief chiều đã gửi thật: mỗi ngày lấy bản HỢP LỆ mới nhất (mode=ro)."""
    db = warehouse / "_meta" / "brief_memory.db"
    if not db.exists():
        return {}
    from vnstock_brief import _detect_stance, _extract_section, floor_dir
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
            "floor": floor_dir(ctx) or "-",
            "breadth_pct": b.get("above_ma200_pct"), "ad_ratio": b.get("ad_ratio"),
            "momentum": (ctx.get("market_sentiment") or {}).get("momentum"),
        }
    return out


# ── Replay ───────────────────────────────────────────────────────────────

def replay(dates, closes, breadth: dict, nn: dict, params: hz.MediumParams,
           rows_from: date | None = None) -> pd.DataFrame:
    """Điểm cũ chấm từ `rows_from`; tầng trung hạn/🚨 gấp từ ĐẦU lịch sử.
    Chấm điểm dùng CHUNG `vnstock_horizons_state.score_inputs` với bước pipeline."""
    from vnstock_horizons_state import score_inputs

    targets = [d for d in dates if rows_from is None or d >= rows_from]
    sc = score_inputs(dates, closes, targets, breadth, nn)
    close_of = dict(zip(dates, closes))
    rows = []
    for d in targets:
        if d not in sc:
            continue
        x = sc[d]
        i = dates.index(d)
        chg = (closes[i] / closes[i - 1] - 1) * 100 if i else 0.0
        rows.append({"date": d, "close": close_of[d], "chg": round(chg, 2),
                     "score": x["score"], "n": x["n"], "label_old": x["label_old"],
                     "momentum": x["momentum"], "floor_old": x["floor_old"] or "-",
                     "breadth_pct": x["breadth_pct"], "nn": x["nn"]})
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
    print(f"  floor cũ GIẢM {(df.floor_old == 'GIẢM').mean()*100:.0f}% phiên → "
          f"bảo vệ cứng {(df.protect == 'cứng').mean()*100:.0f}% · mềm "
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
    reg = reg.get("indicators", reg) if isinstance(reg, dict) else {}
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

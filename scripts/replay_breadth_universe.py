"""Độ rộng trên TẬP MÃ ĐẦU TƯ ĐƯỢC — chạy lại toàn lịch sử, CHỈ ĐỌC kho (PTKT §16).

`VNSTOCK_BREADTH_UNIVERSE=investable` đổi mẫu số của "% mã trên MA200" (~11% → ~30% trên kho
thật) ⇒ phiếu "Breadth MA200" của regime, trạng thái ngắn hạn horizons và Stance có thể đổi.
Script dựng lại ngắn hạn TOÀN lịch sử với CẢ HAI tập bằng đúng đường của
`vnstock_ta_score_io.rebuild_short_states` (`breadth_history` → `score_inputs` →
`short_states_from_scores`; breadth đọc MỘT lần, mỗi tập chọn qua `with_universe`) rồi in:
  1. % phiên phiếu độ rộng đổi (−1/0/+1 cũ → mới);
  2. số phiên trạng thái ngắn hạn khác + bảng chuyển cũ → mới;
  3. số phiên ô Stance (§3.4: nhãn ép / tập cho phép) khác, số phiên lớp bảo vệ khác;
  4. T4: lợi suất VN-Index T+5/T+20/T+60 theo trạng thái ngắn hạn, cả hai tập (số đoạn).

Không ghi gì vào kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop đang chạy
(18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi.

    python scripts/replay_breadth_universe.py
    python scripts/replay_breadth_universe.py --json breadth_universe.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402

import vnstock_horizons as hz  # noqa: E402
import vnstock_horizons_state as hs  # noqa: E402
import vnstock_ta_score as ts  # noqa: E402
from vnstock_breadth_universe import ALL, INVESTABLE, with_universe  # noqa: E402
from vnstock_ta_score_io import short_states_from_scores  # noqa: E402

UNIVERSES = (ALL, INVESTABLE)


# ── Logic thuần ──────────────────────────────────────────────────────────────

def breadth_vote(pct: float | None) -> int | None:
    """Phiếu "Breadth MA200" của chính `vnstock_regime.classify_regime` (None khi thiếu số)."""
    if pct is None:
        return None
    from vnstock_regime import classify_regime
    sig = [s for s in classify_regime({}, {"above_ma200_pct": pct}, 0.0)["signals"]
           if s["name"] == "Breadth MA200"]
    return int(sig[0]["direction"]) if sig else None


def _transitions(old: list, new: list, labels: dict) -> dict[str, int]:
    c = Counter((a, b) for a, b in zip(old, new) if a is not None and b is not None and a != b)
    return {f"{labels.get(a, a)} → {labels.get(b, b)}": n
            for (a, b), n in sorted(c.items(), key=lambda kv: -kv[1])}


def _stance_cell(short: int | None, medium: int, tier: int) -> tuple | None:
    if short is None:
        return None
    r = hz.stance_rule(short, medium, tier)
    return (r.forced, r.allowed)


def _cell_label(cell: tuple) -> str:
    forced, allowed = cell
    return f"ép {forced}" if forced else "cho " + "/".join(allowed)


def compare(dates: list[date], closes: list[float], targets: list[date], breadth: dict,
            nn: dict, horizons=(5, 20, 60)) -> dict:
    """Mọi số đo của báo cáo, từ breadth đã dựng cho ``targets`` (bản ghi có cả hai tập)."""
    per: dict[str, dict] = {}
    for u in UNIVERSES:
        b_u = {d: with_universe(r, u) for d, r in breadth.items()}
        scores = hs.score_inputs(dates, closes, targets, b_u, nn)
        per[u] = {"breadth": b_u, "scores": scores,
                  "short": short_states_from_scores(dates, scores)}

    days = [d for d in dates if d in breadth]
    pct = {u: [per[u]["breadth"][d]["above_ma200_pct"] for d in days] for u in UNIVERSES}
    inv_ok = [per[INVESTABLE]["breadth"][d]["breadth_universe"] == INVESTABLE for d in days]
    v_old = [breadth_vote(p) for p in pct[ALL]]
    v_new = [breadth_vote(p) for p in pct[INVESTABLE]]
    n_vote = sum(1 for a, b in zip(v_old, v_new) if a is not None and b is not None)
    vote_changed = sum(1 for a, b in zip(v_old, v_new) if a is not None and b is not None and a != b)

    weeks = hz.medium_series(dates, closes)
    medium = hz.medium_daily(dates, weeks)
    tiers = [a.tier for a in hz.alert_series(closes)]
    sh = {u: [per[u]["short"].get(d.isoformat()) for d in dates] for u in UNIVERSES}
    both = [i for i in range(len(dates)) if sh[ALL][i] is not None and sh[INVESTABLE][i] is not None]
    cells = {u: [_stance_cell(sh[u][i], medium[i], tiers[i]) for i in range(len(dates))]
             for u in UNIVERSES}
    floor = {u: [(per[u]["scores"].get(d) or {}).get("floor_old") for d in dates] for u in UNIVERSES}
    prot = {u: [hz.protection_level(floor[u][i], sh[u][i], medium[i], tiers[i])
                if sh[u][i] is not None else None for i in range(len(dates))] for u in UNIVERSES}
    cell_tr = Counter((_cell_label(cells[ALL][i]), _cell_label(cells[INVESTABLE][i]))
                      for i in both if cells[ALL][i] != cells[INVESTABLE][i])

    def _med(xs: list) -> float | None:
        xs = [x for x in xs if x is not None]
        return round(float(np.median(xs)), 1) if xs else None

    return {
        "period": [days[0].isoformat(), days[-1].isoformat()] if days else None,
        "sessions": len(days),
        "investable_sessions": sum(inv_ok),
        "breadth_median": {u: _med(pct[u]) for u in UNIVERSES},
        "universe_n_median": {
            ALL: _med([breadth[d]["ma200_n_all"] for d in days]),
            INVESTABLE: _med([breadth[d].get("ma200_n_investable") for d in days])},
        "vote": {
            "sessions": n_vote, "changed": vote_changed,
            "changed_pct": round(vote_changed / n_vote * 100, 1) if n_vote else None,
            "transitions": {f"{a:+d} → {b:+d}".replace("+0", "0"): n for (a, b), n in sorted(
                Counter((a, b) for a, b in zip(v_old, v_new)
                        if a is not None and b is not None and a != b).items(),
                key=lambda kv: -kv[1])}},
        "short": {
            "sessions": len(both),
            "changed": sum(1 for i in both if sh[ALL][i] != sh[INVESTABLE][i]),
            "transitions": _transitions([sh[ALL][i] for i in both],
                                        [sh[INVESTABLE][i] for i in both], hz.SHORT_LABEL)},
        "stance": {
            "sessions": len(both),
            "changed": sum(cell_tr.values()),
            "forced_changed": sum(1 for i in both
                                  if cells[ALL][i][0] != cells[INVESTABLE][i][0]),
            "transitions": {f"{a} → {b}": n for (a, b), n in cell_tr.most_common()}},
        "protect": {
            "sessions": len(both),
            "changed": sum(1 for i in both if prot[ALL][i] != prot[INVESTABLE][i]),
            "transitions": _transitions([prot[ALL][i] or "-" for i in both],
                                        [prot[INVESTABLE][i] or "-" for i in both], {})},
        "t4": {u: ts.forward_returns_by_state(closes, sh[u], horizons, labels=hz.SHORT_LABEL)
               for u in UNIVERSES},
    }


# ── In ───────────────────────────────────────────────────────────────────────

def _f(v, fmt: str = "{:+.2f}") -> str:
    return "-" if v is None else fmt.format(v)


def _trans_lines(tr: dict) -> list[str]:
    return [f"      {k}: {n:,}" for k, n in tr.items()] or ["      (không có)"]


def report(r: dict) -> str:
    if not r["sessions"]:
        return "Không có phiên nào dựng được độ rộng."
    bm, un = r["breadth_median"], r["universe_n_median"]
    lines = [
        f"Độ rộng tái dựng {r['sessions']:,} phiên ({r['period'][0]} → {r['period'][1]}); "
        f"tập thanh khoản tính được {r['investable_sessions']:,} phiên.",
        f"  % trên MA200 (trung vị): mọi mã {_f(bm[ALL], '{:.1f}')}% (n≈{_f(un[ALL], '{:,.0f}')}) · "
        f"thanh khoản {_f(bm[INVESTABLE], '{:.1f}')}% (n≈{_f(un[INVESTABLE], '{:,.0f}')})",
        "",
        f"1) Phiếu độ rộng regime (>55 ⇒ +1, <35 ⇒ −1): đổi {r['vote']['changed']:,}/"
        f"{r['vote']['sessions']:,} phiên ({_f(r['vote']['changed_pct'], '{:.1f}')}%)",
        *_trans_lines(r["vote"]["transitions"]),
        f"2) Ngắn hạn horizons: khác {r['short']['changed']:,}/{r['short']['sessions']:,} phiên "
        "(cũ → mới)",
        *_trans_lines(r["short"]["transitions"]),
        f"3) Ô Stance §3.4: khác {r['stance']['changed']:,}/{r['stance']['sessions']:,} phiên "
        f"(nhãn ép đổi {r['stance']['forced_changed']:,})",
        *_trans_lines(r["stance"]["transitions"]),
        f"   Lớp bảo vệ: khác {r['protect']['changed']:,}/{r['protect']['sessions']:,} phiên",
        *_trans_lines(r["protect"]["transitions"]),
        "",
        "4) T4 — VN-Index T+h sau mỗi phiên theo ngắn hạn (TB% · tăng% · n · số đoạn)",
    ]
    for h, blk_all in r["t4"][ALL].items():
        blk_inv = r["t4"][INVESTABLE][h]
        lines.append(f"   {h.upper()}:")
        for lbl in [*hz.SHORT_LABEL.values(), "_all"]:
            row = []
            for u, blk in ((ALL, blk_all), (INVESTABLE, blk_inv)):
                x = blk.get(lbl)
                row.append("-" if not x else
                           f"{_f(x['mean_pct'])}% · "
                           f"{_f(x['rate'] * 100 if x.get('rate') is not None else None, '{:.0f}')}% · "
                           f"n={x['n']:,}"
                           + (f" · {x['episodes']} đoạn" if x.get("episodes") is not None else ""))
            name = "mọi phiên" if lbl == "_all" else lbl
            lines.append(f"     {name:11s} cũ: {row[0]:40s} | mới: {row[1]}")
    return "\n".join(lines)


# ── Đọc kho + CLI ────────────────────────────────────────────────────────────

def run(warehouse: Path) -> dict:
    dates, closes = hs.load_vnindex(warehouse)
    if len(dates) <= 200:
        return {"sessions": 0}
    targets = dates[199:]                 # như rebuild_short_states
    breadth = hs.breadth_history(warehouse, targets, ALL, sessions=dates)
    return compare(dates, closes, targets, breadth, hs.load_nn(warehouse))


def _clean(v):
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.integer, np.floating)):
        return v.item()
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warehouse", default=str(_REPO / "data_warehouse"))
    ap.add_argument("--json", default=None, help="ghi kết quả JSON ra đường dẫn này")
    a = ap.parse_args(argv)
    wh = Path(a.warehouse)
    if not (wh / "prices").exists():
        print(f"❌ Không thấy {wh / 'prices'}"); return 2
    t0 = time.perf_counter()
    r = run(wh)
    r["elapsed_s"] = round(time.perf_counter() - t0, 1)
    if not r.get("sessions"):
        print("❌ VNINDEX trong kho chưa đủ 201 phiên hoặc không dựng được độ rộng"); return 2
    print(report(r))
    print(f"\n⏱ {r['elapsed_s']:,.1f}s")
    if a.json:
        Path(a.json).write_text(json.dumps(_clean(r), ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"→ {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

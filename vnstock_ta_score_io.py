"""Thước đo nhận định kỹ thuật (P0 PTKT) — lớp ĐỌC kho + CLI. Lõi thuần ở `vnstock_ta_score`.

Đọc (chỉ đọc): `brief_memory.db` (sqlite mở read-only), VNINDEX
(`vnstock_brief._load_vnindex_df(augment=False)`), bar từng mã
(`vnstock_strategy._load_history_from_parquet`), `_meta/horizon_state.json`.
Ghi đúng một file: `_meta/ta_score.json`.

    python run.py ta-score              # chấm lại + ghi + in bảng
    python run.py ta-score --show       # in bảng đã ghi, không chấm lại
    python run.py ta-score --backfill   # như trên + dựng lại ngắn hạn horizons toàn lịch sử (nặng)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pandas as pd

import vnstock_horizons as hz
import vnstock_ta_score as ts

_REPO = Path(__file__).resolve().parent
_WAREHOUSE = _REPO / "data_warehouse"
SCORE_NAME = "ta_score.json"
VERSION = 1


def score_path(warehouse: Path = _WAREHOUSE) -> Path:
    return Path(warehouse) / "_meta" / SCORE_NAME


# ── Đọc ──────────────────────────────────────────────────────────────────

def load_briefs(db_path: Path) -> list[dict]:
    """Mọi brief có chữ, mở sqlite READ-ONLY (không đẻ DB rỗng, không chạy migration)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    c = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(briefs)")}
        sent = "sent" if "sent" in cols else "NULL AS sent"
        rows = c.execute(
            "SELECT id, created_at, brief_date, brief_type, agent_name, agent_type, output, "
            f"error, context_json, {sent} FROM briefs "
            "WHERE output IS NOT NULL AND length(output) > 0").fetchall()
    finally:
        c.close()
    return [dict(r) for r in rows]


def dedupe_briefs(briefs: list[dict]) -> list[dict]:
    """Một bản cho mỗi (loại, phiên, agent): chạy lại cùng phiên chỉ giữ bản ĐÃ GỬI, rồi
    bản KHÔNG lỗi, rồi bản tạo sau cùng — chạy tay nhiều lần không được nhân phiếu agent, và
    bản chạy lại bị lỗi không chiếm chỗ bản hợp lệ cũ hơn (vết stance_track 15/07)."""
    best: dict = {}
    for b in briefs:
        k = (b.get("brief_type"), str(b.get("brief_date"))[:10], b.get("agent_name"))
        rank = (bool(b.get("sent")), not b.get("error"), str(b.get("created_at") or ""))
        if k not in best or rank > best[k][0]:
            best[k] = (rank, b)
    return [v[1] for v in best.values()]


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """time (ngày) + open/high/low/close(/volume), khử trùng ngày giữ bản sau, sắp tăng."""
    if df is None or df.empty or "close" not in df.columns:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    d = df.copy()
    d["time"] = pd.to_datetime(d["time"]).dt.normalize()
    keep = [c for c in ("time", "open", "high", "low", "close", "volume") if c in d.columns]
    d = d[keep].dropna(subset=["close"])
    for c in ("open", "high", "low"):
        if c not in d.columns:
            d[c] = d["close"]
    return (d.drop_duplicates("time", keep="last").sort_values("time")
            .reset_index(drop=True))


def _ctx(b: dict) -> dict:
    try:
        return json.loads(b.get("context_json") or "{}") or {}
    except (TypeError, ValueError):
        return {}


def load_short_states(warehouse: Path) -> dict[str, int]:
    """Ngắn hạn horizons đã publish (`horizon_state.json`) — {as_of: trạng thái}."""
    try:
        st = json.loads((Path(warehouse) / "_meta" / "horizon_state.json")
                        .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(p["as_of"])[:10]: int(p["short"]) for p in st.get("published") or []
            if p.get("as_of") and p.get("short") is not None}


def _backfill_cache(warehouse: Path) -> Path:
    return Path(warehouse) / "_meta" / "ta_score_short_backfill.json"


def save_backfill(warehouse: Path, states: dict[str, int]) -> None:
    """Cất kết quả `--backfill` để lần chạy thường không rơi về vài chục phiên đã publish."""
    if not states:
        return
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic({"built_at": date.today().isoformat(), "states": states},
                      _backfill_cache(warehouse))


def merge_short_states(warehouse: Path) -> tuple[dict[str, int], str]:
    """Bản dựng lại đã cất (nếu có) + `published` (published thắng ở ngày trùng — đó là bản thật
    brief đã đọc). Trả (states, nhãn nguồn)."""
    pub = load_short_states(warehouse)
    try:
        cached = json.loads(_backfill_cache(warehouse).read_text(encoding="utf-8"))
        back = {str(k)[:10]: int(v) for k, v in (cached.get("states") or {}).items()}
        built = cached.get("built_at") or "?"
    except (OSError, ValueError, TypeError, AttributeError):
        return pub, "horizon_state.json"
    if not back:
        return pub, "horizon_state.json"
    return {**back, **pub}, f"dựng lại ngày {built} + horizon_state.json"


def rebuild_short_states(warehouse: Path, universe: str | None = None) -> dict[str, int]:
    """Dựng lại ngắn hạn horizons TOÀN lịch sử bằng đúng code `vnstock_horizons_state`
    (breadth tái dựng từ parquet trên tập `universe` — None ⇒ `VNSTOCK_BREADTH_UNIVERSE`,
    NN thiếu ⇒ 0 như backfill của nó). Nặng: đọc mọi mã."""
    import vnstock_horizons_state as hs
    dates, closes = hs.load_vnindex(Path(warehouse))
    if len(dates) <= 200:
        return {}
    targets = dates[199:]
    print(f"[ta-score] dựng lại ngắn hạn {len(targets):,} phiên — tái dựng breadth từ parquet…")
    breadth = hs.breadth_history(Path(warehouse), targets, universe, sessions=dates)
    scores = hs.score_inputs(dates, closes, targets, breadth, hs.load_nn(Path(warehouse)))
    return short_states_from_scores(dates, scores)


def short_states_from_scores(dates: list[date], scores: dict) -> dict[str, int]:
    """Ngắn hạn từng phiên ({iso: trạng thái}) gấp từ `score_inputs` — bắt đầu từ phiên đầu có
    điểm, phiên thiếu điểm giữ trạng thái trước (như `fold`)."""
    out, st, started = {}, hz.CHUA_RO, False
    for d in dates:
        sc = scores.get(d)
        if sc and sc.get("n"):
            st, started = hz.short_step(st, int(sc["score"]), int(sc["n"])), True
        if started:
            out[d.isoformat()] = st
    return out


# ── Chấm (nhận input đã nạp — test gọi thẳng) ────────────────────────────

def _sessions(briefs: list[dict], brief_type: str = "afternoon") -> dict[str, dict]:
    """{phiên: ctx} — mức S/R là của CODE (cùng ctx cho mọi agent) ⇒ chấm mỗi phiên 1 lần."""
    out: dict[str, dict] = {}
    for b in sorted(briefs, key=lambda x: str(x.get("created_at") or "")):
        if b.get("brief_type") == brief_type:
            ctx = _ctx(b)
            if ctx:
                out[str(b["brief_date"])[:10]] = ctx
    return out


def _level_block(bars: pd.DataFrame, base: int, levels: dict, seed: int,
                 acc: dict, detail: dict) -> None:
    """Chấm S1/R1 thật + mức giả; ghi vào `acc[side] = {"real": [...], "fake": [...]}`."""
    close = float(bars["close"].iloc[base])
    fwd = bars.iloc[base + 1:]
    for side, lv in levels.items():
        if not lv:
            continue
        dist = ts.level_distance_pct(lv, close, side)
        if dist is None:
            acc[side]["wrong_side"] += 1
            continue
        o = ts.score_levels(fwd, lv, side)
        if o is None:
            continue
        acc[side]["real"].append(o)
        acc[side]["fake"] += ts.fake_level_outcomes(bars, dist, side, seed=seed, exclude=[base])
        detail[side] = o


def _new_acc() -> dict:
    return {s: {"real": [], "fake": [], "wrong_side": 0} for s in ("support", "resistance")}


def _close_acc(acc: dict) -> dict:
    return {s: {"real": ts.level_summary(a["real"]), "fake": ts.level_summary(a["fake"]),
                "wrong_side": a["wrong_side"]} for s, a in acc.items()}


def score_index(sessions: dict[str, dict], bars: pd.DataFrame) -> tuple[dict, dict]:
    """T1 + T2 trên VN-Index từ `vnindex_tech` của ctx brief chiều."""
    pos = ts.date_positions(bars["time"])
    acc, trig, detail = _new_acc(), {"resistance": [], "support": []}, []
    for k, (d, ctx) in enumerate(sorted(sessions.items())):
        vt = ctx.get("vnindex_tech") or {}
        base = ts.base_index(pos, d, "afternoon")
        if base is None:
            continue
        row = {"date": d}
        _level_block(bars, base, {"support": vt.get("support_1"),
                                  "resistance": vt.get("resistance_1")},
                     ts.SEED + k, acc, row)
        for side, l1, l2 in (("resistance", vt.get("resistance_1"), vt.get("resistance_2")),
                             ("support", vt.get("support_1"), vt.get("support_2"))):
            r = ts.score_trigger(bars, base, l1, l2, side)
            trig[side].append(r)
            if r["triggered"]:
                row[f"trigger_{side}"] = {"hit": r["hit"], "volume": r["volume"]}
        detail.append(row)
    t1 = {**_close_acc(acc), "detail": detail}
    for j, (side, rows) in enumerate(trig.items()):
        days = {r["trigger_pos"] for r in rows if r["triggered"]}
        for k, r in enumerate(rows):
            if r["triggered"] and r["hit"] is not None:
                r["fake"] = ts.fake_trigger_outcomes(bars, r["gap_pct"], side,
                                                     seed=ts.SEED + 100_000 * j + k, exclude=days)
    t2 = {s: ts.trigger_summary(rows) for s, rows in trig.items()}
    return t1, t2


def _ticker_levels(ctx: dict) -> list[tuple[str, float | None, float | None, float | None]]:
    """[(mã, giá tham chiếu trong ctx, hỗ trợ, kháng cự)] — mover + danh mục."""
    out = []
    for m in (ctx.get("vn30_gainers") or []) + (ctx.get("vn30_losers") or []):
        out.append((str(m.get("Mã") or ""), m.get("last"), m.get("sr_support"),
                    m.get("sr_resistance")))
    for p in ctx.get("portfolio") or []:
        out.append((str(p.get("ticker") or ""), p.get("last_close"), p.get("sr_support"),
                    p.get("sr_resistance")))
    return [(t.upper(), *rest) for t, *rest in out
            if t and (rest[1] is not None or rest[2] is not None)]


def score_tickers(sessions: dict[str, dict],
                  load_ticker: Callable[[str], pd.DataFrame]) -> dict:
    """T5: S/R từng mã như T1. Kho rebase sau GDKHQ ⇒ mức ctx (cơ sở cũ) nhân hệ số
    `đóng cửa kho / giá ctx` của phiên brief; lệch > 30% ⇒ bỏ (`basis_skipped`)."""
    acc, cache = _new_acc(), {}
    n_scaled = n_basis_skip = n_missing = 0
    tickers: set[str] = set()
    for k, (d, ctx) in enumerate(sorted(sessions.items())):
        for j, (tk, ref, sup, res) in enumerate(_ticker_levels(ctx)):
            if tk not in cache:
                b = normalize_bars(load_ticker(tk))
                cache[tk] = (b, ts.date_positions(b["time"]))
            bars, pos = cache[tk]
            base = ts.base_index(pos, d, "afternoon")
            if base is None:
                n_missing += 1
                continue
            f = 1.0
            if ref:
                f = float(bars["close"].iloc[base]) / float(ref)
                if abs(f - 1) > 0.30:
                    n_basis_skip += 1
                    continue
                n_scaled += abs(f - 1) > 0.005
            lv = {"support": sup * f if sup else None, "resistance": res * f if res else None}
            tickers.add(tk)
            _level_block(bars, base, lv, ts.SEED + 1000 * k + j, acc, {})
    return {**_close_acc(acc), "n_tickers": len(tickers), "rescaled": int(n_scaled),
            "basis_skipped": n_basis_skip, "no_bar": n_missing}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


_STANCE_TYPES = ("morning", "afternoon")
_DROPS = ("error", "no_bar", "unknown", "pending", "scored")   # phễu: mỗi brief đúng một ô


def stance_period(ctx: dict) -> str:
    """Giai đoạn luật Stance của MỘT brief, đọc từ ctx đã lưu (không từ ngày cứng): có
    luật bảng 3 khung dùng được (đúng điều kiện `_apply_horizon_stance`/
    `enforce_stance_horizon`) ⇒ "từ 3 khung", không thì "trước 3 khung"."""
    view = ctx.get("horizons")
    snap = view.get("snap") if isinstance(view, dict) and not view.get("stale") else None
    rule = (snap.get("stance") if isinstance(snap, dict) else None) or {}
    return ts.PERIOD_HZ if rule.get("forced") or rule.get("allowed") else ts.PERIOD_PRE


def stance_records(briefs: list[dict], bars: pd.DataFrame) -> tuple[list[dict], dict]:
    """T3: mỗi brief (đã khử trùng) → stance → T+1/T+5 so gốc theo loại brief.
    Trả (records, phễu {loại: {error, no_bar, unknown, pending, scored}}) — mỗi brief rơi
    vào đúng một ô. Nguồn nhãn code|agent = `vnstock_stance_track._stance_source`."""
    from vnstock_stance_track import _stance_source
    pos, closes = ts.date_positions(bars["time"]), bars["close"].tolist()
    recs, funnel = [], {bt: dict.fromkeys(_DROPS, 0) for bt in _STANCE_TYPES}
    for b in briefs:
        bt = b.get("brief_type")
        if bt not in _STANCE_TYPES:
            continue
        if b.get("error"):
            funnel[bt]["error"] += 1
            continue
        stance = ts.brief_stance(b.get("output") or "")
        ctx = _ctx(b)
        vt = ctx.get("vnindex_tech") or {}
        intraday = bool(vt.get("intraday"))
        base = ts.base_index(pos, b["brief_date"], bt, intraday)
        live = _num(vt.get("close")) if intraday and bt == "morning" else None
        rec = {"brief_type": bt, "brief_date": str(b["brief_date"])[:10],
               "agent_name": b.get("agent_name") or "?", "sent": b.get("sent"),
               "stance": stance, "period": stance_period(ctx),
               "source": _stance_source(b, stance),
               **{f"h{h}": (ts.stance_outcome(stance, closes, base, h, base_close=live)
                            if base is not None and stance != "unknown" else None)
                  for h in (1, 5)}}
        recs.append(rec)
        funnel[bt]["no_bar" if base is None else "unknown" if stance == "unknown"
                   else "pending" if rec["h1"] is None else "scored"] += 1
    return recs, funnel


def brief_funnel(raw: list[dict], uniq: list[dict], drops: dict) -> dict:
    """Phễu cỡ mẫu theo loại brief: dòng có chữ trong DB → sau khử trùng → bỏ → chấm."""
    out = {}
    for bt in _STANCE_TYPES:
        n_db = sum(b.get("brief_type") == bt for b in raw)
        if n_db:
            out[bt] = {"db": n_db, "dedup": sum(b.get("brief_type") == bt for b in uniq),
                       **drops[bt]}
    return out


def score_horizons(bars: pd.DataFrame, short_states: dict[str, int] | None) -> dict:
    """T4: trung hạn tuần dựng thuần từ giá (đúng `medium_series`/`medium_daily`);
    ngắn hạn theo `short_states` (published hoặc dựng lại)."""
    dates = [t.date() for t in bars["time"]]
    closes = bars["close"].astype(float).tolist()
    out: dict = {"period": [dates[0].isoformat(), dates[-1].isoformat()] if dates else None}
    if len(dates) < 260:
        return {**out, "medium": None, "short": None}
    weeks = hz.medium_series(dates, closes)
    medium = hz.medium_daily(dates, weeks)
    # Trước tuần đầu đủ MA40 tuần, "ĐI NGANG" chỉ là giá trị khởi tạo ⇒ không tính.
    ready = next((w.week_end for w in weeks if w.reading is not None), None)
    med = [s if ready is not None and d > ready else None for d, s in zip(dates, medium)]
    out["medium"] = ts.forward_returns_by_state(closes, med, labels=hz.MEDIUM_LABEL)
    sh = [(short_states or {}).get(d.isoformat()) for d in dates]
    out["short"] = (ts.forward_returns_by_state(closes, sh, labels=hz.SHORT_LABEL)
                    if any(s is not None for s in sh) else None)
    out["short_sessions"] = sum(s is not None for s in sh)
    return out


def compute(briefs: list[dict], index_bars: pd.DataFrame,
            load_ticker: Callable[[str], pd.DataFrame],
            short_states: dict[str, int] | None = None, short_source: str | None = None) -> dict:
    bars = normalize_bars(index_bars)
    uniq = dedupe_briefs(briefs)
    sessions = _sessions(uniq)
    t1, t2 = score_index(sessions, bars)
    recs, drops = stance_records(uniq, bars)
    return {
        "version": VERSION, "computed_at": datetime.now().isoformat(timespec="seconds"),
        "machine": os.environ.get("COMPUTERNAME") or platform.node() or "?",
        "n_briefs": len(briefs), "n_briefs_dedup": len(uniq),
        "n_sessions_afternoon": len(sessions),
        "rules": {"horizon": ts.HORIZON, "pierce_pct": ts.PIERCE_PCT, "flat_pct": ts.FLAT_PCT,
                  "vol_mult": ts.VOL_MULT, "fake_per_level": ts.FAKE_PER_LEVEL,
                  "seed": ts.SEED},
        "funnel": brief_funnel(briefs, uniq, drops),
        "t1": t1, "t2": t2, "t3": ts.summarize_stances(recs),
        "t4": {**score_horizons(bars, short_states), "short_source": short_source},
        "t5": score_tickers(sessions, load_ticker),
    }


# ── IO ───────────────────────────────────────────────────────────────────

def _db_path() -> Path:
    import vnstock_memory as mem
    p = Path(mem.DB_PATH)
    return p if p.is_absolute() else _REPO / p


def run(warehouse: Path = _WAREHOUSE, backfill: bool = False) -> dict:
    import vnstock_brief as vb
    from vnstock_strategy import _load_history_from_parquet
    warehouse = Path(warehouse)
    briefs = load_briefs(_db_path())
    first = min((str(b["brief_date"])[:10] for b in briefs), default=date.today().isoformat())
    days = (date.today() - date.fromisoformat(first)).days + 420
    prices = warehouse / "prices"
    if backfill:
        short, src = rebuild_short_states(warehouse), "dựng lại (--backfill)"
        save_backfill(warehouse, short)
    else:
        short, src = merge_short_states(warehouse)
    score = compute(briefs, vb._load_vnindex_df(augment=False),
                    lambda tk: _load_history_from_parquet(tk, days, prices_dir=prices),
                    short, src)
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(score, score_path(warehouse))
    return score


def load_score(warehouse: Path = _WAREHOUSE) -> dict | None:
    try:
        return json.loads(score_path(warehouse).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── In bảng ──────────────────────────────────────────────────────────────

def _pct(r: dict | None) -> str:
    if not r or not r.get("n"):
        return "— (n=0)"
    ci = r.get("ci") or (0, 0)
    return f"{r['rate'] * 100:,.1f}% [{ci[0] * 100:,.0f}–{ci[1] * 100:,.0f}] n={r['n']:,}"


def _level_lines(blk: dict, name: str) -> list[str]:
    out = []
    for side, vi in (("support", "hỗ trợ"), ("resistance", "kháng cự")):
        s = blk.get(side) or {}
        real, fake = s.get("real") or {}, s.get("fake") or {}
        out.append(f"  {name} {vi}: chạm thì giữ {_pct(real.get('hold_if_touched'))} · "
                   f"chạm {_pct(real.get('touch'))}")
        out.append(f"      mức giả cùng khoảng cách: chạm thì giữ "
                   f"{_pct(fake.get('hold_if_touched'))} · chạm {_pct(fake.get('touch'))}")
    return out


_BT_VI = (("afternoon", "chiều"), ("morning", "sáng"))
_SRC_VI = {"code": "nhãn code ép", "agent": "nhãn agent tự chọn"}


def _funnel_lines(funnel: dict) -> list[str]:
    if not funnel:
        return []
    L = ["Phễu brief (dòng có chữ trong DB → khử trùng loại×phiên×agent → bỏ → chấm T+1)"]
    for bt, vi in _BT_VI:
        f = funnel.get(bt)
        if f:
            L.append(f"  {vi}: {f['db']:,} dòng → {f['dedup']:,} sau khử trùng → bỏ: lỗi "
                     f"{f['error']:,} · không có bar đúng ngày {f['no_bar']:,} · stance không "
                     f"đọc được {f['unknown']:,} · chưa tới T+1 {f['pending']:,} → chấm "
                     f"{f['scored']:,}")
    return [*L, ""]


def _t2_lines(t2: dict) -> list[str]:
    L = ["T2 · Trigger (đóng cửa vượt mức 1 ⇒ chạm mức 2 trong 5 phiên; mốc = ngày ngẫu "
         "nhiên, đích cách đóng cửa đúng bằng mức 2 cách phiên trigger)"]
    for side, vi in (("resistance", "vượt R1 → R2"), ("support", "thủng S1 → S2")):
        t = t2.get(side) or {}
        fk = t.get("baseline") or {}
        L.append(f"  {vi}: {_pct(t.get('all'))}")
        L.append(f"      mốc cùng khoảng cách: {_pct(fk.get('all'))}")
        L.append(f"      KL xác nhận {_pct(t.get('confirmed'))} · không xác nhận "
                 f"{_pct(t.get('unconfirmed'))} · không đo được KL n="
                 f"{(t.get('unmeasurable') or {}).get('n', 0):,}")
        L.append(f"      mốc cùng khoảng cách: KL xác nhận {_pct(fk.get('confirmed'))} · "
                 f"không xác nhận {_pct(fk.get('unconfirmed'))}")
    return L


def _group_line(name: str, g: dict, indent: str) -> str:
    span = f" · {g['first']} → {g['last']}" if g.get("first") else ""
    return (f"{indent}{name:<22} {_pct(g.get('all'))} · mốc trung tính "
            f"{_pct(g.get('baseline_neutral'))} · lặp {_pct(g.get('baseline_repeat'))} · "
            f"{g.get('n_sessions', 0):,} phiên{span}")


def _t3_block(x: dict) -> list[str]:
    L = [f"      mốc luôn trung tính {_pct(x.get('baseline_neutral'))} · "
         f"lặp chiều hôm qua {_pct(x.get('baseline_repeat'))}"]
    if x.get("by_period"):
        L.append("      theo giai đoạn (mốc tính trên đúng phiên của nhóm):")
        for p, g in x["by_period"].items():
            L.append(_group_line(p, g, "        "))
            for s, gs in (g.get("by_source") or {}).items():
                L.append(_group_line(f"↳ {_SRC_VI.get(s, s)}", gs, "          "))
    if x.get("by_source"):
        L.append("      theo nguồn nhãn:")
        L += [_group_line(_SRC_VI.get(s, s), g, "        ") for s, g in x["by_source"].items()]
    if x.get("by_agent"):
        L.append("      theo agent (mỗi agent một khoảng ngày — so thẳng là so hai giai đoạn):")
    for a, r in sorted((x.get("by_agent") or {}).items(),
                       key=lambda kv: -(kv[1].get("n") or 0))[:8]:
        span = f" · {r['first']} → {r['last']}" if r.get("first") else ""
        L.append(f"        {a[:36]:<36} {_pct(r)}{span}")
    if x.get("paired"):
        L.append("      so cùng phiên (agent vs TB các agent khác trên đúng các phiên chung):")
    for a, r in sorted((x.get("paired") or {}).items(),
                       key=lambda kv: -kv[1]["n_sessions"])[:8]:
        L.append(f"        {a[:36]:<36} {_pct(r['acc'])} vs khác {r['others_rate'] * 100:,.1f}%"
                 f" · chênh {r['diff_pp']:+,.1f} điểm % · {r['n_sessions']:,} phiên chung")
    return L


def _t3_lines(t3: dict) -> list[str]:
    L = [f"T3 · Stance (phẳng = |Δ| < {ts.FLAT_PCT}%)"]
    for bt, vi in _BT_VI:
        blk = t3.get(bt)
        if not blk:
            continue
        for h in (1, 5):
            x = blk.get(f"h{h}") or {}
            L.append(f"  brief {vi} T+{h}: mọi bản {_pct(x.get('all'))} · đã gửi "
                     f"{_pct(x.get('sent'))}")
            L += _t3_block(x)
    return L


def _t4_lines(t4: dict) -> list[str]:
    p = t4.get("period") or []
    L = [f"T4 · VN-Index sau trạng thái horizons (dữ liệu VN-Index từ {' → '.join(p) or '—'}; "
         f"phiên chồng cửa sổ ⇒ đọc kèm số đoạn, < {ts.MIN_EPISODES} đoạn ⇒ chưa kết luận)"]
    for frame, vi in (("medium", "trung hạn"), ("short", "ngắn hạn")):
        blk = t4.get(frame)
        if not blk:
            L.append(f"  {vi}: chưa có trạng thái"
                     + (" — chạy `run.py ta-score --backfill`" if frame == "short" else ""))
            continue
        L.append(f"  {vi}" + (f" (nguồn {t4.get('short_source')}, "
                              f"{t4.get('short_sessions', 0):,} phiên)" if frame == "short" else ""))
        for h in ("t5", "t20", "t60"):
            for lab, r in (blk.get(h) or {}).items():
                ep = f" · {r['episodes']} đoạn" if r.get("episodes") else ""
                if r.get("episodes") and r["episodes"] < ts.MIN_EPISODES:
                    ep += " · ít đoạn — chưa kết luận"
                mean = f"{r['mean_pct']:+,.2f}%" if r.get("mean_pct") is not None else "—"
                L.append(f"      {h.upper():<4} {('mọi phiên' if lab == '_all' else lab):<10} "
                         f"TB {mean} · tỉ lệ tăng {_pct(r)}{ep}")
    return L


def format_table(score: dict | None) -> str:
    if not score:
        return "[ta-score] chưa có _meta/ta_score.json — chạy `python run.py ta-score`"
    L = [f"📏 Thước đo nhận định kỹ thuật — tính {score.get('computed_at')} trên "
         f"{score.get('machine')} · {score.get('n_briefs_dedup', 0):,} brief "
         f"({score.get('n_sessions_afternoon', 0):,} phiên chiều)",
         "  (tỉ lệ kèm khoảng Wilson 95%; n nhỏ ⇒ khoảng rộng, đừng đọc thành kết luận)", ""]
    L += _funnel_lines(score.get("funnel") or {})
    L += ["T1 · S1/R1 VN-Index, 5 phiên sau brief chiều (xuyên = đóng cửa vượt quá 0,5%)"]
    L += _level_lines(score.get("t1") or {}, "VN-Index")
    L += ["", *_t2_lines(score.get("t2") or {})]
    L += ["", *_t3_lines(score.get("t3") or {})]
    L += ["", *_t4_lines(score.get("t4") or {})]
    t5 = score.get("t5") or {}
    L += ["", f"T5 · S/R từng mã ({t5.get('n_tickers', 0):,} mã; chỉnh cơ sở "
              f"{t5.get('rescaled', 0):,} · bỏ vì lệch cơ sở {t5.get('basis_skipped', 0):,})"]
    L += _level_lines(t5, "mã")
    status, msg = ts.badge_verdict(score)
    L += ["", f"Badge: {status} — {msg}"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Thước đo nhận định kỹ thuật (P0 PTKT)")
    ap.add_argument("--show", action="store_true", help="in bảng đã ghi, không chấm lại")
    ap.add_argument("--backfill", action="store_true",
                    help="dựng lại ngắn hạn horizons toàn lịch sử (đọc mọi mã, chậm)")
    ap.add_argument("--warehouse", default=str(_WAREHOUSE))
    a = ap.parse_args(argv)
    wh = Path(a.warehouse)
    if a.show and not a.backfill:
        score = load_score(wh)
        print(format_table(score))
        return 0 if score else 1
    try:
        score = run(wh, backfill=a.backfill)
    except Exception as e:
        print(f"[ta-score] ❌ {type(e).__name__}: {str(e)[:200]}")
        return 1
    print(format_table(score))
    print(f"[ta-score] ✓ ghi {score_path(wh)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

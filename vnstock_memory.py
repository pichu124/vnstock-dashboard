"""
vnstock_memory.py — Persistent storage for AI brief learning loop.

Stores:
  briefs              — every generated brief + market context snapshot
  brief_ratings       — user ⭐ rating + textual feedback
  brief_auto_scores   — automated specificity scoring (numbers density, etc)
  strategies          — agent-generated strategy code + metadata
  backtests           — backtest results per strategy
  recommendations     — buy lists with entry/TP/SL surfaced in briefs
  rec_outcomes        — actual outcomes (filled later) for performance tracking

All operations isolated to a single SQLite file under data_warehouse/_meta/.
No Streamlit dependency — usable from CLI / cron.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

DB_PATH = Path("data_warehouse/_meta/brief_memory.db")
_LOCK = threading.Lock()


# ── Schema ─────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    brief_date      TEXT NOT NULL,
    brief_type      TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    agent_type      TEXT NOT NULL,
    model           TEXT,
    prompt          TEXT,
    output          TEXT,
    error           TEXT,
    context_json    TEXT,
    auto_score      REAL,
    user_rating     INTEGER,
    user_feedback   TEXT
);
CREATE INDEX IF NOT EXISTS ix_briefs_date  ON briefs(brief_date);
CREATE INDEX IF NOT EXISTS ix_briefs_score ON briefs(auto_score);
CREATE INDEX IF NOT EXISTS ix_briefs_rate  ON briefs(user_rating);

CREATE TABLE IF NOT EXISTS strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    code            TEXT NOT NULL,
    params_json     TEXT,
    parent_id       INTEGER,
    family_id       TEXT,
    last_tuned_at   TEXT,
    is_core_stable  INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'draft',
    FOREIGN KEY(parent_id) REFERENCES strategies(id)
);
CREATE INDEX IF NOT EXISTS ix_strats_status ON strategies(status);

CREATE TABLE IF NOT EXISTS backtests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    strategy_id     INTEGER NOT NULL,
    period_start    TEXT,
    period_end      TEXT,
    universe        TEXT,
    n_trades        INTEGER,
    win_rate        REAL,
    avg_return      REAL,
    sharpe          REAL,
    max_drawdown    REAL,
    expectancy      REAL,
    metrics_json    TEXT,
    error           TEXT,
    FOREIGN KEY(strategy_id) REFERENCES strategies(id)
);
CREATE INDEX IF NOT EXISTS ix_bt_strat ON backtests(strategy_id);

CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    brief_id        INTEGER,
    strategy_id     INTEGER,
    ticker          TEXT NOT NULL,
    action          TEXT NOT NULL,
    entry_price     REAL,
    take_profit     REAL,
    cut_loss        REAL,
    rationale       TEXT,
    horizon_days    INTEGER,
    FOREIGN KEY(brief_id) REFERENCES briefs(id),
    FOREIGN KEY(strategy_id) REFERENCES strategies(id)
);
CREATE INDEX IF NOT EXISTS ix_rec_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS ix_rec_strat  ON recommendations(strategy_id);

CREATE TABLE IF NOT EXISTS rec_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rec_id          INTEGER NOT NULL UNIQUE,
    closed_at       TEXT,
    exit_price      REAL,
    pnl_pct         REAL,
    hit_target      TEXT,
    notes           TEXT,
    FOREIGN KEY(rec_id) REFERENCES recommendations(id)
);

"""


# ── Connection helper ──────────────────────────────────────────────────────
@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        c = sqlite3.connect(str(DB_PATH))
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def _migrate(c: sqlite3.Connection) -> None:
    """Add columns introduced after the original schema. Idempotent."""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(strategies)")}
    if "family_id" not in cols:
        c.execute("ALTER TABLE strategies ADD COLUMN family_id TEXT")
    if "last_tuned_at" not in cols:
        c.execute("ALTER TABLE strategies ADD COLUMN last_tuned_at TEXT")
    if "is_core_stable" not in cols:
        c.execute("ALTER TABLE strategies ADD COLUMN is_core_stable INTEGER DEFAULT 0")
    # Tầng thời gian (13/08, user chốt "theo dõi cả ngắn/dài"): 'short' =
    # 5 phiên (mọi chiến lược cũ), 'position' = ~20 phiên. Mỗi tier có MỘT
    # active riêng — DEFAULT 'short' nên toàn bộ dữ liệu cũ giữ nguyên nghĩa.
    if "tier" not in cols:
        c.execute("ALTER TABLE strategies ADD COLUMN tier TEXT NOT NULL DEFAULT 'short'")
    # Indexes that depend on migrated columns
    c.execute("CREATE INDEX IF NOT EXISTS ix_strats_family ON strategies(family_id)")


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        _migrate(c)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Brief operations ───────────────────────────────────────────────────────
def save_brief(
    brief_date: str,
    brief_type: str,
    agent_name: str,
    agent_type: str,
    model: str,
    prompt: str,
    output: str,
    error: Optional[str],
    context: dict,
    auto_score: Optional[float] = None,
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO briefs (created_at, brief_date, brief_type, agent_name, "
            "agent_type, model, prompt, output, error, context_json, auto_score) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), brief_date, brief_type, agent_name, agent_type, model,
             prompt, output, error, json.dumps(context, ensure_ascii=False, default=str),
             auto_score),
        )
        return int(cur.lastrowid)


def update_rating(brief_id: int, rating: int, feedback: str = "") -> None:
    if rating < 1 or rating > 5:
        raise ValueError("rating must be 1..5")
    with _conn() as c:
        c.execute(
            "UPDATE briefs SET user_rating=?, user_feedback=? WHERE id=?",
            (rating, feedback, brief_id),
        )




def top_rated_briefs(brief_type: str, limit: int = 5) -> list[dict]:
    """Return briefs with highest combined score (rating priority, auto_score fallback)."""
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM briefs WHERE brief_type=? AND output IS NOT NULL "
            "AND length(output) > 100 "
            "ORDER BY COALESCE(user_rating, 0) DESC, COALESCE(auto_score, 0) DESC, "
            "created_at DESC LIMIT ?",
            (brief_type, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_briefs(brief_type: Optional[str] = None, limit: int = 20) -> list[dict]:
    with _conn() as c:
        if brief_type:
            rows = c.execute(
                "SELECT * FROM briefs WHERE brief_type=? ORDER BY created_at DESC LIMIT ?",
                (brief_type, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM briefs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ── Strategy operations ────────────────────────────────────────────────────
def save_strategy(
    agent_name: str,
    name: str,
    code: str,
    description: str = "",
    params: Optional[dict] = None,
    parent_id: Optional[int] = None,
    status: str = "draft",
    family_id: Optional[str] = None,
    tier: str = "short",
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO strategies (created_at, agent_name, name, description, "
            "code, params_json, parent_id, status, family_id, tier) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), agent_name, name, description, code,
             json.dumps(params or {}, ensure_ascii=False), parent_id, status,
             family_id, tier),
        )
        return int(cur.lastrowid)


def update_strategy_status(strategy_id: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE strategies SET status=? WHERE id=?", (status, strategy_id))


def update_strategy_params(strategy_id: int, params: dict, agent_name: str) -> None:
    """Mutate params on an active strategy without changing the code.
    Used by daily tune flow — keeps lineage on a single row.
    """
    with _conn() as c:
        c.execute(
            "UPDATE strategies SET params_json=?, last_tuned_at=?, "
            "agent_name=agent_name||' / tuned by '||? WHERE id=?",
            (json.dumps(params or {}, ensure_ascii=False), _now(),
             agent_name, strategy_id),
        )


def mark_core_stable(strategy_id: int, stable: bool = True) -> None:
    with _conn() as c:
        c.execute("UPDATE strategies SET is_core_stable=? WHERE id=?",
                  (1 if stable else 0, strategy_id))


def get_active_family(tier: str = "short") -> Optional[dict]:
    """Return the currently-active strategy OF ONE TIER (no agent filter).
    All enabled agents share this strategy and can tune/revise it.

    Mặc định 'short' giữ nguyên nghĩa cho mọi chỗ gọi cũ (trước 13/08 chỉ có
    một tier). Mỗi tier một active — 'position' chạy song song, không tranh
    ghế với 'short'.
    """
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM strategies WHERE status='active' AND tier=? "
            "ORDER BY created_at DESC LIMIT 1", (tier,)
        ).fetchone()
        return dict(row) if row else None


def promote_strategy(strategy_id: int, retire_others: bool = True) -> None:
    """Mark this strategy as 'active'. Optionally retire other actives.

    `retire_others` chỉ đụng active CÙNG TIER — promote chiến lược vị thế
    không được kéo chiến lược 5-phiên đang chạy xuống ghế (và ngược lại).
    """
    with _conn() as c:
        if retire_others:
            row = c.execute("SELECT tier FROM strategies WHERE id=?",
                            (strategy_id,)).fetchone()
            tier = (row["tier"] if row and row["tier"] else "short")
            c.execute("UPDATE strategies SET status='retired' "
                      "WHERE status='active' AND tier=?", (tier,))
        c.execute("UPDATE strategies SET status='active' WHERE id=?", (strategy_id,))


def family_history(family_id: str, limit: int = 20) -> list[dict]:
    """All strategies sharing a family_id, newest first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT s.*, b.expectancy, b.n_trades, b.win_rate "
            "FROM strategies s LEFT JOIN ("
            "  SELECT bt.* FROM backtests bt INNER JOIN ("
            "    SELECT strategy_id, MAX(created_at) AS mx FROM backtests "
            "    GROUP BY strategy_id"
            "  ) m ON m.strategy_id=bt.strategy_id AND m.mx=bt.created_at"
            ") b ON b.strategy_id=s.id "
            "WHERE s.family_id=? ORDER BY s.created_at DESC LIMIT ?",
            (family_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_strategy(strategy_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM strategies WHERE id=?", (strategy_id,)).fetchone()
        return dict(row) if row else None




def best_strategies(limit: int = 5) -> list[dict]:
    """Strategies ranked by latest backtest expectancy * sqrt(n_trades)."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT s.*, b.expectancy, b.sharpe, b.win_rate, b.n_trades, b.max_drawdown
            FROM strategies s
            LEFT JOIN (
                SELECT bt.* FROM backtests bt
                INNER JOIN (
                    SELECT strategy_id, MAX(created_at) AS mx
                    FROM backtests GROUP BY strategy_id
                ) m ON m.strategy_id=bt.strategy_id AND m.mx=bt.created_at
            ) b ON b.strategy_id=s.id
            WHERE s.status IN ('validated','active') AND b.n_trades >= 10
            ORDER BY (COALESCE(b.expectancy,0) * (b.n_trades * 1.0)) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Backtest operations ────────────────────────────────────────────────────
def save_backtest(
    strategy_id: int,
    period_start: str,
    period_end: str,
    universe: str,
    metrics: dict,
    error: Optional[str] = None,
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO backtests (created_at, strategy_id, period_start, period_end, "
            "universe, n_trades, win_rate, avg_return, sharpe, max_drawdown, expectancy, "
            "metrics_json, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), strategy_id, period_start, period_end, universe,
             metrics.get("n_trades", 0), metrics.get("win_rate"),
             metrics.get("avg_return"), metrics.get("sharpe"),
             metrics.get("max_drawdown"), metrics.get("expectancy"),
             json.dumps(metrics, ensure_ascii=False, default=str), error),
        )
        return int(cur.lastrowid)


def latest_backtest(strategy_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM backtests WHERE strategy_id=? ORDER BY created_at DESC LIMIT 1",
            (strategy_id,),
        ).fetchone()
        return dict(row) if row else None


# ── Recommendation operations ──────────────────────────────────────────────
def save_recommendation(
    ticker: str,
    action: str,
    entry: float,
    tp: float,
    sl: float,
    rationale: str = "",
    horizon_days: int = 5,
    brief_id: Optional[int] = None,
    strategy_id: Optional[int] = None,
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO recommendations (created_at, brief_id, strategy_id, ticker, "
            "action, entry_price, take_profit, cut_loss, rationale, horizon_days) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), brief_id, strategy_id, ticker.upper(), action,
             entry, tp, sl, rationale, horizon_days),
        )
        return int(cur.lastrowid)


def supersede_open_recommendations(ticker: str) -> int:
    """Close any currently-open recs for `ticker` as superseded.

    Called by emit_recommendations() before saving a fresh rec, so the
    DB doesn't accumulate stale entries when the same ticker is re-scanned
    multiple times in a day. Returns count of recs closed.
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT r.id FROM recommendations r
            LEFT JOIN rec_outcomes o ON o.rec_id = r.id
            WHERE o.id IS NULL AND r.ticker = ?
            """,
            (ticker,),
        ).fetchall()
        if not rows:
            return 0
        now = _now()
        for row in rows:
            c.execute(
                "INSERT OR REPLACE INTO rec_outcomes "
                "(rec_id, closed_at, exit_price, pnl_pct, hit_target, notes) "
                "VALUES (?, ?, NULL, NULL, ?, ?)",
                (int(row["id"]), now, "superseded", "Replaced by newer scan"),
            )
        return len(rows)


def open_recommendations() -> list[dict]:
    """Return open recs, deduped to the newest one per ticker.

    Two filters applied:
      1. Skip malformed rows — entry/tp/sl pre-sanitization could leak
         negative SL or 10× TP into the table; hide those.
      2. One row per ticker — emit_recommendations() doesn't supersede
         old recs when re-scanned, so a ticker can accumulate stale
         entries with outdated sanitize defaults. Show only the latest.
    """
    with _conn() as c:
        rows = c.execute(
            """
            WITH ranked AS (
                SELECT r.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY r.ticker
                           ORDER BY r.created_at DESC, r.id DESC
                       ) AS rn
                FROM recommendations r
                LEFT JOIN rec_outcomes o ON o.rec_id = r.id
                WHERE o.id IS NULL
                  AND r.entry_price > 0
                  AND r.cut_loss > 0
                  AND r.cut_loss < r.entry_price
                  AND r.take_profit > r.entry_price
                  AND r.take_profit <= r.entry_price * 2.0
            )
            SELECT * FROM ranked
            WHERE rn = 1
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(r) for r in rows]


def close_recommendation(
    rec_id: int,
    exit_price: Optional[float],
    hit_target: str,
    notes: str = "",
) -> None:
    """Close an open rec with an outcome.

    `exit_price=None` records a non-priced close (e.g. hit_target="stale" for
    recs we can no longer fetch a price for — delisted tickers, covered
    warrants); pnl is left NULL so these don't pollute win-rate stats.
    """
    with _conn() as c:
        rec = c.execute(
            "SELECT entry_price FROM recommendations WHERE id=?", (rec_id,)
        ).fetchone()
        if not rec:
            return
        entry = float(rec["entry_price"] or 0)
        if exit_price is None:
            pnl_pct = None
        else:
            pnl_pct = ((exit_price / entry) - 1.0) * 100 if entry > 0 else 0.0
        c.execute(
            "INSERT OR REPLACE INTO rec_outcomes (rec_id, closed_at, exit_price, "
            "pnl_pct, hit_target, notes) VALUES (?,?,?,?,?,?)",
            (rec_id, _now(), exit_price, pnl_pct, hit_target, notes),
        )


def recent_closed_recommendations(limit: int = 30) -> list[dict]:
    """Return recently-closed recs joined with their outcomes, newest first.

    Used by the market tab UI to show realized P&L and hit-target distribution
    so users can audit what the strategy is actually producing.
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT r.id, r.created_at, r.ticker, r.action, r.entry_price,
                   r.take_profit, r.cut_loss, r.horizon_days, r.strategy_id,
                   r.rationale,
                   o.closed_at, o.exit_price, o.pnl_pct, o.hit_target, o.notes
            FROM recommendations r
            INNER JOIN rec_outcomes o ON o.rec_id = r.id
            WHERE o.hit_target IS NOT NULL
            ORDER BY o.closed_at DESC, r.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def outcome_distribution(strategy_id: Optional[int] = None) -> dict:
    """Count closed recs by hit_target bucket (tp/sl/expire/superseded).

    Skips superseded entries from win/loss aggregates because they were
    closed administratively, not by market outcome.
    """
    with _conn() as c:
        q = """SELECT o.hit_target, COUNT(*) as n FROM rec_outcomes o
               JOIN recommendations r ON r.id=o.rec_id"""
        params: tuple = ()
        if strategy_id is not None:
            q += " WHERE r.strategy_id=?"
            params = (strategy_id,)
        q += " GROUP BY o.hit_target"
        rows = c.execute(q, params).fetchall()
    return {str(r["hit_target"] or "unknown"): int(r["n"]) for r in rows}


def recommendation_performance(strategy_id: Optional[int] = None) -> dict:
    """Aggregate stats over MARKET-closed recommendations.

    Excludes hit_target='superseded' (closed administratively, no real PnL)
    so win_rate reflects actual TP/SL/expire outcomes, not bookkeeping.
    """
    with _conn() as c:
        q = ("SELECT o.pnl_pct, o.hit_target FROM rec_outcomes o "
             "JOIN recommendations r ON r.id=o.rec_id "
             "WHERE COALESCE(o.hit_target,'') != 'superseded' "
             "  AND o.pnl_pct IS NOT NULL")
        params: tuple = ()
        if strategy_id is not None:
            q += " AND r.strategy_id=?"
            params = (strategy_id,)
        rows = c.execute(q, params).fetchall()
    if not rows:
        return {"n": 0}
    pnls = [float(r["pnl_pct"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "n":         len(pnls),
        "win_rate":  len(wins) / len(pnls),
        "avg_pnl":   sum(pnls) / len(pnls),
        "avg_win":   sum(wins) / len(wins) if wins else 0,
        "avg_loss":  sum(losses) / len(losses) if losses else 0,
        "best":      max(pnls),
        "worst":     min(pnls),
    }


# ── Data gap suggestions ───────────────────────────────────────────────────






# ── Prompt version tracking ────────────────────────────────────────────────


# ── CLI: đọc bộ nhớ brief từ terminal ──────────────────────────────────────
# Sinh từ phát hiện 11/08: pipeline KHÔNG ghi log (Task Scheduler chạy python
# thẳng, stdout bị vứt; run_daily.log chưa bao giờ tồn tại) → lỗi agent brief
# chỉ còn dấu vết ở đây (save_brief lưu cột `error`). Đây là cái vòi đọc.


def main(argv: "list | None" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Đọc bộ nhớ brief (SQLite) — pipeline không ghi log nên "
                    "đây là nơi duy nhất giữ lỗi agent brief")
    ap.add_argument("--recent", type=int, default=0, metavar="N",
                    help="In N brief gần nhất: ngày, agent, model, LỖI nếu có")
    # giá trị THẬT trong DB (soi output máy user 11/08): morning / afternoon /
    # allocation — bản đầu ghi "close" theo tên gọi miệng, filter không bao
    # giờ khớp được dòng nào
    ap.add_argument("--type", default=None,
                    choices=["morning", "afternoon", "allocation"],
                    help="Lọc theo loại brief")
    args = ap.parse_args(argv)
    if not args.recent:
        ap.print_help()
        return 0
    rows = recent_briefs(brief_type=args.type, limit=args.recent)
    if not rows:
        print("(chưa có brief nào trong memory)")
        return 1
    for r in rows:
        err = str(r.get("error") or "").strip()
        mark = "❌" if err else "✅"
        score = r.get("auto_score")
        line = (f"{mark} {r.get('brief_date', '?')} "
                f"{str(r.get('brief_type', '?')):8s} "
                f"{str(r.get('agent_name', '?')):22s} "
                f"model={r.get('model', '?')}")
        if score is not None:
            line += f" · score={score}"
        print(line)
        if err:
            print(f"     ↳ {err[:220]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
  data_gap_suggestions — agent suggestions for new data/indicators

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

CREATE TABLE IF NOT EXISTS data_gap_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    brief_id        INTEGER,
    suggestion      TEXT NOT NULL,
    category        TEXT,
    priority        INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'open',
    FOREIGN KEY(brief_id) REFERENCES briefs(id)
);
CREATE INDEX IF NOT EXISTS ix_gap_status ON data_gap_suggestions(status);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    brief_type      TEXT NOT NULL,
    version_tag     TEXT NOT NULL,
    template        TEXT NOT NULL,
    avg_rating      REAL,
    n_briefs        INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_prompt_active ON prompt_versions(is_active);
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


def get_brief(brief_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
        return dict(row) if row else None


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
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO strategies (created_at, agent_name, name, description, "
            "code, params_json, parent_id, status, family_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_now(), agent_name, name, description, code,
             json.dumps(params or {}, ensure_ascii=False), parent_id, status,
             family_id),
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


def get_active_family() -> Optional[dict]:
    """Return the single currently-active strategy (no agent filter).
    All enabled agents share this strategy and can tune/revise it.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM strategies WHERE status='active' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def promote_strategy(strategy_id: int, retire_others: bool = True) -> None:
    """Mark this strategy as 'active'. Optionally retire other actives."""
    with _conn() as c:
        if retire_others:
            c.execute("UPDATE strategies SET status='retired' WHERE status='active'")
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


def list_strategies(status: Optional[str] = None) -> list[dict]:
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM strategies WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM strategies ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [dict(r) for r in rows]


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
    exit_price: float,
    hit_target: str,
    notes: str = "",
) -> None:
    with _conn() as c:
        rec = c.execute(
            "SELECT entry_price FROM recommendations WHERE id=?", (rec_id,)
        ).fetchone()
        if not rec:
            return
        entry = float(rec["entry_price"] or 0)
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
def save_data_gap(
    agent_name: str,
    suggestion: str,
    category: str = "general",
    priority: int = 1,
    brief_id: Optional[int] = None,
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO data_gap_suggestions (created_at, agent_name, brief_id, "
            "suggestion, category, priority) VALUES (?,?,?,?,?,?)",
            (_now(), agent_name, brief_id, suggestion, category, priority),
        )
        return int(cur.lastrowid)


def open_data_gaps(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM data_gap_suggestions WHERE status='open' "
            "ORDER BY priority DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def resolve_data_gap(gap_id: int, status: str = "resolved") -> None:
    with _conn() as c:
        c.execute(
            "UPDATE data_gap_suggestions SET status=? WHERE id=?",
            (status, gap_id),
        )


# ── Prompt version tracking ────────────────────────────────────────────────
def save_prompt_version(brief_type: str, version_tag: str, template: str,
                        is_active: bool = False) -> int:
    init_db()
    with _conn() as c:
        if is_active:
            c.execute(
                "UPDATE prompt_versions SET is_active=0 WHERE brief_type=?",
                (brief_type,),
            )
        cur = c.execute(
            "INSERT INTO prompt_versions (created_at, brief_type, version_tag, "
            "template, is_active) VALUES (?,?,?,?,?)",
            (_now(), brief_type, version_tag, template, 1 if is_active else 0),
        )
        return int(cur.lastrowid)


def active_prompt(brief_type: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM prompt_versions WHERE brief_type=? AND is_active=1 "
            "ORDER BY created_at DESC LIMIT 1",
            (brief_type,),
        ).fetchone()
        return dict(row) if row else None


def refresh_prompt_stats() -> None:
    """Recompute avg_rating + n_briefs per prompt version (cheap aggregate)."""
    with _conn() as c:
        c.executescript("""
            UPDATE prompt_versions SET
                avg_rating = (
                    SELECT AVG(b.user_rating) FROM briefs b
                    WHERE b.brief_type = prompt_versions.brief_type
                      AND b.user_rating IS NOT NULL
                ),
                n_briefs = (
                    SELECT COUNT(*) FROM briefs b
                    WHERE b.brief_type = prompt_versions.brief_type
                );
        """)

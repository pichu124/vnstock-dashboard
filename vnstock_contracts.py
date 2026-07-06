"""
Data contracts for the vnstock warehouse.

Single source of truth for what a valid OHLCV / fundamental / tick row looks
like. Every write path must run its DataFrame through the matching schema
before persisting to parquet. Invalid rows are either dropped (lazy=True) or
raise `pandera.errors.SchemaError` depending on the caller's tolerance.

Design notes
------------
* Prices are stored in the warehouse in **VND units as returned by vnstock's
  Quote API** (typically thousands of VND, e.g. 77.7 for a 77,700 VND stock).
  Bounds below therefore use the warehouse convention, not raw VND.
* Vietnamese exchanges impose daily price-change bands (HOSE ±7%, HNX ±10%,
  UPCOM ±15%). Those are enforced by `vnstock_anomaly` at the row level;
  contracts here only enforce structural invariants (positivity, OHLC
  relationships, dtype).
* Pandera is imported lazily so that modules which only read from the
  warehouse do not pay the import cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import pandera.pandas as pa
    from pandera.pandas import Column, DataFrameSchema


# ─────────────────────────────────────────────────────────────────────────────
# Lazy pandera import
# ─────────────────────────────────────────────────────────────────────────────

_PANDERA_AVAILABLE: bool | None = None


def _load_pandera():
    """Import pandera lazily. Returns the module or None if unavailable."""
    global _PANDERA_AVAILABLE
    if _PANDERA_AVAILABLE is False:
        return None
    try:
        import pandera.pandas as pa  # noqa: WPS433

        _PANDERA_AVAILABLE = True
        return pa
    except ImportError:
        _PANDERA_AVAILABLE = False
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Bounds (warehouse convention: prices in thousand VND)
# ─────────────────────────────────────────────────────────────────────────────

PRICE_MIN = 0.001       # 1 VND (penny stocks)
PRICE_MAX = 10_000.0    # 10,000,000 VND — higher than any real VN stock
VOLUME_MAX = 10_000_000_000  # 10B shares/day ceiling
TICKER_PATTERN = r"^[A-Z0-9]{3,10}$"
VALID_FREQ = {"1D", "1W", "1M"}


# ─────────────────────────────────────────────────────────────────────────────
# Schema builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_ohlcv_schema():
    pa = _load_pandera()
    if pa is None:
        return None
    from pandera.pandas import Column, DataFrameSchema, Check

    return DataFrameSchema(
        {
            "time": Column(
                "datetime64[ns]",
                nullable=False,
                coerce=True,
                description="Bar close timestamp (session end for daily bars)",
            ),
            "open": Column(
                float,
                checks=[Check.in_range(PRICE_MIN, PRICE_MAX)],
                nullable=True,  # sometimes absent for partial bars
                coerce=True,
            ),
            "high": Column(
                float,
                checks=[Check.in_range(PRICE_MIN, PRICE_MAX)],
                nullable=True,
                coerce=True,
            ),
            "low": Column(
                float,
                checks=[Check.in_range(PRICE_MIN, PRICE_MAX)],
                nullable=True,
                coerce=True,
            ),
            "close": Column(
                float,
                checks=[Check.greater_than(0), Check.less_than(PRICE_MAX)],
                nullable=False,
                coerce=True,
            ),
            "volume": Column(
                "int64",
                checks=[
                    Check.greater_than_or_equal_to(0),
                    Check.less_than_or_equal_to(VOLUME_MAX),
                ],
                nullable=False,
                coerce=True,
            ),
            "ticker": Column(
                str,
                checks=[Check.str_matches(TICKER_PATTERN)],
                nullable=False,
            ),
            "year": Column(
                "int16",
                checks=[Check.in_range(1990, 2100)],
                nullable=False,
                coerce=True,
            ),
        },
        checks=[
            # high >= max(open, close, low); low <= min(open, close, high)
            Check(
                lambda df: (
                    df[["open", "high", "low", "close"]].isna().any(axis=1)
                    | (df["high"] >= df[["open", "close", "low"]].max(axis=1))
                ),
                error="high must be >= max(open, close, low)",
            ),
            Check(
                lambda df: (
                    df[["open", "high", "low", "close"]].isna().any(axis=1)
                    | (df["low"] <= df[["open", "close", "high"]].min(axis=1))
                ),
                error="low must be <= min(open, close, high)",
            ),
        ],
        strict=False,   # allow extra columns (e.g. close_adj, corp_action_id)
        ordered=False,
        name="OHLCVSchema",
    )


def _build_fundamental_schema():
    pa = _load_pandera()
    if pa is None:
        return None
    from pandera.pandas import Column, DataFrameSchema, Check

    return DataFrameSchema(
        {
            "ticker": Column(
                str,
                checks=[Check.str_matches(TICKER_PATTERN)],
                nullable=False,
            ),
            "as_of": Column("datetime64[ns]", nullable=False, coerce=True),
            "pe": Column(
                float,
                checks=[Check.in_range(-1000, 10_000)],
                nullable=True,
                coerce=True,
            ),
            "pb": Column(
                float,
                checks=[Check.in_range(-100, 1_000)],
                nullable=True,
                coerce=True,
            ),
            "roe": Column(
                float,
                checks=[Check.in_range(-500, 500)],  # percent
                nullable=True,
                coerce=True,
            ),
            "roa": Column(
                float,
                checks=[Check.in_range(-500, 500)],  # percent
                nullable=True,
                coerce=True,
            ),
            "eps": Column(
                float,
                # Unbounded; some VN stocks have very large or negative EPS
                nullable=True,
                coerce=True,
            ),
        },
        strict=False,
        ordered=False,
        name="FundamentalSchema",
    )


def _build_tick_schema():
    pa = _load_pandera()
    if pa is None:
        return None
    from pandera.pandas import Column, DataFrameSchema, Check

    return DataFrameSchema(
        {
            "time": Column("datetime64[ns]", nullable=False, coerce=True),
            "ticker": Column(
                str,
                checks=[Check.str_matches(TICKER_PATTERN)],
                nullable=False,
            ),
            "price": Column(
                float,
                checks=[Check.greater_than(0), Check.less_than(PRICE_MAX)],
                nullable=False,
                coerce=True,
            ),
            "volume": Column(
                "int64",
                checks=[Check.greater_than_or_equal_to(0)],
                nullable=False,
                coerce=True,
            ),
            "side": Column(
                str,
                checks=[Check.isin(["B", "S", "U", ""])],
                nullable=True,
            ),
        },
        strict=False,
        name="TickSchema",
    )


# Public schema singletons (lazy — built on first access)
_cache: dict[str, object] = {}


def ohlcv_schema():
    if "ohlcv" not in _cache:
        _cache["ohlcv"] = _build_ohlcv_schema()
    return _cache["ohlcv"]


def fundamental_schema():
    if "fundamental" not in _cache:
        _cache["fundamental"] = _build_fundamental_schema()
    return _cache["fundamental"]


def tick_schema():
    if "tick" not in _cache:
        _cache["tick"] = _build_tick_schema()
    return _cache["tick"]


# ─────────────────────────────────────────────────────────────────────────────
# Public API — validation entry points
# ─────────────────────────────────────────────────────────────────────────────


class ContractViolation(Exception):
    """Raised when strict validation fails."""


def validate_ohlcv(
    df: pd.DataFrame,
    *,
    strict: bool = False,
    drop_invalid: bool = True,
    return_dropped: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Run a DataFrame through the OHLCV contract.

    Parameters
    ----------
    df : input DataFrame (columns: time, open, high, low, close, volume, ticker, year)
    strict : if True, any violation raises ContractViolation.
    drop_invalid : if True (and not strict), offending rows are dropped and a
        report is returned; if False, the DataFrame is returned unchanged.
    return_dropped : if True, the report additionally carries a ``dropped_rows``
        DataFrame (the rejected rows, verbatim) and ``dropped_reasons`` list.
        Used by the quarantine pipeline to preserve bad rows instead of
        silently discarding them.

    Returns
    -------
    (clean_df, report) where report = {
        "rows_in": int, "rows_out": int, "dropped": int,
        "pandera_available": bool, "failures": list[str],
        "dropped_rows"?: DataFrame, "dropped_reasons"?: list[str]
    }
    """
    report = {
        "rows_in": len(df),
        "rows_out": len(df),
        "dropped": 0,
        "pandera_available": False,
        "failures": [],
    }
    if df is None or df.empty:
        return df, report

    schema = ohlcv_schema()
    if schema is None:
        # Pandera not installed — fall back to structural filter.
        return _fallback_ohlcv_filter(df, report,
                                       return_dropped=return_dropped)

    report["pandera_available"] = True
    try:
        clean = schema.validate(df, lazy=True)
        report["rows_out"] = len(clean)
        return clean, report
    except Exception as e:  # pandera.errors.SchemaErrors
        failures = _extract_failure_cases(e)
        report["failures"] = failures
        if strict:
            raise ContractViolation(f"OHLCV contract violated: {failures[:5]}") from e
        if drop_invalid:
            clean, dropped_df, reasons = _split_failure_rows(df, e)
            report["rows_out"] = len(clean)
            report["dropped"] = len(dropped_df)
            if return_dropped:
                report["dropped_rows"] = dropped_df
                report["dropped_reasons"] = reasons
            return clean, report
        return df, report


def validate_fundamental(df: pd.DataFrame, *, strict: bool = False) -> tuple[pd.DataFrame, dict]:
    report = {"rows_in": len(df), "rows_out": len(df), "dropped": 0,
              "pandera_available": False, "failures": []}
    if df is None or df.empty:
        return df, report
    schema = fundamental_schema()
    if schema is None:
        return df, report
    report["pandera_available"] = True
    try:
        clean = schema.validate(df, lazy=True)
        report["rows_out"] = len(clean)
        return clean, report
    except Exception as e:
        report["failures"] = _extract_failure_cases(e)
        if strict:
            raise ContractViolation(f"Fundamental contract violated") from e
        clean, dropped = _drop_failure_indices(df, e)
        report["rows_out"] = len(clean)
        report["dropped"] = dropped
        return clean, report


def validate_tick(df: pd.DataFrame, *, strict: bool = False) -> tuple[pd.DataFrame, dict]:
    report = {"rows_in": len(df), "rows_out": len(df), "dropped": 0,
              "pandera_available": False, "failures": []}
    if df is None or df.empty:
        return df, report
    schema = tick_schema()
    if schema is None:
        return df, report
    report["pandera_available"] = True
    try:
        clean = schema.validate(df, lazy=True)
        report["rows_out"] = len(clean)
        return clean, report
    except Exception as e:
        report["failures"] = _extract_failure_cases(e)
        if strict:
            raise ContractViolation(f"Tick contract violated") from e
        clean, dropped = _drop_failure_indices(df, e)
        report["rows_out"] = len(clean)
        report["dropped"] = dropped
        return clean, report


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fallback_ohlcv_filter(
    df: pd.DataFrame,
    report: dict,
    *,
    return_dropped: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Used when pandera is not installed — mirrors the schema's invariants."""
    before = len(df)
    mask_ok = pd.Series(True, index=df.index)
    if "close" in df.columns:
        close = pd.to_numeric(df["close"], errors="coerce")
        mask_ok &= (close > 0) & (close < PRICE_MAX)
    if "volume" in df.columns:
        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(-1)
        mask_ok &= (vol >= 0) & (vol <= VOLUME_MAX)
    for col in ("open", "high", "low"):
        if col in df.columns:
            v = pd.to_numeric(df[col], errors="coerce")
            mask_ok &= v.isna() | ((v >= PRICE_MIN) & (v <= PRICE_MAX))
    if "ticker" in df.columns:
        mask_ok &= df["ticker"].astype(str).str.match(TICKER_PATTERN, na=False)
    ohlc = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if len(ohlc) == 4:
        vals = df[ohlc].apply(pd.to_numeric, errors="coerce")
        any_na = vals.isna().any(axis=1)
        mask_ok &= any_na | (vals["high"] >= vals[["open", "close", "low"]].max(axis=1))
        mask_ok &= any_na | (vals["low"] <= vals[["open", "close", "high"]].min(axis=1))
    out = df[mask_ok]
    report["rows_out"] = len(out)
    report["dropped"] = before - len(out)
    if return_dropped:
        dropped = df[~mask_ok]
        report["dropped_rows"] = dropped
        report["dropped_reasons"] = [
            "fallback: price/volume out of bounds, bad ticker, or high/low inverted"
        ] * len(dropped)
    return out, report


def _split_failure_rows(df: pd.DataFrame, exc) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Return (clean_df, dropped_df, per-row reason list)."""
    try:
        cases = getattr(exc, "failure_cases", None)
        if cases is not None and "index" in cases.columns:
            bad = cases["index"].dropna().astype(int).unique().tolist()
            if bad:
                # Build per-row reason summaries from the failure_cases table
                reasons_by_idx: dict[int, list[str]] = {}
                for _, r in cases.iterrows():
                    idx = r.get("index")
                    if idx is None or pd.isna(idx):
                        continue
                    col = r.get("column", "?")
                    check = r.get("check", "?")
                    reasons_by_idx.setdefault(int(idx), []).append(
                        f"{col}: {check}"
                    )
                clean = df.drop(index=bad, errors="ignore")
                dropped = df.loc[df.index.intersection(bad)]
                reasons = [
                    "; ".join(reasons_by_idx.get(int(i), ["schema failure"]))
                    for i in dropped.index
                ]
                return clean, dropped, reasons
    except Exception:
        pass
    # Fallback: structural filter
    clean, rep = _fallback_ohlcv_filter(df, {"rows_out": 0, "dropped": 0},
                                         return_dropped=True)
    dropped = rep.get("dropped_rows", df.iloc[0:0])
    reasons = rep.get("dropped_reasons", [])
    return clean, dropped, reasons


def _extract_failure_cases(exc) -> list[str]:
    """Extract a short list of human-readable failure messages from pandera."""
    try:
        cases = getattr(exc, "failure_cases", None)
        if cases is not None and not cases.empty:
            return (
                cases[["schema_context", "column", "check", "failure_case"]]
                .astype(str)
                .head(20)
                .agg(" | ".join, axis=1)
                .tolist()
            )
    except Exception:
        pass
    return [str(exc)[:200]]


def _drop_failure_indices(df: pd.DataFrame, exc) -> tuple[pd.DataFrame, int]:
    """Drop rows flagged by pandera's failure_cases. Kept for API compat."""
    clean, dropped, _reasons = _split_failure_rows(df, exc)
    return clean, len(dropped)


__all__ = [
    "ContractViolation",
    "ohlcv_schema",
    "fundamental_schema",
    "tick_schema",
    "validate_ohlcv",
    "validate_fundamental",
    "validate_tick",
    "PRICE_MIN",
    "PRICE_MAX",
    "VOLUME_MAX",
    "TICKER_PATTERN",
]

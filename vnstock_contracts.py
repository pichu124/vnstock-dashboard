"""
Data contracts for the vnstock warehouse.

Single source of truth for what a valid OHLCV row looks like. Every write
path must run its DataFrame through `validate_ohlcv` before persisting to
parquet. Invalid rows are either dropped (default) or raise
`ContractViolation` (strict=True).

Design notes
------------
* Prices are stored in the warehouse in **VND units as returned by vnstock's
  Quote API** (typically thousands of VND, e.g. 77.7 for a 77,700 VND stock).
  Bounds below therefore use the warehouse convention, not raw VND.
* Vietnamese exchanges impose daily price-change bands (HOSE ±7%, HNX ±10%,
  UPCOM ±15%). Those are enforced by `vnstock_anomaly` at the row level;
  contracts here only enforce structural invariants (positivity, OHLC
  relationships, ticker format).
* Implemented with plain pandas masks — no schema-library dependency.
  (A pandera version used to live here; the pandas filter enforces the same
  invariants and works on every Python version. See git history.)
"""

from __future__ import annotations

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Bounds (warehouse convention: prices in thousand VND)
# ─────────────────────────────────────────────────────────────────────────────

PRICE_MIN = 0.001       # 1 VND (penny stocks)
PRICE_MAX = 10_000.0    # 10,000,000 VND — higher than any real VN stock
VOLUME_MAX = 10_000_000_000  # 10B shares/day ceiling
TICKER_PATTERN = r"^[A-Z0-9]{3,10}$"
VALID_FREQ = {"1D", "1W", "1M"}


class ContractViolation(Exception):
    """Raised when strict validation fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def validate_ohlcv(
    df: pd.DataFrame,
    *,
    strict: bool = False,
    drop_invalid: bool = True,
    return_dropped: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Run a DataFrame through the OHLCV contract.

    Checks (mirroring the exchange/warehouse invariants):
      * close > 0 and < PRICE_MAX (required)
      * open/high/low within [PRICE_MIN, PRICE_MAX] when present (NaN allowed
        — partial bars)
      * 0 <= volume <= VOLUME_MAX
      * ticker matches ``^[A-Z0-9]{3,10}$``
      * high >= max(open, close, low) and low <= min(open, close, high)
        (rows with any NaN in OHLC are exempt from the cross-field rules)

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
        "rows_in": int, "rows_out": int, "dropped": int, "failures": list[str],
        "dropped_rows"?: DataFrame, "dropped_reasons"?: list[str]
    }
    """
    report = {
        "rows_in": len(df) if df is not None else 0,
        "rows_out": len(df) if df is not None else 0,
        "dropped": 0,
        "failures": [],
    }
    if df is None or df.empty:
        return df, report

    mask_ok, reasons = _ohlcv_mask(df)

    n_bad = int((~mask_ok).sum())
    if n_bad == 0:
        return df, report

    report["failures"] = sorted({r for keep, r in zip(mask_ok, reasons) if not keep})[:20]
    if strict:
        raise ContractViolation(
            f"OHLCV contract violated: {n_bad} row(s) — {report['failures'][:5]}")
    if not drop_invalid:
        return df, report

    out = df[mask_ok]
    report["rows_out"] = len(out)
    report["dropped"] = n_bad
    if return_dropped:
        dropped = df[~mask_ok]
        report["dropped_rows"] = dropped
        report["dropped_reasons"] = [r for keep, r in zip(mask_ok, reasons) if not keep]
    return out, report


def _ohlcv_mask(df: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Return (keep_mask, per-row reason strings for rejected rows)."""
    mask_ok = pd.Series(True, index=df.index)
    # reason per row — first failing check wins, checked in order below
    reason = pd.Series("", index=df.index, dtype=object)

    def _flag(bad: pd.Series, why: str) -> None:
        nonlocal mask_ok
        newly = bad & mask_ok
        reason[newly] = why
        mask_ok &= ~bad

    if "close" in df.columns:
        close = pd.to_numeric(df["close"], errors="coerce")
        _flag(~((close > 0) & (close < PRICE_MAX)), "close out of bounds")
    if "volume" in df.columns:
        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(-1)
        _flag(~((vol >= 0) & (vol <= VOLUME_MAX)), "volume out of bounds")
    for col in ("open", "high", "low"):
        if col in df.columns:
            v = pd.to_numeric(df[col], errors="coerce")
            _flag(~(v.isna() | ((v >= PRICE_MIN) & (v <= PRICE_MAX))),
                  f"{col} out of bounds")
    if "ticker" in df.columns:
        _flag(~df["ticker"].astype(str).str.match(TICKER_PATTERN, na=False),
              "bad ticker format")
    ohlc = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if len(ohlc) == 4:
        vals = df[ohlc].apply(pd.to_numeric, errors="coerce")
        any_na = vals.isna().any(axis=1)
        _flag(~(any_na | (vals["high"] >= vals[["open", "close", "low"]].max(axis=1))),
              "high < max(open, close, low)")
        _flag(~(any_na | (vals["low"] <= vals[["open", "close", "high"]].min(axis=1))),
              "low > min(open, close, high)")

    return mask_ok, reason.tolist()


__all__ = [
    "ContractViolation",
    "validate_ohlcv",
    "PRICE_MIN",
    "PRICE_MAX",
    "VOLUME_MAX",
    "TICKER_PATTERN",
]

"""vnstock_vn30_weights.py — Dynamic VN30 sector weight calculator.

Derives sector composition of the VN30 index from the actual ticker list
+ industry classification + (optional) market cap data, instead of hardcoded
approximate weights.

Cached to <warehouse>/_meta/vn30_sector_weights.json (default: the
``data_warehouse`` next to this module), refreshed weekly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent
_CACHE_PATH = _REPO / "data_warehouse" / "_meta" / "vn30_sector_weights.json"
_CACHE_MAX_AGE_DAYS = 7

# Fallback weights (used only if dynamic computation fails)
_FALLBACK_WEIGHTS: dict[str, float] = {
    "Ngân hàng":            35.0,
    "Bất động sản":         14.0,
    "Tiêu dùng":             9.0,
    "Công nghệ":             8.0,
    "Thép & Kim loại":       5.0,
    "Năng lượng":            5.0,
    "Chứng khoán":           5.0,
    "Xây dựng & Hạ tầng":   4.0,
    "Vận tải & Cảng":        3.0,
    "Hoá chất & Vật liệu":   3.0,
    "Y tế & Dược":           2.0,
    "Dịch vụ & Du lịch":     2.0,
    "Bảo hiểm":              1.5,
    "Nông & Thuỷ sản":       1.0,
    "Khác":                  1.5,
}


def _cache_path(warehouse: Path | str | None) -> Path:
    """Cache trong kho caller truyền vào (tab Danh mục truyền kho của nó); None ⇒ kho
    cạnh module như trước."""
    if warehouse is None:
        return _CACHE_PATH
    return Path(warehouse) / "_meta" / "vn30_sector_weights.json"


def _load_cache(warehouse: Path | str | None = None) -> dict | None:
    path = _cache_path(warehouse)
    if not path.exists():
        return None
    try:
        age_days = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
        if age_days > _CACHE_MAX_AGE_DAYS:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(weights: dict[str, float], n_tickers: int, mode: str,
                warehouse: Path | str | None = None) -> None:
    path = _cache_path(warehouse)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "weights":    weights,
            "n_tickers":  n_tickers,
            "mode":       mode,   # "equal" | "market_cap"
            "updated_at": datetime.now().isoformat(),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _vn30_tickers() -> list[str]:
    """Get current VN30 composition. Tries vnstock_wss constant first."""
    try:
        from vnstock_wss import VN30_SYMBOLS
        if VN30_SYMBOLS:
            return list(VN30_SYMBOLS)
    except Exception:
        pass
    # Fallback hardcoded list (sync with vnstock_train._VN30_SECTOR_MAP keys)
    try:
        from vnstock_train import _VN30_SECTOR_MAP
        return sorted(_VN30_SECTOR_MAP.keys())
    except Exception:
        return []


def _industry_map() -> dict[str, str]:
    """Map ticker → primary_industry from warehouse parquet."""
    p = _REPO / "data_warehouse" / "_meta" / "industry_classification.parquet"
    if not p.exists():
        return {}
    try:
        import pyarrow.parquet as pq
        df = pq.read_table(str(p), columns=["ticker", "primary_industry"]).to_pandas()
        return dict(zip(df["ticker"], df["primary_industry"]))
    except Exception:
        return {}


def _ticker_market_caps(tickers: list[str]) -> dict[str, float]:
    """Read market_cap for each ticker from per-ticker fund_cache JSONs.
    Returns ticker → market_cap (VND). Missing tickers omitted."""
    cache_dir = _REPO / "data_warehouse" / "_meta" / "fund_cache"
    if not cache_dir.exists():
        return {}
    out: dict[str, float] = {}
    for tk in tickers:
        p = cache_dir / f"{tk}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            mcap = data.get("market_cap")
            if mcap and float(mcap) > 0:
                out[tk] = float(mcap)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return out


def compute_vn30_sector_weights(force_refresh: bool = False,
                                warehouse: Path | str | None = None) -> dict[str, float]:
    """Compute or load VN30 sector weights.

    Strategy:
      1. If cache fresh (<7d) → return cached
      2. Try market-cap weighted (need ≥ 20 of 30 tickers in fund_cache)
      3. Fall back to equal-weight by ticker count per sector
      4. If all fails → return _FALLBACK_WEIGHTS

    ``warehouse`` chỉ định kho chứa cache (None ⇒ kho cạnh module).
    Returns: dict[sector_group → weight_pct]. Sum ≈ 100.
    """
    if not force_refresh:
        cached = _load_cache(warehouse)
        if cached and cached.get("weights"):
            return cached["weights"]

    try:
        from vnstock_dashboard import _get_sector  # type: ignore
    except Exception:
        # Streamlit not loaded; minimal stub
        def _get_sector(x: str) -> str:
            return x or "Khác"

    tickers = _vn30_tickers()
    if not tickers:
        return _FALLBACK_WEIGHTS

    ind_map = _industry_map()
    ticker_sector: dict[str, str] = {
        tk: _get_sector(ind_map.get(tk, "")) or "Khác"
        for tk in tickers
    }

    # Try market-cap weighted
    mcaps = _ticker_market_caps(tickers)
    if len(mcaps) >= 20:
        sector_mcap: dict[str, float] = {}
        for tk, mc in mcaps.items():
            sec = ticker_sector.get(tk, "Khác")
            sector_mcap[sec] = sector_mcap.get(sec, 0.0) + mc
        total = sum(sector_mcap.values()) or 1.0
        weights = {s: round(v / total * 100, 2) for s, v in sector_mcap.items()}
        _save_cache(weights, len(tickers), "market_cap", warehouse)
        return weights

    # Fallback: equal-weight by ticker count
    sector_count: dict[str, int] = {}
    for sec in ticker_sector.values():
        sector_count[sec] = sector_count.get(sec, 0) + 1
    total = sum(sector_count.values()) or 1
    weights = {s: round(n / total * 100, 2) for s, n in sector_count.items()}
    _save_cache(weights, len(tickers), "equal", warehouse)
    return weights


def cache_metadata(warehouse: Path | str | None = None) -> dict | None:
    """Return cache payload (weights + n_tickers + mode + updated_at) or None."""
    return _load_cache(warehouse)

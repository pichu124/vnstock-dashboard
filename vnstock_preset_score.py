"""vnstock_preset_score.py — chấm alpha của các preset screener.

Ý tưởng từ khảo sát ML4T 3rd edition 2026-07-15 (workflow đánh giá alpha
factor, chương 6-8): screener chạy 9 preset mỗi tối và lưu snapshot
`_meta/screener_history/YYYY-MM-DD.json` (giữ ~30 ngày) nhưng tín hiệu
CHƯA BAO GIỜ được chấm — không biết oversold/momentum/breakout… preset
nào thật sự có sức dự báo trên HOSE. Module này tính forward return H
phiên của rổ hit từng preset kể từ ngày phát tín hiệu, so với VNINDEX
cùng cửa sổ (excess) → n tín hiệu + excess trung bình + hit-rate.
Zero LLM, zero fetch — chỉ đọc history + kho giá parquet (CLI-safe,
không import vnstock_dashboard — bài học stance track 15/07).

Đọc số đúng cách:
- "excess" = return mã − return VNINDEX cùng cửa sổ (khử nhiễu thị trường
  một cách THÔ, không phải alpha hàn lâm đủ chuẩn).
- History chỉ giữ ~30 ngày → mẫu đủ để XẾP HẠNG tương đối giữa các preset,
  chưa đủ kết luận tuyệt đối; cache scorecard tích lũy dần theo thời gian.

CLI:
    python vnstock_preset_score.py --show [--horizons 5,20] [--days 30]
    python vnstock_preset_score.py --refresh      # tính + ghi cache
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date as _date
from pathlib import Path
from typing import Optional

_WAREHOUSE = Path("data_warehouse")
_HISTORY_DIR = _WAREHOUSE / "_meta" / "screener_history"
_CACHE = _WAREHOUSE / "_meta" / "preset_scorecard.json"
_DEFAULT_HORIZONS = (5, 20)
_MAX_TICKER_DAYS = 160        # đủ cho horizon 20 + history 30 ngày + đệm


def _stitch_units(closes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Vá artifact chuẩn hóa đơn vị PER-BAR cho mã penny quanh mốc 500 VND:
    `_normalize_prices` chia 1000 cho TỪNG bar > 500 → chuỗi [480, 0.51,
    495, 0.52] sinh return giả ±×1000 (thấy thật 15/07: oversold "excess
    +42.73%/5 phiên" toàn do outlier +96,959% giả). Return bất biến thang
    đo — chỉ cần cả chuỗi CÙNG thang: dò bước nhảy ×≥200 (trần sàn 15%/phiên
    không bao giờ chạm) và rescale phần sau về thang của phần trước."""
    out: list[tuple[str, float]] = []
    factor = 1.0
    prev = None
    for d, c in closes:
        v = c * factor
        if prev is not None and prev > 0 and v > 0:
            if v / prev > 200:
                factor /= 1000.0
                v = c * factor
            elif v / prev < 0.005:
                factor *= 1000.0
                v = c * factor
        out.append((d, v))
        prev = v
    return out


def _close_series(ticker: str, cache: dict) -> list[tuple[str, float]]:
    """[(iso_date, close), …] tăng dần, đơn vị ĐÃ nhất quán — đọc parquet
    trực tiếp, cache per-run."""
    if ticker in cache:
        return cache[ticker]
    from vnstock_strategy import _load_history_from_parquet
    out: list[tuple[str, float]] = []
    try:
        hist = _load_history_from_parquet(ticker, days=_MAX_TICKER_DAYS)
        if hist is not None and not hist.empty and "close" in hist.columns:
            for _, row in hist.iterrows():
                try:
                    d = str(row["time"])[:10]
                    c = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if c > 0:
                    out.append((d, c))
    except Exception:
        out = []
    out = _stitch_units(sorted(out))
    cache[ticker] = out
    return out


def _fwd_return(closes: list[tuple[str, float]], signal_date: str,
                horizon: int) -> Optional[float]:
    """% đổi từ close của phiên ≤ signal_date đến close H PHIÊN sau đó.
    None khi thiếu bar gốc hoặc chưa đủ H phiên tương lai (tín hiệu mới)."""
    base_i = None
    for i, (d, _) in enumerate(closes):
        if d <= signal_date:
            base_i = i
        else:
            break
    if base_i is None or base_i + horizon >= len(closes):
        return None
    base = closes[base_i][1]
    fut = closes[base_i + horizon][1]
    if base <= 0:
        return None
    return (fut / base - 1) * 100


def _history_files(days: int) -> list[Path]:
    files = sorted(_HISTORY_DIR.glob("*.json"))
    return files[-days:] if days else files


def preset_scorecard(horizons: tuple[int, ...] = _DEFAULT_HORIZONS,
                     days: int = 30) -> Optional[dict]:
    """{as_of, n_days, horizons, presets: {name: {desc, n_days_signal,
    h{H}: {n, avg_fwd, avg_excess, hit_rate}}}} — None khi không có history.

    hit_rate = % tín hiệu có excess > 0 (thắng VNINDEX cùng cửa sổ)."""
    files = _history_files(days)
    if not files:
        return None
    cache: dict = {}
    vni = _close_series("VNINDEX", cache)
    if not vni:
        return None

    # preset -> horizon -> list[(fwd, excess)]
    acc: dict[str, dict[int, list[tuple[float, float]]]] = {}
    desc: dict[str, str] = {}
    sig_days: dict[str, set] = {}
    for f in files:
        sig_date = f.stem[:10]
        try:
            snap = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, p in (snap.get("presets") or {}).items():
            tickers = [str(r.get("ticker", "")).upper()
                       for r in (p.get("results") or []) if r.get("ticker")]
            if not tickers:
                continue
            desc.setdefault(name, p.get("desc", ""))
            for h in horizons:
                r_idx = _fwd_return(vni, sig_date, h)
                if r_idx is None:
                    continue
                bucket = acc.setdefault(name, {}).setdefault(h, [])
                for tk in tickers:
                    r_tk = _fwd_return(_close_series(tk, cache), sig_date, h)
                    if r_tk is None:
                        continue
                    bucket.append((r_tk, r_tk - r_idx))
                    sig_days.setdefault(name, set()).add(sig_date)

    if not acc:
        return None
    presets: dict[str, dict] = {}
    for name, by_h in acc.items():
        row: dict = {"desc": desc.get(name, ""),
                     "n_days_signal": len(sig_days.get(name, set()))}
        for h, vals in by_h.items():
            if not vals:
                continue
            excess = [e for _, e in vals]
            row[f"h{h}"] = {
                "n": len(vals),
                "avg_fwd": round(sum(v for v, _ in vals) / len(vals), 2),
                "avg_excess": round(sum(excess) / len(excess), 2),
                "hit_rate": round(100 * sum(1 for e in excess if e > 0) / len(excess), 1),
            }
        presets[name] = row
    return {
        "as_of": _date.today().isoformat(),
        "n_days": len(files),
        "horizons": list(horizons),
        "presets": presets,
    }


def save_scorecard(card: dict) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(card, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _CACHE)


def load_scorecard() -> Optional[dict]:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _print_card(card: dict) -> None:
    hs = card.get("horizons") or list(_DEFAULT_HORIZONS)
    h0 = hs[0]
    print(f"📋 Preset scorecard — {card['n_days']} snapshot, "
          f"tính đến {card['as_of']} (excess = so VNINDEX cùng cửa sổ)")
    ranked = sorted(card["presets"].items(),
                    key=lambda kv: (kv[1].get(f"h{h0}") or {}).get("avg_excess", -99),
                    reverse=True)
    for name, row in ranked:
        parts = []
        for h in hs:
            s = row.get(f"h{h}")
            if s:
                parts.append(f"{h}p: excess {s['avg_excess']:+.2f}% "
                             f"(hit {s['hit_rate']:.0f}%, n={s['n']})")
        if parts:
            print(f"  · {name:<15} {' | '.join(parts)}")
    print("  (hit = % tín hiệu thắng VNINDEX; mẫu ~30 ngày — xếp hạng "
          "tương đối, chưa phải kết luận tuyệt đối)")


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description="Chấm alpha các preset screener")
    p.add_argument("--show", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--horizons", default="5,20")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args(argv)

    horizons = tuple(int(x) for x in str(args.horizons).split(",") if x.strip())
    card = preset_scorecard(horizons=horizons, days=args.days)
    if not card:
        print("[preset-score] chưa có screener_history / kho giá để chấm")
        return 1
    if args.refresh:
        save_scorecard(card)
        print(f"[preset-score] ✅ cache → {_CACHE}")
    _print_card(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

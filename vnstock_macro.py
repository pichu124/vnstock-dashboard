#!/usr/bin/env python3
"""vnstock_macro.py — Theo dõi vĩ mô (lãi suất & tỷ giá) cho AI brief.

Tại sao có module này
---------------------
Block "🔧 Đề xuất bổ sung" của brief từ lâu vẫn liệt kê *tin VĨ MÔ — lãi suất /
tỷ giá* là thứ THIẾU (xem `vnstock_brief` template + ghi chú trong
`vnstock_events`: "tin VĨ MÔ ... chưa tích hợp"). Module này lấp đúng khoảng
trống đó: theo dõi một rổ nhỏ chỉ số vĩ mô cốt lõi — **tỷ giá USD/VND**,
**lãi suất điều hành SBV**, **lãi suất liên ngân hàng** — cache lại theo ngày,
phát hiện THAY ĐỔI (để "đón đầu" biến động), và để brief nạp nhanh.

Chiến lược lấy dữ liệu (HYBRID — auto + ghi đè tay)
--------------------------------------------------
* **Tỷ giá USD/VND**: auto-fetch best-effort từ API FX miễn phí (không cần key).
  Khi mạng bị chặn (egress allowlist của web session) hoặc API lỗi → GIỮ cache
  cũ, KHÔNG bao giờ hiện số bịa.
* **Lãi suất điều hành SBV**: đổi vài lần/năm → seed giá trị đã công bố gần nhất
  (có `as_of` + nguồn "seed"), cập nhật tay khi SBV ra quyết định mới.
* **Lãi suất liên ngân hàng ON**: đổi hằng ngày, không có nguồn free ổn định →
  để trống tới khi nhập tay.
* Mọi chỉ số đều có thể GHI ĐÈ TAY: ``python vnstock_macro.py --set <key> <value>``.

Giống `vnstock_foreign_flow`: live fetch cần mạng nên KHÔNG chạy được trong
sandbox; **xác minh trên máy có mạng**::

    python vnstock_macro.py --diag         # thử fetch FX 1 lần, in kết quả
    python vnstock_macro.py --refresh       # cập nhật cache cho pipeline
    python vnstock_macro.py --show          # xem cache hiện tại
    python vnstock_macro.py --set sbv_policy_rate 4.5 --as-of 2024-06-19

Cache: ``data_warehouse/_meta/macro_indicators.json``
  {
    "updated_at": "...ISO...",
    "indicators": {
      "<key>": {"label", "unit", "kind", "source", "history": {date: value}}
    }
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "macro_indicators.json"

# Keep per-indicator history small — enough for a trend, not a time series.
_MAX_HISTORY = 60

# Free, no-auth FX endpoints (tried in order). Both return JSON with a USD-based
# rate table containing "VND". Reference/market rate, not the bank board rate —
# good enough to track direction; override with --set for an exact bank rate.
_FX_ENDPOINTS = (
    "https://open.er-api.com/v6/latest/USD",
    "https://api.exchangerate.host/latest?base=USD&symbols=VND",
)

# Indicator definitions. ``order`` controls display; ``seed`` (optional) is a
# published baseline written on first refresh so the feature is useful out of
# the box — clearly marked source="seed" + an as_of date the brief always shows,
# and trivially correctable via --set. Only deltas (user updates / fresh fetch)
# move the sentiment signal, so a static seed is neutral.
_DEFS: dict[str, dict] = {
    "usdvnd": {
        "label": "Tỷ giá USD/VND (tham chiếu)",
        "unit": "VND", "kind": "fx", "order": 0,
        # no seed — auto-fetched (or --set); omitted from the brief until present
    },
    "sbv_policy_rate": {
        "label": "Lãi suất tái cấp vốn (SBV)",
        "unit": "%/năm", "kind": "rate", "order": 1,
        # SBV cut the refinancing rate to 4.5% on 2023-06-19 and has held it
        # since; seed that as the baseline. CẬP NHẬT TAY khi SBV ra quyết định.
        "seed": {"value": 4.5, "as_of": "2023-06-19"},
    },
    "interbank_on": {
        "label": "Lãi suất liên ngân hàng ON",
        "unit": "%/năm", "kind": "rate", "order": 2,
        # changes daily, no reliable free source → manual --set only
    },
}

# ── Cache I/O ────────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    try:
        if _CACHE.exists():
            d = json.loads(_CACHE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except (OSError, ValueError):
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=0),
            encoding="utf-8",
        )
    except OSError:
        pass


def _ensure_defs(cache: dict) -> dict:
    """Make sure every defined indicator exists (definitions + optional seed).

    Idempotent: existing history/values are preserved; only missing scaffolding
    and a one-time seed value are added.
    """
    inds = cache.setdefault("indicators", {})
    for key, d in _DEFS.items():
        ind = inds.setdefault(key, {})
        ind["label"] = d["label"]
        ind["unit"] = d["unit"]
        ind["kind"] = d["kind"]
        ind.setdefault("history", {})
        ind.setdefault("source", "")
        seed = d.get("seed")
        if seed and not ind["history"]:
            ind["history"][seed["as_of"]] = float(seed["value"])
            ind["source"] = "seed (cập nhật tay khi đổi)"
    return cache


def _record(cache: dict, key: str, value: float, as_of: str, source: str) -> None:
    """Write one reading into an indicator's per-date history (capped)."""
    inds = cache.setdefault("indicators", {})
    ind = inds.setdefault(key, {})
    ind.setdefault("history", {})[as_of] = float(value)
    ind["source"] = source
    # Trim to the newest _MAX_HISTORY dates.
    hist = ind["history"]
    if len(hist) > _MAX_HISTORY:
        for k in sorted(hist)[: len(hist) - _MAX_HISTORY]:
            hist.pop(k, None)


# ── Live fetch (best-effort) ─────────────────────────────────────────────────


def fetch_usdvnd() -> "float | None":
    """Fetch the USD/VND reference rate from a free FX API. None on any failure
    (no network / host not allowlisted / unexpected payload)."""
    try:
        import requests as _req
    except ImportError:
        return None
    for url in _FX_ENDPOINTS:
        try:
            resp = _req.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        # open.er-api.com → {"rates": {"VND": 25400, ...}}
        # exchangerate.host → {"rates": {"VND": 25400}}
        rates = data.get("rates") if isinstance(data, dict) else None
        vnd = (rates or {}).get("VND") if isinstance(rates, dict) else None
        try:
            v = float(vnd)
            if v > 1000:                      # sanity: USD/VND is tens of thousands
                return round(v, 1)
        except (TypeError, ValueError):
            pass
    return None


# ── Public mutation API ──────────────────────────────────────────────────────


def refresh(*, as_of: "str | None" = None) -> dict:
    """Ensure indicator scaffolding/seed, then auto-fetch what we can (FX).

    Best-effort: a blocked/failed FX fetch leaves the prior cache untouched.
    Returns the updated cache.
    """
    cache = _ensure_defs(_load_cache())
    day = as_of or datetime.now().date().isoformat()
    fx = fetch_usdvnd()
    if fx is not None:
        _record(cache, "usdvnd", fx, day, "open.er-api.com")
    _save_cache(cache)
    return cache


def set_value(key: str, value: float, as_of: "str | None" = None) -> dict:
    """Manual override for any indicator (always works, no network)."""
    if key not in _DEFS:
        raise KeyError(f"Chỉ số không hợp lệ: {key!r}. Hợp lệ: {', '.join(_DEFS)}")
    cache = _ensure_defs(_load_cache())
    day = as_of or datetime.now().date().isoformat()
    _record(cache, key, float(value), day, "manual")
    _save_cache(cache)
    return cache


# ── Read / derive ────────────────────────────────────────────────────────────


def _pick(history: dict, effective_date: "str | None") -> "tuple | None":
    """Return (as_of, value, prev_as_of, prev_value) for an indicator.

    A rate/FX level is a STATE (not a daily flow like NN ròng), so the last
    known reading on-or-before ``effective_date`` is meaningful — we surface it
    with its as_of so staleness is always visible, rather than dropping it the
    way the foreign-flow loader drops a missing exact day. ``prev_*`` is the
    reading before it (for change detection); None when only one reading exists.
    """
    if not history:
        return None
    dates = sorted(history)
    if effective_date:
        usable = [d for d in dates if d <= effective_date]
        chosen = usable[-1] if usable else dates[0]
    else:
        chosen = dates[-1]
    idx = dates.index(chosen)
    prev = dates[idx - 1] if idx > 0 else None
    return (
        chosen, float(history[chosen]),
        prev, (float(history[prev]) if prev is not None else None),
    )


def load_macro(effective_date: "str | None" = None) -> list[dict]:
    """Current macro indicators (only those with a reading), each with change.

    Returns a list sorted by ``_DEFS`` order:
      {key, label, unit, kind, value, as_of, source,
       change: {delta, pct, dir} | None, prev_value, prev_as_of}
    ``dir`` is +1 / -1 / 0. Empty list when the cache holds no readings.
    """
    cache = _load_cache()
    inds = (cache.get("indicators") or {})
    out: list[dict] = []
    for key in sorted(_DEFS, key=lambda k: _DEFS[k].get("order", 99)):
        ind = inds.get(key) or {}
        picked = _pick(ind.get("history") or {}, effective_date)
        if picked is None:
            continue
        as_of, value, prev_as_of, prev_value = picked
        change = None
        if prev_value is not None:
            delta = round(value - prev_value, 4)
            pct = round(delta / prev_value * 100, 2) if prev_value else None
            change = {"delta": delta, "pct": pct,
                      "dir": (1 if delta > 0 else (-1 if delta < 0 else 0))}
        out.append({
            "key": key,
            "label": ind.get("label") or _DEFS[key]["label"],
            "unit": ind.get("unit") or _DEFS[key]["unit"],
            "kind": ind.get("kind") or _DEFS[key]["kind"],
            "source": ind.get("source") or "",
            "value": value, "as_of": as_of,
            "prev_value": prev_value, "prev_as_of": prev_as_of,
            "change": change,
        })
    return out


def macro_pressure_score(macro: "list[dict] | None") -> "dict | None":
    """Composite macro pressure on equities from RECENT CHANGES, in [-1, 1].

    Tightening = bearish: rates rising and/or VND weakening (USD/VND up) push the
    score negative; the reverse pushes it positive. Returns
    ``{score, label, dir}`` only when there's a meaningful recent move to react
    to (so a stable macro backdrop doesn't dilute the sentiment composite);
    None otherwise. Levels still show in the brief block regardless.
    """
    if not macro:
        return None
    subs: list[float] = []
    drivers: list[str] = []
    for ind in macro:
        ch = ind.get("change")
        if not ch:
            continue
        if ind["kind"] == "fx":
            pct = ch.get("pct")
            if pct is None or abs(pct) < 0.3:        # ignore daily FX noise
                continue
            s = -_clamp(pct / 2.0)                   # +2% VND weaker → -1.0
            subs.append(s)
            drivers.append("VND yếu đi" if pct > 0 else "VND mạnh lên")
        elif ind["kind"] == "rate":
            delta = ch.get("delta") or 0.0
            if abs(delta) < 0.1:                     # < 10 bps → not notable
                continue
            s = -_clamp(delta / 1.0)                 # +100 bps → -1.0
            subs.append(s)
            drivers.append("lãi suất tăng" if delta > 0 else "lãi suất giảm")
    if not subs:
        return None
    score = _clamp(sum(subs) / len(subs))
    direction = 1 if score > 0.05 else (-1 if score < -0.05 else 0)
    label = ", ".join(dict.fromkeys(drivers))        # dedup, keep order
    if direction < 0:
        label += " (môi trường thắt chặt)"
    elif direction > 0:
        label += " (môi trường nới lỏng)"
    return {"score": round(score, 2), "label": label or "ổn định", "dir": direction}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── Macro news (keyword filter over the existing news cache) ─────────────────

# Lowercased substrings that mark a headline as macro-relevant. Focused to keep
# false positives low (per-ticker corporate news dominates the cache).
_MACRO_KEYWORDS = (
    "lãi suất", "tỷ giá", "usd/vnd", "tỷ giá trung tâm", "ngân hàng nhà nước",
    " sbv", "omo", "tín phiếu", "bơm ròng", "hút ròng", "thanh khoản hệ thống",
    "dự trữ ngoại hối", "lạm phát", " cpi", " fed", "cục dự trữ liên bang",
    "lợi suất", "trái phiếu chính phủ", "điều hành tỷ giá", "điều hành lãi suất",
)


def macro_news(news: "list[dict] | None" = None, days: int = 7,
               limit: int = 5) -> list[dict]:
    """Macro-relevant headlines from the existing news cache (no new fetch).

    Scans titles/summaries for rate/FX/CPI/Fed keywords. Returns up to ``limit``
    recent items as {ticker, date, title}. Empty list when the cache is missing
    or nothing matches.
    """
    try:
        if news is None:
            from vnstock_news import load_news_cache
            news = load_news_cache()
    except Exception:
        return []
    if not news:
        return []
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.today() - _td(days=days)).isoformat()
    out: list[dict] = []
    seen: set[str] = set()
    for item in news:
        d = item.get("_date_sort", "") or ""
        if d and d < cutoff:
            continue
        title = (item.get("news_title") or item.get("title")
                 or item.get("head") or "").strip()
        if not title:
            continue
        summary = (item.get("news_short_content") or "").strip()
        hay = f"{title} {summary}".lower()
        if not any(k in hay for k in _MACRO_KEYWORDS):
            continue
        norm = title.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append({"ticker": item.get("ticker", ""), "date": d, "title": title})
        if len(out) >= limit:
            break
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────


def _fmt_value(ind: dict) -> str:
    v, unit = ind["value"], ind["unit"]
    return f"{v:,.0f} {unit}" if ind["kind"] == "fx" else f"{v:.2f}{unit}"


def _show() -> None:
    macro = load_macro()
    if not macro:
        print(f"[macro] cache rỗng ({_CACHE}). Chạy --refresh hoặc --set để khởi tạo.")
        return
    print(f"[macro] {_CACHE}")
    for ind in macro:
        ch = ind.get("change")
        chs = ""
        if ch:
            if ind["kind"] == "fx" and ch.get("pct") is not None:
                chs = f"  ({ch['pct']:+.2f}% vs {ind['prev_as_of']})"
            else:
                chs = f"  ({ch['delta']:+.2f} điểm vs {ind['prev_as_of']})"
        print(f"  • {ind['label']}: {_fmt_value(ind)}  (tính đến {ind['as_of']}"
              f", nguồn {ind['source'] or '—'}){chs}")
    p = macro_pressure_score(macro)
    if p:
        print(f"  → Áp lực vĩ mô: {p['label']} (score {p['score']:+.2f})")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Theo dõi vĩ mô: lãi suất & tỷ giá.")
    ap.add_argument("--refresh", action="store_true",
                    help="Seed/scaffold + auto-fetch tỷ giá → cache")
    ap.add_argument("--diag", action="store_true",
                    help="Thử fetch FX 1 lần và in kết quả (xác minh trên máy có mạng)")
    ap.add_argument("--show", action="store_true", help="In cache hiện tại")
    ap.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"),
                    help=f"Ghi đè tay 1 chỉ số. KEY ∈ {{{', '.join(_DEFS)}}}")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD",
                    help="Ngày hiệu lực cho --set / --refresh (mặc định hôm nay)")
    a = ap.parse_args(argv)

    if a.diag:
        fx = fetch_usdvnd()
        if fx is None:
            print("[macro] fetch FX thất bại (không có mạng / host bị chặn / API lỗi).")
            print("  → Trên máy có mạng, kết quả sẽ là tỷ giá USD/VND tham chiếu.")
            return 1
        print(f"[macro] USD/VND tham chiếu = {fx:,.1f} (fetch OK).")
        return 0

    if a.set:
        key, val = a.set
        try:
            set_value(key, float(val), as_of=a.as_of)
        except (KeyError, ValueError) as e:
            print(f"[macro] ❌ {e}")
            return 1
        print(f"[macro] đã ghi {key} = {val} (as_of {a.as_of or 'hôm nay'}).")
        _show()
        return 0

    if a.refresh:
        refresh(as_of=a.as_of)
        _show()
        return 0

    if a.show:
        _show()
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

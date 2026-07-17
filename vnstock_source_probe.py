"""
vnstock_source_probe.py — Đo sức khỏe MỌI nguồn giá + xếp hạng ứng viên fallback
================================================================================
Sinh ra từ VCI outage 21h 17/07 (playbook ⚡ trong CLAUDE.md): cần biết nguồn
nào trong registry vnstock đủ KHỎE làm fallback cho VCI, xếp từ khỏe → yếu.

Đo mỗi nguồn trên RỔ MÃ đại diện (HOSE blue/mid + HNX + UPCOM) + riêng
VNINDEX (bar index là nhu cầu đặc biệt của brief/_augment — nguồn tốt cho cổ
phiếu chưa chắc có index). Chấm theo thứ tự ưu tiên:
  1. ĐỘ PHỦ  — bao nhiêu mã trả data OK (nguồn thiếu HNX/UPCOM = fallback tồi)
  2. ĐÚNG GIÁ — close cuối so MEDIAN các nguồn OK; lệch >3% = nghi SAI DATA
     (loại thẳng khỏi ứng viên — giá sai nguy hiểm hơn không có giá);
     tỷ lệ ~×1000 = LỆCH ĐƠN VỊ (VND vs nghìn VND — wire được nhưng PHẢI chia)
  3. TỐC ĐỘ  — trung bình giây/call của các call OK

Fail-fast: 2 mã ĐẦU của một nguồn đều lỗi → bỏ các mã còn lại (nguồn chết
kiểu VCI-outage đốt 30s+/call, không cần tra tấn đủ rổ). Kết quả append vào
`_meta/source_probe.json` (giữ 20 run) — chạy NHIỀU LẦN ở giờ khác nhau thì
cột "ok tích lũy" mới phản ánh độ bền, 1 run chỉ là snapshot thời điểm.

⚠️ VERIFY-GATED: cần vnstock + mạng → chạy trên máy user; sandbox chỉ test
được tầng chấm điểm (score/render thuần).

CLI:  python vnstock_source_probe.py [--days 14] [--basket FPT,HPG,...] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_CACHE = "source_probe.json"
_RETAIN_RUNS = 20

# Ứng viên thử (registry từng bản vnstock khác nhau — nguồn không có sẽ tự
# ghi "không có trong bản này"). VCI để ĐẦU làm reference/đối chứng outage.
_CANDIDATE_SOURCES = ("vci", "kbs", "dnse", "tcbs", "fmp", "msn")

# Rổ mã đại diện: HOSE blue + HOSE mid + HNX + UPCOM. Index probe riêng.
_DEFAULT_BASKET = ("FPT", "BSR", "SHS", "VGI")
_INDEX_SYMBOL = "VNINDEX"

_MISMATCH_PCT = 3.0            # lệch close vs median > 3% = nghi sai data
_UNIT_RATIO_BAND = (500, 2000)  # v/median trong band này = lệch đơn vị ×1000


def _cache_path() -> Path:
    return _META / _CACHE


# ── Probe 1 nguồn (cần vnstock + mạng — verify-gated) ───────────────────────

def _one_call(source: str, symbol: str, start: str, end: str) -> dict:
    """1 call .history() → {ok, secs, rows, last_close, has_vol, err}."""
    t0 = time.time()
    try:
        from vnstock import Quote
        df = Quote(symbol=symbol, source=source.upper()).history(
            start=start, end=end, interval="1D")
        secs = round(time.time() - t0, 1)
        if df is None or len(df) == 0:
            return {"ok": False, "secs": secs, "err": "rỗng"}
        cols = {c.lower() for c in df.columns}
        return {
            "ok": True, "secs": secs, "rows": int(len(df)),
            "last_close": float(df["close"].iloc[-1]) if "close" in cols else None,
            "has_vol": "volume" in cols,
        }
    except Exception as e:                                 # noqa: BLE001
        return {"ok": False, "secs": round(time.time() - t0, 1),
                "err": f"{type(e).__name__}: {str(e)[:120]}"}


def probe_source(source: str, basket: tuple, start: str, end: str,
                 verbose: bool = True) -> dict:
    """Đo 1 nguồn trên rổ mã + index. Fail-fast: 2 mã đầu đều lỗi → bỏ phần
    còn lại. 'unavailable' khi registry bản này không có nguồn."""
    out: dict = {"source": source, "stocks": {}, "index": None}
    for i, sym in enumerate(basket):
        r = _one_call(source, sym, start, end)
        out["stocks"][sym] = r
        if verbose:
            tag = f"{r.get('rows', 0)} bar/{r['secs']}s" if r["ok"] else r["err"]
            print(f"    {source}:{sym} → {'✅' if r['ok'] else '❌'} {tag}")
        if "not found" in (r.get("err") or "").lower():
            out["unavailable"] = True                      # registry không có
            return out
        if i == 1 and not any(v["ok"] for v in out["stocks"].values()):
            out["fail_fast"] = True                        # 2 mã đầu đều chết
            if verbose:
                print(f"    {source}: 2 mã đầu đều lỗi → fail-fast, bỏ phần còn lại")
            return out
    out["index"] = _one_call(source, _INDEX_SYMBOL, start, end)
    if verbose:
        ir = out["index"]
        tag = f"{ir.get('rows', 0)} bar/{ir['secs']}s" if ir["ok"] else ir["err"]
        print(f"    {source}:{_INDEX_SYMBOL} → {'✅' if ir['ok'] else '❌'} {tag}")
    return out


def run_probe(basket: tuple = _DEFAULT_BASKET, days: int = 14,
              sources: tuple = _CANDIDATE_SOURCES, verbose: bool = True) -> dict:
    end = datetime.now().date()
    start = end - timedelta(days=days)
    results = {}
    for src in sources:
        if verbose:
            print(f"  ── nguồn {src} ──")
        results[src] = probe_source(src, basket, start.isoformat(),
                                    end.isoformat(), verbose=verbose)
    return {"at": datetime.now().isoformat(timespec="seconds"),
            "basket": list(basket), "days": days, "results": results}


# ── Chấm điểm + xếp hạng (THUẦN — testable trong sandbox) ──────────────────

def score_results(run: dict) -> list:
    """run → list xếp hạng [khỏe → yếu]: mỗi entry {source, ok, n, avg_secs,
    mismatch (mã lệch giá >3% vs median), unit_x1000, index_ok, verdict}.
    Nguồn 'unavailable' bị loại khỏi bảng. Sort: độ phủ ↓ → lệch giá ↑ →
    tốc độ ↑. Nguồn có mismatch KHÔNG được đề xuất làm fallback (chỉ ghi chú).
    """
    results = (run or {}).get("results") or {}
    # median close per symbol trên các nguồn OK — chuẩn hoá đơn vị trước khi
    # so (nguồn trả VND thô sẽ lớn ~×1000 → đưa về cùng thang bằng log-band)
    per_sym: dict[str, list] = {}
    for src, r in results.items():
        for sym, c in (r.get("stocks") or {}).items():
            if c.get("ok") and c.get("last_close"):
                per_sym.setdefault(sym, []).append(float(c["last_close"]))

    def _median(vals):
        s = sorted(vals)
        return s[len(s) // 2] if s else None

    med = {}
    for sym, vals in per_sym.items():
        # về cùng thang: giá trị > 500× min coi là VND thô → chia 1000
        base = min(vals)
        norm = [v / 1000 if base > 0 and v / base > _UNIT_RATIO_BAND[0] else v
                for v in vals]
        med[sym] = _median(norm)

    ranked = []
    for src, r in results.items():
        if r.get("unavailable"):
            continue
        stocks = r.get("stocks") or {}
        oks = [c for c in stocks.values() if c.get("ok")]
        n_probed = len(stocks)
        mismatch, unit_x1000 = [], False
        for sym, c in stocks.items():
            if not (c.get("ok") and c.get("last_close") and med.get(sym)):
                continue
            v, m = float(c["last_close"]), med[sym]
            ratio = v / m if m else 1.0
            if _UNIT_RATIO_BAND[0] < ratio < _UNIT_RATIO_BAND[1]:
                unit_x1000 = True
                ratio = ratio / 1000
            if abs(ratio - 1) * 100 > _MISMATCH_PCT:
                mismatch.append(sym)
        avg_secs = (round(sum(c["secs"] for c in oks) / len(oks), 1)
                    if oks else None)
        idx = r.get("index") or {}
        ranked.append({
            "source": src, "ok": len(oks), "n": n_probed,
            "avg_secs": avg_secs, "mismatch": mismatch,
            "unit_x1000": unit_x1000, "index_ok": bool(idx.get("ok")),
            "fail_fast": bool(r.get("fail_fast")),
        })
    ranked.sort(key=lambda e: (-e["ok"], len(e["mismatch"]),
                               e["avg_secs"] if e["avg_secs"] is not None else 999))
    for e in ranked:
        if e["ok"] == 0:
            e["verdict"] = "CHẾT (thời điểm probe)"
        elif e["mismatch"]:
            e["verdict"] = f"LỆCH GIÁ {','.join(e['mismatch'])} — KHÔNG dùng"
        elif e["ok"] < e["n"]:
            e["verdict"] = "thiếu độ phủ"
        else:
            e["verdict"] = "ứng viên tốt" + (" (đơn vị VND thô — phải chia 1000)"
                                             if e["unit_x1000"] else "")
    return ranked


def fallback_order(ranked: list) -> list:
    """Thứ tự fallback đề xuất: chỉ nguồn phủ ĐỦ rổ + không lệch giá."""
    return [e["source"] for e in ranked
            if e["ok"] == e["n"] and e["n"] > 0 and not e["mismatch"]]


def render_report(run: dict, ranked: list, cumulative: "dict | None" = None) -> str:
    lines = [f"🔎 Probe nguồn giá — {run.get('at', '?')} · rổ "
             f"{','.join(run.get('basket') or [])} · {run.get('days')} ngày",
             "",
             f"{'Nguồn':<6} {'OK':>5} {'TB s':>6} {'Index':>6} {'Kết luận'}"]
    for e in ranked:
        cum = ""
        if cumulative and e["source"] in cumulative:
            c = cumulative[e["source"]]
            cum = f"  (tích lũy {c['ok']}/{c['n']} qua {c['runs']} run)"
        lines.append(
            f"{e['source']:<6} {e['ok']}/{e['n']:<3} "
            f"{e['avg_secs'] if e['avg_secs'] is not None else '—':>6} "
            f"{'✅' if e['index_ok'] else '❌':>5}  {e['verdict']}{cum}")
    order = fallback_order(ranked)
    lines.append("")
    if order:
        lines.append("→ THỨ TỰ FALLBACK ĐỀ XUẤT (khỏe → yếu, run này): "
                     + " → ".join(order))
    else:
        lines.append("→ Không nguồn nào đủ điều kiện fallback ở run này.")
    lines.append("  (1 run = snapshot; chạy thêm ở giờ khác để cột tích lũy có nghĩa."
                 " Nguồn lệch đơn vị ×1000 vẫn wire được nhưng PHẢI chia 1000.)")
    return "\n".join(lines)


# ── Cache history (nhiều run → độ bền, không chỉ snapshot) ──────────────────

def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_run(run: dict) -> dict:
    cache = _load_cache()
    runs = cache.get("runs")
    if not isinstance(runs, list):
        runs = []
    runs.append(run)
    cache["runs"] = runs[-_RETAIN_RUNS:]
    _META.mkdir(parents=True, exist_ok=True)
    p = _cache_path()
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(str(tmp), str(p))
    return cache


def cumulative_stats(cache: dict) -> dict:
    """{source: {ok, n, runs}} cộng dồn qua mọi run trong cache."""
    out: dict = {}
    for run in cache.get("runs") or []:
        for src, r in (run.get("results") or {}).items():
            if r.get("unavailable"):
                continue
            s = out.setdefault(src, {"ok": 0, "n": 0, "runs": 0})
            s["runs"] += 1
            for c in (r.get("stocks") or {}).values():
                s["n"] += 1
                s["ok"] += 1 if c.get("ok") else 0
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Đo sức khỏe nguồn giá + xếp hạng ứng viên fallback VCI")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--basket", default=",".join(_DEFAULT_BASKET),
                    help="danh sách mã, phẩy ngăn cách")
    ap.add_argument("--json", action="store_true", help="in JSON thay vì bảng")
    args = ap.parse_args(argv)

    basket = tuple(s.strip().upper() for s in args.basket.split(",") if s.strip())
    print(f"[probe] {len(_CANDIDATE_SOURCES)} nguồn × {len(basket)} mã + "
          f"{_INDEX_SYMBOL} (fail-fast khi nguồn chết — nguồn treo kiểu VCI "
          "outage tốn ~60s trước khi bị bỏ)…")
    run = run_probe(basket=basket, days=args.days, verbose=not args.json)
    cache = save_run(run)
    ranked = score_results(run)
    if args.json:
        print(json.dumps({"run": run, "ranked": ranked}, ensure_ascii=False,
                         indent=1))
        return 0
    print()
    print(render_report(run, ranked, cumulative_stats(cache)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

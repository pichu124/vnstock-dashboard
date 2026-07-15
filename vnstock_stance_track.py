"""vnstock_stance_track.py — chấm điểm "Stance ngày mai" của close brief.

Ý tưởng từ khảo sát HKUDS/AI-Trader 2026-07-15 (vòng signal_predictions →
outcome scoring của họ): hệ này chấm REC qua reconciler nhưng chưa bao giờ
chấm chính BRIEF. Mỗi close brief tuyên bố "Stance ngày mai" (TĂNG/GIẢM/
TRUNG TÍNH) — module này so stance với chiều VNINDEX phiên KẾ TIẾP và trả
% gọi đúng rolling. Zero LLM, zero fetch: đọc brief_memory + kho giá
VNINDEX sẵn có; parser stance tái dùng của consensus (_extract_section +
_detect_stance — cùng cách đọc, không thể lệch nhau).

Luật chấm (deterministic):
- bullish  đúng nếu đổi phiên kế  > +_FLAT_BAND;
- bearish  đúng nếu đổi phiên kế  < −_FLAT_BAND;
- neutral  đúng nếu |đổi| ≤ _NEUTRAL_BAND (đi ngang thật);
- stance CÓ HƯỚNG mà |đổi| ≤ _FLAT_BAND → KHÔNG chấm (phiên quá phẳng,
  đúng/sai đều là nhiễu); stance unknown / brief lỗi → bỏ.

CLI:  python vnstock_stance_track.py --show [--limit N]
"""

from __future__ import annotations

import argparse
from typing import Optional

_FLAT_BAND = 0.1      # % — phiên |đổi| dưới ngưỡng này không chấm lệnh có hướng
_NEUTRAL_BAND = 0.3   # % — trung tính đúng khi |đổi| ≤ ngưỡng này
_DEFAULT_LIMIT = 60   # số brief close gần nhất đem chấm

_STANCE_LABEL = {"bullish": "TĂNG", "bearish": "GIẢM", "neutral": "TRUNG TÍNH"}


def _vnindex_closes(days: int = 200) -> list[tuple[str, float]]:
    """[(iso_date, close), …] tăng dần theo ngày — đọc PARQUET trực tiếp.

    KHÔNG dùng `_load_history` ở đây: nhánh đầu của nó import cả
    vnstock_dashboard (chạy nguyên app Streamlit ở bare mode → cả trăm dòng
    warning "missing ScriptRunContext" khi gọi từ CLI — thấy thật 15/07)."""
    from vnstock_strategy import _load_history_from_parquet
    hist = _load_history_from_parquet("VNINDEX", days=days)
    if hist is None or hist.empty or "close" not in hist.columns:
        return []
    out: list[tuple[str, float]] = []
    for _, row in hist.iterrows():
        try:
            d = str(row["time"])[:10]
            c = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c > 0:
            out.append((d, c))
    return sorted(out)


def _next_session_change(brief_date: str,
                         closes: list[tuple[str, float]]) -> "tuple[str, float] | None":
    """(ngày phiên kế, % đổi so phiên brief_date) — None khi chưa có phiên kế
    (brief mới nhất) hoặc thiếu bar gốc."""
    base = None
    for d, c in closes:
        if d <= brief_date:
            base = c
        elif base:
            return d, (c / base - 1) * 100
        else:
            return None
    return None


def _grade(stance: str, chg: float) -> "bool | None":
    """True/False = đúng/sai; None = không chấm."""
    if stance == "neutral":
        return abs(chg) <= _NEUTRAL_BAND
    if abs(chg) <= _FLAT_BAND:
        return None                      # phiên phẳng — hướng nào cũng là nhiễu
    if stance == "bullish":
        return chg > 0
    if stance == "bearish":
        return chg < 0
    return None                          # unknown


def stance_records(limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Mỗi close brief (mỗi agent 1 dòng) → {date, agent, stance, next_date,
    chg_pct, correct}; correct=None = không chấm. Mới nhất trước."""
    import vnstock_memory as mem
    from vnstock_brief import _detect_stance, _extract_section

    mem.init_db()
    briefs = mem.recent_briefs(brief_type="afternoon", limit=limit)
    closes = _vnindex_closes()
    if not briefs or not closes:
        return []
    # Dedupe: regenerate nhiều lần trong ngày (close 14/07 chạy 4 bản) tạo
    # nhiều row cùng (ngày, agent) → chỉ chấm bản MỚI NHẤT, không thì 1 cú
    # gọi sai bị đếm 3-4 lần. recent_briefs đã sort created_at DESC nên bản
    # đầu tiên gặp là bản mới nhất.
    seen: set[tuple[str, str]] = set()
    dedup: list[dict] = []
    for b in briefs:
        key = (str(b.get("brief_date", ""))[:10], str(b.get("agent_name", "")))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(b)
    out: list[dict] = []
    for b in dedup:
        text = b.get("output") or ""
        if not text or b.get("error"):
            continue
        tldr = _extract_section(text, "TLDR") or text[:600]
        stance = _detect_stance(tldr)
        if stance == "unknown":
            continue
        nxt = _next_session_change(str(b.get("brief_date", ""))[:10], closes)
        if not nxt:
            continue                     # brief mới nhất — phiên kế chưa xảy ra
        next_date, chg = nxt
        out.append({
            "date": str(b.get("brief_date", ""))[:10],
            "agent": b.get("agent_name", "?"),
            "stance": stance,
            "next_date": next_date,
            "chg_pct": round(chg, 2),
            "correct": _grade(stance, chg),
        })
    return out


def stance_summary(limit: int = _DEFAULT_LIMIT) -> Optional[dict]:
    """{n_briefs, n_graded, n_correct, pct, skipped, by_agent} — None khi
    chưa có gì để chấm."""
    recs = stance_records(limit)
    if not recs:
        return None
    graded = [r for r in recs if r["correct"] is not None]
    by_agent: dict[str, dict] = {}
    for r in graded:
        a = by_agent.setdefault(r["agent"], {"n": 0, "correct": 0})
        a["n"] += 1
        a["correct"] += 1 if r["correct"] else 0
    return {
        "n_briefs": len(recs),
        "n_graded": len(graded),
        "n_correct": sum(1 for r in graded if r["correct"]),
        "pct": round(100 * sum(1 for r in graded if r["correct"]) / len(graded), 1)
               if graded else None,
        "skipped": len(recs) - len(graded),
        "by_agent": by_agent,
    }


def summary_line(limit: int = _DEFAULT_LIMIT) -> Optional[str]:
    """1 dòng cho dashboard: '🎯 Stance: đúng 3/5 phiên gần nhất (60%) · 2
    không chấm (phiên phẳng)'. None khi chưa đủ dữ liệu."""
    s = stance_summary(limit)
    if not s or not s["n_graded"]:
        return None
    line = (f"🎯 Stance ngày mai: đúng {s['n_correct']}/{s['n_graded']} "
            f"brief gần nhất ({s['pct']:.0f}%)")
    if s["skipped"]:
        line += f" · {s['skipped']} không chấm (phiên phẳng/chưa có phiên kế)"
    return line


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description="Chấm Stance ngày mai của close brief")
    p.add_argument("--show", action="store_true")
    p.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    args = p.parse_args(argv)

    recs = stance_records(args.limit)
    if not recs:
        print("[stance] chưa có brief close nào chấm được (cần brief đã lưu + kho giá VNINDEX)")
        return 1
    s = stance_summary(args.limit)
    print(summary_line(args.limit))
    for a, st in sorted((s or {}).get("by_agent", {}).items()):
        pct = 100 * st["correct"] / st["n"] if st["n"] else 0
        print(f"  · {a}: {st['correct']}/{st['n']} ({pct:.0f}%)")
    print()
    for r in recs[:15]:
        mark = "✅" if r["correct"] else ("❌" if r["correct"] is False else "⏭")
        print(f"  {mark} [{r['date']}] {_STANCE_LABEL.get(r['stance'], r['stance']):<11}"
              f" → phiên {r['next_date']}: {r['chg_pct']:+.2f}%  ({r['agent']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

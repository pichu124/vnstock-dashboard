#!/usr/bin/env python3
"""vnstock_reflection.py — Rút BÀI HỌC từ quyết định đã biết kết quả (reflection).

Ý tưởng mượn từ khảo sát TradingAgents 2026-07-14 (`graph/reflection.py` của
họ): khi một quyết định đã BIẾT OUTCOME, gọi 1 call LLM ngắn ra đúng 2-4 câu
bài học — gọi đúng hướng chưa, luận điểm nào đứng vững/đổ vỡ, MỘT bài học cụ
thể — lưu log rồi TÁI BƠM vào prompt brief sau, để brief "khôn lên" theo thời
gian thay vì lặp lỗi nhận định cũ.

Nguyên liệu đã có sẵn trong hệ, module này chỉ ráp mảnh còn thiếu:
  * Rec đã đóng — `vnstock_memory.recent_closed_recommendations()` (pnl_pct,
    hit_target tp/sl/expire, rationale lúc mở).
  * Kỳ phân bổ đã khép — `vnstock_scorecard` periods (band vs baseline B2).
  * Few-shot/memory brief — bài học nạp vào prompt qua `collect_context`
    (block "🧠 Bài học" — chỉ ở PROMPT, không phải mục brief; xem P4-wiring
    trong vnstock_brief).

Triết lý giữ nguyên hệ: LLM chỉ viết LỜI bài học (không số nào của nó được
pin vào đâu — bài học là ngữ cảnh mềm); mọi thứ best-effort — không key/lỗi
LLM thì bỏ qua, KHÔNG chặn pipeline; chi phí bị chặn trần `--max` call/lượt
(mặc định 3). LLM đi qua cascade sức-mạnh của vnstock_report_digest
(Claude → GPT → gpt-oss free → 70B — đã verify 14/07).

Cache: ``data_warehouse/_meta/reflection_log.json`` (atomic, cap 200 entry).
CLI::

    python vnstock_reflection.py --refresh [--max N]   # rec/kỳ mới đóng → bài học
    python vnstock_reflection.py --show [N]            # xem bài học gần nhất

Pipeline: bước ``reflection`` trong ``run.py all`` (sau audit — reconciler
vừa đóng rec xong là lúc có outcome mới). Tắt: ``VNSTOCK_REFLECTION=0``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_LOG = _REPO / "data_warehouse" / "_meta" / "reflection_log.json"

_MAX_ENTRIES = 200
_DEFAULT_MAX_CALLS = 3          # trần call LLM mỗi lượt refresh (chi phí bị chặn)
_LESSON_MAX_CHARS = 420

# Chỉ rút bài học từ outcome THỊ TRƯỜNG thật — superseded/stale là đóng hành
# chính (không có bài học nhận định nào trong đó).
_REFLECTABLE_HITS = ("tp", "sl", "expire")

_REC_SYSTEM = (
    "Bạn là nhà phân tích tự rà soát khuyến nghị ĐÃ ĐÓNG của chính mình khi "
    "kết quả đã rõ. Viết ĐÚNG 2-4 câu văn xuôi tiếng Việt (không bullet, "
    "không markdown, không tiêu đề), theo thứ tự: (1) gọi đúng hướng chưa — "
    "nêu con số lãi/lỗ %; (2) luận điểm lúc mở lệnh đứng vững hay đổ vỡ ở "
    "điểm nào; (3) MỘT bài học cụ thể áp dụng cho lần phân tích tương tự. "
    "Cụ thể và ngắn gọn — output được lưu nguyên văn và đọc lại bởi các lần "
    "phân tích sau, từng chữ phải đáng giá. KHÔNG bịa số ngoài dữ kiện đã cho."
)

_ALLOC_SYSTEM = (
    "Bạn là nhà phân tích tự rà soát BAND PHÂN BỔ THÁNG đã khép kỳ khi kết "
    "quả đã rõ. Viết ĐÚNG 2-4 câu văn xuôi tiếng Việt (không bullet/markdown): "
    "(1) band phòng thủ/tấn công của kỳ đó đúng hướng chưa — nêu return danh "
    "mục vs baseline B2 (số đã cho); (2) tín hiệu nào dẫn dắt band tỏ ra "
    "đúng/sai; (3) MỘT bài học cho kỳ sau. KHÔNG bịa số ngoài dữ kiện đã cho."
)


# ── LLM call (tái dùng cascade digest — đã verify sức mạnh 14/07) ────────────


def _reflect_call(system: str, user: str) -> "str | None":
    try:
        from vnstock_report_digest import digest_call
        raw, _provider = digest_call(system, user, step="reflection")
        return raw
    except Exception:
        pass
    try:                                    # fallback ladder cũ (provider-major)
        from vnstock_sentiment import chat_complete
        return chat_complete(system, user, max_tokens=300)
    except Exception:
        return None


def _clean(lesson: str) -> str:
    """1 khối văn xuôi sạch để lưu + bơm vào prompt (mirror sanitize digest)."""
    try:
        from vnstock_report_digest import sanitize_text
        return sanitize_text(lesson)[:_LESSON_MAX_CHARS]
    except Exception:
        return " ".join((lesson or "").split())[:_LESSON_MAX_CHARS]


# ── Log I/O (atomic) ─────────────────────────────────────────────────────────


def _load_log() -> dict:
    try:
        if _LOG.exists():
            return json.loads(_LOG.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _write_log(log: dict) -> None:
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    log["updated_at"] = datetime.now().isoformat(timespec="seconds")
    entries = log.get("entries") or []
    log["entries"] = entries[-_MAX_ENTRIES:]
    tmp = _LOG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _LOG)


def load_lessons(limit: int = 3) -> list[dict]:
    """Bài học mới nhất cho prompt brief — mỗi entry {id, kind, date, label,
    lesson}. [] khi chưa có gì (brief chạy như cũ)."""
    entries = _load_log().get("entries") or []
    return list(reversed(entries[-limit:]))


# ── Reflect từng loại quyết định ─────────────────────────────────────────────


def reflect_rec(rec: dict) -> "str | None":
    """1 call → bài học từ 1 rec đã đóng (tp/sl/expire, có pnl)."""
    user = (
        f"Khuyến nghị: {rec.get('action', '?')} {rec.get('ticker', '?')} — "
        f"mở {rec.get('created_at', '?')[:10]}, entry {rec.get('entry_price')}, "
        f"TP {rec.get('take_profit')}, SL {rec.get('cut_loss')}, "
        f"horizon {rec.get('horizon_days')} ngày.\n"
        f"Luận điểm lúc mở: {rec.get('rationale') or '(không ghi)'}\n"
        f"Kết quả: đóng {str(rec.get('closed_at') or '?')[:10]} tại "
        f"{rec.get('exit_price')}, lãi/lỗ {rec.get('pnl_pct'):+.2f}%, "
        f"lý do đóng: {rec.get('hit_target')}"
        f" ({'chạm chốt lời' if rec.get('hit_target') == 'tp' else 'chạm cắt lỗ' if rec.get('hit_target') == 'sl' else 'hết hạn nắm giữ'})."
    )
    raw = _reflect_call(_REC_SYSTEM, user)
    return _clean(raw) if raw else None


def reflect_allocation_period(period: dict) -> "str | None":
    """1 call → bài học từ 1 kỳ band tháng đã khép (scorecard)."""
    port, base = period.get("port_ret_pct"), period.get("baseline_b2_ret_pct")
    delta = period.get("delta_vs_b2")
    user = (
        f"Kỳ phân bổ tháng {period.get('period_start')} → "
        f"{period.get('period_end')}: band {period.get('band')} "
        f"(band data {period.get('band_data')}, tilt {period.get('tilt', 0):+d}).\n"
        f"Return danh mục theo band: {port}% — baseline B2 (trung tính): "
        f"{base}% — chênh {delta:+.2f} điểm %.\n"
        f"Return proxy từng lớp: "
        + ", ".join(f"{cls} {v}%" for cls, v in
                    (period.get("class_returns") or {}).items() if v is not None)
        + f". Độ phủ data {period.get('coverage_pct')}%."
    )
    raw = _reflect_call(_ALLOC_SYSTEM, user)
    return _clean(raw) if raw else None


# ── Refresh: quét outcome mới, cap chi phí ──────────────────────────────────


def refresh(max_calls: int = _DEFAULT_MAX_CALLS) -> list[dict]:
    """Rút bài học cho các outcome CHƯA có reflection — rec đóng trước (tươi
    hơn, nhiều tín hiệu hơn), rồi kỳ scorecard. Trả list entry mới ghi."""
    if os.environ.get("VNSTOCK_REFLECTION", "1") == "0":
        return []
    log = _load_log()
    entries = log.setdefault("entries", [])
    seen = {e.get("id") for e in entries}
    new: list[dict] = []

    def _budget() -> int:
        return max_calls - len(new)

    # 1. Rec đã đóng với outcome thị trường thật
    try:
        from vnstock_memory import recent_closed_recommendations
        closed = recent_closed_recommendations(limit=30)
    except Exception:
        closed = []
    for rec in closed:
        if _budget() <= 0:
            break
        rid = f"rec-{rec.get('id')}"
        if rid in seen or rec.get("hit_target") not in _REFLECTABLE_HITS \
                or rec.get("pnl_pct") is None:
            continue
        lesson = reflect_rec(rec)
        if not lesson:
            continue                        # LLM chết → thử lại lượt sau
        entry = {
            "id": rid, "kind": "rec",
            "date": str(rec.get("closed_at") or "")[:10],
            "label": (f"{rec.get('action')} {rec.get('ticker')} "
                      f"{rec.get('pnl_pct'):+.1f}% ({rec.get('hit_target')})"),
            "lesson": lesson,
        }
        entries.append(entry)
        seen.add(rid)
        new.append(entry)
        print(f"[reflection] ✅ {entry['label']}: {lesson[:90]}…")

    # 2. Kỳ band tháng đã khép (scorecard)
    try:
        from vnstock_scorecard import load_scorecard
        periods = (load_scorecard() or {}).get("periods") or []
    except Exception:
        periods = []
    for p in periods:
        if _budget() <= 0:
            break
        pid = f"alloc-{p.get('period_start')}"
        if pid in seen or p.get("port_ret_pct") is None:
            continue
        lesson = reflect_allocation_period(p)
        if not lesson:
            continue
        entry = {
            "id": pid, "kind": "allocation",
            "date": p.get("period_end"),
            "label": (f"band {p.get('band')} kỳ {p.get('period_start')} "
                      f"Δ vs B2 {p.get('delta_vs_b2'):+.2f}pp"),
            "lesson": lesson,
        }
        entries.append(entry)
        seen.add(pid)
        new.append(entry)
        print(f"[reflection] ✅ {entry['label']}: {lesson[:90]}…")

    if new:
        _write_log(log)
    else:
        print("[reflection] không có outcome mới cần rút bài học")
    return new


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rút bài học từ rec/kỳ phân bổ đã biết kết quả (reflection)")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max", type=int, default=_DEFAULT_MAX_CALLS,
                    help=f"trần call LLM mỗi lượt (mặc định {_DEFAULT_MAX_CALLS})")
    ap.add_argument("--show", type=int, nargs="?", const=10, default=None,
                    metavar="N", help="in N bài học gần nhất (mặc định 10)")
    args = ap.parse_args(argv)

    if args.refresh:
        new = refresh(max_calls=args.max)
        print(f"[reflection] {len(new)} bài học mới")
        return 0
    lessons = load_lessons(limit=args.show or 10)
    if not lessons:
        print("[reflection] chưa có bài học nào — chạy --refresh sau khi có "
              "rec đóng / kỳ scorecard khép")
        return 1
    for e in lessons:
        print(f"🧠 [{e.get('date')}] {e.get('label')}\n   {e.get('lesson')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

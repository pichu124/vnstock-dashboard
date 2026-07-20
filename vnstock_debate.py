#!/usr/bin/env python3
"""vnstock_debate.py — 1 vòng PHẢN BIỆN (devil's advocate) cho band phân bổ.

Ý tưởng mượn từ khảo sát TradingAgents 2026-07-14 (bull/bear researcher
debate), thu gọn theo triết lý hệ này: KHÔNG chạy nhiều vòng nhiều agent
(10-20 call/quyết định của họ ngược hẳn free-tier), chỉ **1 call/kỳ** cho
brief PHÂN BỔ (cadence THÁNG) — một "người phản biện" đưa 3 luận điểm mạnh
nhất CHỐNG lại band hiện tại + 1 điều kiện đảo ngược, để brief allocation
phải đối diện phe ngược thay vì chỉ xuôi chiều data.

Ranh giới an toàn (giữ 3 nguyên tắc thiết kế):
  * Output phản biện chỉ vào PROMPT của brief allocation (block "🗣 Phản
    biện") — KHÔNG splice vào brief xuất bản; brief cuối vẫn qua nguyên
    guard chain (band/% do enforce_allocation_table pin, lời phản biện nếu
    được trích cũng không mang số được pin sai).
  * Mỗi dòng qua sanitize_text (strip #/emoji/CJK) — không phá section parser.
  * Best-effort + cache theo (as_of, band): cùng kỳ cùng band → đọc cache,
    không call lại. Tắt: ``VNSTOCK_ALLOC_DEBATE=0``.

Cache: ``data_warehouse/_meta/allocation_debate.json``.
CLI: ``--run`` (ép chạy với state hiện hành) / ``--show``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "allocation_debate.json"

_MAX_POINTS = 4                 # 3 luận điểm + 1 điều kiện đảo ngược
_POINT_MAX_CHARS = 240

_SYSTEM = (
    "Bạn là NGƯỜI PHẢN BIỆN (devil's advocate) trong ủy ban phân bổ tài sản. "
    "Nhiệm vụ: tấn công band phân bổ hiện tại bằng lập luận SẮC và CÓ CƠ SỞ "
    "— không phải phủ nhận suông. Trả về ĐÚNG 4 dòng tiếng Việt, mỗi dòng "
    "bắt đầu bằng '- ':\n"
    "- 3 dòng đầu: 3 luận điểm mạnh nhất CHỐNG lại band hiện tại (mỗi dòng 1 "
    "câu, PHẢI bám vào số liệu/tín hiệu đã cho — được phép diễn giải ngược "
    "chiều, TUYỆT ĐỐI KHÔNG bịa số mới không có trong dữ kiện).\n"
    "- Dòng 4: bắt đầu bằng '- Điều kiện đảo ngược:' — điều gì xảy ra "
    "(mức/tín hiệu cụ thể từ dữ kiện) thì band hiện tại là SAI và cần đổi.\n"
    "Không markdown đậm, không tiêu đề, không emoji."
)


def _debate_call(system: str, user: str) -> "str | None":
    try:
        from vnstock_report_digest import digest_call
        raw, _ = digest_call(system, user)
        return raw
    except Exception:
        return None


def _clean(line: str) -> str:
    try:
        from vnstock_report_digest import sanitize_text
        return sanitize_text(line)[:_POINT_MAX_CHARS]
    except Exception:
        return " ".join((line or "").split())[:_POINT_MAX_CHARS]


def _load_cache() -> dict:
    try:
        if _CACHE.exists():
            return json.loads(_CACHE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _write_cache(data: dict) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _CACHE)


def _summary_from_state(state: dict, consensus: "dict | None") -> str:
    """Dữ kiện cho người phản biện — CHỈ số liệu thật từ allocation state
    (band + lý do từng input + consensus báo cáo). Không đưa gì ngoài data."""
    lines = [f"Band hiện tại: {state.get('band')} ({state.get('band_label')}) "
             f"— điểm tổng hợp {state.get('score')}, phiên {state.get('as_of')}."]
    rt = state.get("report_tilt") or {}
    if rt.get("tilt"):
        lines.append(f"Đã gồm tilt {rt['tilt']:+d} band từ {rt.get('n_reports')} "
                     f"báo cáo (band data: {state.get('band_data')}).")
    lines.append("Tín hiệu dẫn tới band (điểm [-1,1], +1 = thuận lợi cổ phiếu):")
    for r in state.get("inputs") or []:
        lines.append(f"- {r.get('label')}: {r.get('value')} (điểm "
                     f"{r.get('score', 0):+.2f}) — {r.get('detail') or ''}"
                     f" [as_of {r.get('as_of')}]")
    if consensus and consensus.get("n_reports"):
        cp = (consensus.get("stance") or {}).get("Cổ phiếu")
        lines.append(f"Consensus {consensus['n_reports']} báo cáo vĩ mô: stance "
                     f"cổ phiếu {cp:+.2f}.")
    lines.append(f"Bảng phân bổ đề xuất của band: "
                 + ", ".join(f"{k} {v}%" for k, v in
                             (state.get("allocation") or {}).items()))
    return "\n".join(lines)


def run_debate(state: dict, consensus: "dict | None" = None,
               force: bool = False) -> "dict | None":
    """1 call phản biện cho (as_of, band) hiện hành — cache theo cặp đó nên
    recompute cùng kỳ không tốn call. None khi tắt/thiếu state/LLM chết."""
    if os.environ.get("VNSTOCK_ALLOC_DEBATE", "1") == "0":
        return None
    if not state or state.get("band") not in ("B0", "B1", "B2", "B3", "B4"):
        return None

    cached = _load_cache()
    if (not force and cached.get("as_of") == state.get("as_of")
            and cached.get("band") == state.get("band")
            and cached.get("points")):
        return cached

    raw = _debate_call(_SYSTEM, _summary_from_state(state, consensus))
    if not raw:
        print("[debate] ⚠ không nấc LLM nào trả lời — bỏ qua phản biện kỳ này")
        return cached if cached.get("points") else None
    points = [_clean(l.lstrip("- ").strip()) for l in raw.splitlines()
              if l.strip().startswith("-")]
    points = [p for p in points if p][:_MAX_POINTS]
    if not points:
        print("[debate] ⚠ output không có dòng luận điểm nào — bỏ qua")
        return cached if cached.get("points") else None

    data = {"as_of": state.get("as_of"), "band": state.get("band"),
            "points": points,
            "created_at": datetime.now().isoformat(timespec="seconds")}
    _write_cache(data)
    print(f"[debate] ✅ {len(points)} luận điểm phản biện band {data['band']} "
          f"(phiên {data['as_of']})")
    return data


def load_debate() -> "dict | None":
    """Phản biện đã cache (cho UI/brief đọc lại) — None khi chưa có."""
    d = _load_cache()
    return d if d.get("points") else None


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Phản biện (devil's advocate) band phân bổ — 1 call/kỳ")
    ap.add_argument("--run", action="store_true",
                    help="chạy phản biện với allocation state hiện hành")
    ap.add_argument("--force", action="store_true",
                    help="cùng --run: bỏ cache, call lại")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)

    if args.run:
        try:
            from vnstock_allocation import load_state
            from vnstock_report_digest import consensus as _cons
            state = load_state()
            cons = _cons()
        except Exception:
            state, cons = None, None
        if not state:
            print("[debate] chưa có allocation state — chạy run.py allocation trước")
            return 1
        d = run_debate(state, cons, force=args.force)
        if not d:
            return 1
        args.show = True
    d = load_debate()
    if not d:
        print("[debate] chưa có phản biện — chạy --run (cần allocation state + LLM)")
        return 1
    print(f"🗣 Phản biện band {d['band']} (phiên {d['as_of']}, tạo {d['created_at']}):")
    for p in d["points"]:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

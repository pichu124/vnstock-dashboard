"""
vnstock_llm_ledger.py — sổ ghi call/token LLM theo provider theo ngày
======================================================================
Món 3 từ deep-dive agent-loop DojoAgents (2026-07-15, mirror
SessionTokenState ledger của họ): mỗi call LLM ghi 1 dòng cộng dồn vào
`_meta/llm_ledger.json` — provider nào, model nào, thành công/lỗi/bị
rate-limit, bao nhiêu token. Trả lời câu hỏi "vì sao ladder dạo này toàn
rơi xuống bậc yếu?" bằng SỐ thay vì đoán.

Nguyên tắc: BEST-EFFORT TUYỆT ĐỐI — ``record()`` không bao giờ raise
(sổ hỏng không được làm hỏng call LLM); ghi atomic tmp+replace; giữ
``_RETAIN_DAYS`` ngày gần nhất. Nhiều tiến trình ghi đua nhau có thể mất
vài dòng đếm — chấp nhận (sổ theo dõi, không phải kế toán).

CLI:  python vnstock_llm_ledger.py --show [--day YYYY-MM-DD]
Doctor: check_llm_ledger (vnstock_doctor) đọc sổ này.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_RETAIN_DAYS = 30

_RATE_LIMIT_TOKENS = ("429", "rate limit", "rate_limit", "ratelimit",
                      "too many requests", "quota")


def _path() -> Path:
    return _META / "llm_ledger.json"


def _is_rate_limited(error: "str | None") -> bool:
    if not error:
        return False
    low = str(error).lower()
    return any(tok in low for tok in _RATE_LIMIT_TOKENS)


def record(provider: str, model: str = "", ok: bool = True,
           usage: "dict | None" = None, error: "str | None" = None) -> None:
    """Ghi 1 call vào sổ. KHÔNG BAO GIỜ raise — mọi lỗi nuốt im lặng
    (mirror best-effort: sổ chết không được kéo chết call LLM)."""
    try:
        _META.mkdir(parents=True, exist_ok=True)
        p = _path()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        days = data.get("days")
        if not isinstance(days, dict):
            days = {}
        today = date.today().isoformat()
        day = days.get(today)
        if not isinstance(day, dict):
            day = {}
        key = f"{provider}:{model}" if model else str(provider)
        row = day.get(key)
        if not isinstance(row, dict):
            row = {"calls": 0, "ok": 0, "fail": 0, "rate_limited": 0,
                   "prompt_tokens": 0, "completion_tokens": 0}
        row["calls"] = int(row.get("calls", 0)) + 1
        if ok:
            row["ok"] = int(row.get("ok", 0)) + 1
        else:
            row["fail"] = int(row.get("fail", 0)) + 1
            if _is_rate_limited(error):
                row["rate_limited"] = int(row.get("rate_limited", 0)) + 1
        if isinstance(usage, dict):
            # OpenAI-style (prompt/completion) LẪN Anthropic-style (input/output)
            for srcs, dst in ((("prompt_tokens", "input_tokens"), "prompt_tokens"),
                              (("completion_tokens", "output_tokens"), "completion_tokens")):
                for src in srcs:
                    try:
                        v = int(usage.get(src) or 0)
                    except (TypeError, ValueError):
                        v = 0
                    if v:
                        row[dst] = int(row.get(dst, 0)) + v
                        break
        day[key] = row
        days[today] = day
        # prune ngày cũ (giữ _RETAIN_DAYS gần nhất theo thứ tự khóa ISO)
        for old in sorted(days)[:-_RETAIN_DAYS]:
            days.pop(old, None)
        data["days"] = days

        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(str(tmp), str(p))
    except Exception:
        pass


def summary(day: "str | None" = None) -> dict:
    """{day, providers: {key: row}, totals: {...}} — {} khi chưa có sổ/ngày."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        days = data.get("days") or {}
        if day is None:
            day = date.today().isoformat()
            if day not in days and days:
                day = sorted(days)[-1]        # chưa có hôm nay → ngày gần nhất
        providers = days.get(day) or {}
        if not providers:
            return {}
        totals = {"calls": 0, "ok": 0, "fail": 0, "rate_limited": 0,
                  "prompt_tokens": 0, "completion_tokens": 0}
        for row in providers.values():
            for k in totals:
                try:
                    totals[k] += int(row.get(k, 0))
                except (TypeError, ValueError):
                    pass
        return {"day": day, "providers": providers, "totals": totals}
    except Exception:
        return {}


def summary_lines(day: "str | None" = None) -> list:
    """Dòng hiển thị cho CLI/doctor."""
    s = summary(day)
    if not s:
        return []
    t = s["totals"]
    out = [f"📒 LLM ledger {s['day']}: {t['calls']} call · {t['ok']} OK · "
           f"{t['fail']} lỗi ({t['rate_limited']} rate-limit) · "
           f"~{t['prompt_tokens'] + t['completion_tokens']:,} token"]
    for key in sorted(s["providers"]):
        r = s["providers"][key]
        flag = " ⚠️" if int(r.get("rate_limited", 0)) > 0 else ""
        out.append(f"  {key:40s} {r.get('calls', 0):>4} call · "
                   f"{r.get('ok', 0)} OK · {r.get('fail', 0)} lỗi"
                   f" ({r.get('rate_limited', 0)} rate-limit){flag}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sổ call/token LLM per provider")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (mặc định hôm nay/gần nhất)")
    args = ap.parse_args(argv)
    lines = summary_lines(args.day)
    if not lines:
        print("Chưa có dữ liệu ledger (sổ tự tích lũy khi có call LLM).")
        return 1
    for ln in lines:
        print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Brief 3 khung — BẢN MẪU để duyệt + KIỂM VÒNG TRÒN trên ctx THẬT (P1b-8, #26).

Không gọi LLM, không gửi Telegram, không ghi kho/marker. Chỉ ĐỌC sổ brief
(`brief_memory.db`, mode=ro) + state 3 khung (`_meta/horizon_state.json`) — cả hai
nằm trong kho Dropbox ⇒ ○ máy nào cũng được (tránh khung pipeline 18:00 → `⏱ TỔNG`):

    python scripts/sample_horizons_brief.py              # bản mẫu: brief chiều MỚI NHẤT
                                                         # đi lại chuỗi guard, công tắc BẬT
    python scripts/sample_horizons_brief.py --check 5    # vòng tròn: 5 brief chiều gần nhất
    python scripts/sample_horizons_brief.py --out mau.md # ghi bản mẫu ra file (ngoài kho)

Bản mẫu = chữ agent đã viết phiên đó + phần CODE của brief 3 khung (khối 🔭, TLDR
dòng 3, nhãn Stance ghim theo bảng, lời bảo vệ, từ vựng) dựng từ state của
CHÍNH phiên đó. Vòng tròn đạt khi: khối 🔭 trong bản qua chuỗi guard đúng từng
byte bản canon, và chạy chuỗi guard lần 2 không đổi gì (gửi lại --from-file).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def view_for(state: dict, session: str) -> "dict | None":
    """ctx["horizons"] của MỘT phiên đã qua: bản published đúng ngày đó (không
    lấy bản mới nhất — brief cũ phải gặp lại đúng trạng thái nó đã thấy)."""
    import vnstock_horizons_state as hs
    snap = next((p for p in reversed(state.get("published") or [])
                 if p.get("as_of") == session), None)
    if snap is None:
        return None
    lp = hs.Latest(state=state, snap=snap, missing=None, expect=date.fromisoformat(session))
    view = hs.brief_view(lp)
    view["macro"] = True
    return view


def rebuild_ctx(saved: dict, view: dict) -> dict:
    """ctx đã lưu của brief + phần 3 khung (state đúng phiên) như bước 10 của
    collect_context: 🔭, bảng Stance, lớp bảo vệ, mức đã biết."""
    import vnstock_brief as vb
    ctx = dict(saved)
    ctx["brief_type"] = "afternoon"
    ctx["horizons"] = view
    if isinstance(ctx.get("vnindex_tech"), dict) and not view.get("stale"):
        ctx["vnindex_tech"] = {**ctx["vnindex_tech"],
                               "horizon_levels": list(view.get("known_levels") or [])}
    vb._apply_horizon_stance(ctx)
    vb._apply_horizon_defensive(ctx)
    return ctx


def round_trip(text: str, ctx: dict) -> "tuple[str, list[str]]":
    """(bản qua chuỗi guard, các lỗi vòng tròn — rỗng là đạt)."""
    import vnstock_brief as vb
    once = vb.apply_brief_guards(text, ctx)
    twice = vb.apply_brief_guards(once, dict(ctx))
    errs = []
    if twice != once:
        errs.append("chạy chuỗi guard lần 2 ĐỔI chữ (gửi lại --from-file sẽ khác)")
    body, tldr = vb._horizon_render(ctx)
    lines = once.split("\n")
    if vb._HORIZON_TITLE not in lines:
        errs.append("không có khối 🔭")
    else:
        i = lines.index(vb._HORIZON_TITLE)
        got = lines[i + 1:i + 1 + len(body)]
        # dòng Ngắn/Trung hạn được mang thêm "→ <1 câu agent>" — phần code phải nguyên văn
        ok = len(got) == len(body) and all(
            g == c or (c.startswith(vb._HORIZON_AGENT_PREFIXES) and g.startswith(c + " → "))
            for g, c in zip(got, body))
        if not ok:
            errs.append("khối 🔭 lệch canon (guard khác đã sửa chữ code in)")
    if once.count("**Trung hạn:**") > 1:
        errs.append("dòng '**Trung hạn:**' bị nhân đôi")
    if tldr and tldr not in lines:
        errs.append("thiếu TLDR dòng 3")
    return once, errs


def _rows(limit: int, db: "Path | None" = None) -> list[dict]:
    """Brief chiều hợp lệ mới nhất, mỗi ngày 1 bản — mở sổ CHỈ ĐỌC (mode=ro): sổ
    nằm trong kho Dropbox, chạy ở máy KHÔNG phát (💻 laptop) không được ghi gì."""
    import sqlite3
    import vnstock_memory as mem
    db = Path(db or mem.DB_PATH)
    if not db.is_absolute():
        db = _REPO / db
    if not db.exists():
        return []
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM briefs WHERE brief_type='afternoon' ORDER BY created_at DESC, id DESC "
            "LIMIT ?", (limit * 4,))]
    finally:
        con.close()
    seen, out = set(), []
    for b in rows:
        d = str(b.get("brief_date") or "")[:10]
        if not b.get("output") or b.get("error") or d in seen:
            continue
        seen.add(d)
        out.append(b)
        if len(out) >= limit:
            break
    return out


def _saved_ctx(row: dict) -> dict:
    try:
        ctx = json.loads(row.get("context_json") or "{}")
    except ValueError:
        return {}
    return ctx if isinstance(ctx, dict) else {}


def telegram_preview(text: str, ctx: dict) -> str:
    """Tin Telegram y như push_close_brief sẽ dựng (header 3 khung + thân) — KHÔNG gửi."""
    import vnstock_telegram as tg
    head = tg._horizon_header_lines(ctx["horizons"], ctx.get("allocation") or {},
                                    ctx.get("vnindex_tech") or {})
    msg = "\n".join(head + ["", "🧠 <b>AI Outlook:</b>", tg._snippet_from_text(text)])
    parts = tg._split_for_telegram(tg._sanitize_html(msg))
    return "\n\n".join(f"──── tin {k + 1}/{len(parts)} ({len(p)} ký tự) ────\n{p}"
                       for k, p in enumerate(parts))


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Brief 3 khung: bản mẫu + kiểm vòng tròn (P1b-8)")
    ap.add_argument("--check", type=int, default=0, metavar="N",
                    help="kiểm vòng tròn N brief chiều gần nhất")
    ap.add_argument("--out", default=None, help="ghi bản mẫu ra file (ngoài kho)")
    a = ap.parse_args(argv)
    os.environ["VNSTOCK_HORIZONS"] = "1"          # chỉ trong tiến trình này
    import vnstock_horizons_state as hs
    state = hs.load_state()
    if not state.get("published"):
        print("[mẫu] chưa có state 3 khung — chạy: python run.py horizons --backfill")
        return 1
    rows = _rows(max(a.check, 1))
    if not rows:
        print("[mẫu] sổ brief chưa có brief chiều nào")
        return 1
    if a.check:
        bad = 0
        for row in rows:
            d = str(row["brief_date"])[:10]
            view = view_for(state, d)
            if view is None:
                print(f"  ⏭ {d}: state không có bản published phiên này")
                continue
            _, errs = round_trip(row["output"], rebuild_ctx(_saved_ctx(row), view))
            bad += bool(errs)
            print(f"  {'❌' if errs else '✅'} {d}: " + ("; ".join(errs) or "🔭 đúng canon, 2 lượt giống nhau"))
        print(f"[vòng tròn] {len(rows) - bad}/{len(rows)} đạt")
        return 1 if bad else 0
    row = rows[0]
    d = str(row["brief_date"])[:10]
    view = view_for(state, d)
    if view is None:
        print(f"[mẫu] state không có bản published phiên {d}")
        return 1
    ctx = rebuild_ctx(_saved_ctx(row), view)
    text, errs = round_trip(row["output"], ctx)
    out = (f"# Brief chiều MẪU 3 khung — phiên {d} (agent {row.get('agent_name')})\n\n"
           f"{text}\n\n# Bản Telegram (không gửi)\n\n{telegram_preview(text, ctx)}\n")
    print(out)
    if errs:
        print("⚠️ vòng tròn: " + "; ".join(errs))
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
        print(f"[mẫu] đã ghi {a.out}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

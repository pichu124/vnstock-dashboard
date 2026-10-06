"""Chấm 86 tài khoản Bluesky bằng SỐ LIỆU — ai đáng vào List cảnh báo, ai nên bỏ (04/10/2026, #31).

Thay cho "đọc tay một tuần": lấy bài GỐC (không repost/không trả lời) `--days` ngày qua của
mọi tài khoản trong `docs/bluesky-macro-list.md` (cả bảng trừ ⛔ = List đọc thử, gồm 24 ⭐),
cho Claude chấm bằng ĐÚNG prompt/thang 1–5 của cảnh báo tin (`vnstock_news_alert.SCORE_SYSTEM`,
dòng `Loại: bình luận chuyên gia`), rồi xếp hạng theo số bài đạt ngưỡng gửi (≥3).

    python scripts/bsky_eval.py --dry-run     # 🖥️ chỉ đếm bài (không gọi LLM, ~30s)
    python scripts/bsky_eval.py               # đếm + chấm (hỏi trước, in ước tính chi phí)

Luật kết luận (`verdict`, hàm thuần — có test):
  ⭐ THÊM / ⭐ giữ : ≥2 bài ≥3/5 VÀ ≥20% bài được chấm ≥3/5
  ồn              : >10 bài/ngày mà <15% đạt ≥3 — chiếm suất 6 bài Bluesky/lượt của người khác
  bỏ / hạ ⭐      : chấm ≥5 bài mà 0 bài ≥3, hoặc ≥50% bài bị chấm 1 (lạc đề: chính trị nội bộ, đời tư)
  im              : 0 bài gốc trong `--days` ngày — không tốn suất, giữ hay bỏ đều được
  đọc thêm/giữ ⭐ : còn lại — chưa đủ bằng chứng

Không ghi gì ngoài stdout. Chạy trên máy có mạng (sandbox không tới được API Bluesky).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parent
for _p in (str(REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bsky_make_list as bml  # noqa: E402
import vnstock_news_alert as na  # noqa: E402

DEFAULT_DAYS = 7
DEFAULT_PER_ACCOUNT = 15        # bài mới nhất/người đem chấm — đủ để thấy tỉ lệ, không đốt token
DEFAULT_BATCH = 40              # bài/call Claude (cảnh báo tin chấm 15–60 bài/call)
MAX_PAGES = 5                   # getAuthorFeed ≤100 bài/trang
COST_PER_POST = 0.0025          # Sonnet đo 04/10: $0,03–0,04 cho 15–21 tin
SECS_PER_POST = 0.7

PROMOTE_MIN_HI = 2
PROMOTE_MIN_RATE = 0.20
NOISY_PER_DAY = 10
NOISY_MAX_RATE = 0.15
OFFTOPIC_RATE = 0.50
DROP_MIN_SCORED = 5

_REASON_PIN = "app.bsky.feed.defs#reasonPin"


def author_posts(handle: str, since_iso: str, max_pages: int = MAX_PAGES) -> dict:
    """Bài GỐC của `handle` từ `since_iso` (giờ địa phương) tới nay, mới trước. Repost
    không tính (lời người khác) nhưng đếm riêng; bài ghim cũ không làm dừng lật trang."""
    posts, reposts, cursor = [], 0, None
    for _ in range(max_pages):
        params = {"actor": handle, "limit": 100, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        data = bml._get("app.bsky.feed.getAuthorFeed", params)
        feed = data.get("feed") or []
        reached_old = False
        for entry in feed:
            reason = entry.get("reason") or {}
            rtype = str(reason.get("$type") or "")
            if rtype == _REASON_PIN:
                continue
            if reason:
                if na._iso_dt(reason.get("indexedAt")) >= since_iso:
                    reposts += 1
                continue
            raw = na._bsky_post_to_raw(entry, f"Bluesky · @{handle}")
            if not raw or str(raw.get("author") or "").lower() != handle.lower():
                continue
            pub = na._iso_dt(raw.get("published"))
            if not pub or pub < since_iso:
                reached_old = True
                continue
            posts.append({**raw, "_pub": pub})
        cursor = data.get("cursor")
        if reached_old or not cursor or not feed:
            break
    posts.sort(key=lambda p: p["_pub"], reverse=True)
    return {"posts": posts, "reposts": reposts}


def fetch_all(handles: list, since_iso: str, workers: int = 8) -> dict:
    """{handle: {"posts": [...], "reposts": n} | {"error": "..."}} — một người lỗi không dừng cả lượt."""
    def _one(h):
        try:
            return h, author_posts(h, since_iso)
        except Exception as e:                       # noqa: BLE001
            return h, {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_one, handles))


_SRC = na.Source(key="bsky:eval", name="Bluesky", fetch=lambda: [], kind="social", lang="en",
                 relevant=None)


def build_samples(fetched: dict, per_account: int) -> list:
    """[(handle, item)] — ≤ `per_account` bài ≥ SOCIAL_MIN_CHARS mới nhất mỗi người, xếp
    mới → cũ toàn cục như lượt cảnh báo thật."""
    out = []
    for h, res in fetched.items():
        long = [p for p in res.get("posts") or [] if len(na._one_line(p.get("title"))) >= na.SOCIAL_MIN_CHARS]
        for p in long[:per_account]:
            it = na.normalize_item(p, _SRC)
            if it:
                out.append((h, it))
    out.sort(key=lambda hi: hi[1].get("_published_at") or "", reverse=True)
    return out


def score_samples(samples: list, batch: int = DEFAULT_BATCH) -> "tuple[dict, list]":
    """Chấm theo lô bằng `na.score_items_cli` (Claude Code, cùng prompt cảnh báo).
    Trả ({chỉ số sample: {muc_do, nhan, tac_dong}}, [lỗi từng lô])."""
    got_all, errors = {}, []
    n_batches = (len(samples) + batch - 1) // batch
    for k, start in enumerate(range(0, len(samples), batch), 1):
        chunk = samples[start:start + batch]
        print(f"[bsky-eval] lô {k}/{n_batches}: {len(chunk)} bài")
        got, err = na.score_items_cli([it for _, it in chunk])
        if err and not got:
            errors.append(f"lô {k}: {err}")
            print(f"  ⚠️ lô {k} hỏng ({err}) — {len(chunk)} bài không được chấm")
            continue
        for i, sc in got.items():
            got_all[start + i] = sc
    return got_all, errors


def aggregate(handles: list, fetched: dict, samples: list, scored: dict, days: int) -> dict:
    stats = {h: {"posts": 0, "long": 0, "reposts": 0, "scored": 0, "hi": 0, "top": 0, "off": 0,
                 "sum": 0, "best": None, "error": ""} for h in handles}
    for h in handles:
        res = fetched.get(h) or {}
        st = stats[h]
        if res.get("error"):
            st["error"] = res["error"]
            continue
        posts = res.get("posts") or []
        st["posts"] = len(posts)
        st["long"] = sum(1 for p in posts if len(na._one_line(p.get("title"))) >= na.SOCIAL_MIN_CHARS)
        st["reposts"] = int(res.get("reposts") or 0)
    for idx, (h, it) in enumerate(samples):
        sc = scored.get(idx)
        if not sc:
            continue
        st = stats[h]
        m = int(sc.get("muc_do") or 0)
        st["scored"] += 1
        st["sum"] += m
        st["hi"] += m >= 3
        st["top"] += m >= 4
        st["off"] += m <= 1
        if st["best"] is None or m > st["best"][0]:
            st["best"] = (m, na._one_line(it.get("title"))[:110], sc.get("tac_dong") or "")
    for st in stats.values():
        st["per_day"] = st["posts"] / max(1, days)
        st["mean"] = st["sum"] / st["scored"] if st["scored"] else 0.0
        st["rate"] = st["hi"] / st["scored"] if st["scored"] else 0.0
        st["off_rate"] = st["off"] / st["scored"] if st["scored"] else 0.0
    return stats


def verdict(st: dict, starred: bool, scored_run: bool = True) -> str:
    """Kết luận MỘT tài khoản (luật ở docstring module). `scored_run=False` (--dry-run)
    ⇒ chỉ phán được 'im'."""
    if st.get("error"):
        return "lỗi"
    if st["posts"] == 0:
        return "im"
    if not scored_run or st["scored"] == 0:
        return "?" if scored_run else ("giữ ⭐" if starred else "—")
    if st["hi"] >= PROMOTE_MIN_HI and st["rate"] >= PROMOTE_MIN_RATE:
        return "⭐ giữ" if starred else "⭐ THÊM"
    if st["per_day"] > NOISY_PER_DAY and st["rate"] < NOISY_MAX_RATE:
        return "hạ ⭐ (ồn)" if starred else "ồn"
    if (st["hi"] == 0 and st["scored"] >= DROP_MIN_SCORED) or st["off_rate"] >= OFFTOPIC_RATE:
        return "hạ ⭐" if starred else "bỏ"
    return "giữ ⭐" if starred else "đọc thêm"


_ORDER = ["⭐ THÊM", "⭐ giữ", "giữ ⭐", "hạ ⭐ (ồn)", "hạ ⭐", "đọc thêm", "ồn", "bỏ", "im", "?", "—", "lỗi"]


def print_table(rows: list, stats: dict, scored_run: bool) -> dict:
    groups: dict = {}
    for r in rows:
        v = verdict(stats[r["handle"]], r["starred"], scored_run)
        groups.setdefault(v, []).append(r)
    print(f"\n{'handle':34s} {'⭐':2s} {'bài':>4s} {'≥60':>4s} {'RT':>4s} {'chấm':>4s} {'≥3':>3s} {'≥4':>3s} "
          f"{'TB':>4s} {'lạc':>4s}  kết luận")
    for v in sorted(groups, key=lambda x: _ORDER.index(x) if x in _ORDER else 99):
        members = sorted(groups[v], key=lambda r: (-stats[r["handle"]]["hi"], -stats[r["handle"]]["mean"],
                                                  -stats[r["handle"]]["posts"]))
        for r in members:
            st = stats[r["handle"]]
            if st["error"]:
                print(f"{r['handle']:34s} {'⭐' if r['starred'] else '':2s} ❌ {st['error']}")
                continue
            print(f"{r['handle']:34s} {'⭐' if r['starred'] else '':2s} {st['posts']:>4d} {st['long']:>4d} "
                  f"{st['reposts']:>4d} {st['scored']:>4d} {st['hi']:>3d} {st['top']:>3d} {st['mean']:>4.1f} "
                  f"{st['off_rate'] * 100:>3.0f}%  {v}")
    return groups


def print_summary(groups: dict, stats: dict, days: int = DEFAULT_DAYS) -> None:
    def names(key):
        return ", ".join(r["handle"] for r in groups.get(key, [])) or "—"
    print("\nĐỀ XUẤT (luật: ≥2 bài ≥3/5 và ≥20% bài chấm đạt ≥3/5 ⇒ ⭐):")
    print(f"  THÊM ⭐ ({len(groups.get('⭐ THÊM', []))}): {names('⭐ THÊM')}")
    print(f"  HẠ ⭐  ({len(groups.get('hạ ⭐', [])) + len(groups.get('hạ ⭐ (ồn)', []))}): "
          f"{names('hạ ⭐')}{' · ồn: ' + names('hạ ⭐ (ồn)') if groups.get('hạ ⭐ (ồn)') else ''}")
    print(f"  BỎ khỏi List đọc thử ({len(groups.get('bỏ', [])) + len(groups.get('ồn', []))}): "
          f"{names('bỏ')}{' · ồn: ' + names('ồn') if groups.get('ồn') else ''}")
    print(f"  IM {days} ngày qua ({len(groups.get('im', []))}): {names('im')}")
    best = [r for r in groups.get("⭐ THÊM", []) + groups.get("⭐ giữ", []) if stats[r["handle"]]["best"]]
    if best:
        print("\nBài điểm cao nhất (để soi lại phán quyết):")
        for r in best:
            m, title, impact = stats[r["handle"]]["best"]
            print(f"  @{r['handle']} {m}/5 · {title}" + (f"\n      → {impact}" if impact else ""))


def _model_hint() -> str:
    try:
        import vnstock_claude_cli as vcc
        return vcc.cli_model(na.ENV_CLI_MODEL)
    except Exception:                                # noqa: BLE001
        return "?"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Chấm tài khoản Bluesky bằng số liệu 7 ngày (prompt cảnh báo tin)")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--per-account", type=int, default=DEFAULT_PER_ACCOUNT)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm bài, không gọi Claude")
    ap.add_argument("--yes", action="store_true", help="không hỏi trước khi chấm")
    ap.add_argument("--handles", default="", help="chỉ các handle này (phẩy)")
    ap.add_argument("--md", default=str(bml.DEFAULT_MD))
    a = ap.parse_args(argv)
    na._load_env()

    rows = bml.parse_md(Path(a.md), starred_only=False)
    if a.handles:
        want = {h.strip().lstrip("@").lower() for h in a.handles.split(",") if h.strip()}
        rows = [r for r in rows if r["handle"] in want] + \
               [{"name": h, "handle": h, "starred": False, "confidence": "?"}
                for h in sorted(want - {r["handle"] for r in rows})]
    if not rows:
        print("Không có tài khoản nào.")
        return 1
    days = max(1, a.days)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    print(f"[bsky-eval] {len(rows)} tài khoản ({sum(r['starred'] for r in rows)} ⭐) — lấy bài gốc {days} ngày qua…")
    handles = [r["handle"] for r in rows]
    fetched = fetch_all(handles, since)
    samples = build_samples(fetched, max(1, a.per_account))
    total = sum(len((fetched.get(h) or {}).get("posts") or []) for h in handles)
    print(f"[bsky-eval] {total} bài gốc · {len(samples)} bài ≥{na.SOCIAL_MIN_CHARS} ký tự đem chấm "
          f"(≤{a.per_account}/người)")

    scored: dict = {}
    if not a.dry_run and samples:
        n_batches = (len(samples) + a.batch - 1) // a.batch
        print(f"[bsky-eval] sẽ chấm {len(samples)} bài trong {n_batches} call Claude — ước "
              f"~${len(samples) * COST_PER_POST:.2f}, ~{len(samples) * SECS_PER_POST / 60:.0f} phút "
              f"(model {_model_hint()})")
        if not a.yes and input("Tiếp tục? [y/N] ").strip().lower() not in ("y", "yes", "c", "có", "co"):
            print("Huỷ — chỉ in phần đếm bài.")
            a.dry_run = True
        else:
            scored, errors = score_samples(samples, max(1, a.batch))
            if errors and not scored:
                print("❌ không chấm được bài nào — kiểm Claude CLI: python vnstock_brief_pack.py --check")
                return 2
    stats = aggregate(handles, fetched, samples, scored, days)
    groups = print_table(rows, stats, scored_run=not a.dry_run)
    if not a.dry_run:
        print_summary(groups, stats, days)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nHuỷ.")
        raise SystemExit(130)

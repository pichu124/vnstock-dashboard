"""
vnstock_mcp_enrich.py — dữ liệu chỉ connector MCP mới có, cho mã ĐANG GIỮ +
LỆNH MỞ (U79 pha 1 — CHẠY BÓNG, 08/10)
==========================================================================
Vì sao: 08/10 SHB giảm sàn; báo chí cùng ngày nêu ~750 triệu cp phát hành 2026
CHƯA niêm yết (cổ đông mua ưu đãi 12.500 > thị giá 10.050) là áp lực cung.
vnstock không có số này; connector TCBS có trong MỘT tool:
`tcinvest-getTickerOverview` → `outstandingShare` (lưu hành) / `issueShare`
(niêm yết), triệu cp — SHB 5.343,7 / 4.594,2 khớp số HOSE.

Mỗi lượt: MỘT lần `claude -p` (bộ cờ gọn, `vnstock_claude_cli.complete_mcp`)
gọi 2 tool TCBS cho từng mã: overview + `tcinvest-getTickerActivityNews` (5
tin công bố mới nhất). **Số liệu KHÔNG đi qua chữ model** — code đọc thẳng
`tool_result` trong stream, kiểm mã khớp tham số gọi.

Khoảng lệch lưu hành − niêm yết có HAI loại, phải tách:
  · cp THƯỞNG/cổ tức cp vừa GDKHQ chờ niêm yết (GMD 07/10: 649,3/432,9 =
    đúng +50%) — giá ĐÃ điều chỉnh ngày GDKHQ;
  · phát hành THÊM chưa niêm yết (SHB) — cung mới, giá vốn khác thị giá.
  ⇒ đối chiếu sổ sự kiện (`vnstock_events.price_events` + `vnstock_corp_ratio`):
  lệch ≈ tỉ lệ thưởng × niêm yết ⇒ `bonus`; dư ra ⇒ `bonus_plus`; không sự
  kiện nào ⇒ `unlisted`.

CHẠY BÓNG: ghi `_meta/mcp_enrich.json` (kho — Dropbox), brief CHƯA đọc. Trong
pipeline chạy SAU brief (không thể làm chậm/chặn brief). Cùng ngày đã có bản
ok cho đủ mã ⇒ no-op (máy kia / "Cập nhật còn lại" không tốn thêm lượt).

Nút vặn: VNSTOCK_MCP_ENRICH=0 tắt · VNSTOCK_MCP_ENRICH_MAX_TICKERS (30) ·
VNSTOCK_MCP_ENRICH_TIMEOUT_S (420) · VNSTOCK_MCP_TCBS_SERVER (tên server,
mặc định `claude.ai TCBS MCP`) · VNSTOCK_MCP_CLI_MODEL (Sonnet).

    python vnstock_mcp_enrich.py              # một lượt (no-op nếu hôm nay đã có)
    python vnstock_mcp_enrich.py --show       # in bản mới nhất
    python vnstock_mcp_enrich.py --force --tickers SHB GMD
    python vnstock_mcp_enrich.py --dry-run    # in prompt, không gọi
"""
from __future__ import annotations

import json
import os
import socket
from datetime import date, datetime, timedelta
from pathlib import Path

import vnstock_claude_cli as cc

META_DIR = Path(__file__).parent / "data_warehouse" / "_meta"
OUT_NAME = "mcp_enrich.json"
SCHEMA = 1

ENV_SWITCH = "VNSTOCK_MCP_ENRICH"
ENV_MAX = "VNSTOCK_MCP_ENRICH_MAX_TICKERS"
ENV_TIMEOUT = "VNSTOCK_MCP_ENRICH_TIMEOUT_S"
ENV_SERVER = "VNSTOCK_MCP_TCBS_SERVER"
DEFAULT_SERVER = "claude.ai TCBS MCP"
TOOL_OVERVIEW = "tcinvest-getTickerOverview"
TOOL_NEWS = "tcinvest-getTickerActivityNews"
NEWS_SIZE = 5
NEWS_RECENT_DAYS = 3
DEFAULT_MAX_TICKERS = 30
DEFAULT_TIMEOUT_S = 420
MAX_TURNS = 12

GAP_MIN_PCT = 5.0            # lệch lưu hành/niêm yết dưới mức này ⇒ bỏ qua
BONUS_LOOKBACK_DAYS = 120    # sự kiện thưởng/cổ tức cp trong cửa sổ này
BONUS_TOL = 0.10             # |lệch − kỳ vọng| ≤ 10% kỳ vọng (tối thiểu 1 triệu cp)
BONUS_TOL_MIN_M = 1.0
_OFF = ("0", "false", "off", "no")


# ── Nút vặn ─────────────────────────────────────────────────────────────────
def enabled() -> bool:
    return (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in _OFF


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name) or default)))
    except ValueError:
        return default


def tool_names(server: "str | None" = None) -> tuple[str, str]:
    prefix = cc.mcp_server_prefix(server or os.environ.get(ENV_SERVER) or DEFAULT_SERVER)
    return prefix + TOOL_OVERVIEW, prefix + TOOL_NEWS


# ── Vũ trụ mã ───────────────────────────────────────────────────────────────
def portfolio_tickers(meta_dir: Path) -> list[str]:
    """Mã trong `_meta/portfolio.json` (tab Danh mục) có số lượng > 0."""
    try:
        raw = json.loads((Path(meta_dir) / "portfolio.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for pos in raw if isinstance(raw, list) else []:
        try:
            tk = str(pos.get("ticker") or "").strip().upper()
            if tk and float(pos.get("quantity") or 0) > 0 and tk not in out:
                out.append(tk)
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def open_rec_tickers(today: date) -> list[str]:
    """Mã của lệnh đang hiện ở footer Telegram — đúng tập mục Rủi ro dùng."""
    try:
        from vnstock_brief import _load_open_recs
        return sorted({r["ticker"] for r in _load_open_recs(today.isoformat()) if r.get("ticker")})
    except Exception:
        return []


def build_universe(held: list, recs: list, max_n: int) -> dict:
    """{mã: ["held"|"rec", …]} — mã đang giữ trước, cắt ở `max_n`."""
    out: dict = {}
    for src, tickers in (("held", held), ("rec", recs)):
        for t in tickers or []:
            t = str(t).strip().upper()
            if not t:
                continue
            if t not in out and len(out) >= max_n:
                continue
            out.setdefault(t, [])
            if src not in out[t]:
                out[t].append(src)
    return out


# ── Prompt ──────────────────────────────────────────────────────────────────
def build_prompt(tickers: list, ov_tool: str, news_tool: str) -> tuple[str, str]:
    """(system, user). System KHÔNG có |<>%" hay xuống dòng (shim .cmd)."""
    system = (f"Bạn là bộ thu thập dữ liệu, không phân tích. Với MỖI mã trong tin nhắn, "
              f"gọi tool {ov_tool} với ticker là mã đó, và tool {news_tool} với ticker là "
              f"mã đó, page 0, size {NEWS_SIZE}. Gọi song song nhiều tool trong một lượt. "
              f"Được dùng ToolSearch để nạp hai tool này trước. Không gọi tool nào khác. "
              f"Gọi xong tất cả thì trả lời đúng một chữ: XONG.")
    user = (f"Danh sách mã: {', '.join(tickers)}\n"
            f"Nếu tool chưa có sẵn: gọi ToolSearch với query select:{ov_tool},{news_tool}")
    return system, user


# ── Đọc kết quả tool (hàm thuần) ────────────────────────────────────────────
def _num(v) -> "float | None":
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse_overview(text: str, ticker: str) -> "tuple[dict | None, str | None]":
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return None, "overview: không phải JSON"
    if not isinstance(body, dict):
        return None, "overview: JSON không phải object"
    if str(body.get("ticker") or "").upper() != ticker:
        return None, f"overview: mã trả về {body.get('ticker')!r} ≠ {ticker}"
    out_m, iss_m = _num(body.get("outstandingShare")), _num(body.get("issueShare"))
    if not out_m or not iss_m or out_m <= 0 or iss_m <= 0:
        return None, "overview: thiếu outstandingShare/issueShare"
    return {"outstanding_m": out_m, "issue_m": iss_m,
            "exchange": body.get("exchange")}, None


def parse_news(text: str, ticker: str) -> "tuple[list | None, str | None]":
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return None, "news: không phải JSON"
    items = body.get("listActivityNews") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return None, "news: thiếu listActivityNews"
    out = []
    for it in items:
        if not isinstance(it, dict) or str(it.get("ticker") or ticker).upper() != ticker:
            continue
        out.append({"id": it.get("id"), "title": str(it.get("title") or "").strip(),
                    "source": it.get("source"), "published": str(it.get("publishDate") or "")})
    return out, None


def parse_exchanges(exchanges: list, ov_tool: str, news_tool: str, tickers) -> dict:
    """{mã: {"overview", "news", "errors"}} từ cặp tool_use/tool_result. Mã
    lấy từ THAM SỐ gọi; kết quả phải nói đúng mã đó."""
    want = {str(t).upper() for t in tickers}
    data: dict = {t: {"overview": None, "news": None, "errors": []} for t in want}
    for ex in exchanges or []:
        t = str((ex.get("input") or {}).get("ticker") or "").upper()
        if t not in data:
            continue
        rec = data[t]
        if ex.get("text") is None:
            rec["errors"].append(f"{ex.get('name')}: không có kết quả")
            continue
        if ex.get("is_error"):
            rec["errors"].append(f"{ex.get('name')}: lỗi — {str(ex['text'])[:120]}")
            continue
        if ex.get("name") == ov_tool and rec["overview"] is None:
            rec["overview"], err = parse_overview(ex["text"], t)
        elif ex.get("name") == news_tool and rec["news"] is None:
            rec["news"], err = parse_news(ex["text"], t)
        else:
            continue
        if err:
            rec["errors"].append(err)
    return data


def listing_gap(outstanding_m: float, issue_m: float) -> dict:
    gap = outstanding_m - issue_m
    return {"gap_m": round(gap, 1),
            "gap_pct": round(gap / issue_m * 100, 2) if issue_m > 0 else None}


def classify_gap(gap_m: float, issue_m: float, bonus_ratio: float) -> dict:
    """`none` (lệch < GAP_MIN_PCT) · `bonus` (khớp cp thưởng/cổ tức cp) ·
    `bonus_plus` (thưởng + phần dư) · `unlisted` (không sự kiện nào giải thích)."""
    pct = gap_m / issue_m * 100 if issue_m > 0 else 0.0
    expected = issue_m * max(bonus_ratio or 0.0, 0.0)
    out = {"kind": "none", "expected_bonus_m": round(expected, 1), "residual_m": round(gap_m, 1)}
    if pct < GAP_MIN_PCT:
        return out
    tol = max(BONUS_TOL * expected, BONUS_TOL_MIN_M)
    if expected > 0 and abs(gap_m - expected) <= tol:
        out.update(kind="bonus", residual_m=round(gap_m - expected, 1))
    elif expected > 0 and gap_m > expected:
        out.update(kind="bonus_plus", residual_m=round(gap_m - expected, 1))
    else:
        out["kind"] = "unlisted"
    return out


def bonus_events(ticker: str, today: date) -> tuple[float, list]:
    """Σ tỉ lệ cp thưởng/cổ tức cp có GDKHQ trong BONUS_LOOKBACK_DAYS ngày qua."""
    try:
        from vnstock_corp_ratio import parse_event
        from vnstock_events import price_events
        evs = price_events(ticker, today - timedelta(days=BONUS_LOOKBACK_DAYS), today)
    except Exception:
        return 0.0, []
    ratio, kept = 0.0, []
    for e in evs:
        p = parse_event(e.get("title") or "")
        if p and p.get("kind") == "stock":
            ratio += float(p.get("share_ratio") or 0.0)
            d = e.get("ex_date")
            kept.append({"ex_date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                         "title": e.get("title"), "share_ratio": p.get("share_ratio")})
    return ratio, kept


def recent_count(news: "list | None", now: datetime, days: int = NEWS_RECENT_DAYS) -> int:
    floor = now - timedelta(days=days)
    n = 0
    for it in news or []:
        try:
            if datetime.fromisoformat(str(it.get("published"))[:19]) >= floor:
                n += 1
        except ValueError:
            continue
    return n


def build_entry(sources: list, rec: dict, ratio: float, events: list, now: datetime) -> dict:
    entry: dict = {"source": sources, "errors": list(rec.get("errors") or [])}
    ov = rec.get("overview")
    if ov:
        entry.update(outstanding_m=ov["outstanding_m"], issue_m=ov["issue_m"],
                     **listing_gap(ov["outstanding_m"], ov["issue_m"]))
        cls = classify_gap(entry["gap_m"], ov["issue_m"], ratio)
        entry.update(gap_kind=cls["kind"], expected_bonus_m=cls["expected_bonus_m"],
                     residual_m=cls["residual_m"], bonus_events=events)
    if rec.get("news") is not None:
        entry.update(news=rec["news"], news_recent=recent_count(rec["news"], now))
    return entry


# ── Ghi / đọc ───────────────────────────────────────────────────────────────
def out_path(meta_dir: "Path | None" = None) -> Path:
    return Path(meta_dir or META_DIR) / OUT_NAME


def read_state(meta_dir: "Path | None" = None) -> "dict | None":
    try:
        body = json.loads(out_path(meta_dir).read_text(encoding="utf-8"))
        return body if isinstance(body, dict) else None
    except Exception:
        return None


def write_state(payload: dict, meta_dir: "Path | None" = None) -> None:
    from vnstock_parquet_io import write_json_atomic
    p = out_path(meta_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(payload, p)


def already_done(state: "dict | None", today: date, tickers) -> bool:
    if not state or state.get("run_date") != today.isoformat() or state.get("status") != "ok":
        return False
    return set(tickers) <= set((state.get("tickers") or {}).keys())


def summary_lines(state: "dict | None") -> list[str]:
    if not state:
        return ["[mcp-enrich] chưa có bản nào"]
    eng = state.get("engine") or {}
    cost = eng.get("cost_usd")
    head = (f"[mcp-enrich] {state.get('run_at')} · máy {state.get('machine')} · "
            f"{state.get('status')} · {len(state.get('tickers') or {})} mã"
            + (f" · ${cost:,.3f}" if isinstance(cost, (int, float)) else "")
            + (f" · {float(eng.get('elapsed_s') or 0):,.0f}s" if eng.get("elapsed_s") else ""))
    lines = [head]
    if state.get("error"):
        lines.append(f"    ❌ {state['error']}")
    label = {"bonus": "cp thưởng/cổ tức cp chờ niêm yết",
             "bonus_plus": "thưởng + PHẦN DƯ chưa giải thích",
             "unlisted": "phát hành thêm CHƯA niêm yết (không khớp sự kiện quyền nào)"}
    for t, e in sorted((state.get("tickers") or {}).items()):
        bits = [f"    {t:<5} {'/'.join(e.get('source') or [])}"]
        if "gap_m" in e:
            bits.append(f"lưu hành {e['outstanding_m']:,.1f} · niêm yết {e['issue_m']:,.1f} tr cp")
            if e.get("gap_kind") and e["gap_kind"] != "none":
                bits.append(f"⚠️ lệch {e['gap_m']:,.1f} tr ({e['gap_pct']:,.1f}%) — "
                            f"{label.get(e['gap_kind'], e['gap_kind'])}")
        if "news" in e:
            bits.append(f"{e.get('news_recent', 0)} công bố/{NEWS_RECENT_DAYS} ngày")
            if e["news"]:
                bits.append(f"mới nhất: {e['news'][0]['published'][:10]} {e['news'][0]['title'][:60]}")
        if e.get("errors"):
            bits.append("lỗi: " + "; ".join(e["errors"])[:160])
        lines.append(" · ".join(bits))
    return lines


# ── Một lượt ────────────────────────────────────────────────────────────────
def run(*, tickers: "list | None" = None, force: bool = False, dry_run: bool = False,
        meta_dir: "Path | None" = None, now: "datetime | None" = None,
        collect=None) -> dict:
    """Một lượt chạy bóng. Trả payload đã ghi (hoặc `{"status": "skipped"|…}`).
    `collect(user, system, allowed) -> (exchanges, err, info)` — tiêm cho test."""
    now = now or datetime.now()
    today = now.date()
    meta = Path(meta_dir or META_DIR)
    if not enabled():
        return {"status": "disabled", "reason": f"{ENV_SWITCH}=0"}
    max_n = _env_int(ENV_MAX, DEFAULT_MAX_TICKERS, 1, 100)
    if tickers:
        uni = build_universe([t.upper() for t in tickers], [], max_n)
    else:
        uni = build_universe(portfolio_tickers(meta), open_rec_tickers(today), max_n)
    if not uni:
        return {"status": "skipped", "reason": "không có mã đang giữ / lệnh mở"}
    if not force and not dry_run and already_done(read_state(meta), today, uni):
        return {"status": "skipped", "reason": f"đã có bản ok ngày {today.isoformat()}"}
    ov_tool, news_tool = tool_names()
    system, user = build_prompt(list(uni), ov_tool, news_tool)
    if dry_run:
        return {"status": "dry-run", "system": system, "user": user, "tickers": list(uni)}
    if collect is None:
        timeout = _env_int(ENV_TIMEOUT, DEFAULT_TIMEOUT_S, 60, 1800)

        def collect(u, s, allowed):
            return cc.complete_mcp(u, system=s, allowed_tools=allowed, timeout_s=timeout,
                                   max_turns=MAX_TURNS, tag="mcp_enrich")
    exchanges, err, info = collect(user, system, [ov_tool, news_tool])
    if info.get("no_exe"):
        return {"status": "skipped", "reason": "máy này không có Claude Code CLI"}
    data = parse_exchanges(exchanges, ov_tool, news_tool, uni)
    entries = {}
    for t, src in uni.items():
        ratio, evs = bonus_events(t, today) if data[t].get("overview") else (0.0, [])
        entries[t] = build_entry(src, data[t], ratio, evs, now)
    got = sum(1 for e in entries.values() if "gap_m" in e)
    status = "ok" if got == len(uni) else ("partial" if got else "error")
    payload = {"schema": SCHEMA, "machine": socket.gethostname(),
               "run_at": now.isoformat(timespec="seconds"), "run_date": today.isoformat(),
               "status": status, "error": err if status != "ok" else None,
               "engine": {"model": info.get("model"), "cost_usd": info.get("cost_usd"),
                          "elapsed_s": round(float(info.get("elapsed_s") or 0), 1),
                          "calls": len(exchanges), "helpers": info.get("helpers"),
                          "strangers": info.get("strangers"), "denials": info.get("denials")},
               "server": os.environ.get(ENV_SERVER) or DEFAULT_SERVER,
               "tickers": entries}
    write_state(payload, meta)
    return payload


def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Connector MCP (TCBS) cho mã đang giữ + lệnh mở — chạy bóng")
    ap.add_argument("--show", action="store_true", help="in bản mới nhất, không gọi")
    ap.add_argument("--force", action="store_true", help="chạy dù hôm nay đã có bản ok")
    ap.add_argument("--dry-run", action="store_true", help="in prompt, không gọi")
    ap.add_argument("--tickers", nargs="+", help="mã cụ thể thay cho danh mục + lệnh mở")
    ap.add_argument("--json", action="store_true", help="in payload thô")
    a = ap.parse_args(argv)
    cc._ensure_env_loaded()
    if a.show:
        st = read_state()
        print("\n".join(summary_lines(st)))
        if a.json and st:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    res = run(tickers=a.tickers, force=a.force, dry_run=a.dry_run)
    if res.get("status") in ("disabled", "skipped"):
        print(f"[mcp-enrich] bỏ qua: {res.get('reason')}")
        return 0
    if res.get("status") == "dry-run":
        print(f"[mcp-enrich] {len(res['tickers'])} mã\n--- system ---\n{res['system']}\n"
              f"--- user ---\n{res['user']}")
        return 0
    print("\n".join(summary_lines(res)))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

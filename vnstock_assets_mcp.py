#!/usr/bin/env python3
"""vnstock_assets_mcp.py — nguồn MCP (Finhay + SSI) cho kho đa tài sản, P1 (U82).

Connector gắn TÀI KHOẢN Claude ⇒ chỉ đi qua `vnstock_claude_cli.complete_mcp` (bộ cờ gọn,
~16 tool/lượt); số đọc THẲNG `tool_result`, không qua chữ model. User 09/10: MCP chưa tốn
phí (gói thuê bao trừ hạn mức) ⇒ 3–4 lượt/ngày theo giờ VN (`vnstock_assets.mcp_due`).

Lượt ngày (cửa sổ 10 ngày, ghi đè dòng trùng): Finhay XAU · BZ · CL (nến ngày) · USDVND ·
10 sản phẩm vàng đại lý (SJC/PNJ/DOJI/BTMC/BTMH × miếng/nhẫn) + SSI tỷ giá VCB và SBVN.

SBVN = tỷ giá MUA/BÁN THAM KHẢO tại Cục Quản lý ngoại hối NHNN (đối chiếu báo chí 08/10:
24.407 – 26.869, đúng từng đồng) — KHÔNG phải tỷ giá trung tâm: (mua+bán)/2 khớp trung tâm
3/5 phiên 05–09/10, lệch 4–7 đ các phiên còn lại ⇒ chuỗi RIÊNG `USD_SBV_REF` (close = giá bán).
`backfill` dùng nó đo xem vnstock_data mbk ghi tỷ giá trung tâm đúng ngày hay lùi một phiên
(10/10: mbk ngày 08/10 = 25.629 = số NHNN công bố sáng 09/10; số 08/10 là 25.634).

Trần kết quả: Claude Code cắt kết quả MCP > ~25k token (SJC miếng 4 năm ~37k ⇒ 10/10 cả ba
khung 2015–18/2019–22/2023–nay về "kết quả rỗng") ⇒ backfill xin TỪNG NĂM; kết quả không đọc
được thì sổ lỗi ghi đoạn đầu text thật, không gộp chung thành "rỗng".

Đơn vị: Finhay đại lý = NGHÌN đồng/chỉ (14.480 ⇔ 144,8 tr/lượng) ⇒ kho lưu ĐỒNG/lượng
(× 10.000), giá chính `close` = giá BÁN (ask). Finhay forex có nến cuối tuần đứng giá ⇒ kho
bỏ (Spec.weekends). Tool tài khoản Finhay KHÔNG BAO GIỜ được mở.
"""
from __future__ import annotations

import contextlib
import json
import os
from datetime import date, datetime, timedelta

import vnstock_assets as va
import vnstock_assets_sources as src

ENV_FINHAY = "VNSTOCK_MCP_FINHAY_SERVER"
ENV_SSI = "VNSTOCK_MCP_SSI_SERVER"
DEFAULT_FINHAY = "claude.ai Finhay"            # tên server đo 08/10 trên 🖥️ (U78)
DEFAULT_SSI = "claude.ai SSI MCP"
T_COMMODITY = "get_commodity_history"
T_FOREX = "get_forex_history"
T_DEALER = "get_dealer_product_history"
T_SSI_FX = "marketdata_list_foreign_currency_converter"
DAILY_DAYS = 10
TIMEOUT_S = 420
MAX_TURNS = 16
DEALER_UNIT = 10_000                           # nghìn đồng/chỉ → đồng/lượng

# (khoá kho, tool, tham số gốc)
DAILY = (
    ("XAU", T_COMMODITY, {"symbol": "XAU"}),
    ("BRENT", T_COMMODITY, {"symbol": "BZ"}),
    ("WTI", T_COMMODITY, {"symbol": "CL"}),
    ("USDVND", T_FOREX, {"symbol": "USDVND"}),
) + tuple(
    (f"GOLD_{d}_{kind}", T_DEALER, {"symbol": "XAU", "code": f"GOLD_{kind}_{d}"})
    for d in va.DEALERS for kind in ("BAR", "RING")
)
SSI_BANKS = (("USDVND_VCB", "VCB"), ("USD_SBV_REF", "SBVN"))


def prefixes() -> "tuple[str, str]":
    import vnstock_claude_cli as cc
    return (cc.mcp_server_prefix(os.environ.get(ENV_FINHAY) or DEFAULT_FINHAY),
            cc.mcp_server_prefix(os.environ.get(ENV_SSI) or DEFAULT_SSI))


def vn_ts(d: date) -> int:
    """Unix giây lúc 00:00 giờ VN — đúng cách Finhay đánh dấu nến ngày."""
    return int(datetime(d.year, d.month, d.day, tzinfo=src.VN_TZ).timestamp())


def ts_date(t) -> "str | None":
    with contextlib.suppress(Exception):
        return datetime.fromtimestamp(int(float(t)), tz=src.VN_TZ).date().isoformat()
    return None


def finhay_call(key: str, tool: str, base: dict, prefix: str, start: date, end: date) -> dict:
    return {"key": key, "tool": prefix + tool, "input": {**base, "from": vn_ts(start), "to": vn_ts(end)}}


def plan_daily(today: date, fp: str, sp: str) -> list:
    start, end = today - timedelta(days=DAILY_DAYS), today + timedelta(days=1)
    plan = [finhay_call(k, t, b, fp, start, end) for k, t, b in DAILY]
    plan += [{"key": k, "tool": sp + T_SSI_FX, "input": {"bank": bank, "range": "1w"}}
             for k, bank in SSI_BANKS]
    return plan


def build_prompt(plan: list) -> "tuple[str, str]":
    """(system, user). System KHÔNG có |<>%\" hay xuống dòng (shim .cmd trên Windows)."""
    tools = sorted({p["tool"] for p in plan})
    system = ("Bạn là bộ thu thập dữ liệu, không phân tích. Gọi ĐÚNG từng lệnh gọi tool liệt kê "
              "trong tin nhắn, mỗi lệnh một lần, tham số giữ y nguyên. Gọi song song tối đa mười tool "
              "mỗi lượt. Được dùng ToolSearch để nạp tool trước. Không gọi tool nào khác. Gọi xong "
              "tất cả thì trả lời đúng một chữ: XONG.")
    lines = [f"Nếu tool chưa có sẵn: gọi ToolSearch với query select:{','.join(tools)}",
             f"Danh sách {len(plan)} lệnh gọi (tên tool rồi tham số JSON):"]
    lines += [f"{i}. {p['tool']} {json.dumps(p['input'], ensure_ascii=False)}"
              for i, p in enumerate(plan, 1)]
    return system, "\n".join(lines)


def _loads(text):
    with contextlib.suppress(Exception):
        return json.loads(text)
    i = str(text or "").find("{")
    with contextlib.suppress(Exception):
        return json.loads(str(text)[i:]) if i >= 0 else None
    return None


def parse_finhay(text, dealer: bool) -> list:
    """Kết quả lịch sử Finhay → dòng kho (nguồn 'finhay'). Đại lý: đồng/lượng, close = bán."""
    data = _loads(text)
    rows = []
    for b in (data or {}).get("series") or [] if isinstance(data, dict) else []:
        if not isinstance(b, dict):
            continue
        d = ts_date(b.get("t"))
        if not d:
            continue
        if dealer:
            bid, ask = src.num(b.get("bid")), src.num(b.get("ask"))
            if ask is None:
                continue
            rows.append({"date": d, "close": ask * DEALER_UNIT, "ask": ask * DEALER_UNIT,
                         "bid": bid * DEALER_UNIT if bid is not None else None, "source": "finhay"})
        else:
            c = src.num(b.get("c"))
            if c is not None:
                rows.append({"date": d, "close": c, "open": src.num(b.get("o")),
                             "high": src.num(b.get("h")), "low": src.num(b.get("l")),
                             "source": "finhay"})
    return rows


def parse_ssi(text, bank: str) -> list:
    data = _loads(text)
    rates = ((data or {}).get("data") or {}).get("rates") if isinstance(data, dict) else None
    rows = []
    for r in rates or []:
        if not isinstance(r, dict) or not str(r.get("currency_name") or "").upper().endswith("-USD"):
            continue
        d, buy, sell = src.iso(r.get("trading_date")), src.num(r.get("buy")), src.num(r.get("sell"))
        if not d or not sell:
            continue
        if bank == "SBVN":
            if buy:
                rows.append({"date": d, "close": sell, "bid": buy, "ask": sell, "source": "ssi"})
        else:
            rows.append({"date": d, "close": sell, "bid": src.num(r.get("transfer")), "ask": sell,
                         "source": "ssi", "meta": {"cash": buy}})
    return rows


def empty_reason(text) -> str:
    """Vì sao một kết quả không ra dòng nào: nguồn trả rỗng thật / nguồn báo lỗi / text không
    phải JSON (Claude Code cắt kết quả quá lớn, thông báo lỗi…) — kèm đoạn đầu text thật."""
    data = _loads(text)
    if isinstance(data, dict):
        err = data.get("error") or data.get("message")
        if err:
            return "nguồn báo lỗi: " + src.scrub(str(err))[:160]
        return "kết quả rỗng (nguồn không có số cho khung này)"
    head = src.scrub(" ".join(str(text or "").split()))[:200]
    return f"không đọc được kết quả ({len(str(text or '')):,} ký tự): {head}"


def rows_from_exchanges(plan: list, exchanges: list) -> "tuple[dict, dict]":
    """({khoá: [dòng]}, {khoá: lỗi}) — ghép lượt gọi thật với kế hoạch theo (tool, mã,
    from | toDate). Một khoá nhiều lượt (backfill theo năm/tháng): lượt nào ra dòng thì lấy;
    lượt hỏng vẫn ghi lỗi (lỗi đầu tiên của khoá) để một năm thiếu không lặng lẽ."""
    def ident(tool, inp):
        inp = inp if isinstance(inp, dict) else {}
        f = src.num(inp.get("from"))
        return (tool, str(inp.get("code") or inp.get("bank") or inp.get("symbol") or "").upper(),
                int(f) if f is not None else str(inp.get("toDate") or ""))
    got = {}
    for e in exchanges or []:
        got.setdefault(ident(e.get("name"), e.get("input")), e)
    rows, errors = {}, {}
    for p in plan:
        e = got.get(ident(p["tool"], p["input"]))
        k = p["key"]
        if not e or e.get("text") is None:
            errors[k] = "model không gọi tool này"
            continue
        if e.get("is_error"):
            errors[k] = src.scrub(e["text"])[:120]
            continue
        if p["tool"].endswith(T_SSI_FX):
            r = parse_ssi(e["text"], p["input"]["bank"])
        else:
            r = parse_finhay(e["text"], dealer=p["tool"].endswith(T_DEALER))
        if r:
            rows.setdefault(k, []).extend(r)
        else:
            errors.setdefault(k, empty_reason(e["text"]))
    return rows, errors


def _collect(plan: list, timeout_s: int, tag: str, collect=None):
    system, user = build_prompt(plan)
    allowed = sorted({p["tool"] for p in plan})
    if collect is None:
        import vnstock_claude_cli as cc

        def collect(u, s, a):
            return cc.complete_mcp(u, system=s, allowed_tools=a, timeout_s=timeout_s,
                                   max_turns=MAX_TURNS, tag=tag)
    return collect(user, system, allowed)


def _write_all(rows: dict, now: datetime) -> "tuple[int, list]":
    fetched_at = now.isoformat(timespec="seconds")
    n, flags = 0, []
    for key, krows in rows.items():
        flags += va.write(key, krows, today=now.date(), fetched_at=fetched_at)
        n += len(krows)
    return n, flags


def _last_run_age_h(now: datetime) -> "float | None":
    last = (va.read_status().get("mcp") or {}).get("run_at")
    with contextlib.suppress(Exception):
        return (now - datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
    return None


def refresh(now: "datetime | None" = None, *, force: bool = False, stale_h: "float | None" = None,
            collect=None, timeout_s: int = TIMEOUT_S) -> dict:
    """Một lượt MCP ngày. `force` ⇒ chạy luôn (tay); `stale_h` ⇒ chạy khi lượt trước cũ hơn
    `stale_h` giờ (pipeline đêm — lưới khi máy tắt đúng giờ đặt); mặc định ⇒ theo giờ
    `VNSTOCK_ASSETS_MCP_HOURS` (task mỗi giờ). Gọi `claude -p` KHÔNG giữ khoá (chờ ~1 phút);
    chỉ khoá lúc ghi."""
    now = now or datetime.now()
    if not va.enabled() or not va.enabled(va.ENV_MCP):
        return {"status": "disabled"}
    if not force:
        if stale_h is not None:
            age = _last_run_age_h(now)
            if age is not None and age < stale_h:
                return {"status": "skipped", "reason": f"lượt MCP trước mới {age:.1f} giờ"}
        elif not va.mcp_due(now, va.read_status()):
            return {"status": "skipped", "reason": "chưa tới giờ đặt / vừa chạy"}
    fp, sp = prefixes()
    plan = plan_daily(now.date(), fp, sp)
    exchanges, err, info = _collect(plan, timeout_s, "assets_mcp", collect)
    info = info or {}
    if info.get("no_exe"):
        return {"status": "skipped", "reason": "máy này không có Claude Code CLI"}
    rows, errors = rows_from_exchanges(plan, exchanges)
    with va.machine_lock() as got:
        if not got:
            payload = {"run_at": now.isoformat(timespec="seconds"), "status": "busy",
                       "error": "kho đang bị tiến trình khác ghi — bỏ lượt này"}
            return payload
        n, flags = _write_all(rows, now)
        keys = sorted({p["key"] for p in plan})
        ok = [k for k in keys if k in rows]
        status = "ok" if len(ok) == len(keys) else ("partial" if ok else "error")
        payload = {"run_at": now.isoformat(timespec="seconds"), "status": status, "rows": n,
                   "keys_ok": len(ok), "keys": len(keys), "errors": errors,
                   "error": err if status != "ok" else None, "model": info.get("model"),
                   "cost_usd": info.get("cost_usd"), "elapsed_s": info.get("elapsed_s")}
        va.update_status("mcp", payload, flags, now=now)
    return {**payload, "flags": flags}


# ── Backfill: lượt nhỏ để mỗi phiên claude -p không quá tải ngữ cảnh ─────────
# Trần một kết quả MCP của Claude Code ~25k token (vượt ⇒ cắt, text không còn là JSON). Đo
# 10/10: Finhay đại lý ~15 token/ngày (SJC miếng 4 năm ~37k ⇒ hỏng; đại lý 21 tháng ~16k ⇒
# được); SSI SBVN 1 tháng = 7 ngoại tệ × ~22 phiên = 154 dòng ~7k (3 tháng ⇒ hỏng).
BACKFILL_FROM = date(2025, 1, 1)
SJC_BAR_FROM_YEAR = 2015
YEARS_PER_SESSION = 2                  # 2 lượt gọi × ≤1 năm ⇒ ≤~12k token/lượt kết quả
SBVN_MONTHS = 3                        # 3 lượt range=1m, toDate lùi 30 ngày


def _ssi_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def plan_backfill(today: date, fp: str, sp: str) -> "list[tuple[str, list]]":
    """[(nhãn, kế hoạch)] — mỗi phiên ≤2 lượt gọi, mỗi lượt ≤~12k token kết quả."""
    end = today + timedelta(days=1)
    by_key = {k: (t, b) for k, t, b in DAILY}
    sessions = [("XAU", [finhay_call("XAU", *by_key["XAU"], fp, BACKFILL_FROM, end)]),
                ("BZ+CL", [finhay_call(k, *by_key[k], fp, BACKFILL_FROM, end) for k in ("BRENT", "WTI")]),
                ("USDVND", [finhay_call("USDVND", *by_key["USDVND"], fp, BACKFILL_FROM, end)])]
    years = list(range(SJC_BAR_FROM_YEAR, today.year + 1))
    for i in range(0, len(years), YEARS_PER_SESSION):
        chunk = years[i:i + YEARS_PER_SESSION]
        sessions.append((f"SJC miếng {chunk[0]}" + (f"–{chunk[-1]}" if len(chunk) > 1 else ""),
                         [finhay_call("GOLD_SJC_BAR", *by_key["GOLD_SJC_BAR"], fp, date(y, 1, 1),
                                      min(date(y + 1, 1, 1), end)) for y in chunk]))
    rest = [k for k, _, _ in DAILY if k.startswith("GOLD_") and k != "GOLD_SJC_BAR"]
    for i in range(0, len(rest), 2):
        pair = rest[i:i + 2]
        sessions.append((" + ".join(pair), [finhay_call(k, *by_key[k], fp, BACKFILL_FROM, end) for k in pair]))
    sessions.append((f"SSI SBVN {SBVN_MONTHS} tháng",
                     [{"key": "USD_SBV_REF", "tool": sp + T_SSI_FX,
                       "input": {"bank": "SBVN", "range": "1m",
                                 "toDate": _ssi_date(today - timedelta(days=30 * m))}}
                      for m in range(SBVN_MONTHS)]))
    return sessions


CENTRAL_SHIFTS = (-1, 0, 1)


def verify_central(sbvn_rows: list, mbk: "dict[str, float]") -> dict:
    """mbk ghi tỷ giá trung tâm ĐÚNG ngày hay lệch phiên? Thước đo: (mua+bán)/2 tham khảo Cục
    QLNH (SSI SBVN) — ≈ trung tâm CÙNG ngày, lệch 0–7 đ (báo chí 05–09/10: khớp 3/5 phiên).
    shift s: so giữa SBVN phiên D[i] với mbk phiên D[i−s] (lịch phiên SBVN); s=+1 ⇔ mbk ghi số
    của phiên D vào phiên TRƯỚC. Phiên khớp = lệch ≤1 đ; shift thắng = nhiều phiên khớp nhất."""
    mids = {r["date"]: (r["bid"] + r["ask"]) / 2 for r in sbvn_rows
            if src.num(r.get("bid")) and src.num(r.get("ask"))}
    days = sorted(mids)
    tail = {d: mbk[d] for d in sorted(mbk)[-6:]}
    stats = {}
    for s in CENTRAL_SHIFTS:
        diffs = sorted(abs(mids[d] - mbk[days[i - s]]) for i, d in enumerate(days)
                       if 0 <= i - s < len(days) and days[i - s] in mbk)
        if diffs:
            stats[s] = {"n": len(diffs), "exact": sum(1 for x in diffs if x <= 1.0),
                        "median_diff": round(diffs[len(diffs) // 2], 1)}
    if not stats:
        return {"n": 0, "verdict": "không có phiên chung với mbk — chưa kiểm được",
                "sbvn_days": len(days), "mbk_tail": tail}
    best = max(stats, key=lambda s: (stats[s]["exact"], -stats[s]["median_diff"], -abs(s)))
    b = stats[best]
    if b["n"] < 5 or b["exact"] < 3:
        verdict = "chưa rõ (ít phiên chung / ít phiên khớp)"
    elif best == 0:
        verdict = "mbk ĐÚNG ngày"
    else:
        verdict = f"mbk ghi {'LÙI' if best > 0 else 'TIẾN'} {abs(best)} phiên"
    return {"n": b["n"], "best_shift": best, "verdict": verdict,
            "by_shift": {str(s): v for s, v in stats.items()}, "mbk_tail": tail}


def backfill(now: "datetime | None" = None, *, collect=None, log=print,
             timeout_s: int = TIMEOUT_S, only: "set[str] | None" = None) -> dict:
    """Lịch sử MCP theo phiên nhỏ. `only` = tập khoá kho (vd {"GOLD_SJC_BAR", "USD_SBV_REF"}) ⇒
    chỉ chạy phiên có khoá đó (chạy lại phần hỏng mà không gọi lại cả bộ)."""
    now = now or datetime.now()
    fp, sp = prefixes()
    df = va.load("USD_CENTRAL")                # backfill Python đã nạp mbk trước bước này
    mbk = {str(d): float(c) for d, c, s in zip(df["date"], df["close"], df["source"]) if s == "mbk"}
    report: dict = {}
    for label, plan in plan_backfill(now.date(), fp, sp):
        if only and not {p["key"] for p in plan} & only:
            continue
        log(f"… MCP {label}")
        exchanges, err, info = _collect(plan, timeout_s, "assets_mcp_backfill", collect)
        if (info or {}).get("no_exe"):
            report["_"] = {"ok": False, "error": err}
            log(f"  ❌ không có Claude Code CLI: {err}")
            break
        rows, errors = rows_from_exchanges(plan, exchanges)
        if label.startswith("SSI SBVN"):
            report["central_verify"] = verify_central(rows.get("USD_SBV_REF", []), mbk)
            log(f"  đo lệch ngày mbk (tỷ giá trung tâm) vs SBVN: {report['central_verify']}")
        with va.machine_lock() as got:
            if not got:
                report[label] = {"ok": False, "error": "kho đang bị ghi"}
                continue
            n, _ = _write_all(rows, now)
        report[label] = {"ok": bool(rows) and not errors, "rows": n, "errors": errors,
                         "cost_usd": (info or {}).get("cost_usd")}
        log(f"  {'✅' if report[label]['ok'] else '⚠'} {label}: {n} dòng"
            + (f" · lỗi {errors}" if errors else ""))
    if "central_verify" in report:
        va.update_status("central_verify", {**report["central_verify"],
                                            "run_at": now.isoformat(timespec="seconds")}, now=now)
    return report

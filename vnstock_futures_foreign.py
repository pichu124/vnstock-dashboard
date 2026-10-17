#!/usr/bin/env python3
"""vnstock_futures_foreign.py — vị thế ròng khối ngoại trên HĐTL chỉ số VN30 (U88, 15/10).

Nguồn DUY NHẤT: SSI MCP `marketdata_list_daily_stock_infor` (trường foreign_buy/sell_volume_total
từng hợp đồng, từng phiên). Connector gắn TÀI KHOẢN Claude ⇒ chỉ đi qua
`vnstock_claude_cli.complete_mcp`; số đọc THẲNG `tool_result`, không qua chữ model.

- Lịch sử: file seed trong repo (`data/seed/futures_foreign_ssi.csv.gz`, dựng 15/10/2026 trong
  phiên cloud từ CHÍNH nguồn đó: 28 hợp đồng VN30F2410 → VN30F2703, mỗi hợp đồng từ phiên niêm
  yết). Kho trống ⇒ tự nạp seed, không tốn lượt MCP.
- Hằng ngày: bước pipeline `futures-foreign` (sau assets, TRƯỚC brief) gọi MCP lấy các phiên gần
  nhất của mọi hợp đồng có thể đang lưu hành; kho đã có phiên phủ ⇒ no-op.

Mã ở SSI: hợp đồng niêm yết TRƯỚC khi chuyển hệ KRX (~05/05/2025) mang tên cũ `VN30FYYMM` (kể cả
sau ngày chuyển); hợp đồng niêm yết sau đó mang mã KRX `41I1` + năm + tháng + `000`. Từ 03/2026
mọi hợp đồng còn lưu hành đều là mã KRX ⇒ lượt ngày chỉ gọi mã KRX. Dòng trả về mới nhất TRƯỚC,
mã KRX hay có HAI dòng mỗi ngày (bản thứ hai các trường giá điều chỉnh = 0) ⇒ khử trùng theo ngày.

Kho: `data_warehouse/futures/foreign_contracts.parquet` (một file nhỏ, mọi hợp đồng — nằm trong
Dropbox như mọi thứ dưới kho). Đọc gộp cả bản '(conflicted copy)', khử trùng giữ bản lấy mới nhất.
Số tính (vị thế, chuỗi, cực trị, dòng brief) ở `vnstock_futures_foreign_view` (thuần, có test).
Kill-switch: `VNSTOCK_FUTURES_FOREIGN=0` (bước pipeline + MCP).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import socket
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent
FUT_DIR = _REPO / "data_warehouse" / "futures"
META_DIR = _REPO / "data_warehouse" / "_meta"
STORE_STEM = "foreign_contracts"
STATUS_NAME = "futures_foreign_status.json"
SEED_PATH = _REPO / "data" / "seed" / "futures_foreign_ssi.csv.gz"
SEED_FETCHED_AT = "2026-10-15T17:10:00"
SCHEMA = 1

ENV_SWITCH = "VNSTOCK_FUTURES_FOREIGN"
_OFF = ("0", "false", "off", "no")

T_DAILY = "marketdata_list_daily_stock_infor"
MULTIPLIER = 100_000                 # đồng / 1 điểm chỉ số / 1 hợp đồng
PAGE_MIN, PAGE_MAX = 10, 60          # dòng/lượt gọi — 60 dòng ≈ 52 KB ≈ 16k token < trần ~25k của Claude Code
CALLS_PER_SESSION = 6                # lượt gọi tool / một phiên `claude -p`
LOOKBACK_DAYS = 7                    # luôn lấy lại ≥1 tuần — nguồn sửa số muộn thì kho theo
TIMEOUT_S = 420
MAX_TURNS = 12
# range của tool (ngày lịch tính lùi từ toDate) — "1d" chỉ trả 2 ngày nên không dùng.
_RANGES = (("3m", 90), ("6m", 180), ("1y", 365), ("max_range", 730))
COLUMNS = ["date", "contract", "symbol", "buy", "sell", "close", "volume", "ff", "source", "fetched_at"]
_NUM = ("buy", "sell", "close", "volume")


def enabled() -> bool:
    return (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in _OFF


# ── Hợp đồng ─────────────────────────────────────────────────────────────────
def contract_name(y: int, m: int) -> str:
    return f"VN30F{y % 100:02d}{m:02d}"


def contract_ym(name: str) -> "tuple[int, int]":
    s = str(name)
    return 2000 + int(s[5:7]), int(s[7:9])


_KRX_MONTHS = "123456789ABC"
_KRX_RE = re.compile(r"^41I1([A-Z])([1-9ABC])000$")
_OLD_RE = re.compile(r"^VN30F(\d{2})(\d{2})$")


def krx_symbol(y: int, m: int) -> str:
    """Mã KRX ở SSI: 41I1 + năm + tháng + 000. Năm một chữ từ A=2020 — đo được 2024=E … 2027=H
    (15/10/2026); năm ≥2028 CHƯA đo, badge doctor réo nếu tổng thiếu hợp đồng."""
    return f"41I1{chr(ord('A') + y - 2020)}{_KRX_MONTHS[m - 1]}000"


def symbol_contract(sym) -> "str | None":
    """Mã SSI (tên cũ hoặc KRX) → tên hợp đồng VN30FYYMM; None khi không phải HĐTL VN30."""
    s = str(sym or "").strip().upper()
    m = _OLD_RE.match(s)
    if m:
        return s
    m = _KRX_RE.match(s)
    if m:
        return contract_name(2020 + ord(m.group(1)) - ord("A"), _KRX_MONTHS.index(m.group(2)) + 1)
    return None


def third_thursday(y: int, m: int) -> date:
    """Ngày đáo hạn theo luật: thứ Năm tuần thứ ba của tháng đáo hạn (trùng nghỉ lễ ⇒ phiên liền
    trước — Tết 2026: VN30F2602 đáo hạn 13/02 thay 19/02)."""
    d = date(y, m, 1)
    return d + timedelta(days=(3 - d.weekday()) % 7 + 14)


def _add_months(y: int, m: int, k: int) -> "tuple[int, int]":
    i = y * 12 + (m - 1) + k
    return i // 12, i % 12 + 1


def candidates(today: date, since: date) -> "list[str]":
    """Hợp đồng có thể có phiên trong [since, today]: 3 tháng liền kề + tháng quý trong 8 tháng tới
    (VN30F luôn có 2 tháng gần + 2 quý gần), cộng tháng đã qua nếu đáo hạn sau `since` (kho hở)."""
    out = []
    for k in range(-3, 9):
        y, m = _add_months(today.year, today.month, k)
        if k > 2 and m % 3:
            continue
        if third_thursday(y, m) < since:
            continue
        out.append(contract_name(y, m))
    return out


# ── Kho Parquet ──────────────────────────────────────────────────────────────
def _empty():
    import pandas as pd
    return pd.DataFrame(columns=COLUMNS)


def store_files(base: "Path | None" = None) -> "list[Path]":
    d = Path(base or FUT_DIR)
    return sorted(d.glob(f"{STORE_STEM}*.parquet"), key=lambda p: p.stat().st_mtime) if d.exists() else []


def conflicted_files(base: "Path | None" = None) -> "list[str]":
    return [p.name for p in store_files(base) if "conflicted" in p.name.lower()]


def _normalize(df):
    import pandas as pd
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    for c in _NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    for c in ("contract", "symbol", "ff", "source", "fetched_at"):
        df[c] = df[c].fillna("").astype(str)
    return df[COLUMNS]


def load(base: "Path | None" = None):
    """Mọi dòng (ngày, hợp đồng) — gộp bản chính + bản Dropbox '(conflicted copy)', giữ bản lấy
    MỚI nhất. Sắp theo (ngày, hợp đồng); rỗng khi chưa có."""
    import pandas as pd
    frames = []
    for pf in store_files(base):
        try:
            frames.append(pd.read_parquet(pf))
        except Exception as e:                                     # noqa: BLE001
            print(f"  [futures-foreign] ⚠ {pf.name} không đọc được ({type(e).__name__}) — bỏ qua")
    if not frames:
        return _empty()
    df = _normalize(pd.concat(frames, ignore_index=True))
    df = df.sort_values("fetched_at", kind="stable").drop_duplicates(["date", "contract"], keep="last")
    return df.sort_values(["date", "contract"]).reset_index(drop=True)


def merge(existing, rows: "list[dict]", *, source: str, fetched_at: str):
    """Ghép dòng mới vào kho: cùng (ngày, hợp đồng) thì bản MỚI thắng — trừ khi bản mới MẤT trường
    khối ngoại mà bản cũ có (nguồn trả trống tạm thời không được xoá số đã có)."""
    import pandas as pd
    keep = {(r["date"], r["contract"]): r for r in existing.to_dict("records")} if len(existing) else {}
    for r in rows:
        k = (r["date"], r["contract"])
        old = keep.get(k)
        if old is not None and old.get("ff") == "ok" and r.get("ff") != "ok":
            continue
        keep[k] = {**r, "source": source, "fetched_at": fetched_at}
    if not keep:
        return _empty()
    df = _normalize(pd.DataFrame(list(keep.values())))
    return df.sort_values(["date", "contract"]).reset_index(drop=True)


def save(df, base: "Path | None" = None) -> Path:
    import pyarrow as pa
    from vnstock_parquet_io import write_table_atomic
    out = Path(base or FUT_DIR) / f"{STORE_STEM}.parquet"
    write_table_atomic(pa.Table.from_pandas(_normalize(df.copy()), preserve_index=False), out)
    return out


# ── Seed lịch sử ─────────────────────────────────────────────────────────────
def read_seed(path: "Path | None" = None) -> "list[dict]":
    import pandas as pd
    p = Path(path or SEED_PATH)
    if not p.exists():
        return []
    df = pd.read_csv(p, dtype={"date": str, "contract": str, "symbol": str, "ff": str})
    rows = []
    for r in df.to_dict("records"):
        rows.append({"date": r["date"], "contract": r["contract"], "symbol": r["symbol"],
                     **{c: (None if pd.isna(r.get(c)) else r.get(c)) for c in _NUM},
                     "ff": r.get("ff") or ff_flag(r.get("buy"), r.get("sell"))})
    return rows


def seed(base: "Path | None" = None, *, path: "Path | None" = None, force: bool = False) -> dict:
    """Nạp lịch sử từ file seed. Kho đã có số ⇒ chỉ thêm dòng còn thiếu (không ghi đè số lấy sau),
    `force` ⇒ seed thắng mọi dòng trùng (bản lấy sau vẫn giữ trường khối ngoại nếu seed thiếu)."""
    rows = read_seed(path)
    if not rows:
        return {"status": "error", "error": f"không có file seed {Path(path or SEED_PATH).name}"}
    cur = load(base)
    have = set(zip(cur["date"], cur["contract"])) if len(cur) else set()
    add = rows if force else [r for r in rows if (r["date"], r["contract"]) not in have]
    if not add:
        return {"status": "ok", "rows": 0, "note": "kho đã đủ các dòng của seed"}
    df = merge(cur, add, source="ssi-seed", fetched_at=SEED_FETCHED_AT)
    save(df, base)
    return {"status": "ok", "rows": len(add), "contracts": len({r["contract"] for r in add}),
            "last_date": max(r["date"] for r in add)}


# ── MCP SSI ──────────────────────────────────────────────────────────────────
def ssi_prefix() -> str:
    import vnstock_claude_cli as cc
    from vnstock_assets_mcp import DEFAULT_SSI, ENV_SSI
    return cc.mcp_server_prefix(os.environ.get(ENV_SSI) or DEFAULT_SSI)


def _weekdays_between(a: date, b: date) -> int:
    return sum(1 for i in range(1, (b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5)


def plan_refresh(today: date, last_date: "date | None", prefix: str) -> "list[dict]":
    """Lượt gọi cho mọi hợp đồng ứng viên, đủ dòng để phủ từ `since` tới hôm nay.

    since = min(phiên cuối trong kho, hôm nay − 7 ngày). Mỗi phiên tính 2 dòng (mã KRX trả trùng)
    + 2 dòng đệm; quá `PAGE_MAX` thì chia trang (dòng mới nhất ở trang 1)."""
    since = min(last_date or today, today - timedelta(days=LOOKBACK_DAYS))
    need = 2 * (_weekdays_between(since, today) + 1) + 2
    size = max(PAGE_MIN, min(PAGE_MAX, need))
    pages = math.ceil(need / size)
    span = (today - since).days + 3
    rng = next((r for r, d in _RANGES if d >= span), _RANGES[-1][0])
    plan = []
    for c in candidates(today, since):
        y, m = contract_ym(c)
        sym = krx_symbol(y, m)
        for i in range(1, pages + 1):
            plan.append({"contract": c, "tool": prefix + T_DAILY,
                         "input": {"symbol": sym, "range": rng, "pageSize": size, "pageIndex": i}})
    return plan


def build_prompt(plan: "list[dict]") -> "tuple[str, str]":
    """(system, user). System KHÔNG có |<>%\" hay xuống dòng (shim .cmd trên Windows)."""
    tools = sorted({p["tool"] for p in plan})
    system = ("Bạn là bộ thu thập dữ liệu, không phân tích. Gọi ĐÚNG từng lệnh gọi tool liệt kê "
              "trong tin nhắn, mỗi lệnh một lần, tham số giữ y nguyên. Gọi song song tối đa sáu tool "
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
    s = str(text or "")
    i = s.find("{")
    with contextlib.suppress(Exception):
        return json.loads(s[i:]) if i >= 0 else None
    return None


def _int(v) -> "int | None":
    if v is None or str(v).strip() == "":
        return None
    with contextlib.suppress(Exception):
        return int(float(v))
    return None


def _float(v) -> "float | None":
    if v is None or str(v).strip() == "":
        return None
    with contextlib.suppress(Exception):
        return float(v)
    return None


def _iso(dmy) -> "str | None":
    with contextlib.suppress(Exception):
        return datetime.strptime(str(dmy).strip(), "%d/%m/%Y").date().isoformat()
    return None


def ff_flag(buy, sell) -> str:
    """ok = đủ hai vế khối ngoại · partial = thiếu một vế · none = nguồn không có trường nào."""
    has_b = buy is not None and not (isinstance(buy, float) and math.isnan(buy))
    has_s = sell is not None and not (isinstance(sell, float) and math.isnan(sell))
    return "ok" if has_b and has_s else ("partial" if has_b or has_s else "none")


def parse_rows(text, symbol: str) -> "tuple[list[dict], str | None]":
    """Kết quả tool → ([dòng kho], lỗi). Rỗng không lỗi = hợp đồng chưa niêm yết / ngoài khung.
    Ngày trùng (mã KRX trả hai bản) giữ bản đầu; dòng mang mã khác bị bỏ."""
    data = _loads(text)
    if not isinstance(data, dict):
        head = " ".join(str(text or "").split())[:160]
        return [], f"không đọc được kết quả ({len(str(text or '')):,} ký tự): {head}"
    if str(data.get("status") or "ok").lower() != "ok" or data.get("error"):
        return [], f"nguồn báo lỗi: {str(data.get('error') or data.get('message') or data.get('status'))[:160]}"
    stocks = (data.get("data") or {}).get("stocks") if isinstance(data.get("data"), dict) else None
    contract = symbol_contract(symbol)
    rows, seen = [], set()
    for r in stocks or []:
        if not isinstance(r, dict) or str(r.get("symbol") or "").upper() != symbol.upper():
            continue
        d = _iso(r.get("trading_date"))
        if not d or d in seen:
            continue
        seen.add(d)
        buy, sell = _int(r.get("foreign_buy_volume_total")), _int(r.get("foreign_sell_volume_total"))
        rows.append({"date": d, "contract": contract, "symbol": symbol.upper(), "buy": buy,
                     "sell": sell, "close": _float(r.get("close")), "volume": _int(r.get("volume")),
                     "ff": ff_flag(buy, sell)})
    return rows, None


def rows_from_exchanges(plan: "list[dict]", exchanges: "list[dict]") -> "tuple[list, dict]":
    """Ghép lượt gọi thật với kế hoạch theo (mã, trang). ([dòng], {hợp đồng: lỗi})."""
    def ident(inp) -> tuple:
        inp = inp if isinstance(inp, dict) else {}
        return str(inp.get("symbol") or "").upper(), int(inp.get("pageIndex") or 1)
    got = {}
    for e in exchanges or []:
        if str(e.get("name") or "").endswith(T_DAILY):
            got.setdefault(ident(e.get("input")), e)
    rows, errors = [], {}
    for p in plan:
        e = got.get(ident(p["input"]))
        c = p["contract"]
        if not e or e.get("text") is None:
            errors.setdefault(c, "model không gọi tool này")
            continue
        if e.get("is_error"):
            errors.setdefault(c, " ".join(str(e["text"]).split())[:160])
            continue
        r, err = parse_rows(e["text"], p["input"]["symbol"])
        if err:
            errors.setdefault(c, err)
        rows.extend(r)
    return rows, errors


def _collect(plan: "list[dict]", timeout_s: int, collect=None) -> "tuple[list, str | None, dict]":
    """Gọi theo lô ≤ CALLS_PER_SESSION lượt / phiên `claude -p` — mỗi kết quả vào ngữ cảnh model."""
    if collect is None:
        import vnstock_claude_cli as cc

        def collect(u, s, a):
            return cc.complete_mcp(u, system=s, allowed_tools=a, timeout_s=timeout_s,
                                   max_turns=MAX_TURNS, tag="futures_foreign")
    exchanges, errs, info = [], [], {"cost_usd": 0.0, "elapsed_s": 0.0}
    for i in range(0, len(plan), CALLS_PER_SESSION):
        chunk = plan[i:i + CALLS_PER_SESSION]
        system, user = build_prompt(chunk)
        ex, err, inf = collect(user, system, sorted({p["tool"] for p in chunk}))
        inf = inf or {}
        if inf.get("no_exe"):
            return [], err, {**info, "no_exe": True}
        exchanges += ex or []
        if err:
            errs.append(err)
        info["cost_usd"] += float(inf.get("cost_usd") or 0)
        info["elapsed_s"] += float(inf.get("elapsed_s") or 0)
        info["model"] = inf.get("model") or info.get("model")
    return exchanges, ("; ".join(errs) or None), info


# ── Trạng thái ───────────────────────────────────────────────────────────────
def status_path(meta: "Path | None" = None) -> Path:
    return Path(meta or META_DIR) / STATUS_NAME


def read_status(meta: "Path | None" = None) -> dict:
    try:
        return json.loads(status_path(meta).read_text(encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return {}


def write_status(payload: dict, meta: "Path | None" = None) -> dict:
    from vnstock_parquet_io import write_json_atomic
    st = {"schema": SCHEMA, "machine": os.environ.get("COMPUTERNAME") or socket.gethostname(), **payload}
    write_json_atomic(st, status_path(meta))
    return st


def expected_session(now: datetime, warehouse: "Path | None" = None) -> date:
    """Phiên mà lượt chạy lúc `now` PHẢI có: bar VNINDEX mới nhất trong kho ≤ phiên phủ
    (`session_covered_at`) — biết cả ngày lễ; kho VNINDEX không đọc được ⇒ chính phiên phủ."""
    from vnstock_rollup import session_covered_at
    covered = session_covered_at(now)
    with contextlib.suppress(Exception):
        import vnstock_horizons_state as hs
        dates, _ = hs.load_vnindex(Path(warehouse) if warehouse else hs._WAREHOUSE)
        best = max((d for d in dates if d <= covered), default=None)
        if best:
            return best
    return covered


def refresh(now: "datetime | None" = None, *, force: bool = False, collect=None,
            base: "Path | None" = None, meta: "Path | None" = None,
            expect: "date | None" = None, timeout_s: int = TIMEOUT_S) -> dict:
    """Một lượt: kho trống ⇒ nạp seed; đã có phiên `expect` ⇒ no-op (trừ `force`); còn lại gọi MCP
    rồi ghép vào kho. Gọi `claude -p` KHÔNG giữ khoá; chỉ khoá lúc ghi. Không bao giờ ném."""
    now = now or datetime.now()
    if not enabled():
        return {"status": "disabled"}
    seeded = None
    if not len(load(base)):
        seeded = seed(base)
    df = load(base)
    last = date.fromisoformat(str(df["date"].max())) if len(df) else None
    expect = expect or expected_session(now)
    if not force and last and last >= expect:
        return {"status": "skipped", "reason": f"kho đã có phiên {last.isoformat()}", "seeded": seeded}
    plan = plan_refresh(now.date(), last, ssi_prefix())
    exchanges, err, info = _collect(plan, timeout_s, collect)
    if info.get("no_exe"):
        return {"status": "skipped", "reason": "máy này không có Claude Code CLI", "seeded": seeded}
    rows, errors = rows_from_exchanges(plan, exchanges)
    import vnstock_assets as va
    with va.machine_lock("vnstock_futures_foreign.lock") as got:
        if not got:
            return {"status": "busy", "error": "kho đang bị tiến trình khác ghi — bỏ lượt này"}
        fetched_at = now.isoformat(timespec="seconds")
        merged = merge(load(base), rows, source="ssi-mcp", fetched_at=fetched_at)
        if rows:
            save(merged, base)
        new_last = str(merged["date"].max()) if len(merged) else None
        ok = bool(rows) and new_last is not None and new_last >= expect.isoformat()
        status = "ok" if ok and not errors else ("partial" if rows else "error")
        payload = {"run_at": fetched_at, "status": status, "rows": len(rows),
                   "contracts": sorted({r["contract"] for r in rows}), "errors": errors,
                   "error": err if status != "ok" else None, "expect": expect.isoformat(),
                   "last_date": new_last, "calls": len(plan), "model": info.get("model"),
                   "cost_usd": round(info.get("cost_usd") or 0, 4),
                   "elapsed_s": round(info.get("elapsed_s") or 0, 1), "seeded": seeded}
        write_status(payload, meta)
    return payload


# ── CLI ──────────────────────────────────────────────────────────────────────
def show(base: "Path | None" = None, meta: "Path | None" = None) -> str:
    import vnstock_futures_foreign_view as fv
    df = load(base)
    st = read_status(meta)
    out = [f"Kho: {len(df):,} dòng · {df['contract'].nunique() if len(df) else 0} hợp đồng · "
           f"{df['date'].min() if len(df) else '—'} → {df['date'].max() if len(df) else '—'}",
           f"Lượt cuối: {st.get('run_at') or '—'} · {st.get('status') or '—'} · máy {st.get('machine') or '—'}"
           + (f" · lỗi {st['errors']}" if st.get("errors") else "")]
    if conflicted_files(base):
        out.append(f"⚠ conflicted copy: {', '.join(conflicted_files(base))}")
    s = fv.summary(df)
    if s:
        out += ["", fv.SECTION_TITLE] + fv.brief_lines(s)
    return "\n".join(out)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Vị thế ròng khối ngoại trên HĐTL VN30 (SSI MCP)")
    ap.add_argument("--refresh", action="store_true", help="lượt MCP (kho trống ⇒ nạp seed trước)")
    ap.add_argument("--force", action="store_true", help="gọi MCP dù kho đã có phiên phủ")
    ap.add_argument("--seed", action="store_true", help="nạp lịch sử từ file seed (không tốn MCP)")
    ap.add_argument("--dry-run", action="store_true", help="in kế hoạch gọi MCP, không gọi")
    ap.add_argument("--show", action="store_true", help="in trạng thái + các dòng brief")
    a = ap.parse_args(argv)
    if a.seed:
        print(json.dumps(seed(force=a.force), ensure_ascii=False))
        return 0
    if a.dry_run:
        df = load()
        last = date.fromisoformat(str(df["date"].max())) if len(df) else None
        plan = plan_refresh(date.today(), last, ssi_prefix())
        print(build_prompt(plan)[1])
        return 0
    if a.refresh or a.force:
        res = refresh(force=a.force)
        print(f"[futures-foreign] {json.dumps(res, ensure_ascii=False, default=str)}")
        return 0 if res.get("status") in ("ok", "skipped", "disabled") else 1
    print(show())
    return 0


if __name__ == "__main__":
    sys.exit(main())

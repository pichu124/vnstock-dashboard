#!/usr/bin/env python3
"""vnstock_doctor.py — khám sức khỏe TOÀN BỘ nguồn dữ liệu nuôi brief/dashboard.

Trước đây mỗi nguồn có ``--diag`` riêng rải rác (news_feeds / macro / vbma / nso /
foreign_flow / events / fundamentals) — phải nhớ chạy từng cái. Module này gom về
MỘT lệnh theo mô hình "doctor" của Agent-Reach: mỗi nguồn tự check (kiểm tra
THẬT chứ không chỉ "file tồn tại") và trả về trạng thái + ĐƠN THUỐC sửa cụ thể.

    python run.py doctor            # nhanh, OFFLINE — tuổi cache + key cấu hình
    python run.py doctor --net      # thêm probe MẠNG (RSS/FX/VBMA/NSO/API/Jina)
    python vnstock_doctor.py [...]  # chạy trực tiếp, thêm --json / --no-save

Hai tầng check:
  • OFFLINE (mặc định, <1s): đọc cache/_meta — tuổi data so với NGÀY GIAO DỊCH
    trước đó (không báo động giả sáng thứ 2 / trước pipeline 18:00), key .env.
    Trạng thái: ok ✅ · warn ⚠️ (cũ/thiếu một phần) · off ⬜ (chưa cấu hình/chưa
    chạy) · error ❌ (hỏng, cần sửa).
  • NET (--net): fetch thử từng nguồn ngoài — đúng việc các ``--diag`` lẻ làm,
    chạy trên MÁY CÓ MẠNG (sandbox/web session bị allowlist chặn → toàn ❌ là
    bình thường, không phải bug).

Kết quả ghi ``data_warehouse/_meta/doctor_status.json`` → sidebar dashboard hiện
badge 🩺 (mirror badge test_status). Mọi check đều best-effort: một nguồn nổ
không được kéo sập cả báo cáo (exception → status "error" của riêng nguồn đó).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_STATUS_NAME = "doctor_status.json"

_ICONS = {"ok": "✅", "warn": "⚠️", "off": "⬜", "error": "❌"}
# Thứ tự xấu dần — dùng chọn "trạng thái tệ nhất" cho badge/exit code
_SEVERITY = {"ok": 0, "off": 1, "warn": 2, "error": 3}

# Tuổi tối đa (ngày lịch) cho as_of từng chỉ số vĩ mô trước khi coi là cũ —
# theo cadence nguồn: FX auto hằng ngày, VBMA tuần, NSO tháng, GDP quý.
# sbv_policy_rate nhập tay khi SBV ra quyết định → không bao giờ tính cũ.
_MACRO_MAX_AGE_DAYS = {
    "usdvnd": 5,
    "interbank_on": 12,
    "interbank_1w": 12,
    "govt_bond_yield_2y": 12,
    "govt_bond_yield_10y": 12,
    "us10y": 7,                # FRED daily (DGS10 nghỉ cuối tuần/lễ)
    "fed_funds": 7,
    "cpi_yoy": 45,
    "iip_yoy": 45,
    "pmi": 40,
    "gdp_yoy": 120,
    "trade_balance": 45,
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _result(key: str, name: str, status: str, message: str, fix: str = "") -> dict:
    return {"key": key, "name": name, "status": status,
            "message": message, "fix": fix}


def _prev_trading_day(d: "date | None" = None) -> date:
    """Ngày giao dịch (T2-T6) TRƯỚC ``d`` — chuẩn so tuổi data EOD: sáng nay
    chưa chạy pipeline thì data hôm qua vẫn là tươi; T2 nhìn về T6 tuần trước."""
    d = d or date.today()
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _age_days(iso: str) -> "int | None":
    """Tuổi (ngày lịch) của một mốc ISO 'YYYY-MM-DD[THH:MM:SS]' — None nếu rác."""
    try:
        return (date.today() - date.fromisoformat(str(iso)[:10])).days
    except (TypeError, ValueError):
        return None


def _mtime_age_days(path: Path) -> "int | None":
    try:
        return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    except OSError:
        return None


def _fmt_age(n: "int | None") -> str:
    if n is None:
        return "?"
    return "hôm nay" if n <= 0 else f"{n} ngày trước"


# ── OFFLINE checks — tuổi cache + cấu hình ───────────────────────────────────


_UNIT_WARN_DAYS = 7     # vết cũ hơn coi như đã xem — warn vĩnh viễn = alarm fatigue


def check_unit_normalizations() -> dict:
    """Guard đơn vị giá penny (rollup 07/08) có VỪA kích hoạt không.

    `_normalize_units` tự quy đổi khi giá bar lệch ≥100× lịch sử của chính mã
    đó, và ghi vết vào `_meta/unit_normalizations.json` (11/08). Tự sửa xong
    vẫn cần NGƯỜI liếc chart mã đó — ca quy đổi OAN lý thuyết là chia tách tỉ
    lệ cực lớn. Trước đây việc này là "nhớ quét run_daily.log"; nay badge tự
    báo, đúng doctrine: mọi lớp best-effort tự-sửa cần một doctor check.
    """
    name = "Quy đổi đơn vị giá (rollup)"
    path = _META / "unit_normalizations.json"
    if not path.exists():
        return _result("unit_norm", name, "ok", "guard chưa từng kích hoạt", "")
    try:
        events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except Exception as e:
        return _result("unit_norm", name, "error",
                       f"không đọc được vết quy đổi: {type(e).__name__}",
                       f"xem tay file {path}")
    cutoff = datetime.now() - timedelta(days=_UNIT_WARN_DAYS)
    fresh = []
    for ev in events:
        try:
            if datetime.fromisoformat(str(ev.get("at", ""))) >= cutoff:
                fresh.append(ev)
        except ValueError:
            fresh.append(ev)        # timestamp hỏng → coi là MỚI, thà soi thừa
    if not fresh:
        last = events[-1] if events else None
        note = (f"lần cuối {str(last.get('at', '?'))[:10]} "
                f"({last.get('ticker', '?')})" if last
                else "guard chưa từng kích hoạt")
        return _result("unit_norm", name, "ok", note, "")
    tickers = ", ".join(f"{e.get('ticker', '?')} ({e.get('ratio', '?')}×)"
                        for e in fresh[-5:])
    return _result(
        "unit_norm", name, "warn",
        f"{len(fresh)} lần quy đổi trong {_UNIT_WARN_DAYS} ngày: {tickers} — "
        f"guard ĐÃ tự sửa, việc còn lại là soi chart các mã này xem giá có "
        f"liên tục không",
        "nghi quy đổi OAN (mã vừa chia tách?) → báo Claude kèm dòng này")


def check_warehouse() -> dict:
    """Kho giá EOD: bar VNINDEX cuối cùng, dung sai 2 PHIÊN.

    VNINDEX daily qua API EOD về trễ ~1 phiên so với cổ phiếu (lý do tồn tại
    của `_augment_with_live_vnindex` trong brief), và pipeline sync chạy 18:00
    — chạy doctor ban ngày thì bar index mới nhất hợp lệ là 2 phiên trước.
    Chỉ warn khi TRỄ HƠN thế (sync thật sự bị bỏ); ngày chính xác luôn in ra.
    """
    name = "Kho giá EOD (VNINDEX)"
    vn_dir = _META.parent / "prices" / "ticker=VNINDEX"
    files = sorted(vn_dir.glob("year=*/*.parquet")) if vn_dir.exists() else []
    if not files:
        return _result("warehouse", name, "off",
                       "chưa có dữ liệu VNINDEX trong kho",
                       "python run.py sync")
    import pandas as pd
    df = pd.read_parquet(files[-1], columns=["time"])
    last = pd.to_datetime(df["time"]).max().date()
    threshold = _prev_trading_day(_prev_trading_day())     # 2 phiên trước
    status = "ok" if last >= threshold else "warn"
    return _result("warehouse", name, status,
                   f"bar cuối {last.isoformat()} ({_fmt_age((date.today() - last).days)})",
                   "" if status == "ok" else "python run.py sync")


def check_dir_shapes() -> dict:
    """Thư mục kho có ĐÚNG là thư mục không — bắt kiểu hỏng ÂM THẦM nhất.

    Máy user 06/08: `data_warehouse/_live` là một FILE RỖNG 0 byte (không
    phải thư mục), tạo lúc 07/07 03:13 — trùng sự cố Dropbox 2 máy đã ghi
    trong journal. Suốt MỘT THÁNG sau đó WSS không ghi nổi quote/bar nào, mà
    không có tín hiệu nào báo: mọi đường ghi đều nằm trong `try/except` để
    khỏi kéo sập vòng poll. Triệu chứng duy nhất lộ ra là `missing_in_rolled`
    cao bất thường trong reconciler — nhìn qua rất giống "WSS không chạy".

    Check này rẻ (vài lần `stat`) và bắt đúng lớp lỗi đó.
    """
    name = "Hình dạng thư mục kho"
    root = _META.parent
    expected = [root, root / "prices", root / "_live", _META]
    bad = []
    for p in expected:
        try:
            if p.exists() and not p.is_dir():
                bad.append(p.name)
        except OSError:
            bad.append(f"{p.name}(stat lỗi)")
    if not bad:
        return _result("dir_shapes", name, "ok",
                       f"{len(expected)} thư mục đều đúng dạng", "")
    joined = ", ".join(bad)
    return _result(
        "dir_shapes", name, "error",
        f"KHÔNG phải thư mục: {joined} — mọi thao tác ghi vào đó đều hỏng "
        f"âm thầm (WSS/rollup)",
        f"kiểm tra rồi xoá vật cản: python -c \"import pathlib;"
        f"p=pathlib.Path('data_warehouse/_live');print(p.stat())\" — nếu là "
        f"file rỗng thì xoá đi, thư mục sẽ được tạo lại tự động")


def check_market_overview() -> dict:
    """market_overview.json (độ rộng/movers/dòng tiền ngành/regime) — so data_date."""
    name = "Market overview (screener)"
    p = _META / "market_overview.json"
    if not p.exists():
        return _result("market_overview", name, "off",
                       "chưa có market_overview.json", "python run.py screener")
    data = json.loads(p.read_text(encoding="utf-8"))
    dd = str(data.get("data_date") or "").strip()
    if not dd:                       # file cũ trước khi có field data_date
        gen = str(data.get("generated_at", ""))
        dd = gen[:10] if gen else ""
    age = _age_days(dd)
    stale = bool(dd) and date.fromisoformat(dd) < _prev_trading_day()
    status = "warn" if (stale or age is None) else "ok"
    return _result("market_overview", name, status,
                   f"data_date {dd or '?'} ({_fmt_age(age)})",
                   "python run.py screener" if status != "ok" else "")


def check_fundamentals() -> dict:
    """fundamentals.parquet — cadence 1×/tuần (thêm trong mùa BCTC)."""
    name = "Cơ bản VN30 (fundamentals)"
    p = _META / "fundamentals.parquet"
    age = _mtime_age_days(p)
    if age is None:
        return _result("fundamentals", name, "off",
                       "chưa có fundamentals.parquet",
                       "python vnstock_fundamental_updater.py")
    status = "ok" if age <= 10 else "warn"
    return _result("fundamentals", name, status, f"cập nhật {_fmt_age(age)}",
                   "python vnstock_fundamental_updater.py" if status != "ok" else "")


def check_macro() -> dict:
    """Vĩ mô: từng chỉ số so cadence nguồn của nó + nhắc PMI quên set."""
    name = "Vĩ mô (lãi suất/tỷ giá/CPI…)"
    from vnstock_macro import load_macro, pmi_reminder
    macro = load_macro()
    if not macro:
        return _result("macro", name, "off", "cache vĩ mô rỗng",
                       "python run.py macro")
    stale = []
    for ind in macro:
        max_age = _MACRO_MAX_AGE_DAYS.get(ind.get("key") or "")
        age = _age_days(ind.get("as_of") or "")
        if max_age is not None and age is not None and age > max_age:
            stale.append(f"{ind.get('label')} (as_of {ind.get('as_of')})")
    remind = pmi_reminder(macro)
    parts = [f"{len(macro)} chỉ số có reading"]
    if stale:
        parts.append("cũ: " + "; ".join(stale))
    if remind:
        parts.append(remind.strip())
    status = "warn" if (stale or remind) else "ok"
    return _result("macro", name, status, " · ".join(parts),
                   "python run.py macro (auto) hoặc python vnstock_macro.py "
                   "--set <key> <value>" if status != "ok" else "")


def check_market_news() -> dict:
    """Tin kinh tế/chính trị RSS — tuổi lần fetch cuối + độ phủ phân tích LLM."""
    name = "Tin vĩ mô RSS (market news)"
    p = _META / "market_news_cache.json"
    if not p.exists():
        return _result("market_news", name, "off",
                       "chưa có market_news_cache.json", "python run.py news")
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    fetched = str(data.get("fetched_at", "")) if isinstance(data, dict) else ""
    age = _age_days(fetched)
    cutoff = (date.today() - timedelta(days=3)).isoformat()
    recent = [it for it in items if (it.get("_date_sort") or "") >= cutoff]
    analyzed = sum(1 for it in recent if it.get("_impact"))
    status = "ok" if age is not None and age <= 3 else "warn"
    return _result("market_news", name, status,
                   f"fetch {_fmt_age(age)} · {len(recent)} tin ≤3 ngày "
                   f"({analyzed} có tác động LLM)",
                   "python run.py news" if status != "ok" else "")


def check_ticker_news() -> dict:
    """Tin theo mã (vnstock company.news) — tuổi cache."""
    name = "Tin theo mã (news cache)"
    p = _META / "news_cache.json"
    age = _mtime_age_days(p)
    if age is None:
        return _result("ticker_news", name, "off", "chưa có news_cache.json",
                       "python run.py news")
    status = "ok" if age <= 3 else "warn"
    return _result("ticker_news", name, status, f"cập nhật {_fmt_age(age)}",
                   "python run.py news" if status != "ok" else "")


def check_foreign_flow() -> dict:
    """NN ròng 1D full-market — phiên mới nhất trong cache theo ngày."""
    name = "NN ròng 1D (foreign flow)"
    p = _META / "foreign_net_daily.json"
    if not p.exists():
        return _result("foreign_flow", name, "off",
                       "chưa có foreign_net_daily.json",
                       "python run.py foreign-flow --days 5")
    cache = json.loads(p.read_text(encoding="utf-8"))
    if not cache:
        return _result("foreign_flow", name, "off", "cache rỗng",
                       "python run.py foreign-flow --days 5")
    last = max(cache)
    rec = cache.get(last) or {}
    stale = date.fromisoformat(last) < _prev_trading_day()
    n_sym = rec.get("n_symbols")
    parts = [f"phiên {last}: net {rec.get('net', '?')} tỷ ({n_sym} mã)"]
    # CLAUDE.md: chỉ ~100 mã ⇒ API đang cap limit → tổng net méo (top-100 bug cũ)
    capped = isinstance(n_sym, int) and n_sym <= 120
    if capped:
        parts.append("⚠️ số mã ≤120 — API có thể đang cap limit, net thiếu đuôi small-cap")
    status = "warn" if (stale or capped) else "ok"
    return _result("foreign_flow", name, status, " · ".join(parts),
                   "python run.py foreign-flow --days 5" if status != "ok" else "")


def check_events() -> dict:
    """Sự kiện GDKHQ sắp tới — brief tự refresh 1×/ngày nên cache phải mới."""
    name = "Sự kiện DN (GDKHQ)"
    p = _META / "upcoming_events.parquet"
    age = _mtime_age_days(p)
    if age is None:
        return _result("events", name, "off", "chưa có upcoming_events.parquet",
                       "python vnstock_events.py")
    status = "ok" if age <= 3 else "warn"
    return _result("events", name, status, f"refresh {_fmt_age(age)}",
                   "python vnstock_events.py" if status != "ok" else "")


def _has_pypdf() -> bool:
    # BaseException chứ không chỉ Exception: pypdf kéo cryptography (native) —
    # bản cài hỏng có thể nổ pyo3 PanicException (kế thừa BaseException, thấy
    # thật trong sandbox 10/07). Import hỏng kiểu gì cũng = "không dùng được".
    try:
        import pypdf  # noqa: F401
        return True
    except BaseException:  # noqa: BLE001
        return False


def check_pdf_tooling() -> dict:
    """Khả năng PDF→text cho nguồn VBMA (pdftotext trên PATH hoặc pypdf).

    Máy MỚI hay dính bẫy này (desktop user 10/07: venv thiếu pypdf → VBMA chết
    IM LẶNG vì best-effort giữ cache cũ, LNH/2Y/10Y không bao giờ cập nhật) —
    check offline rẻ, khỏi đợi --net mới lộ."""
    name = "PDF→text (nguồn VBMA)"
    if os.environ.get("VNSTOCK_MACRO_VBMA", "1") == "0":
        return _result("pdf_tooling", name, "off", "đã tắt (VNSTOCK_MACRO_VBMA=0)")
    import shutil
    if shutil.which("pdftotext"):
        return _result("pdf_tooling", name, "ok", "pdftotext (poppler) trên PATH")
    if _has_pypdf():
        return _result("pdf_tooling", name, "ok", "pypdf khả dụng")
    return _result("pdf_tooling", name, "error",
                   "thiếu cả pdftotext lẫn pypdf — lãi suất LNH / lợi suất TPCP "
                   "sẽ KHÔNG BAO GIỜ cập nhật (fetch fail im lặng, giữ cache cũ)",
                   "pip install pypdf (đã cài mà vẫn lỗi → "
                   "pip install --force-reinstall pypdf cryptography)")


def check_llm_ledger() -> dict:
    """Sổ call LLM per provider (món 3 deep-dive DojoAgents 15/07) — cảnh
    báo khi hôm nay có call bị RATE-LIMIT (= lý do ladder rơi bậc âm thầm)
    hoặc quá nửa call lỗi. off khi sổ chưa tồn tại (tự tích lũy)."""
    name = "LLM call ledger"
    p = _META / "llm_ledger.json"
    if not p.exists():
        return _result("llm_ledger", name, "off",
                       "chưa có llm_ledger.json (sổ tự tích lũy khi có call LLM)")
    data = json.loads(p.read_text(encoding="utf-8"))
    days = data.get("days") or {}
    today = date.today().isoformat()
    day = days.get(today) or {}
    if not day:
        last = sorted(days)[-1] if days else "?"
        return _result("llm_ledger", name, "ok",
                       f"hôm nay chưa có call nào (ngày gần nhất có sổ: {last})")
    calls = sum(int(r.get("calls", 0)) for r in day.values())
    fails = sum(int(r.get("fail", 0)) for r in day.values())
    limited = sum(int(r.get("rate_limited", 0)) for r in day.values())
    oks = sum(int(r.get("ok", 0)) for r in day.values())
    hot = [k for k, r in day.items() if int(r.get("rate_limited", 0)) > 0]
    msg = f"hôm nay {calls} call · {fails} lỗi · {limited} rate-limit"
    if calls >= 3 and oks == 0:
        # all-free 22/07: KHÔNG call nào thành công = ladder down toàn phần
        return _result("llm_ledger", name, "error",
                       msg + " — TOÀN BỘ call lỗi (ladder down)",
                       "python scripts/probe_models.py soi slug/key; "
                       "python vnstock_llm_ledger.py --show soi provider")
    if limited > 0:
        return _result("llm_ledger", name, "warn",
                       msg + f" — chạm trần: {', '.join(sorted(hot))}",
                       "đợi trần reset / giảm số call (--max) / để ladder rơi bậc")
    if calls >= 4 and fails * 2 > calls:
        return _result("llm_ledger", name, "warn",
                       msg + " — quá nửa call lỗi (không phải rate-limit)",
                       "python vnstock_llm_ledger.py --show rồi soi provider lỗi")
    return _result("llm_ledger", name, "ok", msg)


def check_llm_keys() -> dict:
    """Key LLM trong .env: provider chấm sentiment + key agent viết brief."""
    name = "LLM keys (.env)"
    from vnstock_sentiment import available_provider
    provider = available_provider()
    brief_keys = [k for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                              "OPENAI_API_KEY", "GROQ_API_KEY",
                              "MISTRAL_API_KEY", "DEEPSEEK_API_KEY")
                  if (os.environ.get(k) or "").strip()]
    if not provider and not brief_keys:
        return _result("llm_keys", name, "off", "chưa có key nào trong .env",
                       "thêm GROQ_API_KEY / ANTHROPIC_API_KEY… vào .env")
    parts = [f"sentiment: {provider or '❌ không có (GEMINI/GROQ/CEREBRAS/OPENROUTER)'}"]
    parts.append(f"brief agent: {len(brief_keys)} key" if brief_keys
                 else "brief agent: ❌ không có key")
    status = "ok" if (provider and brief_keys) else "warn"
    return _result("llm_keys", name, status, " · ".join(parts),
                   "bổ sung key thiếu vào .env" if status != "ok" else "")


def check_telegram() -> dict:
    name = "Telegram push"
    tok = bool((os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip())
    chat = bool((os.environ.get("TELEGRAM_CHAT_ID") or "").strip())
    if tok and chat:
        return _result("telegram", name, "ok", "BOT_TOKEN + CHAT_ID có trong env")
    if tok or chat:
        missing = "TELEGRAM_CHAT_ID" if tok else "TELEGRAM_BOT_TOKEN"
        return _result("telegram", name, "warn", f"thiếu {missing}",
                       f"thêm {missing} vào .env")
    return _result("telegram", name, "off", "chưa cấu hình",
                   "thêm TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID vào .env")


def check_reports() -> dict:
    """Thư viện báo cáo vĩ mô (P2/P3) — metadata thiếu / digest chưa chạy /
    claim lệch registry. off khi chưa dùng tính năng (không tính exit code)."""
    name = "Báo cáo vĩ mô (reports)"
    p = _META / "reports_index.json"
    if not p.exists():
        return _result("reports", name, "off", "chưa có báo cáo nào trong thư viện",
                       "thêm qua sub-tab 📚 Báo cáo hoặc vnstock_reports.py --add")
    reports = list((json.loads(p.read_text(encoding="utf-8"))
                    .get("reports") or {}).values())
    from vnstock_reports import in_analysis
    ready = [r for r in reports if in_analysis(r)]
    no_meta = sum(1 for r in reports if not in_analysis(r))
    no_digest = sum(1 for r in ready if not r.get("digest"))
    mismatch = sum(1 for r in ready
                   if (r.get("digest") or {}).get("has_mismatch"))
    parts = [f"{len(reports)} báo cáo, {len(ready)} đủ điều kiện phân tích"]
    if no_meta:
        parts.append(f"{no_meta} thiếu metadata/scan")
    if no_digest:
        parts.append(f"{no_digest} chưa digest")
    if mismatch:
        parts.append(f"{mismatch} digest có claim lệch registry")
    status = "warn" if (no_digest or mismatch) else "ok"
    fix = ("python vnstock_report_digest.py --refresh" if no_digest else
           "python vnstock_report_digest.py --show <id> — soi claim lệch"
           if mismatch else "")
    return _result("reports", name, status, " · ".join(parts), fix)


def _allocation_brief_reminder(today: "date | None" = None) -> "str | None":
    """Nhắc tạo brief phân bổ KỲ THÁNG (mirror pmi_reminder): từ mùng 3 mà
    tháng này chưa có brief_type='allocation' trong memory → 1 dòng nhắc.
    Best-effort — memory lỗi/thiếu coi như không nhắc (không báo động giả)."""
    t = today or date.today()
    if t.day < 3:
        return None
    try:
        from vnstock_memory import recent_briefs
        rows = recent_briefs("allocation", limit=5)
        month = t.strftime("%Y-%m")
        if any((r.get("created_at") or "").startswith(month) for r in rows):
            return None
        return (f"⏰ chưa có brief phân bổ tháng {t.month}/{t.year} — tạo ở "
                "sub-tab 🧭 Phân bổ (cadence tháng)")
    except Exception:
        return None


def check_allocation() -> dict:
    """Band phân bổ (P1) — tuổi state so phiên trước (run.py all refresh hằng
    ngày) + nhắc brief kỳ tháng. off khi chưa chạy lần nào."""
    name = "Phân bổ tài sản (allocation)"
    p = _META / "allocation_state.json"
    if not p.exists():
        return _result("allocation", name, "off", "chưa có allocation_state.json",
                       "python run.py allocation")
    st = json.loads(p.read_text(encoding="utf-8"))
    as_of = str(st.get("as_of") or "")
    stale = bool(as_of) and date.fromisoformat(as_of) < _prev_trading_day()
    parts = [f"band {st.get('band', '?')} ({st.get('band_label', '?')}) · "
             f"phiên {as_of or '?'} · {st.get('n_inputs', 0)} tín hiệu · "
             f"history {len(st.get('history') or [])} phiên"]
    if (st.get("report_tilt") or {}).get("tilt"):
        parts.append(f"tilt {st['report_tilt']['tilt']:+d} từ báo cáo")
    remind = _allocation_brief_reminder()
    if remind:
        parts.append(remind)
    status = "warn" if (stale or remind) else "ok"
    fix = "python run.py allocation" if stale else \
        ("tạo brief phân bổ ở sub-tab 🧭" if remind else "")
    return _result("allocation", name, status, " · ".join(parts), fix)


def check_tests() -> dict:
    """Badge test gần nhất — fail thì đừng deploy/merge (kỷ luật trong CLAUDE.md)."""
    name = "Tests (pytest)"
    p = _META / "test_status.json"
    if not p.exists():
        return _result("tests", name, "off", "chưa chạy",
                       "python run.py test --fast")
    st = json.loads(p.read_text(encoding="utf-8"))
    bad = int(st.get("failed", 0)) + int(st.get("errors", 0))
    age = _age_days(str(st.get("ran_at", "")))
    msg = (f"{st.get('passed', 0)} passed"
           + (f", {bad} FAIL" if bad else "")
           + f" · chạy {_fmt_age(age)} ({st.get('mode', '?')})")
    if bad:
        return _result("tests", name, "error", msg,
                       "python run.py test --fast — xem test nào fail trước khi merge")
    return _result("tests", name, "ok" if (age is not None and age <= 7) else "warn",
                   msg, "" if (age is not None and age <= 7) else "python run.py test --fast")


# ── NET checks (--net) — probe thật từng nguồn ngoài ─────────────────────────


def net_rss_feeds() -> dict:
    """Fetch thử TỪNG feed RSS (song song) — đúng việc news_feeds --diag làm."""
    name = "RSS feeds (mạng)"
    from concurrent.futures import ThreadPoolExecutor
    import vnstock_news_feeds as nf
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda f: (f["name"], len(nf.fetch_feed(f))), nf._FEEDS))
    ok = [n for n, c in counts if c]
    dead = [n for n, c in counts if not c]
    msg = f"{len(ok)}/{len(counts)} feed trả dữ liệu"
    if dead:
        msg += " · ❌ " + ", ".join(dead)
    status = "ok" if not dead else ("warn" if ok else "error")
    return _result("net_rss", name, status, msg,
                   "feed ❌ → URL sai/bị chặn: sửa/xoá trong vnstock_news_feeds._FEEDS"
                   if dead else "")


def net_fx() -> dict:
    """API tỷ giá free (er-api → exchangerate.host)."""
    name = "FX USD/VND (mạng)"
    from vnstock_macro import fetch_usdvnd
    v = fetch_usdvnd()
    if v:
        return _result("net_fx", name, "ok", f"fetch OK: {v:,.0f} VND")
    return _result("net_fx", name, "error", "không fetch được tỷ giá",
                   "kiểm tra mạng/allowlist (open.er-api.com, exchangerate.host); "
                   "cache cũ vẫn được giữ")


def net_vbma() -> dict:
    """Báo cáo tuần VBMA (PDF) → lãi suất LNH + lợi suất TPCP."""
    name = "VBMA weekly (mạng)"
    if os.environ.get("VNSTOCK_MACRO_VBMA", "1") == "0":
        return _result("net_vbma", name, "off", "đã tắt (VNSTOCK_MACRO_VBMA=0)")
    from vnstock_vbma import fetch_weekly
    got = fetch_weekly()
    if got:
        keys = ", ".join(sorted(k for k in got if k not in ("as_of", "source_url")))
        return _result("net_vbma", name, "ok",
                       f"parse OK (as_of {got.get('as_of', '?')}): {keys}")
    return _result("net_vbma", name, "error", "không tải/parse được PDF tuần",
                   "python vnstock_vbma.py --diag --dump — gửi output để chỉnh regex; "
                   "tạm thời: python vnstock_macro.py --set interbank_on <số>")


def net_nso() -> dict:
    """Báo cáo tháng NSO → CPI/IIP/GDP/cán cân thương mại."""
    name = "NSO monthly (mạng)"
    if os.environ.get("VNSTOCK_MACRO_NSO", "1") == "0":
        return _result("net_nso", name, "off", "đã tắt (VNSTOCK_MACRO_NSO=0)")
    from vnstock_nso import fetch_monthly
    got = fetch_monthly()
    if got:
        keys = ", ".join(sorted(k for k in got if k not in ("as_of", "source_url")))
        return _result("net_nso", name, "ok",
                       f"parse OK (as_of {got.get('as_of', '?')}): {keys}")
    return _result("net_nso", name, "error", "không tải/parse được bài NSO",
                   "python vnstock_nso.py --diag --dump — gửi output để chỉnh regex")


def net_foreign_flow_api() -> dict:
    """API TopStock foreign buy/sell cho phiên giao dịch trước."""
    name = "Foreign-flow API (mạng)"
    from vnstock_foreign_flow import fetch_market_net
    d = _prev_trading_day().isoformat()
    rec = fetch_market_net(d)
    if not rec:
        return _result("net_foreign_flow", name, "error",
                       f"API không trả dữ liệu cho {d}",
                       "kiểm tra vnstock_data/sponsor API + mạng; "
                       "python vnstock_foreign_flow.py --diag " + d)
    n = rec.get("n_symbols", 0)
    msg = f"{d}: net {rec.get('net')} tỷ, {n} mã"
    if n <= 120:
        return _result("net_foreign_flow", name, "warn",
                       msg + " · số mã ≤120 — API có thể cap limit",
                       "tăng --limit hoặc đổi nguồn (xem TODO #0/#1 trong CLAUDE.md)")
    return _result("net_foreign_flow", name, "ok", msg)


def net_fred() -> dict:
    """FRED (US10Y + Fed funds) — cần FRED_API_KEY free trong .env."""
    name = "FRED US10Y/Fed (mạng)"
    if os.environ.get("VNSTOCK_MACRO_FRED", "1") == "0":
        return _result("net_fred", name, "off", "đã tắt (VNSTOCK_MACRO_FRED=0)")
    from vnstock_fred import _api_key, fetch_daily
    if not _api_key():
        return _result("net_fred", name, "off",
                       "chưa có FRED_API_KEY trong .env — us10y/fed_funds sẽ "
                       "không tự cập nhật",
                       "đăng ký key free (~2 phút): "
                       "https://fred.stlouisfed.org/docs/api/api_key.html "
                       "→ thêm FRED_API_KEY=<key> vào .env")
    got = fetch_daily()
    if got:
        parts = ", ".join(f"{k}={v} ({d})" for k, (v, d) in sorted(got.items()))
        return _result("net_fred", name, "ok", f"fetch OK: {parts}")
    return _result("net_fred", name, "error",
                   "có key nhưng không fetch được",
                   "kiểm tra mạng/allowlist api.stlouisfed.org + key còn hiệu lực; "
                   "python vnstock_fred.py --diag")


def net_hnx() -> dict:
    """HNX yield curve (POST API) → lợi suất TPCP 8 kỳ hạn theo ngày."""
    name = "HNX yield curve (mạng)"
    if os.environ.get("VNSTOCK_HNX", "1") == "0":
        return _result("net_hnx", name, "off", "đã tắt (VNSTOCK_HNX=0)")
    from vnstock_hnx import fetch_latest
    got = fetch_latest(verbose=False)
    if got:
        d, ys = got
        return _result("net_hnx", name, "ok",
                       f"fetch OK ({d}): " + ", ".join(f"{k}={v}" for k, v in ys.items()))
    return _result("net_hnx", name, "error",
                   "không tải/parse được đường cong HNX",
                   "python vnstock_hnx.py --diag — kiểm endpoint/selector còn đúng; "
                   "tạm thời VBMA PDF vẫn nuôi 2Y/10Y")


def net_sbv() -> dict:
    """Bản tin tuần SBV (PDF) → LNH + OMO ròng + tỷ giá trung tâm."""
    name = "SBV weekly (mạng)"
    if os.environ.get("VNSTOCK_SBV", "1") == "0":
        return _result("net_sbv", name, "off", "đã tắt (VNSTOCK_SBV=0)")
    from vnstock_sbv import fetch_weekly
    got = fetch_weekly()
    if got:
        fields = ", ".join(k for k, v in got.__dict__.items() if v is not None)
        return _result("net_sbv", name, "ok", f"parse OK: {fields or '(rỗng)'}")
    return _result("net_sbv", name, "warn",
                   "không tải/parse được bản tin SBV (LNH vẫn có từ VBMA/HNX)",
                   "python vnstock_sbv.py --diag — kiểm slug bài/URL PDF; "
                   "OMO tạm nhập tay: python vnstock_sbv.py --set-omo <số>")


def net_sbv_daily() -> dict:
    """LNH bình quân THEO NGÀY (headless-delivery API portal SBV)."""
    name = "SBV daily LNH (mạng)"
    if os.environ.get("VNSTOCK_SBV_DAILY", "1") == "0":
        return _result("net_sbv_daily", name, "off", "đã tắt (VNSTOCK_SBV_DAILY=0)")
    from vnstock_sbv_rates import fetch_daily
    entries = fetch_daily()
    if entries:
        e = entries[0]
        return _result("net_sbv_daily", name, "ok",
                       f"fetch OK ({e['date']}): "
                       + ", ".join(f"{k}={v}" for k, v in sorted(e["rates"].items())))
    return _result("net_sbv_daily", name, "warn",
                   "không fetch/parse được LNH ngày (registry vẫn có nguồn tuần)",
                   "python vnstock_sbv_rates.py --diag — kiểm endpoint "
                   "headless-delivery / schema contentFields còn đúng")


def net_jina() -> dict:
    """Jina Reader (r.jina.ai) — full text cho tin chấm LLM."""
    name = "Jina Reader (mạng)"
    from vnstock_news_feeds import _fulltext_enabled, fetch_fulltext
    if not _fulltext_enabled():
        return _result("net_jina", name, "off", "đã tắt (VNSTOCK_NEWS_FULLTEXT=0)")
    body = fetch_fulltext("https://example.com/")
    if body:
        return _result("net_jina", name, "ok",
                       f"đọc thử OK ({len(body)} ký tự)")
    return _result("net_jina", name, "warn",
                   "không truy cập được r.jina.ai — tin chấm LLM sẽ chỉ dùng "
                   "title+summary (vẫn chạy được)",
                   "kiểm tra mạng/allowlist r.jina.ai; tắt hẳn: VNSTOCK_NEWS_FULLTEXT=0")


OFFLINE_CHECKS = [
    check_dir_shapes, check_unit_normalizations,
    check_warehouse, check_market_overview, check_fundamentals, check_macro,
    check_pdf_tooling, check_market_news, check_ticker_news,
    check_foreign_flow, check_events, check_reports, check_allocation,
    check_llm_keys, check_llm_ledger, check_telegram, check_tests,
]
NET_CHECKS = [
    net_rss_feeds, net_fx, net_vbma, net_hnx, net_sbv, net_sbv_daily,
    net_nso, net_fred, net_foreign_flow_api, net_jina,
]


def run_checks(net: bool = False) -> list[dict]:
    """Chạy toàn bộ check (offline; + net khi ``net=True``). Một check nổ →
    status "error" của riêng nó, KHÔNG kéo sập báo cáo (mirror doctor Agent-Reach)."""
    results: list[dict] = []
    for fn in OFFLINE_CHECKS + (NET_CHECKS if net else []):
        try:
            results.append(fn())
        except KeyboardInterrupt:      # Ctrl+C của user thì phải thoát thật
            raise
        except BaseException as e:  # noqa: BLE001 — doctor phải sống sót mọi nguồn,
            # KỂ CẢ BaseException ngoài Exception (pyo3 PanicException từ native
            # package hỏng — thấy thật khi import pypdf trên bản cryptography lỗi)
            key = fn.__name__.removeprefix("check_").removeprefix("net_")
            results.append(_result(key, fn.__name__, "error",
                                   f"check lỗi: {type(e).__name__}: {e}"))
    return results


# ── report / persist ─────────────────────────────────────────────────────────


def worst_status(results: list[dict]) -> str:
    return max((r["status"] for r in results),
               key=lambda s: _SEVERITY.get(s, 3), default="ok")


def format_report(results: list[dict], net: bool = False) -> str:
    lines = ["🩺 vnstock doctor — sức khỏe nguồn dữ liệu",
             "=" * 46,
             "✅ ok · ⚠️ cũ/thiếu một phần · ⬜ chưa cấu hình/chưa chạy · ❌ hỏng",
             ""]
    for r in results:
        lines.append(f"  {_ICONS.get(r['status'], '?')} {r['name']} — {r['message']}")
        if r.get("fix"):
            lines.append(f"       ↳ sửa: {r['fix']}")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in _ICONS}
    lines.append("")
    lines.append("Tổng: " + " · ".join(
        f"{counts[s]} {_ICONS[s]}" for s in ("ok", "warn", "off", "error") if counts[s]))
    if not net:
        lines.append("(offline — thêm --net trên máy có mạng để probe "
                     "RSS/FX/VBMA/NSO/API/Jina)")
    return "\n".join(lines)


def write_status(results: list[dict], mode: str) -> "Path | None":
    """Ghi doctor_status.json cho badge sidebar. Best-effort."""
    payload = {
        "ran_at": datetime.now().isoformat(),
        "mode": mode,
        "counts": {s: sum(1 for r in results if r["status"] == s) for s in _ICONS},
        "worst": worst_status(results),
        "checks": results,
    }
    try:
        _META.mkdir(parents=True, exist_ok=True)
        out = _META / _STATUS_NAME
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        return out
    except OSError:
        return None


def main(argv: "list[str] | None" = None) -> int:
    # .env trước khi check key (mirror generate_brief._ensure_env_loaded)
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Khám sức khỏe nguồn dữ liệu (doctor).")
    ap.add_argument("--net", action="store_true",
                    help="Thêm probe mạng (RSS/FX/VBMA/NSO/foreign-flow/Jina) — chậm hơn")
    ap.add_argument("--json", action="store_true", help="In JSON thay vì text")
    ap.add_argument("--no-save", action="store_true",
                    help="Không ghi doctor_status.json (badge sidebar)")
    a = ap.parse_args(argv)

    results = run_checks(net=a.net)
    mode = "net" if a.net else "offline"
    if not a.no_save:
        write_status(results, mode)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_report(results, net=a.net))
    return 1 if worst_status(results) in ("warn", "error") else 0


if __name__ == "__main__":
    sys.exit(main())

"""
vnstock_model_watch.py — theo dõi sức khoẻ ladder model LLM hàng tuần
=====================================================================
Chạy 1 lần/tuần (gắn vào `run.py weekend`, 09:00 T7) và trả lời 2 câu:

  1. Model nào ĐANG DÙNG đã chết?          → probe 1 call/slug (chi phí ~0)
  2. Model nào SẮP bị thay/gỡ?             → diff danh mục provider tuần này
                                              với tuần trước

Vì sao cần cả hai: **probe KHÔNG phát hiện được "sắp hết hạn"**. Model đã bị
khai tử nhưng còn phục vụ trả `200 OK` y hệt model khỏe — bằng chứng ngay
trong repo: `llama-3.3-70b-versatile` (Groq deprecated 17/06/2026, "còn phục
vụ nhưng sẽ gỡ") và `zai-glm-4.7` (Cerebras sắp dep 17/08/2026); hai dòng đó
đến từ ĐỌC THÔNG BÁO nhà cung cấp chứ không phải từ probe. Model thường rời
DANH MỤC trước khi ngừng phục vụ → diff danh mục là tín hiệu sớm thật.

Ghi `data_warehouse/_meta/model_status.json` (badge sidebar, cùng họ với
test_status.json / doctor_status.json) + lịch sử snapshot để tuần sau diff.

Kill-switch: `VNSTOCK_MODEL_WATCH=0` tắt hẳn · `VNSTOCK_MODEL_WATCH_EVAL=0`
tắt riêng phần chấm điểm (tốn call hơn) · `VNSTOCK_MODEL_WATCH_ALERT=0` tắt
báo Telegram.

CLI:
    python vnstock_model_watch.py             # probe + diff danh mục
    python vnstock_model_watch.py --eval      # + chấm điểm bộ đề (GĐ2-3)
    python vnstock_model_watch.py --json      # in JSON thay vì bảng
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"

_STATUS_NAME = "model_status.json"
_HISTORY_NAME = "model_watch_history.json"
_HISTORY_MAX = 8              # ~2 tháng chạy hàng tuần

_TIMEOUT = 45
_MAX_TOKENS = 256             # model reasoning (gpt-oss/qwen3) cần chỗ suy nghĩ
_SLEEP_BETWEEN = 1.0          # lịch sự với rate limit free tier (Groq TPM 8K)

_THINK_RE = re.compile(
    r"<\s*(think|thinking|reasoning|thought)\s*>.*?<\s*/\s*\1\s*>\s*", re.S | re.I)

# endpoint chat + endpoint DANH MỤC của 4 provider free.
# `catalog_shape`: "openai" = {"data":[{"id":…}]}, "gemini" = {"models":[{"name":
# "models/…"}]}. Gemini nhận key qua query param, không phải Bearer.
_PROVIDERS: dict[str, dict] = {
    "Groq": {
        "env": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "catalog": "https://api.groq.com/openai/v1/models",
        "catalog_shape": "openai",
    },
    "Cerebras": {
        "env": "CEREBRAS_API_KEY",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "catalog": "https://api.cerebras.ai/v1/models",
        "catalog_shape": "openai",
    },
    "OpenRouter": {
        "env": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "catalog": "https://openrouter.ai/api/v1/models",
        "catalog_shape": "openai",
        "catalog_public": True,          # danh mục không cần key
    },
    "Gemini": {
        "env": "GEMINI_API_KEY",
        "env_alt": "GOOGLE_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "catalog": "https://generativelanguage.googleapis.com/v1beta/models",
        "catalog_shape": "gemini",
    },
    # User quyết 11/08: GIỮ Mistral làm giọng brief thứ tư → vào lưới hạng
    # nhất (trước đó vô hình: không probe, không diff danh mục, không eval —
    # lộ qua ledger trong tin test-alert). Slug mistral-small-latest không
    # cần probe trước: đang chạy THẬT trong production (2 OK, score 0.836
    # ngày 11/08) — bằng chứng mạnh hơn một call ping.
    "Mistral": {
        "env": "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "catalog": "https://api.mistral.ai/v1/models",
        "catalog_shape": "openai",
    },
}

_BRIEF_TYPE2PROVIDER = {"gemini": "Gemini", "groq": "Groq",
                        "cerebras": "Cerebras", "openrouter": "OpenRouter",
                        "mistral": "Mistral"}

# Hết hạn mức ≠ model chết. Gộp hai ca là báo động giả (ca thật 08/08: 3 model
# OpenRouter dính `free-models-per-day` do chính eval của ta đốt, bị báo ❌
# chết + đẩy trạng thái đỏ). Đây là ĐIỂM DÙNG CHUNG — `vnstock_model_eval`
# import lại, đừng viết bản thứ hai.
_RATE_LIMIT_MARKS = ("429", "rate limit", "rate_limit", "quota",
                     "resource_exhausted", "free-models-per-day")


def _is_rate_limited(err: "str | None") -> bool:
    return bool(err) and any(m in err.lower() for m in _RATE_LIMIT_MARKS)


# ── Tiện ích ─────────────────────────────────────────────────────────────────

def _flag(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() \
        not in ("0", "false", "off", "no")


def _ensure_env_loaded() -> None:
    """CLI fresh chưa chắc đã load .env (bẫy đã ghi trong CLAUDE-NOTES)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass


def _key_for(provider: str) -> str:
    cfg = _PROVIDERS.get(provider) or {}
    key = (os.environ.get(cfg.get("env", "")) or "").strip()
    if not key and cfg.get("env_alt"):
        key = (os.environ.get(cfg["env_alt"]) or "").strip()
    return key


def _preview(text: str) -> str:
    out = _THINK_RE.sub("", text or "").strip()
    return re.sub(r"\s+", " ", out)[:40] or "(rỗng sau strip think)"


# ── Gọi 1 model CỤ THỂ (không phải ladder) ───────────────────────────────────

def chat_once(provider: str, model: str, system: str, user: str,
              max_tokens: int = _MAX_TOKENS,
              extra: "dict | None" = None) -> "tuple[str | None, str | None]":
    """(text, err) — gọi ĐÍCH DANH một model. Ladder của `chat_complete` tự
    rơi nấc nên không dùng đo được từng model; ở đây cần biết CHÍNH model này
    trả lời ra sao."""
    cfg = _PROVIDERS.get(provider)
    if not cfg:
        return None, f"provider lạ: {provider}"
    key = _key_for(provider)
    if not key:
        return None, f"thiếu {cfg['env']}"
    try:
        r = requests.post(
            cfg["endpoint"],
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  **(extra or {})},
            timeout=_TIMEOUT)
        if r.status_code != 200:
            # regex tách khỏi f-string: Python 3.11 cấm backslash trong f-string
            # (máy user 3.13 cho phép — sửa để chạy được cả hai)
            snippet = re.sub(r"\s+", " ", r.text or "")[:120]
            return None, f"HTTP {r.status_code}: {snippet}"
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return _THINK_RE.sub("", content or ""), None
    except requests.Timeout:
        return None, f"timeout >{_TIMEOUT}s"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def probe_one(provider: str, model: str,
              extra: "dict | None" = None) -> "tuple[bool, str, float]":
    """1 call thử → (sống, mô tả, giây). Giữ nguyên hợp đồng của
    scripts/probe_models.py (script đó nay import lại từ đây)."""
    t0 = time.time()
    text, err = chat_once(provider, model, "Reply with exactly: OK", "ping",
                          max_tokens=_MAX_TOKENS, extra=extra)
    dt = time.time() - t0
    if err:
        # Param lạ (vd reasoning_effort) bị từ chối → thử lại không kèm param
        if extra and err.startswith("HTTP 400") and any(k in err for k in extra):
            ok2, desc2, dt2 = probe_one(provider, model, None)
            return ok2, f"{desc2} (bỏ {'/'.join(extra)})", dt + dt2
        return False, err, dt
    return True, f'→ "{_preview(text)}"', dt


# ── Slug ĐANG DÙNG trong code ────────────────────────────────────────────────

def _ladder_slugs() -> "list[tuple[str, str, str, dict]]":
    """Gom slug free ĐANG DÙNG ở các điểm [1]-[8], mỗi slug kèm tag điểm dùng.

    THÊM ĐIỂM DÙNG MODEL MỚI → phải khai vào đây, không thì health check mù
    đúng chỗ đó (`test_probe_ladder_covers_all_free_live_slugs` canh việc này).
    """
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    import vnstock_brief as vb
    import vnstock_news_feeds as nf
    import vnstock_report_digest as dg
    import vnstock_sentiment as snt

    tags: dict[tuple[str, str], list[str]] = {}

    def _add(provider: str, model: str, tag: str) -> None:
        if provider in _PROVIDERS:
            tags.setdefault((provider, model), []).append(tag)

    for p in snt._PROVIDERS:
        _add(p["name"], p["model"], "[1] sentiment")
    for prov, m in nf._ANALYZE_MODELS.items():
        _add(prov, m, "[2] analyze")
    for prov, m in dg._FREE_MODELS.items():
        _add(prov, m, "[3-6] digest b1")
    for prov, m in dg._FREE_TIER2:
        _add(prov, m, "[3-6] digest b2")
    for c in vb._DEFAULT_AGENT_CONFIGS:
        prov = _BRIEF_TYPE2PROVIDER.get(c["type"])
        if prov:
            _add(prov, c["model"], "[7] brief")
    for m in vb.CerebrasAgent._MODEL_FALLBACKS:
        _add("Cerebras", m, "[7] fallback")

    # [8] classifier CÁCH LY: module này kéo theo SDK vnstock + xác thực mạng.
    # Công cụ chẩn đoán LLM không được chết vì key DATA hết hạn — đó đúng lúc
    # cần nó nhất. Hỏng thì bỏ nấc [8] nhưng KÊU TO, không nuốt im lặng.
    try:
        import vnstock_classifier as vc
        classify_models = dict(vc._CLASSIFY_MODELS)
    except Exception as e:
        classify_models = {}
        print(f"⚠ KHÔNG đọc được slug [8] classifier ({type(e).__name__}: "
              f"{str(e)[:100]}) — ladder [8] KHÔNG được health-check lần này")
    for prov, m in classify_models.items():
        _add(prov, m, "[8] classifier")

    return [(prov, model, " + ".join(dict.fromkeys(ts)), {})
            for (prov, model), ts in tags.items()]


# ── Danh mục provider ────────────────────────────────────────────────────────

_CATALOG_PAGE_MAX = 12        # 12 × 400 = 4.800 model — thừa cho mọi provider


def _fetch_openai_catalog(url: str, headers: dict) -> "tuple[set, int | None]":
    """(slug, total_count) — đi hết các trang.

    OpenRouter trả `{data, links, total_count}` và CẮT ở 400/trang (xác minh
    trên máy user 08/08). Hai chiến lược nối trang, theo thứ tự: `links.next`
    (chuẩn) → tham số `offset` khi total_count nói còn thiếu.
    """
    ids: set = set()
    total: "int | None" = None
    seen: set = set()
    next_url, params, page = url, {}, 0

    while next_url and page < _CATALOG_PAGE_MAX:
        marker = (next_url, tuple(sorted(params.items())))
        if marker in seen:            # links.next trỏ vòng lại → thoát
            break
        seen.add(marker)
        page += 1
        r = requests.get(next_url, headers=headers, params=params or None,
                         timeout=_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        batch = {str(m.get("id", "")) for m in body.get("data", [])}
        batch.discard("")
        if not batch:
            break
        before = len(ids)
        ids |= batch
        if isinstance(body.get("total_count"), int):
            total = body["total_count"]

        links = body.get("links")
        nxt = links.get("next") if isinstance(links, dict) else None
        if nxt:
            next_url, params = str(nxt), {}
            continue
        # Không có next: chỉ đi tiếp khi total_count nói còn thiếu VÀ trang vừa
        # rồi có thêm slug mới (tránh lặp khi provider bỏ qua offset)
        if total is not None and len(ids) < total and len(ids) > before:
            next_url, params = url, {"offset": len(ids)}
            continue
        break
    return ids, total


def fetch_catalog(provider: str) -> "set[str] | None":
    """Tập slug provider đang công bố, hoặc None khi KHÔNG đọc được ĐỦ.

    None ≠ tập rỗng — điểm sống còn: gộp hai ca lại thì một lần mạng lỗi sẽ
    thành "toàn bộ model biến mất" và báo động giả hàng loạt.

    Đọc THIẾU cũng trả None (kèm dòng nói rõ lý do): diff một danh mục cụt
    sinh ra "bị gỡ" giả hàng tuần — thà không biết còn hơn báo sai.
    """
    cfg = _PROVIDERS.get(provider)
    if not cfg or not cfg.get("catalog"):
        return None
    key = _key_for(provider)
    if not key and not cfg.get("catalog_public"):
        return None
    try:
        if cfg["catalog_shape"] == "gemini":
            r = requests.get(cfg["catalog"],
                             params={"key": key, "pageSize": 200},
                             timeout=_TIMEOUT)
            r.raise_for_status()
            ids = {str(m.get("name", "")).removeprefix("models/")
                   for m in r.json().get("models", [])}
            ids.discard("")
            total = None
        else:
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            ids, total = _fetch_openai_catalog(cfg["catalog"], headers)

        if not ids:
            return None               # danh mục rỗng = đọc hụt, không phải thật
        if total is not None and len(ids) < total:
            print(f"⚠ {provider}: chỉ đọc được {len(ids)}/{total} model "
                  f"(phân trang chưa đi hết) — BỎ QUA diff lần này thay vì "
                  f"báo nhầm 'bị gỡ'")
            return None
        return ids
    except Exception as e:
        # KHÔNG nuốt im lặng: báo cáo chỉ in "không đọc được danh mục", không
        # kèm lý do thì không phân biệt được hết key / đổi endpoint / mạng
        # chập. Mọi lớp best-effort nuốt lỗi phải có một dòng chẩn đoán.
        print(f"⚠ {provider}: không đọc được danh mục — "
              f"{type(e).__name__}: {str(e)[:120]}")
        return None


def snapshot_catalogs() -> dict:
    """{provider: sorted list slug} — provider đọc hụt để None (xem fetch_catalog)."""
    out: dict[str, "list | None"] = {}
    for name in _PROVIDERS:
        got = fetch_catalog(name)
        out[name] = sorted(got) if got else None
    return out


# Mất quá tỉ lệ này trong MỘT tuần thì gần như chắc chắn là đọc thiếu (phân
# trang/response cụt) chứ không phải provider gỡ thật — gắn nhãn nghi ngờ.
_SUSPECT_DROP = 0.5
_SUSPECT_MIN = 10          # danh mục bé thì mất vài model là chuyện thường


def diff_catalogs(prev: dict, cur: dict) -> dict:
    """{provider: {gone, new, size, status}}.

    status ∈ ok | skipped | no_baseline | suspect_partial
      skipped         — lần này đọc hụt
      no_baseline     — chưa có snapshot trước (lần chạy đầu)
      suspect_partial — mất >50% danh mục trong 1 tuần: nghi đọc thiếu

    Hai trạng thái đầu trả gone/new RỖNG (thà không biết còn hơn báo sai).
    `suspect_partial` VẪN liệt kê gone — nhãn nghi ngờ để người soi tự quyết,
    không được nuốt mất tín hiệu "model đang dùng biến mất".
    """
    out: dict[str, dict] = {}
    for name in cur:
        now, before = cur.get(name), prev.get(name)
        if now is None:
            out[name] = {"gone": [], "new": [], "size": 0, "status": "skipped"}
            continue
        if before is None:
            out[name] = {"gone": [], "new": [], "size": len(now),
                         "status": "no_baseline"}
            continue
        gone = sorted(set(before) - set(now))
        new = sorted(set(now) - set(before))
        status = "ok"
        if len(before) >= _SUSPECT_MIN:
            if len(gone) > _SUSPECT_DROP * len(before):
                status = "suspect_partial"      # lần này đọc thiếu
            elif len(new) > _SUSPECT_DROP * len(before):
                status = "suspect_baseline"     # mốc CŨ mới là cái cụt
        out[name] = {"gone": gone, "new": new, "size": len(now),
                     "status": status}
    return out


def gone_models_in_use(diff: dict, in_use: dict) -> list:
    """Model BIẾN MẤT khỏi danh mục mà code ĐANG DÙNG → [(provider, model, tag)].

    Lọc theo "đang dùng" là chủ ý: danh mục provider đổi liên tục, báo mọi
    thay đổi thì tuần nào cũng có tin và người đọc sẽ bỏ qua hết.
    """
    hits = []
    for provider, d in diff.items():
        for model in d.get("gone", []):
            tag = in_use.get((provider, model))
            if tag:
                hits.append((provider, model, tag))
    return sorted(hits)


# ── Lịch sử ──────────────────────────────────────────────────────────────────

def load_history() -> dict:
    try:
        return json.loads((_META / _HISTORY_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {"runs": []}


def save_history(hist: dict) -> None:
    try:
        _META.mkdir(parents=True, exist_ok=True)
        hist["runs"] = hist.get("runs", [])[-_HISTORY_MAX:]
        (_META / _HISTORY_NAME).write_text(
            json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"⚠ không ghi được lịch sử model watch: {e}")


# ── Độ trễ theo tuần ─────────────────────────────────────────────────────────
# So với MEDIAN nhiều tuần, không so tuần liền trước: đêm 07/08 chạy dồn 4 lần
# trong 45 phút làm free tier bóp băng thông (0.9s → 17s) rồi tự hồi ngay sau
# đó. Một lần đo là nhiễu; median chịu được cú nhảy lẻ.
_SLOW_FACTOR = 3.0          # chậm gấp mấy lần median mới tính
_SLOW_MIN_SECONDS = 5.0     # sàn tuyệt đối: 0.8s → 2.4s cũng 3× nhưng vô hại
_SLOW_ALERT_SECONDS = 15.0  # tới đây thì sắp chạm timeout 25s của chat_complete
_LATENCY_MIN_SAMPLES = 2    # 1 mẫu không đủ làm median


def _latency_medians(hist: dict) -> dict:
    """{provider:model: median giây} từ các lần chạy trước.

    Bỏ qua run không có `probe_seconds` — lịch sử trước 08/08 chưa lưu khoá
    này, đọc mà không phòng là nổ trên đúng máy đang có dữ liệu cũ.
    """
    import statistics

    samples: dict[str, list] = {}
    for run in hist.get("runs", []):
        for key, secs in (run.get("probe_seconds") or {}).items():
            if isinstance(secs, (int, float)):
                samples.setdefault(key, []).append(float(secs))
    return {k: round(statistics.median(v), 3)
            for k, v in samples.items() if len(v) >= _LATENCY_MIN_SAMPLES}


def _latency_flags(rows: list, hist: dict) -> list:
    """Model chậm bất thường so với chính nó các tuần trước.

    Chỉ xét model CÒN SỐNG — model chết đã có cảnh báo riêng, đếm nó vào
    thống kê độ trễ chỉ làm nhiễu.
    """
    medians = _latency_medians(hist)
    out = []
    for r in rows:
        if not r.get("ok"):
            continue
        key = f"{r['provider']}:{r['model']}"
        med, now = medians.get(key), float(r.get("seconds") or 0)
        if not med or now < _SLOW_MIN_SECONDS or now < _SLOW_FACTOR * med:
            continue
        out.append({"key": key, "tag": r.get("tag", ""), "now": round(now, 2),
                    "median": med, "factor": round(now / med, 1),
                    "severe": now >= _SLOW_ALERT_SECONDS})
    return sorted(out, key=lambda d: -d["factor"])


def _last_catalogs(hist: dict) -> dict:
    for run in reversed(hist.get("runs", [])):
        if run.get("catalogs"):
            return run["catalogs"]
    return {}


# ── Cảnh báo ─────────────────────────────────────────────────────────────────

def _alert(lines: list) -> bool:
    """Báo Telegram — best-effort tuyệt đối, tắt bằng VNSTOCK_MODEL_WATCH_ALERT=0.

    CỐ Ý gửi cả khi chạy TAY, không chỉ khi task tự chạy: user chốt 10/08 —
    muốn có bản lưu trên điện thoại để theo dõi, chấp nhận trùng với output
    trên màn hình. Đừng "tối ưu" bằng cách bỏ alert lúc chạy tay.
    """
    if not lines or not _flag("VNSTOCK_MODEL_WATCH_ALERT"):
        return False
    try:
        from vnstock_telegram import send_message
        send_message("⚠️ <b>Model watch</b>\n" + "\n".join(lines))
        return True
    except Exception:
        return False


# ── Chạy ─────────────────────────────────────────────────────────────────────

def run_watch(do_eval: bool = False) -> dict:
    """Probe ladder + diff danh mục (+ chấm điểm khi do_eval). Ghi status file.

    Không bao giờ sửa config model — xem `vnstock_model_eval.propose_swaps`:
    kết quả chỉ là ĐỀ XUẤT để user duyệt.
    """
    _ensure_env_loaded()
    if not _flag("VNSTOCK_MODEL_WATCH"):
        status = {"ran_at": datetime.now().isoformat(), "level": "skipped",
                  "note": "VNSTOCK_MODEL_WATCH=0"}
        _write_status(status)
        return status

    slugs = _ladder_slugs()
    in_use = {(p, m): tag for p, m, tag, _ in slugs}

    rows = []
    for i, (prov, model, tag, extra) in enumerate(sorted(slugs)):
        if i:
            time.sleep(_SLEEP_BETWEEN)
        ok, desc, dt = probe_one(prov, model, extra or None)
        rows.append({"provider": prov, "model": model, "tag": tag,
                     "ok": bool(ok), "detail": desc, "seconds": round(dt, 2),
                     "rate_limited": (not ok) and _is_rate_limited(desc)})

    hist = load_history()
    catalogs = snapshot_catalogs()
    diff = diff_catalogs(_last_catalogs(hist), catalogs)
    gone_used = gone_models_in_use(diff, in_use)

    slow = _latency_flags(rows, hist)
    limited = [r for r in rows if r.get("rate_limited")]
    dead = [r for r in rows if not r["ok"] and not r.get("rate_limited")]
    n_fail = len(dead)
    severe_slow = [s for s in slow if s["severe"]]
    # Hết hạn mức chỉ là cảnh báo: model vẫn sống, mai có quota lại chạy.
    level = ("red" if n_fail
             else "warn" if (gone_used or severe_slow or limited) else "green")

    status = {
        "ran_at": datetime.now().isoformat(),
        "level": level,
        "probe": {"ok": sum(1 for r in rows if r["ok"]), "fail": n_fail,
                  "rate_limited": len(limited), "rows": rows},
        "catalog": {
            "diff": diff,
            "gone_in_use": [{"provider": p, "model": m, "tag": t}
                            for p, m, t in gone_used],
            "skipped": sorted(k for k, v in diff.items()
                              if v["status"] == "skipped"),
        },
        "latency": {"slow": slow},
        "eval": None,
        "proposals": [],
    }

    if do_eval and _flag("VNSTOCK_MODEL_WATCH_EVAL"):
        status.update(_run_eval_stage(rows, hist))

    _write_status(status)
    hist.setdefault("runs", []).append({
        "at": status["ran_at"], "level": level, "catalogs": catalogs,
        "proposals": status["proposals"],
        # Lưu từ 08/08 để tuần sau so được độ trễ — không có dữ liệu thì
        # không có median, nên phải bắt đầu tích từ đâu đó.
        "probe_seconds": {f"{r['provider']}:{r['model']}": r["seconds"]
                          for r in rows if r["ok"]},
        "eval_measured": status.get("eval_measured") or [],
    })
    save_history(hist)

    alert_lines = [f"❌ {r['provider']} {r['model']} — {r['tag']}: {r['detail'][:80]}"
                   for r in dead]
    alert_lines += [f"🗑 {p} {m} biến mất khỏi danh mục — {t}"
                    for p, m, t in gone_used]
    alert_lines += [f"🐌 {s['key']} chậm {s['factor']}× ({s['now']}s so median "
                    f"{s['median']}s) — {s['tag']}" for s in severe_slow]
    _alert(alert_lines)
    return status


def _eval_order(models: list, hist: dict) -> list:
    """Model CHƯA đo lần gần nhất lên đầu — xoay vòng.

    Không xoay thì model bị cắt vì hạn mức (xem `EVAL_BUDGET`) sẽ không bao
    giờ được đo: lần nào cũng đứng cuối hàng và lần nào cũng hết quota.
    """
    last = set()
    for run in reversed(hist.get("runs", [])):
        if run.get("eval_measured"):
            last = set(run["eval_measured"])
            break
    return sorted(models, key=lambda pm: (f"{pm[0]}:{pm[1]}" in last, pm))


def _run_eval_stage(rows: list, hist: dict) -> dict:
    """GĐ2-3 — chấm bộ đề rồi sinh đề xuất. Tách hàm để GĐ1 chạy độc lập
    được (eval tốn call hơn hẳn: ~23 ca × số model)."""
    try:
        import vnstock_model_eval as me
    except Exception as e:
        return {"eval": {"error": f"{type(e).__name__}: {e}"}}

    alive = _eval_order([(r["provider"], r["model"]) for r in rows if r["ok"]],
                        hist)
    # PHẢI truyền delay: bộ đề ~25 ca × ~10 model = ~250 call. Mặc định của
    # run_eval là 0 (cho test/thư viện chạy nhanh) — bắn 250 call liên tiếp
    # lên free tier là dính rate limit ngay (Groq TPM 8K).
    scores = me.run_eval(alive, delay=_SLEEP_BETWEEN, budget=me.EVAL_BUDGET)
    prev = next((r.get("proposals") or [] for r in reversed(hist.get("runs", []))
                 if r.get("proposals") is not None), [])
    proposals = me.propose_swaps(scores, me.current_models(),
                                 previous_proposals=prev)
    return {
        "eval": {f"{p}:{m}": sc for (p, m), sc in scores.items()},
        "eval_measured": [f"{p}:{m}" for (p, m), sc in scores.items()
                          if not sc.get("skipped")],
        "proposals": proposals,
    }


def _write_status(status: dict) -> None:
    try:
        _META.mkdir(parents=True, exist_ok=True)
        (_META / _STATUS_NAME).write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"⚠ không ghi được {_STATUS_NAME}: {e}")


# ── In báo cáo ───────────────────────────────────────────────────────────────

_LEVEL_ICON = {"green": "✅", "warn": "⚠️", "red": "❌", "skipped": "⏭"}


def render_report(status: dict) -> str:
    if status.get("level") == "skipped":
        return f"⏭ model watch bỏ qua ({status.get('note', '')})"
    out = [f"{_LEVEL_ICON.get(status['level'], '?')} MODEL WATCH — "
           f"{status['ran_at'][:16].replace('T', ' ')}"]

    pr = status["probe"]
    slow = (status.get("latency") or {}).get("slow") or []
    slow_keys = {s["key"] for s in slow}
    n_lim = pr.get("rate_limited", 0)
    head = f"{pr['ok']} sống / {pr['fail']} chết"
    if n_lim:
        head += f" / {n_lim} hết hạn mức"
    out.append(f"\n── Probe ladder: {head} ──")
    for r in pr["rows"]:
        mark = " 🐌" if f"{r['provider']}:{r['model']}" in slow_keys else ""
        icon = "✅" if r["ok"] else ("⏳" if r.get("rate_limited") else "❌")
        out.append(f"  {icon} {r['provider']:<11}"
                   f"{r['model']:<45}{r['seconds']:>5.1f}s  {r['tag']}{mark}")
        if not r["ok"]:
            out.append(f"       ↳ {r['detail'][:110]}")
    if n_lim:
        out.append("     ⏳ = HẾT HẠN MỨC hôm nay, KHÔNG phải model chết — mai "
                   "có quota là chạy lại. Nếu do chính `--eval` đốt thì giãn "
                   "lịch chạy, đừng vội kết luận provider hỏng.")

    if slow:
        out.append("\n── Chậm bất thường (so median các tuần trước) ──")
        for s in slow:
            icon = "🚨" if s["severe"] else "🐌"
            out.append(f"  {icon} {s['key']:<52}{s['now']:>6.1f}s "
                       f"(median {s['median']}s · chậm {s['factor']}×) {s['tag']}")
        if any(s["severe"] for s in slow):
            out.append(f"     ⚠ Mốc {_SLOW_ALERT_SECONDS:.0f}s là để so với "
                       f"timeout 25s của chat_complete ([1] sentiment, "
                       f"[2] chấm tin, [8] classifier) — prompt thật nặng hơn "
                       f"ping rất nhiều.")

    cat = status["catalog"]
    out.append("\n── Danh mục provider (so tuần trước) ──")
    for prov, d in sorted(cat["diff"].items()):
        size = d.get("size", 0)
        if d["status"] == "skipped":
            out.append(f"  ⏭ {prov:<11} không đọc được danh mục lần này")
        elif d["status"] == "no_baseline":
            out.append(f"  · {prov:<11} lần đầu — đã lưu mốc {size} model "
                       f"để tuần sau so")
        elif d["status"] == "suspect_partial":
            out.append(f"  ❓ {prov:<11} còn {size} model, mất {len(d['gone'])} "
                       f"— NGHI ĐỌC THIẾU hơn là bị gỡ thật, soi kỹ trước khi tin")
            for m in d["gone"][:6]:
                out.append(f"       ? vắng: {m}")
        elif d["status"] == "suspect_baseline":
            out.append(f"  ❓ {prov:<11} {size} model, +{len(d['new'])} so tuần "
                       f"trước — NGHI MỐC CŨ BỊ CỤT (đọc thiếu lần trước), "
                       f"không phải provider ra loạt model mới")
        elif not d["gone"] and not d["new"]:
            out.append(f"  · {prov:<11} không đổi ({size} model)")
        else:
            out.append(f"  ⚠ {prov:<11} -{len(d['gone'])} / +{len(d['new'])} "
                       f"(còn {size})")
            for m in d["gone"][:6]:
                out.append(f"       🗑 gỡ:  {m}")
            for m in d["new"][:6]:
                out.append(f"       🆕 mới: {m}")

    if cat["gone_in_use"]:
        out.append("\n🚨 MODEL ĐANG DÙNG ĐÃ BIẾN MẤT KHỎI DANH MỤC:")
        for g in cat["gone_in_use"]:
            out.append(f"  {g['provider']} {g['model']} — {g['tag']}")

    if status.get("eval"):
        out.append("\n── Điểm bộ đề (theo TỪNG việc, thang 0-1) ──")
        err = status["eval"].get("error") if isinstance(status["eval"], dict) else None
        if err:
            out.append(f"  (không chấm được: {err})")
        else:
            for key, sc in sorted(status["eval"].items(),
                                  key=lambda kv: -sum(
                                      v for t, v in kv[1].items()
                                      if t not in ("errors", "coverage")
                                      and isinstance(v, (int, float)))):
                if sc.get("skipped") == "budget":
                    out.append(f"  {key:<52} (để tuần sau — chạm hạn mức "
                               f"call/lần của provider)")
                    continue
                cov = sc.get("coverage") or {}
                parts = []
                for t in ("classify", "sentiment", "json"):
                    if t in sc:
                        parts.append(f"{t}={sc[t]:.2f}")
                    elif t in cov:
                        # KHÔNG ĐO ĐƯỢC ≠ 0 điểm: hạn mức của ta, không phải
                        # model dở. Ghi rõ để không ai đọc nhầm thành "kém".
                        parts.append(f"{t}=n/a")
                err = sc.get("errors") or 0
                tail = f"   ⚠ {err} ca hụt" if err else ""
                out.append(f"  {key:<52} {' '.join(parts)}{tail}")
            if any((sc.get("errors") or 0) for sc in status["eval"].values()
                   if isinstance(sc, dict)):
                out.append("     ⚠ 'n/a' = không đo được (hụt >30% số ca, "
                           "thường do hạn mức free tier) — KHÔNG phải điểm 0. "
                           "Đừng so hạng khi còn n/a.")

    if status.get("proposals"):
        out.append("\n── ĐỀ XUẤT (chỉ đề xuất — không tự áp) ──")
        for p in status["proposals"]:
            mark = "🟢 CHÍN" if p["ripe"] else "🟡 chờ tuần sau xác nhận"
            out.append(f"  {mark} · {p['task']}: {p['current'][0]}:{p['current'][1]}"
                       f" ({p['current_score']:.2f}) → "
                       f"{p['candidate'][0]}:{p['candidate'][1]}"
                       f" ({p['candidate_score']:.2f})")
        out.append("  Áp dụng: sửa map model của điểm tương ứng rồi chạy "
                   "`python run.py test --fast`")
    return "\n".join(out)


def main(argv: "list | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Theo dõi ladder model LLM (probe + diff danh mục)")
    ap.add_argument("--eval", action="store_true",
                    help="Chấm thêm bộ đề chuẩn + sinh đề xuất (tốn call hơn)")
    ap.add_argument("--json", action="store_true", help="In JSON thay vì bảng")
    args = ap.parse_args(argv)

    status = run_watch(do_eval=args.eval)
    print(json.dumps(status, ensure_ascii=False, indent=2) if args.json
          else render_report(status))
    return {"green": 0, "skipped": 0, "warn": 1, "red": 2}.get(status["level"], 1)


if __name__ == "__main__":
    raise SystemExit(main())

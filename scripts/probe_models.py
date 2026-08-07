#!/usr/bin/env python3
"""
scripts/probe_models.py — thăm dò slug model LLM trước khi thay ladder
=======================================================================
Bài học 14/07: thay model theo catalog trên mạng → kimi-k2/llama-4-maverick
đều model_not_found. Script này gọi 1 call thử/slug (vài chục token, toàn
free tier → chi phí ~0) để chốt danh sách slug SỐNG trên máy thật, rồi mới
sửa ladder trong code.

Chạy trên máy Windows (nơi có .env đầy đủ key):

    python scripts/probe_models.py

Dán TOÀN BỘ output cho Claude. Thiếu key provider nào → provider đó SKIP
(muốn probe Gemini: tạo key free tại https://aistudio.google.com/apikey,
điền GEMINI_API_KEY vào .env).

Script CHỈ ĐỌC, không sửa gì — không đụng warehouse/ledger/config.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

_REPO = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env", override=False)
except Exception:
    pass

_TIMEOUT = 45
_MAX_TOKENS = 256          # model reasoning (gpt-oss/qwen3) cần chỗ "suy nghĩ"
_SLEEP_BETWEEN = 1.0       # lịch sự với rate limit free tier

# Cùng họ regex strip_think_tags của vnstock_sentiment (bản rút gọn, chỉ để
# preview output — không dùng cho logic gì khác).
_THINK_RE = re.compile(r"<\s*(think|thinking|reasoning|thought)\s*>.*?<\s*/\s*\1\s*>\s*",
                       re.S | re.I)

_PROVIDERS = {
    "Groq": {
        "env": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
    },
    "Cerebras": {
        "env": "CEREBRAS_API_KEY",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
    },
    "OpenRouter": {
        "env": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    },
    "Gemini": {
        # Google AI Studio, endpoint OpenAI-compatible. Key: GEMINI_API_KEY
        # (fallback GOOGLE_API_KEY).
        "env": "GEMINI_API_KEY",
        "env_alt": "GOOGLE_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    },
}

# (provider, model, ghi chú, extra_body)
# VÒNG 2 (22/07) — vòng 1 đã chốt: Groq gpt-oss-20b/120b + qwen3.6-27b ✅,
# Cerebras chỉ còn gpt-oss-120b ✅, OpenRouter gpt-oss-20b:free ✅; toàn bộ
# llama cũ + qwen-235b:free chết. Vòng này verify nốt slug Gemini 3.x
# (dòng 2.5 khóa với user mới) + 3 model :free mới trên OpenRouter.
_CANDIDATES: list[tuple[str, str, str, dict]] = [
    # ── Gemini (slug lấy từ chính listing key của user, vòng 1) ─────────
    ("Gemini", "gemini-3.5-flash-lite",         "ứng viên CHÍNH [1] sentiment",  {}),
    ("Gemini", "gemini-3.5-flash",              "ứng viên [2][8]",               {}),
    ("Gemini", "gemini-flash-lite-latest",      "alias tự trỏ bản mới nhất",     {}),
    # ── OpenRouter (từ danh sách :free thật, vòng 1) ────────────────────
    ("OpenRouter", "nvidia/nemotron-3-super-120b-a12b:free", "ứng viên [2][3] lớp 70-120B", {}),
    ("OpenRouter", "nvidia/nemotron-3-ultra-550b-a55b:free", "ứng viên [3] bậc 1 digest",   {}),
    ("OpenRouter", "google/gemma-4-31b-it:free",             "ứng viên [1] dự phòng",       {}),
]


# Map agent type (vnstock_brief) → tên provider trong _PROVIDERS.
_BRIEF_TYPE2PROVIDER = {"gemini": "Gemini", "groq": "Groq",
                        "cerebras": "Cerebras", "openrouter": "OpenRouter"}


def _ladder_slugs() -> list[tuple[str, str, str, dict]]:
    """--ladder: gom slug free ĐANG DÙNG trong code (mirror _all_live_slugs
    của tests/test_model_ladder.py, chỉ 4 provider free probe được — model
    trả phí Anthropic/OpenAI khác API, bỏ qua). Mỗi slug kèm tag điểm dùng
    ([1] sentiment…[8] classifier) để nhìn output biết lỗi rơi vào tính năng
    nào. THÊM ĐIỂM DÙNG MODEL MỚI → phải khai vào đây, không thì health check
    mù đúng chỗ đó (test_probe_ladder_covers_all_free_live_slugs canh việc này).
    Health check chạy SAU sự cố key/deprecation: 1 call/slug, chi phí ~0."""
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
    # [8] classifier CÁCH LY: module này kéo theo cả SDK vnstock + xác thực
    # mạng (máy user 07/08: --ladder in "Authentication successful … golden").
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


def _key_for(provider: str) -> str:
    cfg = _PROVIDERS[provider]
    key = (os.environ.get(cfg["env"]) or "").strip()
    if not key and cfg.get("env_alt"):
        key = (os.environ.get(cfg["env_alt"]) or "").strip()
    return key


def _preview(text: str) -> str:
    out = _THINK_RE.sub("", text or "").strip()
    out = re.sub(r"\s+", " ", out)
    return out[:40] or "(rỗng sau strip think)"


def probe_one(provider: str, model: str, extra: dict) -> tuple[bool, str, float]:
    """1 call thử → (ok, mô tả, giây). Lỗi trả mô tả ngắn để chẩn đoán."""
    cfg = _PROVIDERS[provider]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with exactly: OK"},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": _MAX_TOKENS,
        **extra,
    }
    t0 = time.time()
    try:
        r = requests.post(
            cfg["endpoint"],
            headers={"Authorization": f"Bearer {_key_for(provider)}",
                     "Content-Type": "application/json"},
            json=body, timeout=_TIMEOUT,
        )
        dt = time.time() - t0
        if r.status_code != 200:
            snippet = re.sub(r"\s+", " ", r.text or "")[:140]
            # Param không được nhận (vd reasoning_effort) → thử lại không param
            if r.status_code == 400 and extra and any(k in (r.text or "") for k in extra):
                ok, desc, dt2 = probe_one(provider, model, {})
                return ok, f"{desc} (bỏ {'/'.join(extra)})", dt + dt2
            return False, f"HTTP {r.status_code}: {snippet}", dt
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return True, f"→ \"{_preview(content)}\"", dt
    except requests.Timeout:
        return False, f"timeout >{_TIMEOUT}s", time.time() - t0
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}", time.time() - t0


def list_openrouter_free() -> None:
    """Danh sách :free ĐẦY ĐỦ hiện tại từ API public (không cần key)."""
    print("\n── OpenRouter: toàn bộ model :free hiện có ──")
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=_TIMEOUT)
        r.raise_for_status()
        free = sorted(m["id"] for m in r.json().get("data", [])
                      if str(m.get("id", "")).endswith(":free"))
        for mid in free:
            print(f"   {mid}")
        print(f"   (tổng: {len(free)} model :free)")
    except Exception as e:
        print(f"   (không lấy được: {type(e).__name__}: {str(e)[:100]})")


def list_and_probe_cerebras() -> None:
    """Hỏi thẳng API Cerebras còn model nào (vòng 1: mọi slug đoán đều 404),
    rồi probe luôn các model lạ (trừ gpt-oss-120b đã xác nhận sống)."""
    key = _key_for("Cerebras")
    if not key:
        return
    print("\n── Cerebras: catalog thật từ GET /v1/models ──")
    try:
        r = requests.get("https://api.cerebras.ai/v1/models",
                         headers={"Authorization": f"Bearer {key}"},
                         timeout=_TIMEOUT)
        r.raise_for_status()
        ids = sorted(str(m.get("id", "")) for m in r.json().get("data", []))
        for mid in ids:
            print(f"   {mid}")
        todo = [m for m in ids if m and m != "gpt-oss-120b"][:5]
        if todo:
            print("   → probe thử các model trên (tối đa 5):")
        for mid in todo:
            time.sleep(_SLEEP_BETWEEN)
            ok, desc, dt = probe_one("Cerebras", mid, {})
            print(f"   {'✅' if ok else '❌'} {mid:40s} {dt:5.1f}s  {desc}")
    except Exception as e:
        print(f"   (không lấy được: {type(e).__name__}: {str(e)[:100]})")


def list_gemini_models() -> None:
    """Model Gemini khả dụng với key hiện tại (xác nhận slug 2.5 flash)."""
    key = _key_for("Gemini")
    if not key:
        return
    print("\n── Gemini: model khả dụng với key này (lọc 'flash') ──")
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key, "pageSize": 100}, timeout=_TIMEOUT)
        r.raise_for_status()
        names = [m.get("name", "").removeprefix("models/")
                 for m in r.json().get("models", [])]
        for n in sorted(n for n in names if "flash" in n):
            print(f"   {n}")
    except Exception as e:
        print(f"   (không lấy được: {type(e).__name__}: {str(e)[:100]})")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Probe slug model LLM (1 call thử/slug — chi phí ~0)")
    ap.add_argument(
        "--slug", action="append", default=[], metavar="Provider=model",
        help='Probe CHỈ slug này, lặp lại được — vd --slug "Groq=qwen/qwen4-30b". '
             "Provider ∈ Groq/Cerebras/OpenRouter/Gemini. "
             "Không có --slug → chạy trọn bộ mặc định + listing catalog.")
    ap.add_argument(
        "--ladder", action="store_true",
        help="Probe ĐÚNG bộ slug free đang dùng trong code (health check "
             "toàn ladder [1]-[8] sau sự cố key/deprecation); bỏ listing "
             "catalog. Kết hợp được với --slug.")
    args = ap.parse_args(argv)

    candidates = list(_CANDIDATES)
    if args.ladder or args.slug:      # chế độ chọn lọc: bỏ danh sách ứng viên
        candidates = []
    if args.ladder:
        candidates += _ladder_slugs()
    if args.slug:                     # chế độ ad-hoc: probe thêm slug được nêu
        for part in args.slug:
            name, sep, model = part.partition("=")
            name = name.strip()
            if sep and name in _PROVIDERS and model.strip():
                candidates.append((name, model.strip(), "slug ad-hoc (--slug)", {}))
            else:
                print(f"⚠️  bỏ qua --slug không hợp lệ: {part!r} "
                      f"(dạng Provider=model, Provider ∈ {'/'.join(_PROVIDERS)})")

    print("=" * 74)
    print("PROBE MODEL LLM — chạy xong DÁN TOÀN BỘ OUTPUT cho Claude")
    print(time.strftime("Thời điểm: %Y-%m-%d %H:%M:%S"))
    print("=" * 74)

    for provider, cfg in _PROVIDERS.items():
        label = cfg["env"] + (f" (hoặc {cfg['env_alt']})" if cfg.get("env_alt") else "")
        print(f"key {provider:11s} {label:40s} "
              f"{'✅ có' if _key_for(provider) else '⏭️  THIẾU → skip'}")

    last_provider = None
    for provider, model, note, extra in candidates:
        if not _key_for(provider):
            print(f"⏭️  {provider:10s} {model:45s} SKIP (thiếu key)")
            continue
        if last_provider is not None:
            time.sleep(_SLEEP_BETWEEN)
        last_provider = provider
        ok, desc, dt = probe_one(provider, model, dict(extra))
        icon = "✅" if ok else "❌"
        print(f"{icon} {provider:10s} {model:45s} {dt:5.1f}s  {note}")
        print(f"   {desc}")

    if not (args.slug or args.ladder):  # listing catalog chỉ ở chế độ đầy đủ
        list_openrouter_free()
        list_and_probe_cerebras()
        list_gemini_models()

    print("\n" + "=" * 74)
    print("XONG — copy toàn bộ output phía trên (từ dòng PROBE MODEL LLM) cho Claude.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())

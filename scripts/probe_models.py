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

# Logic probe (provider, gọi thử, gom slug đang dùng) nay là NGUỒN DUY NHẤT
# ở vnstock_model_watch.py — script này còn là CLI mỏng. Trước 07/08 hai bản
# tồn tại song song, đúng kiểu 'replica trôi xa bản thật' mà audit 06/08 bắt.
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from vnstock_model_watch import (_MAX_TOKENS, _PROVIDERS,  # noqa: E402
                                 _SLEEP_BETWEEN, _TIMEOUT, _key_for,
                                 _ladder_slugs, _preview, probe_one)

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

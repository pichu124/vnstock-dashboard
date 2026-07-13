#!/usr/bin/env python3
"""vnstock_report_digest.py — Digest báo cáo vĩ mô bằng LLM + cross-check + tilt (Phase 3).

Vị trí trong thiết kế (user duyệt 2026-07-13)
---------------------------------------------
P2 (`vnstock_reports`) đã có thư viện báo cáo (text + metadata). Phase 3 biến
mỗi báo cáo đủ điều kiện thành **digest có cấu trúc** rồi tổng hợp thành
**consensus → tilt ±1 band** cho `vnstock_allocation`:

* **Digest** (1 call LLM/báo cáo): JSON {tom_tat, stance 5 lớp tài sản
  (-2..+2, 0 = TRUNG_LẬP được phép), claims số + kỳ, risks}. Nguồn tiếng Anh
  → digest DỊCH sang tiếng Việt (brief có luật thuần-tiếng-Việt).
* **Provider**: key trả phí trước — Claude (ANTHROPIC_API_KEY) → GPT
  (OPENAI_API_KEY); ladder free 70B (Groq→Cerebras→OpenRouter qua
  `vnstock_sentiment.chat_complete`) CHỈ làm fallback (TODO 1b: 70B free yếu).
  Chi phí nhỏ: 1-2 báo cáo/tháng × ~2K token.
* **Sanitize cấu trúc**: mọi text từ LLM bị strip `#`/emoji/CJK + ép 1 dòng —
  digest sẽ được splice vào brief (P4) nên KHÔNG được chứa token mà
  section-parser của guard chain hiểu nhầm là ranh giới mục.
* **Cross-check số — REGISTRY THẮNG** (mirror `_fx_crosscheck`): claim mang
  key thuộc registry 13 chỉ số được so với giá trị registry hiện hành; lệch
  quá dung sai → cờ ``mismatch`` trên claim + ``has_mismatch`` trên digest.
  Claim mismatch KHÔNG được vào brief (P4 lọc); stance vẫn dùng cho consensus
  (quan điểm ≠ số đo — số sai thì số bị chặn, quan điểm giữ nhưng có cờ).
  Số từ báo cáo KHÔNG BAO GIỜ ghi vào registry (nguyên tắc #2).
* **Consensus + tilt**: stance "Cổ phiếu" trung bình có trọng số decay tuổi
  (≤30 ngày = 1.0, tuyến tính về 0 ở 90 ngày — đúng tham số duyệt) trên các
  digest hợp lệ. |consensus| ≥ ``_TILT_THRESHOLD`` (1.0) → tilt ∓1 band.
  Allocation áp tilt SAU band data (P1) — chỉ ±1, KHÔNG override data sống.

Cache: digest nằm NGAY TRONG record của ``reports_index.json``
(``rec["digest"]``) — một nguồn sự thật, xoá báo cáo là digest đi theo.

CLI::

    python vnstock_report_digest.py --refresh          # digest báo cáo chưa có
    python vnstock_report_digest.py --refresh --redigest   # chấm lại TẤT CẢ
    python vnstock_report_digest.py --show <id>
    python vnstock_report_digest.py --consensus        # stance tổng hợp + tilt
    python vnstock_report_digest.py --diag             # thử 1 call LLM (cần key)

Tắt tilt phía allocation: env ``VNSTOCK_ALLOCATION_TILT=0``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

import vnstock_reports as _rp

# Stance khai báo trên đúng 5 lớp tài sản của bảng phân bổ.
_ASSET_CLASSES = ("Cổ phiếu", "Trái phiếu", "Tiền gửi", "Vàng", "USD")

# Decay tuổi (tham số user duyệt): trọng số 1.0 tới 30 ngày, tuyến tính về 0
# ở 90 ngày (load_for_analysis đã loại > 90).
_DECAY_FULL_DAYS = 30
_DECAY_ZERO_DAYS = 90

# |consensus stance Cổ phiếu| phải ≥ ngưỡng này mới tilt (thang -2..+2 —
# 1.0 = các báo cáo nghiêng RÕ một chiều, không phải nhiễu quanh trung lập).
_TILT_THRESHOLD = 1.0

_PROMPT_MAX_CHARS = 12_000     # phần thân báo cáo đưa vào prompt
_DIGEST_MAX_TOKENS = 700

# Model mặc định — mirror brief agents (ClaudeAgent/OpenAIAgent).
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = "gpt-4o-mini"
_FREE_MODELS = {                # fallback ladder — 70B mạnh nhất mỗi provider
    "Groq": "llama-3.3-70b-versatile",
    "Cerebras": "llama3.3-70b",
    "OpenRouter": "meta-llama/llama-3.3-70b-instruct:free",
}

# Dung sai cross-check theo key registry (kỳ báo cáo có thể lệch kỳ registry
# nên dung sai RỘNG có chủ đích — chỉ chặn số SAI HẲN, không bắt nạt lệch kỳ).
#   ("rel", x) — lệch tương đối x%   ·   ("abs", x) — lệch tuyệt đối x đơn vị
_CLAIM_TOLERANCE: dict[str, tuple[str, float]] = {
    "usdvnd":              ("rel", 2.0),
    "sbv_policy_rate":     ("abs", 0.5),
    "interbank_on":        ("abs", 1.0),   # LNH dao động mạnh theo tuần
    "interbank_1w":        ("abs", 1.0),
    "govt_bond_yield_2y":  ("abs", 0.5),
    "govt_bond_yield_10y": ("abs", 0.5),
    "us10y":               ("abs", 0.5),
    "fed_funds":           ("abs", 0.5),
    "cpi_yoy":             ("abs", 1.0),
    "iip_yoy":             ("abs", 3.0),   # IIP tháng biến động lớn
    "pmi":                 ("abs", 2.0),
    "gdp_yoy":             ("abs", 1.5),
    "trade_balance":       ("abs", 2.0),   # tỷ USD, kỳ tháng ≠ lũy kế
}


def _registry_keys() -> list[str]:
    try:
        from vnstock_macro import _DEFS
        return list(_DEFS)
    except Exception:
        return list(_CLAIM_TOLERANCE)


# ── Sanitize (digest sẽ vào brief — không được phá section parser) ──────────

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")          # mirror enforce_no_cjk
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def sanitize_text(s: str) -> str:
    """1 dòng sạch: bỏ #/emoji/CJK/xuống dòng — an toàn để splice vào brief."""
    s = str(s or "")
    s = _CJK_RE.sub("", s)
    s = _EMOJI_RE.sub("", s)
    s = s.replace("#", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── LLM call (Claude → GPT → ladder free) ───────────────────────────────────

_DIGEST_SYSTEM = (
    "Bạn tóm tắt BÁO CÁO VĨ MÔ cho nhà đầu tư Việt Nam. Trả về DUY NHẤT một "
    "JSON object (không markdown, không giải thích) đúng schema:\n"
    '{"tom_tat": "<2-3 câu tiếng Việt tóm quan điểm vĩ mô chính>",\n'
    ' "stance": {"Cổ phiếu": <-2..2>, "Trái phiếu": <-2..2>, "Tiền gửi": <-2..2>,'
    ' "Vàng": <-2..2>, "USD": <-2..2>},\n'
    ' "claims": [{"key": "<key>", "value": <số>, "unit": "<đơn vị>",'
    ' "period": "<kỳ, vd 2026-06 / Q2/2026>", "text": "<trích ngắn>"}],\n'
    ' "risks": ["<rủi ro 1>", "<rủi ro 2>"]}\n'
    "Quy tắc: stance = quan điểm CỦA BÁO CÁO về từng lớp tài sản 3-6 tháng tới "
    "(-2 rất tiêu cực, 0 = trung lập/không nêu — ĐƯỢC PHÉP, +2 rất tích cực). "
    "claims CHỈ gồm số liệu vĩ mô báo cáo nêu RÕ RÀNG, key lấy từ danh sách: "
    "{keys} — không khớp key nào thì dùng \"khac\". Báo cáo tiếng Anh vẫn trả "
    "lời HOÀN TOÀN tiếng Việt. Số dùng định dạng EN (chấm thập phân). "
    "KHÔNG bịa số không có trong báo cáo."
)


def _call_claude(system: str, user: str,
                 max_tokens: int = _DIGEST_MAX_TOKENS) -> "str | None":
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import requests as _req
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"},
            json={"model": _CLAUDE_MODEL, "max_tokens": max_tokens,
                  "temperature": 0, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=90)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception:
        return None


def _call_openai(system: str, user: str,
                 max_tokens: int = _DIGEST_MAX_TOKENS) -> "str | None":
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import requests as _req
        resp = _req.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            json={"model": _OPENAI_MODEL, "max_tokens": max_tokens,
                  "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=90)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def digest_call(system: str, user: str) -> tuple["str | None", str]:
    """(raw_text, provider) qua ladder: Claude → GPT → free 70B. (None, '')
    khi không key nào chạy được."""
    raw = _call_claude(system, user)
    if raw:
        return raw, "claude"
    raw = _call_openai(system, user)
    if raw:
        return raw, "openai"
    try:
        from vnstock_sentiment import chat_complete
        raw = chat_complete(system, user, max_tokens=_DIGEST_MAX_TOKENS,
                            model_map=_FREE_MODELS)
        if raw:
            return raw, "free-ladder"
    except Exception:
        pass
    return None, ""


# ── Parse + validate digest JSON ─────────────────────────────────────────────


def parse_digest(raw: str) -> "dict | None":
    """JSON từ output LLM → digest đã validate/sanitize; None khi vô phương.

    Chấp nhận JSON lẫn trong văn bản/code fence (lấy từ ``{`` đầu tới ``}``
    cuối). stance ép int và clamp -2..+2, lớp thiếu → 0 (trung lập); claims
    giữ dòng có ``value`` số; mọi text qua ``sanitize_text``.
    """
    if not raw:
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    stance_in = data.get("stance") or {}
    stance = {}
    for cls in _ASSET_CLASSES:
        try:
            stance[cls] = max(-2, min(2, int(round(float(stance_in.get(cls, 0))))))
        except (TypeError, ValueError):
            stance[cls] = 0

    claims = []
    for c in (data.get("claims") or []):
        if not isinstance(c, dict):
            continue
        try:
            value = float(c.get("value"))
        except (TypeError, ValueError):
            continue
        claims.append({
            "key":    sanitize_text(c.get("key") or "khac").lower() or "khac",
            "value":  value,
            "unit":   sanitize_text(c.get("unit") or ""),
            "period": sanitize_text(c.get("period") or ""),
            "text":   sanitize_text(c.get("text") or "")[:160],
        })

    risks = [sanitize_text(r)[:160] for r in (data.get("risks") or [])
             if sanitize_text(r)]
    return {
        "tom_tat": sanitize_text(data.get("tom_tat") or "")[:400],
        "stance":  stance,
        "claims":  claims,
        "risks":   risks[:5],
    }


# ── Cross-check với registry (REGISTRY THẮNG) ───────────────────────────────


def cross_check_claims(claims: list[dict],
                       macro: "list[dict] | None") -> bool:
    """Đối chiếu claim số với registry — mutate cờ ``mismatch`` từng claim,
    trả True khi có ít nhất 1 mismatch.

    Registry là SỐ ĐO, báo cáo là QUAN ĐIỂM: lệch quá dung sai → claim bị cờ
    (P4 không đưa vào brief), registry KHÔNG bao giờ bị sửa theo báo cáo.
    Claim key "khac"/không có trong registry → bỏ qua (không có gì để đối
    chiếu). Registry trống → không check được, không cờ ai.
    """
    rows = {m.get("key"): m for m in (macro or [])}
    any_mismatch = False
    for c in claims:
        key = c.get("key")
        row = rows.get(key)
        tol = _CLAIM_TOLERANCE.get(key)
        if not row or not tol or row.get("value") is None:
            continue
        reg, val = float(row["value"]), float(c["value"])
        mode, lim = tol
        diff_ok = (abs(val - reg) / max(abs(reg), 1e-9) * 100 <= lim) \
            if mode == "rel" else (abs(val - reg) <= lim)
        if not diff_ok:
            c["mismatch"] = True
            c["registry_value"] = reg
            c["registry_as_of"] = row.get("as_of")
            any_mismatch = True
    return any_mismatch


# ── Digest 1 báo cáo + refresh cả thư viện ──────────────────────────────────


def digest_report(rec: dict, text: "str | None" = None) -> "dict | None":
    """Digest 1 báo cáo (1 call LLM) + cross-check. Trả digest dict hoặc None
    (không provider / parse fail) — KHÔNG tự ghi index (caller ghi)."""
    text = text if text is not None else _rp.load_report_text(rec["id"])
    if not text.strip():
        return None
    system = _DIGEST_SYSTEM.replace("{keys}", ", ".join(_registry_keys()))
    user = (f"Nguồn: {rec.get('source', '?')} — ngày báo cáo "
            f"{rec.get('report_date', '?')} — {rec.get('title') or ''}\n\n"
            f"{text[:_PROMPT_MAX_CHARS]}")
    raw, provider = digest_call(system, user)
    if not raw:
        print(f"[digest] ❌ {rec['id']}: không provider nào trả lời "
              f"(cần ANTHROPIC/OPENAI key, hoặc GROQ/CEREBRAS/OPENROUTER)")
        return None
    digest = parse_digest(raw)
    if digest is None:
        print(f"[digest] ❌ {rec['id']}: output không parse được JSON")
        return None
    try:
        from vnstock_macro import load_macro
        macro = load_macro()
    except Exception:
        macro = []
    digest["has_mismatch"] = cross_check_claims(digest["claims"], macro)
    digest["provider"] = provider
    digest["digested_at"] = datetime.now().isoformat(timespec="seconds")
    if digest["has_mismatch"]:
        bad = [c for c in digest["claims"] if c.get("mismatch")]
        print(f"[digest] ⚠ {rec['id']}: {len(bad)} claim lệch registry "
              f"(REGISTRY THẮNG — claim không vào brief): "
              + "; ".join(f"{c['key']} {c['value']:g} vs {c['registry_value']:g}"
                          for c in bad))
    return digest


def refresh(redigest: bool = False, max_reports: int = 10) -> list[dict]:
    """Digest các báo cáo đủ điều kiện chưa có digest (``redigest=True`` =
    chấm lại tất cả — dùng khi đổi prompt/extractor). Trả list record đã chấm."""
    done: list[dict] = []
    for rec in _rp.load_for_analysis():
        if len(done) >= max_reports:
            print(f"[digest] dừng ở {max_reports} báo cáo/lượt (--max để nới)")
            break
        if rec.get("digest") and not redigest:
            continue
        digest = digest_report(rec)
        if digest is None:
            continue
        _rp.set_digest(rec["id"], digest)
        done.append(rec | {"digest": digest})
        print(f"[digest] ✅ {rec['id']} [{rec.get('source')}] via "
              f"{digest['provider']} — stance CP "
              f"{digest['stance']['Cổ phiếu']:+d}")
    return done


# ── Consensus + tilt ─────────────────────────────────────────────────────────


def _age_weight(age_days: int) -> float:
    if age_days <= _DECAY_FULL_DAYS:
        return 1.0
    if age_days >= _DECAY_ZERO_DAYS:
        return 0.0
    return (_DECAY_ZERO_DAYS - age_days) / (_DECAY_ZERO_DAYS - _DECAY_FULL_DAYS)


def consensus(as_of: "str | None" = None) -> "dict | None":
    """Stance tổng hợp decay-theo-tuổi trên mọi digest hợp lệ + tilt đề xuất.

    Trả ``{stance: {lớp: float}, tilt: -1|0|+1, n_reports, drivers[]}`` —
    tilt từ stance "Cổ phiếu": ≥ +1.0 → -1 (nghiêng tấn công = về band thấp
    hơn), ≤ -1.0 → +1 (phòng thủ). None khi chưa có digest nào còn trọng số.
    v1 giữ ĐƠN GIẢN (1-2 báo cáo/tháng — tham số duyệt #2): trung bình có
    trọng số, không phân biệt uy tín nguồn (xếp hạng nguồn = P6).
    """
    rows = []
    for rec in _rp.load_for_analysis(as_of=as_of):
        d = rec.get("digest")
        if not d or not d.get("stance"):
            continue
        w = _age_weight(rec["age_days"])
        if w <= 0:
            continue
        rows.append((w, rec, d))
    if not rows:
        return None
    wsum = sum(w for w, _, _ in rows)
    stance = {cls: round(sum(w * d["stance"].get(cls, 0)
                             for w, _, d in rows) / wsum, 2)
              for cls in _ASSET_CLASSES}
    cp = stance["Cổ phiếu"]
    tilt = -1 if cp >= _TILT_THRESHOLD else (1 if cp <= -_TILT_THRESHOLD else 0)
    return {
        "stance": stance,
        "tilt": tilt,
        "n_reports": len(rows),
        "as_of": as_of or date.today().isoformat(),
        "drivers": [{"id": rec["id"], "source": rec.get("source"),
                     "report_date": rec.get("report_date"),
                     "age_days": rec["age_days"], "weight": round(w, 2),
                     "stance_cp": d["stance"].get("Cổ phiếu", 0),
                     "has_mismatch": bool(d.get("has_mismatch"))}
                    for w, rec, d in rows],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Digest báo cáo vĩ mô (LLM) + consensus/tilt — Phase 3")
    ap.add_argument("--refresh", action="store_true",
                    help="digest các báo cáo đủ điều kiện chưa có digest")
    ap.add_argument("--redigest", action="store_true",
                    help="cùng --refresh: chấm lại TẤT CẢ (đổi prompt/extractor)")
    ap.add_argument("--max", type=int, default=10,
                    help="tối đa báo cáo digest mỗi lượt (mặc định 10)")
    ap.add_argument("--show", metavar="ID", help="in digest của 1 báo cáo")
    ap.add_argument("--consensus", action="store_true",
                    help="in stance tổng hợp + tilt hiện hành")
    ap.add_argument("--diag", action="store_true",
                    help="thử 1 call LLM ngắn qua ladder (cần key + mạng)")
    args = ap.parse_args(argv)

    if args.refresh or args.redigest:
        done = refresh(redigest=args.redigest, max_reports=args.max)
        print(f"[digest] {len(done)} báo cáo đã digest")
        return 0
    if args.show:
        rec = next((r for r in _rp.list_reports() if r["id"] == args.show), None)
        if rec is None:
            print(f"[digest] ❌ không có id {args.show}")
            return 1
        if not rec.get("digest"):
            print(f"[digest] {args.show} chưa có digest — chạy --refresh")
            return 1
        print(json.dumps(rec["digest"], ensure_ascii=False, indent=2))
        return 0
    if args.consensus:
        c = consensus()
        if c is None:
            print("[digest] chưa có digest nào còn trọng số — ingest báo cáo "
                  "(vnstock_reports) rồi chạy --refresh")
            return 1
        print(f"🧭 Consensus {c['n_reports']} báo cáo (as_of {c['as_of']}):")
        for cls in _ASSET_CLASSES:
            print(f"  {cls:<12} {c['stance'][cls]:+.2f}")
        lab = {0: "không tilt", -1: "tilt -1 (tấn công hơn)",
               1: "tilt +1 (phòng thủ hơn)"}[c["tilt"]]
        print(f"  → {lab} (ngưỡng ±{_TILT_THRESHOLD})")
        for dr in c["drivers"]:
            flag = " ⚠mismatch" if dr["has_mismatch"] else ""
            print(f"    • {dr['report_date']} {dr['source']} "
                  f"(w={dr['weight']}, CP {dr['stance_cp']:+d}){flag}")
        return 0
    if args.diag:
        raw, provider = digest_call(
            "Trả về đúng JSON: {\"ok\": true}", "ping")
        print(f"LLM ladder: {'OK via ' + provider if raw else 'FAIL — không key nào chạy (cần .env + mạng)'}")
        return 0 if raw else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

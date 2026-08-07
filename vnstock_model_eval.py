"""
vnstock_model_eval.py — chấm điểm model bằng BỘ ĐỀ CHUẨN, theo TỪNG VIỆC
========================================================================
Vì sao không có bảng "mạnh → yếu" chung (user hỏi 07/08, chốt sau khi bàn):

  * Probe chỉ trả "OK" — không nói gì về CHẤT LƯỢNG.
  * "Mạnh" phụ thuộc VIỆC: model viết brief hay chưa chắc xuất JSON 32 nhóm
    ngành chuẩn. Repo đang có 8 điểm với 8 bộ model khác nhau — đó không phải
    lộn xộn mà là tri thức tích luỹ ("70B free bịa chiều tác động", "Gemini
    flash-lite chấm tin đạt", "Cerebras gpt-oss-120b digest chập chờn"). Gộp
    thành một thứ hạng chung là VỨT BỎ đúng phần giá trị nhất.

Nên: bộ đề nhỏ có ĐÁP ÁN NGƯỜI DUYỆT, chấm bằng luật xác định, ra bảng điểm
TÁCH THEO VIỆC. Ba việc phủ 3 dạng output khác hẳn nhau:

  classify  → JSON + chọn đúng 1 trong 32 nhãn cố định   (điểm [8])
  sentiment → phân loại 3 nhãn từ văn bản tự do          (điểm [2])
  json      → xuất JSON đúng schema yêu cầu              (điểm [3-6])

⚠️ Module này CHỈ ĐỀ XUẤT. Không có `apply_swaps` và sẽ không bao giờ có:
brief bắn thẳng Telegram mỗi sáng, script tự đổi model nghĩa là user đọc bản
không ai duyệt. Có test chốt ranh giới đó.
"""
from __future__ import annotations

import json
import re
import time

from vnstock_model_watch import chat_once

# Chênh điểm tối thiểu mới đáng đề xuất đổi. Thấp hơn = nhiễu: bộ đề chỉ
# ~12 ca nên lệch 1 ca đã là 0.08 — đổi model vì 1 ca là thrash.
_MIN_GAP = 0.15

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# ═══ Bộ đề ═══════════════════════════════════════════════════════════════════
# ⚠️ ĐÁP ÁN CẦN NGƯỜI DUYỆT MỘT LẦN. Cố ý chọn ca KHÔNG mập mờ (mã đầu ngành,
# tin có chiều tác động rõ) — bộ đề để đo MODEL, không phải để đố mẹo. Ca nào
# người còn phân vân thì bỏ, đừng giữ lại rồi trách model sai.

GOLDEN_CLASSIFY = [
    {"ticker": "VCB", "name": "Ngân hàng TMCP Ngoại thương Việt Nam",
     "desc": "Ngân hàng thương mại: huy động vốn, cho vay, thanh toán quốc tế.",
     "expected": "Ngân hàng"},
    {"ticker": "HPG", "name": "CTCP Tập đoàn Hòa Phát",
     "desc": "Sản xuất thép xây dựng, ống thép, tôn mạ; lò cao luyện gang thép.",
     "expected": "Thép & Kim loại"},
    {"ticker": "VNM", "name": "CTCP Sữa Việt Nam",
     "desc": "Sản xuất và kinh doanh sữa nước, sữa bột, sữa chua, nước giải khát.",
     "expected": "Thực phẩm & Đồ uống"},
    {"ticker": "FPT", "name": "CTCP FPT",
     "desc": "Xuất khẩu phần mềm, tích hợp hệ thống, dịch vụ viễn thông, giáo dục.",
     "expected": "Công nghệ thông tin & Phần mềm"},
    {"ticker": "VHM", "name": "CTCP Vinhomes",
     "desc": "Phát triển và kinh doanh bất động sản nhà ở, khu đô thị.",
     "expected": "Bất động sản"},
    {"ticker": "GAS", "name": "Tổng Công ty Khí Việt Nam",
     "desc": "Thu gom, vận chuyển, chế biến và kinh doanh khí, LPG, LNG.",
     "expected": "Dầu khí"},
    {"ticker": "SSI", "name": "CTCP Chứng khoán SSI",
     "desc": "Môi giới chứng khoán, tự doanh, cho vay ký quỹ, quản lý quỹ.",
     "expected": "Chứng khoán & Đầu tư tài chính"},
    {"ticker": "BVH", "name": "Tập đoàn Bảo Việt",
     "desc": "Kinh doanh bảo hiểm nhân thọ và phi nhân thọ, tái bảo hiểm.",
     "expected": "Bảo hiểm"},
    {"ticker": "POW", "name": "Tổng Công ty Điện lực Dầu khí Việt Nam",
     "desc": "Sản xuất và kinh doanh điện năng từ nhà máy nhiệt điện khí, than.",
     "expected": "Điện & Năng lượng tái tạo"},
    {"ticker": "DHG", "name": "CTCP Dược Hậu Giang",
     "desc": "Sản xuất và phân phối dược phẩm, thực phẩm chức năng.",
     "expected": "Y tế & Dược phẩm"},
    {"ticker": "MWG", "name": "CTCP Đầu tư Thế giới Di động",
     "desc": "Chuỗi bán lẻ điện thoại, điện máy, bách hoá.",
     "expected": "Bán lẻ & Thương mại"},
    {"ticker": "VSC", "name": "CTCP Container Việt Nam",
     "desc": "Khai thác cảng biển, kho bãi container, dịch vụ logistics cảng.",
     "expected": "Cảng & Hạ tầng logistics"},
]

GOLDEN_SENTIMENT = [
    {"title": "Xuất khẩu thủy sản tháng 7 tăng 18% so với cùng kỳ",
     "expected": "positive"},
    {"title": "Ngân hàng Nhà nước hạ lãi suất điều hành 0,5 điểm phần trăm",
     "expected": "positive"},
    {"title": "Giá thép xây dựng trong nước giảm phiên thứ năm liên tiếp",
     "expected": "negative"},
    {"title": "Mỹ áp thuế chống bán phá giá với tôm nhập khẩu từ Việt Nam",
     "expected": "negative"},
    {"title": "Doanh nghiệp bất động sản chậm thanh toán lô trái phiếu 2.000 tỷ",
     "expected": "negative"},
    {"title": "Vốn FDI đăng ký 7 tháng đạt 18 tỷ USD, tăng 10%",
     "expected": "positive"},
    {"title": "Sở Giao dịch Chứng khoán công bố lịch nghỉ lễ Quốc khánh",
     "expected": "neutral"},
    {"title": "Công ty tổ chức đại hội cổ đông thường niên vào cuối tháng",
     "expected": "neutral"},
]

GOLDEN_JSON = [
    {"name": "verdict", "required": ["approved", "confidence", "issues"],
     "system": "Bạn là bộ phản biện. CHỈ trả JSON, không thêm chữ nào.",
     "user": 'Đánh giá: "VN-Index tăng 1,2% với thanh khoản 18.000 tỷ". Trả JSON '
             '{"approved": bool, "confidence": số 0-1, "issues": [chuỗi]}'},
    {"name": "summary", "required": ["title", "points"],
     "system": "Bạn tóm tắt tin tài chính. CHỈ trả JSON.",
     "user": 'Tóm tắt: "NHNN bơm ròng 12.000 tỷ qua kênh OMO tuần qua". Trả JSON '
             '{"title": chuỗi, "points": [chuỗi]}'},
    {"name": "extract", "required": ["ticker", "action"],
     "system": "Bạn trích xuất thông tin. CHỈ trả JSON.",
     "user": 'Trích: "HPG thông báo mua lại 100 triệu cổ phiếu quỹ". Trả JSON '
             '{"ticker": chuỗi, "action": chuỗi}'},
    {"name": "rating", "required": ["score", "reason"],
     "system": "Bạn chấm điểm cơ hội đầu tư. CHỈ trả JSON.",
     "user": 'Chấm: "Doanh nghiệp P/E 8, ROE 22%, nợ vay/VCSH 0,3". Trả JSON '
             '{"score": số 1-10, "reason": chuỗi}'},
    {"name": "nested", "required": ["symbol", "levels"],
     "system": "Bạn trả về mốc kỹ thuật. CHỈ trả JSON.",
     "user": 'Cho VNINDEX hỗ trợ 1250 kháng cự 1300. Trả JSON '
             '{"symbol": chuỗi, "levels": {"support": số, "resistance": số}}'},
]


# ═══ Chấm điểm (xác định, không dùng LLM chấm LLM) ═══════════════════════════

def _first_json(raw: str) -> "dict | None":
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        out = json.loads(m.group())
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def score_classify(raw: str, expected: str) -> float:
    """1.0 khi chọn ĐÚNG nhãn ngành; JSON hỏng hoặc bịa ngành → 0.0."""
    data = _first_json(raw)
    if not data:
        return 0.0
    return 1.0 if str(data.get("primary_industry", "")).strip() == expected else 0.0


def score_sentiment(raw: str, expected: str) -> float:
    """1.0 khi ra đúng nhãn (positive/negative/neutral). Dùng chung bảng ánh
    xạ tiếng Việt của vnstock_sentiment để giống hệt đường chấm tin thật."""
    try:
        from vnstock_sentiment import _SENTIMENT_MAP
    except Exception:
        _SENTIMENT_MAP = {"tích cực": "positive", "tiêu cực": "negative",
                          "trung lập": "neutral"}
    low = (raw or "").lower()
    got = next((v for k, v in _SENTIMENT_MAP.items() if k in low), "")
    return 1.0 if got == expected else 0.0


def score_json(raw: str, required: list) -> float:
    """1.0 khi JSON parse được VÀ có đủ khoá yêu cầu."""
    data = _first_json(raw)
    if not data:
        return 0.0
    return 1.0 if all(k in data for k in required) else 0.0


# ═══ Prompt bộ đề (bám sát prompt thật của từng điểm) ════════════════════════

def _industry_groups() -> list:
    """Danh sách ngành thật. Cách ly import như model_watch: vnstock_classifier
    kéo theo SDK vnstock + xác thực mạng, không được làm chết cả bộ đề."""
    try:
        import vnstock_classifier as vc
        return list(vc.INDUSTRY_GROUPS)
    except Exception:
        return []


_CLASSIFY_SYSTEM = "Bạn là chuyên gia phân tích tài chính Việt Nam."
_SENTIMENT_SYSTEM = ("Bạn chấm sắc thái tin tài chính. Trả đúng một trong ba: "
                     "TÍCH_CỰC, TIÊU_CỰC, TRUNG_LẬP — kèm 1 câu ngắn sau dấu |.")


def _classify_user(case: dict, groups: list) -> str:
    return (f"MÃ CK: {case['ticker']}\nTÊN: {case['name']}\n"
            f"MÔ TẢ: {case['desc']}\n\nDANH SÁCH NHÓM NGÀNH:\n"
            + "\n".join(f"- {g}" for g in groups)
            + '\n\nTrả ĐÚNG JSON: {"primary_industry": "tên nhóm ngành chính '
              '(chọn chính xác từ danh sách)"}')


# ═══ Chạy bộ đề ══════════════════════════════════════════════════════════════

_TASKS = ("classify", "sentiment", "json")


def run_eval(models: list, tasks: tuple = _TASKS, delay: float = 0.0) -> dict:
    """{(provider, model): {task: điểm 0-1, "errors": n}}.

    `delay` mặc định 0 để test/gọi thư viện chạy nhanh; production truyền
    ngưỡng lịch sự (Groq TPM 8K) — xem `vnstock_model_watch._run_eval_stage`.
    """
    groups = _industry_groups()
    out: dict = {}
    for provider, model in models:
        scores: dict = {"errors": 0}
        for task in tasks:
            got, n_err = _run_one_task(provider, model, task, groups, delay)
            if got is not None:
                scores[task] = got
            scores["errors"] += n_err
        out[(provider, model)] = scores
    return out


def _run_one_task(provider: str, model: str, task: str, groups: list,
                  delay: float) -> "tuple[float | None, int]":
    """(điểm trung bình, số ca lỗi). None khi việc đó không chạy được."""
    if task == "classify":
        if not groups:
            return None, 0
        cases = [(_CLASSIFY_SYSTEM, _classify_user(c, groups),
                  lambda raw, c=c: score_classify(raw, c["expected"]))
                 for c in GOLDEN_CLASSIFY]
    elif task == "sentiment":
        cases = [(_SENTIMENT_SYSTEM, f"Tiêu đề: {c['title']}",
                  lambda raw, c=c: score_sentiment(raw, c["expected"]))
                 for c in GOLDEN_SENTIMENT]
    elif task == "json":
        cases = [(c["system"], c["user"],
                  lambda raw, c=c: score_json(raw, c["required"]))
                 for c in GOLDEN_JSON]
    else:
        return None, 0

    total, errors = 0.0, 0
    for i, (system, user, scorer) in enumerate(cases):
        if i and delay:
            time.sleep(delay)
        raw, err = chat_once(provider, model, system, user, max_tokens=400)
        if err or raw is None:
            errors += 1
            continue                      # ca lỗi tính 0 điểm, KHÔNG bỏ khỏi mẫu
        total += scorer(raw)
    return round(total / len(cases), 3), errors


# ═══ Điểm dùng thật của từng việc ═══════════════════════════════════════════

def current_models() -> dict:
    """{task: [(provider, model)…]} — nấc ĐANG DÙNG, nấc đầu là nấc dẫn.

    Mỗi việc trong bộ đề trỏ về đúng một điểm dùng thật, nếu không thì đề xuất
    không biết đang so với cái gì.
    """
    out: dict[str, list] = {"classify": [], "sentiment": [], "json": []}
    try:
        import vnstock_classifier as vc
        out["classify"] = list(vc._CLASSIFY_MODELS.items())
    except Exception:
        pass
    try:
        import vnstock_news_feeds as nf
        out["sentiment"] = list(nf._ANALYZE_MODELS.items())
    except Exception:
        pass
    try:
        import vnstock_report_digest as dg
        out["json"] = list(dg._FREE_MODELS.items())
    except Exception:
        pass
    return out


# ═══ Đề xuất (KHÔNG áp) ══════════════════════════════════════════════════════

def propose_swaps(scores: dict, current: dict,
                  previous_proposals: "list | None" = None) -> list:
    """Đề xuất đổi nấc DẪN của từng việc. Chỉ đề xuất — không sửa gì.

    `ripe=True` khi lần chạy TRƯỚC cũng đã đề xuất y hệt. Ngưỡng 2 lần liên
    tiếp là để chống thrash: tiền lệ OpenRouter `qwen3-235b:free` sống → 404 →
    sống lại trong vòng một ngày; đổi config theo một lần đo là loạn.
    """
    prev = {(p["task"], tuple(p["candidate"])) for p in (previous_proposals or [])}
    out = []
    for task, pairs in sorted(current.items()):
        if not pairs:
            continue
        lead = tuple(pairs[0])
        ranked = sorted(
            ((k, v.get(task)) for k, v in scores.items() if v.get(task) is not None),
            key=lambda kv: -kv[1])
        if not ranked:
            continue
        best, best_score = ranked[0]
        cur_score = scores.get(lead, {}).get(task)
        if cur_score is None or tuple(best) == lead:
            continue
        if best_score - cur_score < _MIN_GAP:
            continue
        out.append({
            "task": task,
            "current": list(lead), "current_score": round(cur_score, 3),
            "candidate": list(best), "candidate_score": round(best_score, 3),
            "gap": round(best_score - cur_score, 3),
            "ripe": (task, tuple(best)) in prev,
        })
    return out

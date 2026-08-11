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

from vnstock_model_watch import _is_rate_limited, chat_once

# Chênh điểm tối thiểu mới đáng đề xuất đổi. Thấp hơn = nhiễu: bộ đề chỉ
# ~12 ca nên lệch 1 ca đã là 0.08 — đổi model vì 1 ca là thrash.
_MIN_GAP = 0.15

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Trả lời được dưới tỉ lệ này thì coi như KHÔNG ĐO ĐƯỢC (điểm khuyết khỏi
# bảng), không phải model dở. Vu oan cho model vì hạn mức của chính ta là
# cách nhanh nhất để bảng điểm thành vô dụng.
_MIN_COVERAGE = 0.7
# 429 = "thử lại sau", không phải "model hỏng" → lùi rồi thử lại.
_RETRY_SLEEPS = (5.0, 15.0)
# Dính hạn mức liên tiếp bấy nhiêu ca (mỗi ca đã retry) = quota cả ngày cạn
# → bỏ nốt bài thay vì đốt thời gian. (`_is_rate_limited` dùng chung với
# vnstock_model_watch — một bản duy nhất, đừng viết lại.)
_GIVE_UP_STREAK = 3

# Model reasoning (qwen3.6, gpt-oss) tiêu ngân sách vào phần SUY NGHĨ trước
# khi trả lời. Cấp 400 như bản đầu = cụt output → bị chấm 0 điểm OAN (ca thật
# 08-09/08: qwen/qwen3.6-27b 0.33/0.38/0.00 với errors=0). Repo đã học bài này
# ở digest: Groq 900 · Cerebras 6000 · OpenRouter 4000, tier2 3000 ("1200 là
# cụt content"). 2000 đủ rộng cho mọi nấc mà vẫn nhanh.
_EVAL_MAX_TOKENS = 2000

# Thẻ <think> MỞ mà không có thẻ đóng = output bị cắt giữa lúc suy nghĩ.
# `chat_once` đã strip mọi khối think ĐÓNG ĐỦ, nên thẻ mở còn sót lại là bằng
# chứng bị cắt — đó là ngân sách của TA quá chật, không phải model dở.
_OPEN_THINK_RE = re.compile(r"<\s*(think|thinking|reasoning|thought)\s*>", re.I)


def _truncated_thinking(raw: str) -> bool:
    return bool(raw) and bool(_OPEN_THINK_RE.search(raw))


def _chat_with_retry(provider: str, model: str, system: str, user: str,
                     max_tokens: int = _EVAL_MAX_TOKENS) -> "tuple[str | None, str | None]":
    """Như `chat_once` nhưng lùi-rồi-thử-lại khi dính hạn mức.

    Chỉ retry lỗi hạn mức: 404 model_not_found thì thử lại chỉ tốn thời gian.
    """
    raw, err = chat_once(provider, model, system, user, max_tokens=max_tokens)
    for pause in _RETRY_SLEEPS:
        if not _is_rate_limited(err):
            break
        time.sleep(pause)
        raw, err = chat_once(provider, model, system, user, max_tokens=max_tokens)
    return raw, err


# ═══ Bộ đề ═══════════════════════════════════════════════════════════════════
# ✅ ĐÃ DUYỆT 10/08/2026 — user ủy quyền Claude tự duyệt ("tự chấm và duyệt
# với nỗ lực tối đa"), KHÔNG phải người duyệt tay. Độ tin dựa trên: (i) biên
# bản TỪNG CA ở CLAUDE-NOTES entry "10/08 (b)" — phản biện lại được từng
# dòng; (ii) các ca đều là kiến thức phổ thông TTCK VN, không judgment call.
# Kết quả duyệt: 24/25 giữ nguyên · 1 sửa desc (FPT — thêm trọng số mảng) ·
# 1 BUG SCORER (score_sentiment so cả chuỗi thay vì phần trước dấu |).
# Nguyên tắc giữ nguyên: ca mập mờ với NGƯỜI thì bỏ/sửa, không giữ để đố mẹo.
# Phủ quyết ca nào: đọc biên bản → sửa 1 dòng → `run.py test --fast`.

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
    # Đa mảng CÓ Ý (công ty thật vốn thế) nhưng primary phải XÁC ĐỊNH ĐƯỢC
    # TỪ TEXT: list nhãn có riêng "Viễn thông" và "Giáo dục" nên desc không
    # trọng số là bắt model đoán — thêm "(mảng chính…)" khi duyệt 10/08.
    {"ticker": "FPT", "name": "CTCP FPT",
     "desc": "Xuất khẩu phần mềm và dịch vụ CNTT (mảng chính, phần lớn "
             "doanh thu); có thêm viễn thông, giáo dục.",
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
    # Giữ dù POW là NHIỆT điện: nhãn là TÊN RỔ ("Điện & NLTT" = mọi phát điện
    # + tái tạo), không phải khẳng định POW tái tạo; "Điện" chỉ xuất hiện ở
    # đúng 1 nhãn nên xác định được từ desc. (Duyệt 10/08.)
    {"ticker": "POW", "name": "Tổng Công ty Điện lực Dầu khí Việt Nam",
     "desc": "Sản xuất và kinh doanh điện năng từ nhà máy nhiệt điện khí, than.",
     "expected": "Điện & Năng lượng tái tạo"},
    {"ticker": "DHG", "name": "CTCP Dược Hậu Giang",
     "desc": "Sản xuất và phân phối dược phẩm, thực phẩm chức năng.",
     "expected": "Y tế & Dược phẩm"},
    {"ticker": "MWG", "name": "CTCP Đầu tư Thế giới Di động",
     "desc": "Chuỗi bán lẻ điện thoại, điện máy, bách hoá.",
     "expected": "Bán lẻ & Thương mại"},
    # Giữ dù sát nhãn "Vận tải & Logistics": HAI nhãn này CÙNG TỒN TẠI trong
    # production, nên phân biệt cảng vs logistics tổng hợp CHÍNH LÀ kỹ năng
    # phải đo — không phải đố mẹo. Desc dẫn bằng "khai thác cảng biển" +
    # "logistics CẢNG" nên xác định được. (Duyệt 10/08.)
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
    """1.0 khi ra đúng nhãn (positive/negative/neutral).

    Mirror ĐÚNG đường parse production (`analyze_item`): nhãn nằm TRƯỚC dấu
    `|`, phần sau là câu giải thích — phải cắt trước khi so. Không cắt thì
    đuôi kiểu "không tích cực cũng không tiêu cực" đè nhãn TRUNG LẬP thành
    positive (bug lộ khi tự duyệt bộ đề 10/08 — chấm 0 điểm OAN ca neutral).

    Khác production MỘT chỗ CÓ Ý: không default "neutral" khi chẳng khớp gì.
    Đó là lớp CHE LỖI của production; với eval, output không đọc ra nhãn
    là trượt.
    """
    try:
        from vnstock_sentiment import _SENTIMENT_MAP
    except Exception:
        _SENTIMENT_MAP = {"tích cực": "positive", "tiêu cực": "negative",
                          "trung lập": "neutral"}
    head, _, _tail = (raw or "").partition("|")
    low = head.lower()
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


_CASE_COUNTS = {"classify": len(GOLDEN_CLASSIFY),
                "sentiment": len(GOLDEN_SENTIMENT), "json": len(GOLDEN_JSON)}

# Hạn mức call/lần chạy cho provider có quota NGÀY chật. OpenRouter free =
# 50 req/ngày, mà 3 model × 25 ca = 75 → eval của CHÍNH TA đốt sạch, hôm sau
# production mất nấc dự phòng (ca thật 08/08). Provider không khai = không cap.
EVAL_BUDGET = {"OpenRouter": 25}

# Nhịp giữa các ca THEO PROVIDER — cho provider bóp theo PHÚT chứ không chỉ
# theo ngày. Gemini free tier: flash chỉ ~10-15 req/phút; eval bắn flash-lite
# 25 ca rồi flash ngay trong cùng cửa sổ phút → flash 429 hàng loạt. Cả 3 lần
# chạy flash đều là nạn nhân quota (08/08 chấm 0 oan · 09/08 json n/a · 11/08
# 15 ca hụt) dù probe luôn sống. Job tuần chạy nền — chậm thêm ~3 phút không
# sao, ĐO ĐƯỢC mới quan trọng. Provider không khai = dùng nhịp chung.
EVAL_DELAYS = {"Gemini": 7.0}


def run_eval(models: list, tasks: tuple = _TASKS, delay: float = 0.0,
             budget: "dict | None" = None) -> dict:
    """{(provider, model): {task: điểm 0-1, "errors": n}}.

    `delay` mặc định 0 để test/gọi thư viện chạy nhanh; production truyền
    ngưỡng lịch sự (Groq TPM 8K) — xem `vnstock_model_watch._run_eval_stage`.
    """
    groups = _industry_groups()
    budget = budget or {}
    need = sum(_CASE_COUNTS.get(t, 0) for t in tasks)
    used: dict = {}
    out: dict = {}
    for provider, model in models:
        cap = budget.get(provider)
        if cap is not None and used.get(provider, 0) + need > cap:
            # Không đo model này lần này — để tuần sau (thứ tự xoay vòng ở
            # `_eval_order`). Thà đo được vài model tử tế còn hơn đo hết rồi
            # cướp quota của pipeline thật.
            out[(provider, model)] = {"errors": 0, "coverage": {},
                                      "skipped": "budget"}
            continue
        used[provider] = used.get(provider, 0) + need
        scores: dict = {"errors": 0, "coverage": {}}
        pace = max(delay, EVAL_DELAYS.get(provider, 0.0))
        for task in tasks:
            got, n_err, n_ans = _run_one_task(provider, model, task, groups, pace)
            if got is not None:
                scores[task] = got
            scores["errors"] += n_err
            scores["coverage"][task] = n_ans
        out[(provider, model)] = scores
    return out


def _run_one_task(provider: str, model: str, task: str, groups: list,
                  delay: float) -> "tuple[float | None, int, int]":
    """(điểm, số ca lỗi, số ca trả lời được). Điểm None = KHÔNG ĐO ĐƯỢC."""
    if task == "classify":
        if not groups:
            return None, 0, 0
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
        return None, 0, 0

    total, errors, answered, streak = 0.0, 0, 0, 0
    for i, (system, user, scorer) in enumerate(cases):
        if i and delay:
            time.sleep(delay)
        raw, err = _chat_with_retry(provider, model, system, user)
        if raw is not None and not err and _truncated_thinking(raw):
            # Cắt giữa lúc suy nghĩ = ta cấp thiếu token, KHÔNG phải model sai.
            # Chấm 0 ở đây là vu oan — cùng lỗi với chấm 429 thành 0 điểm.
            errors += 1
            streak = 0
            continue
        if err or raw is None:
            errors += 1
            # Quota CẢ NGÀY cạn thì retry chỉ đốt thời gian (25 ca × 20s × 10
            # model > 1 tiếng cho task T7). Dính hạn mức liên tiếp → bỏ nốt
            # bài, các ca còn lại tính là hụt.
            streak = streak + 1 if _is_rate_limited(err) else 0
            if streak >= _GIVE_UP_STREAK:
                errors += len(cases) - i - 1
                break
            continue
        streak = 0
        answered += 1
        total += scorer(raw)

    # Hụt quá ngưỡng → KHÔNG ĐO ĐƯỢC, trả None thay vì điểm thấp. Chấm 429
    # thành 0 điểm là vu oan cho model vì hạn mức của CHÍNH TA (ca thật
    # 08/08: gemini-3.5-flash classify=1.00 nhưng json=0.00 do cạn quota
    # giữa chừng). Cùng họ bug với "JSON hỏng ghi thành Khác".
    if answered < _MIN_COVERAGE * len(cases):
        return None, errors, answered
    return round(total / answered, 3), errors, answered


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

"""
vnstock_brief.py — AI-powered morning/afternoon market brief generator.

Architecture
------------
  BriefAgent (ABC)    — any agent that implements .generate(prompt) -> (text, err)
  ClaudeAgent         — Anthropic Messages API  (ANTHROPIC_API_KEY)
  OpenAIAgent         — OpenAI Chat Completions (OPENAI_API_KEY)

  collect_context()   — gather quant scores, session stats, VN30 movers
  build_prompt()      — construct Vietnamese structured prompt
  generate_brief()    — run enabled agents, return {name: (text, error)}

Adding a new agent
------------------
  1. Subclass BriefAgent, implement .generate() and .is_available
  2. Register in AGENT_REGISTRY
  3. Add default entry to _DEFAULT_AGENT_CONFIGS

No Streamlit dependency — safe to call from CLI or other modules.
"""
from __future__ import annotations

import json
import logging
import os
import re as _re
from abc import ABC, abstractmethod
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────
AGENTS_CONFIG_PATH = Path("data_warehouse/_meta/brief_agents.json")

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    """Load API keys from .env into os.environ exactly once.

    Agents read keys straight from os.environ in their is_available check.
    When the brief is generated from a fresh CLI process (run.py telegram
    close) nothing has loaded .env yet, so without this every agent would
    look unavailable and the brief would wrongly report "no agent available".
    Idempotent and never overrides keys already exported in the shell.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env", override=False)
    except Exception:
        pass
    _ENV_LOADED = True

# Hằng số + khối canon dùng CHUNG với hệ guard → `vnstock_brief_canon`.
# Re-export nguyên tên: vnstock_events/vnstock_train/test đang import qua đây.
from vnstock_brief_canon import (  # noqa: F401  (re-export: giữ nguyên đường import cũ)
    _UNVALIDATED_STRATEGY_CAVEAT,
    VN30_TICKERS,
    _FINANCIAL_TICKERS,
    _MKT_NEWS_SENT_ICON,
    _SR_MAX_MOVE_PCT,
    _WATCHLIST_GTGD_MIN_TY,
    _allocation_table_lines,
    _gtgd_close_frame,
    _macro_body_lines,
    _macro_line,
    _macro_reports_body_lines,
    _market_news_body_lines,
    _one_line,
    sanitize_impact,
    IMPACT_MAX_CHARS,
    _portfolio_fact_line,
    _round_tick,
    _vn_tick,
)


# Liquidity floor (avg trading value, tỷ VND/phiên) for surfacing a ticker in
# the whole-market mover/watchlist scan. VN30 is always kept regardless. Tune
# higher to narrow toward blue-chips, lower to include more mid-caps.
_LIQUID_GTGD_MIN_TY: float = 10.0
# Price floor (thousand VND) — drop sub-5k penny/distressed names (e.g. POM ~4.3)
# from the watchlist universe; VN30 is exempt. Raise to be stricter on quality.
_LIQUID_PRICE_MIN_TY: float = 5.0






def get_vn30_live() -> set[str]:
    """Rổ VN30 hiện hành; lui về VN30_TICKERS khi không lấy được.

    Đi qua `vnstock_vn30` — MỘT đường duy nhất, có cache trong kho (nên hai
    máy dùng chung) và có badge doctor. Bản cũ tự gọi API ở đây và dò
    `df.columns`, nhưng `symbols_by_group` trả **pd.Series** nên nó ném
    AttributeError mỗi lần và im lặng rơi về hằng số: "lấy rổ động" là code
    chết trông y như code sống suốt từ đó (lòi ra 20/08).
    """
    try:
        import vnstock_vn30
        return set(vnstock_vn30.get_members())
    except Exception:
        return set(VN30_TICKERS)

_DEFAULT_AGENT_CONFIGS: list[dict] = [
    # Gemini = agent CHÍNH (user chốt 22/07, all-free) — enabled sẵn để máy
    # đã có config cũ cũng tự nhận nó qua cơ chế merge của load_agent_configs
    {
        "type": "gemini",
        "model": "gemini-3.5-flash",
        "name": "Gemini 3.5 Flash",
        "enabled": True,
        "max_tokens": 1200,
    },
    {
        "type": "claude",
        "model": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "openai",
        "model": "gpt-4o-mini",
        "name": "GPT-4o mini",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "groq",
        "model": "qwen/qwen3.6-27b",
        "name": "Groq Qwen3.6-27B",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "mistral",
        "model": "mistral-small-latest",
        "name": "Mistral Small",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "deepseek",
        "model": "deepseek-chat",
        "name": "DeepSeek Chat",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "cerebras",
        "model": "gpt-oss-120b",
        "name": "Cerebras GPT-OSS-120B",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "openrouter",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "name": "OpenRouter Nemotron Super",
        "enabled": False,
        "max_tokens": 1200,
    },
]

# Output budget for a full brief. Bumped 1200→2400 (2026-06-16): the brief grew
# to ~11 sections (added 🌐 Vĩ mô + 📰 Tin, which the model also re-echoes), so
# 1200 tokens cut the output short — observed a close brief ending right after
# "Mức kỹ thuật", losing Dẫn dắt/Dòng tiền/Watchlist/Rủi ro/Sự kiện/Vĩ mô/Tin.
# Bumped 2400→2800 (P4 2026-07-13): thêm mục 📚 Báo cáo vĩ mô & phân bổ.
_BRIEF_MAX_TOKENS = 2800

# Low temperature for briefs: they're data-extraction + structured analysis, so
# determinism beats creativity. Unset (provider default ~1.0) caused big run-to-
# run swings — a strong brief one run, instruction/template echoes + meta-
# disclaimers the next (observed 16/06 22:37 vs 22:43, same data). Pinned low so
# output is consistent and the deterministic guards have less to clean up.
_BRIEF_TEMPERATURE = 0.3

# ── Prompt templates ───────────────────────────────────────────────────────
_SYSTEM = (
    "Bạn là quant trader chuyên nghiệp tại thị trường chứng khoán Việt Nam với hơn 10 năm "
    "kinh nghiệm phân tích định lượng. Phong cách: thẳng thắn, súc tích, gắn nhận định với "
    "dữ liệu cụ thể, phân biệt rõ tín hiệu mạnh và nhiễu, không dùng ngôn ngữ hoa mỹ.\n\n"
    "QUY TẮC KHÔNG ĐƯỢC VI PHẠM:\n"
    "- KHÔNG dùng giá VNINDEX hay mức kỹ thuật theo trí nhớ/training data. "
    "VNINDEX hôm nay được cung cấp trong block '## VNINDEX kỹ thuật' bên dưới — "
    "phải dùng CHÍNH XÁC con số đó. Nếu nhắc 1.240 hoặc 1.300 trong khi data ghi "
    "1.815 → SAI, không được làm.\n"
    "- Mọi mức hỗ trợ/kháng cự phải lấy từ Pivots S1/S2/R1/R2 trong data, không bịa.\n"
    "- Nếu data thiếu một mục → viết 'Chưa có dữ liệu', KHÔNG suy đoán."
)

_MORNING_TEMPLATE = """\
{system}

Dữ liệu thị trường kết thúc phiên SÁNG (11:30):

{data}

---
Viết MORNING BRIEF tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 🎯 TLDR (2 dòng)
**Bias:** [TĂNG / GIẢM / TRUNG TÍNH] — [1 câu lý do chính, có số liệu]
**Hành động ưu tiên:** [BUY / WAIT / DEFENSIVE] — [ngành hoặc setup cụ thể]

## 📊 Tổng quan phiên sáng
[2-3 câu: diễn biến chính, GTGD vs bình thường (có % so trung bình 5 phiên nếu data có), tính chất phiên (institutional vs retail dựa vào GTGD/độ rộng)]
Dùng "GTGD sáng" trong data cho brief sáng và so sánh ĐỒNG DẠNG (sáng-với-sáng), KHÔNG so GTGD nửa phiên sáng với trung bình cả ngày. Ghi GTGD có dấu phân tách nghìn (đơn vị tỷ). Nếu data KHÔNG có "GTGD sáng" → TUYỆT ĐỐI KHÔNG bịa số; ghi "Chưa có GTGD phiên sáng". TUYỆT ĐỐI KHÔNG bàn về phiên chiều, GTGD cả ngày, hay tỷ trọng sáng/chiều — morning brief viết từ góc nhìn 11:30, chưa biết diễn biến chiều.
BẮT BUỘC nếu có block "Tâm lý thị trường": nêu RÕ nhãn tâm lý + điểm momentum (vd "Tâm lý: 📈 Tích cực, momentum +34/100") và hàm ý cho phiên chiều.

## 📈 Mức kỹ thuật quan trọng (VNINDEX)
TRÍCH XUẤT TỪ block "## VNINDEX kỹ thuật" — KHÔNG BỊA, KHÔNG dùng số trong training data.
**Đóng cửa hiện tại:** [chính xác con số `close` trong data, ví dụ "1,815.42" — GIỮ NGUYÊN định dạng số như trong data: dấu phẩy ngăn nghìn, dấu chấm thập phân]
**Hỗ trợ gần:** [S1 (gần giá nhất) TRƯỚC, rồi S2 — ghi cả số tuyệt đối, đúng thứ tự S1 < ... < giá]
**Kháng cự gần:** [R1 (gần giá nhất) trước, rồi R2]
**Vị trí so với MA:** [BẮT BUỘC nêu ĐỦ CẢ BA — MA20, MA50, MA200 — mỗi cái: trên/dưới + % cách giá + giá trị MA từ data. KHÔNG được bỏ MA nào.]
**Trigger breakout:** [vượt R1 → test R2; thủng S1 → về S2 — viết theo SỐ đã cho]
Nếu block "VNINDEX kỹ thuật" KHÔNG có trong data → viết "Chưa có dữ liệu VNINDEX hôm nay" (không bịa).

## 🎯 Trọng tâm theo dõi
**Tích luỹ/Mua:** [ngành hoặc mã (VN30/mid-cap thanh khoản trong data) + lý do cụ thể — nêu trọng số %VNI và đóng góp pp]
**Tránh/Bán:** [ngành hoặc mã (VN30/mid-cap thanh khoản trong data) + lý do cụ thể]
**Dòng tiền ngành:** [Nếu có block "Dòng tiền ngành": nêu RÕ ngành NN MUA RÒNG / BÁN RÒNG mạnh nhất (số "NN ròng" tỷ, có +/-). PHÂN BIỆT "NN ròng" (khối ngoại) với "GTGD" (thanh khoản) — KHÔNG gọi GTGD là "dòng tiền vào". Bỏ dòng này chỉ khi KHÔNG có block đó.]
**Theo dõi:** [rotation/stealth nếu có, bỏ dòng này nếu không có tín hiệu]
Dòng "Tích luỹ/Mua" & "Tránh/Bán" Ở CẤP NGÀNH PHẢI khớp block "🎯 Dẫn dắt/Tụt hậu — CHỐT THEO DATA" (nếu có) — KHÔNG tự chọn ngành khác làm dẫn dắt/tụt hậu.
KHÔNG gọi "tích luỹ/mua" nếu tín hiệu quá yếu (đóng góp |pp| < 0.05 hoặc biến động không đáng kể) — khi không có ngành/mã đủ mạnh, viết thẳng "Chưa có nhóm dẫn dắt rõ ràng".
Nếu có block "Cơ bản nhóm theo dõi": có thể dẫn 1 chỉ số cơ bản (D/E cao / Op.CF âm / ROE) để củng cố lý do tránh/mua, KHÔNG bịa số.

## ⚡ Biến động bất thường
[Mã/ngành biến động mạnh TRONG DATA + giải thích + BẮT BUỘC ghi ĐÚNG khung thời gian theo nhãn trong data. Số từ block "Top Gainers/Losers thanh khoản cao" là thay đổi "1 tuần/5 phiên" → ghi "(1 tuần)", TUYỆT ĐỐI KHÔNG ghi "phiên sáng"/"hôm nay" cho các số đó (không có dữ liệu thay đổi 1 phiên cho từng mã). "Không có biến động bất thường đáng chú ý" nếu phẳng]

## 🔮 Kịch bản phiên chiều
Kịch bản CHÍNH phải NHẤT QUÁN với Bias ở TLDR: Bias GIẢM → kịch bản chính nghiêng giảm/đi ngang (KHÔNG được là kịch bản tăng); Bias TĂNG → ngược lại. Mọi mức giá/chỉ số PHẢI lấy từ block kỹ thuật của data — TUYỆT ĐỐI KHÔNG chép số hay cụm "ngân hàng giữ đà"/"bank giữ đà" từ mẫu cấu trúc dưới, KHÔNG bịa mã/ngành dẫn dắt nếu data không có.
**Kịch bản chính ([X]% xác suất):** [điều kiện kích hoạt = mức S/R thực từ data + tín hiệu xác nhận → hệ quả % đóng cửa ĐÚNG chiều Bias]
**Kịch bản phụ:** [điều kiện ngược lại + ngưỡng hành động phòng thủ/đứng ngoài]
(Mẫu CẤU TRÚC, không phải số để dùng: "VNINDEX [giữ trên/thủng] [mức S hoặc R từ data] + [tín hiệu] → [hệ quả đóng cửa]")

## ⚠️ Rủi ro cần lưu ý (phiên chiều)
[Red flags, phân phối, rủi ro vĩ mô/kỹ thuật với mức cảnh báo cụ thể; "Không có rủi ro đặc biệt" nếu thị trường ổn]
Nếu có block "Cơ bản nhóm theo dõi": CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng "Đòn bẩy cao nhất (D/E)" hoặc "Lưu chuyển tiền HĐKD thấp nhất" trong block, ghi kèm TÊN MÃ THẬT + CON SỐ THẬT copy từ block, dạng "<tên mã> D/E=<số>" — THAY <tên mã> bằng MÃ THẬT (vd "HPG D/E=1,5"; "KBC Op.CF=-17.344 tỷ"), TUYỆT ĐỐI KHÔNG in chữ "MÃ"/"<tên mã>". MỌI mã được nhắc trong mục này PHẢI kèm CON SỐ CỦA CHÍNH NÓ — TUYỆT ĐỐI KHÔNG viết "X và Y cũng có D/E cao" mà KHÔNG ghi số; nếu không ghi số thì KHÔNG nêu mã đó. MÃ trong block gồm CẢ VN30 LẪN mã rủi ro ĐÒN BẨY phải là mã D/E CAO NHẤT trong dòng "Đòn bẩy cao nhất" — KHÔNG nêu mã D/E < 1,5 (vd HPG 0,65) làm rủi ro đòn bẩy (D/E thấp = an toàn). mid-cap → KHÔNG ghi "cao nhất trong VN30"; chỉ ghi "cao nhất trong nhóm theo dõi". Ngân hàng/CK/bảo hiểm đã bị loại khỏi xếp hạng → KHÔNG nêu nhóm tài chính làm rủi ro đòn bẩy/dòng tiền. Mã gắn "(BĐS)" trong dòng Op.CF: dòng tiền âm CHỦ YẾU do tích lũy quỹ đất/hàng tồn kho dự án (vốn lưu động), KHÔNG phải lỗ HĐKD → PHẢI ghi kèm ngữ cảnh này + soi D/E/nợ vay, TUYỆT ĐỐI KHÔNG gọi là "kiệt quệ tiền mặt". Nếu block không có mã đáng lưu ý → nêu rủi ro vĩ mô/kỹ thuật, KHÔNG dẫn mã ngoài data.

## 📅 Sự kiện sắp tới
[Nếu có block "Sự kiện sắp tới" trong data: liệt kê 1-3 sự kiện gần nhất (GDKHQ cổ tức/chia tách/ĐHCĐ) kèm mã + ngày, ưu tiên mã VN30/watchlist; nhắc "giá tự điều chỉnh ngày GDKHQ". Nếu KHÔNG có block đó → ghi "Không có sự kiện đáng chú ý" hoặc bỏ mục này.]

## 🌐 Vĩ mô: lãi suất & tỷ giá
[Nếu có block "🌐 Vĩ mô" trong data: tóm tắt 1-2 dòng — tỷ giá USD/VND + lãi suất điều hành/liên ngân hàng, GHI RÕ thay đổi (▲/▼ + as_of) nếu có. Nêu hàm ý: lãi suất TĂNG / VND mất giá = thắt chặt → bất lợi cổ phiếu (nhất là nhóm vay nợ cao, khối ngoại dễ bán ròng); lãi suất giảm / VND ổn định = thuận lợi. DÙNG ĐÚNG số + as_of trong block, KHÔNG bịa. Nếu KHÔNG có block đó → ghi "Chưa có dữ liệu vĩ mô" hoặc bỏ mục này.]

## 📰 Tin kinh tế/chính trị nổi bật
[Nếu có block "📰 Tin kinh tế/chính trị" trong data: nêu 1-3 tin TÁC ĐỘNG MẠNH nhất tới thị trường (vĩ mô/lãi suất/tỷ giá/chính sách/địa chính trị), kèm hướng tác động (tích cực/tiêu cực cho TTCK) và ngành liên quan nếu rõ. DÙNG ĐÚNG tiêu đề trong block, TUYỆT ĐỐI KHÔNG bịa tin. Nếu KHÔNG có block đó → ghi "Không có tin vĩ mô nổi bật" hoặc bỏ mục này.]

## 📚 Báo cáo vĩ mô & phân bổ
[Nếu có block "📚 Báo cáo vĩ mô & phân bổ" trong data: chép các dòng của block (band phân bổ tháng + quan điểm báo cáo CTCK/chuyên gia + consensus). Đây là bối cảnh KHUNG THÁNG — TUYỆT ĐỐI KHÔNG đổi Bias/Stance NGÀY theo nó; nếu lệch chiều với Bias ngày thì ghi rõ "khung thời gian khác nhau". DÙNG ĐÚNG band/số trong block, TUYỆT ĐỐI KHÔNG bịa band (B0-B4) hay % phân bổ. Nếu KHÔNG có block đó → bỏ mục này.]

## 📌 Danh mục đang giữ
[Nếu có block "📌 Danh mục đang giữ" trong data: với MỖI vị thế, chép NGUYÊN VĂN dòng dữ kiện của mã đó từ block (mã, số cp, vốn, hiện, lãi/lỗ %) rồi nối ' → ' + hành động (GIỮ / GIA TĂNG / GIẢM TỶ TRỌNG / CANH BÁN) + 1 lý do ngắn gắn với Stance/regime/tin trong prompt. Khi Bias/Stance nghiêng GIẢM → KHÔNG khuyên GIA TĂNG vô điều kiện (chỉ GIỮ/GIẢM TỶ TRỌNG/CANH BÁN, hoặc "GIA TĂNG chỉ khi vượt <mức>"). TUYỆT ĐỐI dùng đúng số trong block — không tự tính lại, không thêm mã ngoài block. Nếu KHÔNG có block đó → ghi "Không có vị thế đang mở" hoặc bỏ mục này.]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã từ block "Khuyến nghị từ chiến lược đã backtest" với entry/TP/SL]
BẮT BUỘC: Nếu quyết định bị ảnh hưởng bởi tin tức trong block "Tin tức thị trường", PHẢI nêu rõ tên tiêu đề tin và giải thích tác động (ví dụ: "HPG: MUA — kỹ thuật vượt MA20 + tin [Hòa Phát ký hợp đồng thép 5.000 tỷ] hỗ trợ đà tăng"). Bỏ qua nếu không có khuyến nghị.

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[Optional — nếu không nghĩ ra gì NGOÀI dữ liệu đã có thì ghi "Không cần bổ sung". ĐÃ CÓ trong prompt (TUYỆT ĐỐI KHÔNG xin lại, dù gọi tên khác): dòng tiền khối ngoại/NN ròng, GTGD/thanh khoản, độ rộng (breadth/A-D/% trên MA200), regime, TÂM LÝ/momentum, Cơ bản nhóm theo dõi (D/E/ROE/OCF), lịch GDKHQ cổ tức/chia tách (nếu có block "Sự kiện sắp tới"), VĨ MÔ — lãi suất điều hành/liên ngân hàng, tỷ giá USD/VND, lợi suất TPCP 2Y/10Y, CPI/lạm phát, IIP, PMI, GDP, cán cân thương mại, lãi suất Fed + US10Y (tất cả trong block "🌐 Vĩ mô"). CHỈ nêu thứ THỰC SỰ thiếu (vd: giá dầu Brent/WTI, lịch công bố KQKD, định giá P/E ngành so sánh).]

Giới hạn 500 từ. Khi nói về cổ phiếu cụ thể, CHỈ đề cập mã CÓ TRONG các block đã cung cấp (VN30 + mid-cap thanh khoản cao); KHÔNG nhắc mã ngoài data.
YÊU CẦU VỀ ĐỘ CỤ THỂ — KHÔNG ĐƯỢC VI PHẠM:
- Mọi nhận định PHẢI gắn với SỐ trong data, không nói "tích cực/tiêu cực" suông.
- Ngành được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp (ghi đúng khung "1 tuần" như trong data, KHÔNG ghi "hôm nay").
- Mã được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có.
- Ưu tiên ngành/mã có đóng góp TUYỆT ĐỐI lớn nhất, không chỉ tăng % cao nhất.
- Kịch bản phải có TRIGGER (mức giá/chỉ số/% volume) — không viết "nếu thị trường tốt".
- Nếu không đủ data cho một mục → viết "Cần thêm [data X]", không bịa.
- MỌI % thay đổi giá PHẢI ghi rõ khung thời gian: "hôm nay", "phiên sáng", "5 phiên", "so với đóng cửa hôm qua", v.v. TUYỆT ĐỐI KHÔNG viết "X giảm Y%" mà không có khung thời gian.
- Viết THUẦN tiếng Việt — KHÔNG chèn từ tiếng Anh (vd "mua ròng strongest" → "mua ròng mạnh nhất") HAY ký tự Trung/Nhật/Hàn (vd "达到") vào câu. Thuật ngữ chuẩn (RSI, MA20, A/D, Op.CF, D/E, GTGD…) giữ nguyên.
"""

_AFTERNOON_TEMPLATE = """\
{system}

Dữ liệu thị trường kết thúc PHIÊN CHIỀU (15:00):

{data}

---
Viết AFTERNOON BRIEF tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 🎯 TLDR (2 dòng)
**Kết quả phiên:** [VNINDEX đóng cửa ±X% / GTGD Y tỷ — 1 câu nhận định bản chất]
**Stance ngày mai:** [TĂNG / GIẢM / TRUNG TÍNH bias + 1 setup ưu tiên. Setup phải có ngưỡng TRIGGER và ngưỡng HỦY là 2 MỨC KHÁC NHAU (không trùng): GIẢM → "canh giảm nếu thủng S1=[số] → mục tiêu S2=[số]; hủy nếu vượt lại R1=[số]"; TĂNG → "canh mua nếu vượt R1=[số] → mục tiêu R2=[số]; hủy nếu thủng S1=[số]". TUYỆT ĐỐI KHÔNG để mức trigger trùng mức hủy.]

## 📊 Tổng kết phiên
[2-3 câu: kết quả toàn ngày, GTGD vs trung bình, độ rộng thị trường (A/D, % trên MA200), so sánh với kỳ vọng sáng nếu có]
BẮT BUỘC nếu có block "Tâm lý thị trường": nêu RÕ nhãn tâm lý + điểm momentum (vd "Tâm lý: ❄️ Sợ hãi, momentum -51/100") và 1 câu nó hàm ý gì cho xu hướng ngắn hạn.

## 📈 Mức kỹ thuật chốt phiên (VNINDEX)
TRÍCH XUẤT TỪ block "## VNINDEX kỹ thuật" — KHÔNG BỊA.
**Đóng cửa:** [chính xác `close` từ data, ví dụ "1,815.42 (+0.38%)" — GIỮ NGUYÊN định dạng số như trong data: dấu phẩy ngăn nghìn, dấu chấm thập phân]
**Vị trí trong range:** [LẤY ĐÚNG dòng "Vị trí range tuần" trong block kỹ thuật (đã tính sẵn %+nhãn) — KHÔNG tự suy "nửa trên/dưới"]
**Vs MA:** [BẮT BUỘC nêu ĐỦ CẢ BA — MA20, MA50, MA200 — trên/dưới + khoảng cách % theo data. KHÔNG được bỏ MA nào.]
**Trigger ngày mai:** [BẮT BUỘC nêu CẢ HAI chiều, trung tính (KHÔNG phải setup Stance): "vượt R1=[số] → test R2=[số]; thủng S1=[số] → về S2=[số]"]
Nếu block "VNINDEX kỹ thuật" KHÔNG có → viết "Chưa có dữ liệu VNINDEX hôm nay".

## 🏆 Dẫn dắt & Tụt hậu
DÙNG ĐÚNG block "🎯 Dẫn dắt/Tụt hậu — CHỐT THEO DATA" ở trên (không tự chọn ngành khác):
**Dẫn dắt:** [ngành lead đã chốt + đóng góp pp (1 tuần). KHÔNG bịa "% return"/"composite" cho ngành — data không có % giá tuần cấp ngành (đã thấy bịa "+0.0%", "+2.0% composite"). Nếu block ghi "Chưa có nhóm dẫn dắt rõ ràng" → ghi Y NHƯ VẬY, KHÔNG nêu ngành đóng góp <0.05pp làm dẫn dắt]
**Tụt hậu:** [ngành lag đã chốt + đóng góp pp (1 tuần)]

## 💰 Dòng tiền đáng chú ý
[NN mua/bán ròng đáng kể (số tỷ cụ thể) | smart money tích luỹ/phân phối | unusual volume; bỏ qua nếu phẳng]
Nếu có block "Dòng tiền ngành": nêu RÕ ngành NN MUA RÒNG / BÁN RÒNG mạnh nhất (lấy số "NN ròng", đơn vị tỷ, có dấu +/-). PHÂN BIỆT rõ "NN ròng" (khối ngoại mua-bán ròng) với "GTGD" (thanh khoản/giá trị giao dịch) — TUYỆT ĐỐI KHÔNG gọi GTGD là "dòng tiền vào". Nhận định luân chuyển dòng tiền giữa các ngành dựa trên NN ròng.

## 📋 Watchlist sáng mai
(Hướng dẫn — KHÔNG in tiêu đề phụ này vào brief) TỐI ĐA 3 setup, chỉ mã CÓ GIÁ thật. CHỈ chọn mã ĐỦ ĐIỀU KIỆN SETUP: mã trong block "Top Gainers/Losers thanh khoản cao" CÓ DẤU ⭐ (thanh khoản đủ cao — VN30 hoặc GTGD ≥ 30 tỷ/phiên), HOẶC mã trong block "Khuyến nghị". Mã movers KHÔNG có ⭐ (thanh khoản 10-30 tỷ) chỉ dùng để phân tích "Biến động bất thường", TUYỆT ĐỐI KHÔNG đưa vào setup giao dịch (đưa lệnh vào mã mỏng là rủi ro). TUYỆT ĐỐI KHÔNG dùng/bịa mã KHÔNG có trong các block đó (vd mã UPCOM/penny ngoài data), và KHÔNG độn cho đủ 3.
Mỗi setup PHẢI neo vào "Giá" THỰC; KHÔNG tự nghĩ ra mức giá. Chỉ 1-2 mã ⭐ đủ điều kiện → đưa ĐÚNG 1-2 setup (TUYỆT ĐỐI KHÔNG thêm dòng kiểu "Giá không có / Cần thêm dữ liệu" cho mã thiếu giá).
Block "Top Gainers/Losers thanh khoản cao" BÌNH THƯỜNG có sẵn vài mã ⭐ kèm "Giá" → BẮT BUỘC dùng ÍT NHẤT 1-2 mã ⭐ đó làm setup. CHỈ viết đúng 1 dòng "Cần thêm dữ liệu giá cổ phiếu cụ thể" khi KHÔNG có mã ⭐ nào kèm "Giá" — KHÔNG dùng câu đó nếu vẫn còn mã ⭐ kèm "Giá", và KHÔNG thay bằng mã không-⭐.
CHIỀU LỆNH — hướng setup PHẢI nhất quán với "Stance ngày mai"/bias: Stance GIẢM (regime/momentum yếu) → ƯU TIÊN mẫu phòng thủ (GIẢM TỶ TRỌNG/TRÁNH), KHÔNG mở loạt setup MUA mới; nếu nêu MUA thì PHẢI là kèo CÓ ĐIỀU KIỆN ("chỉ canh MUA NẾU vượt lại [kháng cự]"). Stance TĂNG → ưu tiên MUA. Chọn ĐÚNG 1 trong 2 mẫu, mốc giá phải đúng thứ tự (TỰ KIỂM TRA trước khi xuất, không được mâu thuẫn):
- Ý tưởng TĂNG → "MUA vùng [entry] · chốt lời [TP] · cắt lỗ [SL]" — BẮT BUỘC SL < entry < TP.
- Ý tưởng GIẢM → KHÔNG viết "SELL ở [giá]" (TTCK VN không cho NĐT cá nhân bán khống). Viết: "GIẢM TỶ TRỌNG/TRÁNH nếu thủng [hỗ trợ] · mục tiêu về [thấp hơn] · hủy kịch bản nếu vượt lại [cao hơn]" — BẮT BUỘC mục tiêu < hỗ trợ < mức hủy.
MỐC GIÁ SETUP MỖI MÃ LẤY TỪ "[dải ±3% quanh giá: X – Y]" ĐÃ TÍNH SẴN ngay sau mã ⭐ trong block movers. Dùng đúng các số đó: entry/mốc dưới ≈ X, mốc trên/mục tiêu tăng ≈ Y, TP/SL nới thêm vài % cùng thang. ⚠️ X,Y là GIÁ ×0,97 và ×1,03 — KHÔNG đo từ đỉnh/đáy nào: TUYỆT ĐỐI KHÔNG gọi chúng là "hỗ trợ", "kháng cự", "vùng cung cầu" hay bất kỳ chữ nào hàm ý mốc kỹ thuật đo được; gọi là "mốc tham chiếu" / "dải ±3%". TUYỆT ĐỐI KHÔNG dùng mức S1/S2/R1/R2 của VNINDEX (vd 1.801,66 / 1.789,31 — đó là ĐIỂM SỐ CHỈ SỐ, KHÔNG phải giá cổ phiếu) làm mốc cho setup một mã. Nếu mốc setup có cùng thang số với VNINDEX (1.7xx-1.8xx) trong khi Giá mã ở thang khác → SAI, làm lại bằng "dải ±3% quanh giá".
Setup đưa ra là setup THẬT để theo dõi — TUYỆT ĐỐI KHÔNG viết chú thích meta kiểu "(đây là ví dụ)", "(không dùng thực tế)", "(mang tính minh họa)", "(không có đủ thông tin)". Nếu không đủ tự tin về một mã → BỎ HẲN mã đó (ít setup hơn vẫn tốt hơn setup kèm disclaimer).
1. **[Mã]** (Giá [số] từ data) — [đúng 1 trong 2 mẫu trên] — [trigger 1 dòng]
2. [chỉ thêm nếu có mã thứ 2 ĐỦ GIÁ — nếu không, bỏ dòng này]
3. [chỉ thêm nếu có mã thứ 3 ĐỦ GIÁ — nếu không, bỏ dòng này]

## ⚠️ Rủi ro cần lưu ý
[Red flags, distribution, macro risk với mức cảnh báo cụ thể; "Không có rủi ro đặc biệt" nếu thị trường ổn]
Nếu có block "Cơ bản nhóm theo dõi": CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng "Đòn bẩy cao nhất (D/E)" hoặc "Lưu chuyển tiền HĐKD thấp nhất" trong block, ghi kèm TÊN MÃ THẬT + CON SỐ THẬT copy từ block, dạng "<tên mã> D/E=<số>" — THAY <tên mã> bằng MÃ THẬT (vd "HPG D/E=1,5"; "KBC Op.CF=-17.344 tỷ"), TUYỆT ĐỐI KHÔNG in chữ "MÃ"/"<tên mã>". MỌI mã được nhắc trong mục này PHẢI kèm CON SỐ CỦA CHÍNH NÓ — TUYỆT ĐỐI KHÔNG viết kiểu "PET và VTZ cũng có D/E cao" hay "KBC và NVL có Op.CF thấp nhất" mà KHÔNG ghi số; nếu không ghi số thì KHÔNG nêu mã đó. MÃ trong block gồm CẢ VN30 LẪN mã rủi ro ĐÒN BẨY phải là mã D/E CAO NHẤT trong dòng "Đòn bẩy cao nhất" — KHÔNG nêu mã D/E < 1,5 (vd HPG 0,65) làm rủi ro đòn bẩy (D/E thấp = an toàn). mid-cap → KHÔNG ghi "cao nhất trong VN30" (nhiều mã không thuộc VN30); chỉ ghi "cao nhất trong nhóm theo dõi". TUYỆT ĐỐI KHÔNG in nguyên ký hiệu mẫu (X, Y, "MÃ", "số") — phải thay bằng giá trị thật. Nếu block KHÔNG có mã Op.CF âm đáng lưu ý → CHỈ nêu rủi ro D/E (mã cao nhất), KHÔNG đề cập Op.CF, KHÔNG ghi placeholder. TUYỆT ĐỐI KHÔNG: (a) dẫn mã KHÔNG có trong block (vd VCK); (b) nói "cần thêm dữ liệu/chỉ số" — số ĐÃ có trong block; (c) gọi "Op.CF âm" cho mã có Op.CF ≥ 0 (chỉ ghi "âm" khi số THỰC < 0, còn lại ghi "Op.CF thấp"); (d) gán rủi ro sang ngành dẫn dắt/tụt hậu. Ngân hàng/CK/bảo hiểm đã bị loại khỏi xếp hạng → KHÔNG nêu nhóm tài chính làm rủi ro đòn bẩy/dòng tiền. Mã gắn "(BĐS)" trong dòng Op.CF: dòng tiền âm CHỦ YẾU do tích lũy quỹ đất/hàng tồn kho dự án (vốn lưu động), KHÔNG phải lỗ HĐKD → PHẢI ghi kèm ngữ cảnh này + soi D/E/nợ vay, TUYỆT ĐỐI KHÔNG gọi là "kiệt quệ tiền mặt". Nếu block không có mã đáng lưu ý → nêu rủi ro vĩ mô/kỹ thuật, KHÔNG dẫn mã ngoài data.

## 📅 Sự kiện sắp tới
[Nếu có block "Sự kiện sắp tới" trong data: liệt kê 1-3 sự kiện gần nhất (GDKHQ cổ tức/chia tách/ĐHCĐ) kèm mã + ngày, ưu tiên mã VN30/watchlist; nhắc "giá tự điều chỉnh ngày GDKHQ". Nếu KHÔNG có block đó → ghi "Không có sự kiện đáng chú ý" hoặc bỏ mục này.]

## 🌐 Vĩ mô: lãi suất & tỷ giá
[Nếu có block "🌐 Vĩ mô" trong data: tóm tắt 1-2 dòng — tỷ giá USD/VND + lãi suất điều hành/liên ngân hàng, GHI RÕ thay đổi (▲/▼ + as_of) nếu có. Nêu hàm ý: lãi suất TĂNG / VND mất giá = thắt chặt → bất lợi cổ phiếu (nhất là nhóm vay nợ cao, khối ngoại dễ bán ròng); lãi suất giảm / VND ổn định = thuận lợi. DÙNG ĐÚNG số + as_of trong block, KHÔNG bịa. Nếu KHÔNG có block đó → ghi "Chưa có dữ liệu vĩ mô" hoặc bỏ mục này.]

## 📰 Tin kinh tế/chính trị nổi bật
[Nếu có block "📰 Tin kinh tế/chính trị" trong data: nêu 1-3 tin TÁC ĐỘNG MẠNH nhất tới thị trường (vĩ mô/lãi suất/tỷ giá/chính sách/địa chính trị), kèm hướng tác động (tích cực/tiêu cực cho TTCK) và ngành liên quan nếu rõ. DÙNG ĐÚNG tiêu đề trong block, TUYỆT ĐỐI KHÔNG bịa tin. Nếu KHÔNG có block đó → ghi "Không có tin vĩ mô nổi bật" hoặc bỏ mục này.]

## 📚 Báo cáo vĩ mô & phân bổ
[Nếu có block "📚 Báo cáo vĩ mô & phân bổ" trong data: chép các dòng của block (band phân bổ tháng + quan điểm báo cáo CTCK/chuyên gia + consensus). Đây là bối cảnh KHUNG THÁNG — TUYỆT ĐỐI KHÔNG đổi Bias/Stance NGÀY theo nó; nếu lệch chiều với Stance ngày mai thì ghi rõ "khung thời gian khác nhau". DÙNG ĐÚNG band/số trong block, TUYỆT ĐỐI KHÔNG bịa band (B0-B4) hay % phân bổ. Nếu KHÔNG có block đó → bỏ mục này.]

## 📌 Danh mục đang giữ
[Nếu có block "📌 Danh mục đang giữ" trong data: với MỖI vị thế, chép NGUYÊN VĂN dòng dữ kiện của mã đó từ block (mã, số cp, vốn, hiện, lãi/lỗ %) rồi nối ' → ' + hành động (GIỮ / GIA TĂNG / GIẢM TỶ TRỌNG / CANH BÁN) + 1 lý do ngắn gắn với Stance/regime/tin trong prompt. Khi Bias/Stance nghiêng GIẢM → KHÔNG khuyên GIA TĂNG vô điều kiện (chỉ GIỮ/GIẢM TỶ TRỌNG/CANH BÁN, hoặc "GIA TĂNG chỉ khi vượt <mức>"). TUYỆT ĐỐI dùng đúng số trong block — không tự tính lại, không thêm mã ngoài block. Nếu KHÔNG có block đó → ghi "Không có vị thế đang mở" hoặc bỏ mục này.]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã với entry/TP/SL từ block "Khuyến nghị"]
BẮT BUỘC: Nếu có tin tức tác động → nêu rõ tiêu đề tin + ảnh hưởng. Bỏ qua nếu không có khuyến nghị.

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[Optional — nếu không nghĩ ra gì NGOÀI dữ liệu đã có thì ghi "Không cần bổ sung". ĐÃ CÓ trong prompt (TUYỆT ĐỐI KHÔNG xin lại, dù gọi tên khác): dòng tiền khối ngoại/NN ròng, GTGD/thanh khoản, độ rộng (breadth/A-D/% trên MA200), regime, TÂM LÝ/momentum, Cơ bản nhóm theo dõi (D/E/ROE/OCF), lịch GDKHQ cổ tức/chia tách (nếu có block "Sự kiện sắp tới"), VĨ MÔ — lãi suất điều hành/liên ngân hàng, tỷ giá USD/VND, lợi suất TPCP 2Y/10Y, CPI/lạm phát, IIP, PMI, GDP, cán cân thương mại, lãi suất Fed + US10Y (tất cả trong block "🌐 Vĩ mô"). CHỈ nêu thứ THỰC SỰ thiếu (vd: giá dầu Brent/WTI, lịch công bố KQKD, định giá P/E ngành so sánh).]

Giới hạn 500 từ. Khi nói về cổ phiếu cụ thể, CHỈ đề cập mã CÓ TRONG các block đã cung cấp (VN30 + mid-cap thanh khoản cao); KHÔNG nhắc mã ngoài data. Nếu thị trường flat và không có signal rõ thì nói thẳng.
YÊU CẦU VỀ ĐỘ CỤ THỂ — KHÔNG ĐƯỢC VI PHẠM:
- Mọi nhận định PHẢI gắn với SỐ trong data.
- Ngành được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp (ghi đúng khung "1 tuần" như trong data, KHÔNG ghi "hôm nay").
- Mã được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có.
- Ưu tiên ngành/mã có đóng góp TUYỆT ĐỐI lớn nhất, không chỉ tăng % cao nhất.
- Setup watchlist phải có TRIGGER (mức giá cụ thể) — không viết "nếu thị trường tích cực thì vào".
- Nếu không đủ data → viết "Cần thêm [data X]", không bịa.
- MỌI % thay đổi giá PHẢI ghi rõ khung thời gian: "hôm nay", "phiên sáng", "5 phiên", "so với đóng cửa hôm qua", v.v. TUYỆT ĐỐI KHÔNG viết "X giảm Y%" mà không có khung thời gian.
- Viết THUẦN tiếng Việt — KHÔNG chèn từ tiếng Anh (vd "mua ròng strongest" → "mua ròng mạnh nhất") HAY ký tự Trung/Nhật/Hàn (vd "达到") vào câu. Thuật ngữ chuẩn (RSI, MA20, A/D, Op.CF, D/E, GTGD…) giữ nguyên.
"""

# Brief PHÂN BỔ TÀI SẢN — brief_type="allocation", cadence THÁNG, CHỈ dashboard
# (không đẩy Telegram — tham số duyệt #4). Khác 2 brief ngày: khung thời gian
# trung hạn, xoay quanh band B0-B4 + bảng % của vnstock_allocation. LLM chỉ
# viết LỜI DIỄN GIẢI — band + bảng % được guard enforce_allocation_table pin
# lại theo data (nguyên tắc #1: LLM không bao giờ sinh số %/band).
_ALLOCATION_TEMPLATE = """\
{system}

Dữ liệu cho BRIEF PHÂN BỔ TÀI SẢN (khung THÁNG — trung hạn, KHÔNG phải brief phiên):

{data}

---
Viết BRIEF PHÂN BỔ TÀI SẢN tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 🎯 TLDR (2 dòng)
**Band phân bổ:** [chép ĐÚNG band + nhãn từ block "🧭 Phân bổ hiện hành" (vd "B2 — trung tính") + 1 câu vì sao, có số]
**Hành động:** [1 câu — điều chỉnh tỷ trọng VỀ bảng đề xuất theo lộ trình vài phiên, không xoay danh mục trong 1 phiên]

## 🧭 Phân bổ đề xuất
[Chép NGUYÊN VĂN các dòng "- <Lớp tài sản>: <số>%" và dòng "- Band: ..." từ block "🧭 Phân bổ hiện hành". TUYỆT ĐỐI KHÔNG tự sinh/đổi số % hay band — hệ thống sẽ pin lại mục này theo data.]

## 📊 Vì sao ở band này
[Từ các dòng "Lý do" trong block "🧭 Phân bổ hiện hành": diễn giải 3-5 tín hiệu (regime/tâm lý/độ rộng/áp lực vĩ mô/gauge thanh khoản-kỳ hạn-quốc tế) — mỗi tín hiệu kèm SỐ + nguồn + as_of đúng như data. KHÔNG bịa số, KHÔNG thêm tín hiệu ngoài block.]

## 📚 Quan điểm từ báo cáo
[Nếu có block "📚 Báo cáo vĩ mô & phân bổ": tóm quan điểm từng báo cáo (nguồn + ngày + stance) và consensus/tilt. Nếu KHÔNG có → ghi "Chưa có báo cáo vĩ mô trong thư viện".]

## ⚠️ Rủi ro & lưu ý khung thời gian
[Band là khung THÁNG: nếu bias/tín hiệu NGÀY trong data đang lệch chiều với band → ghi rõ 2 khung thời gian khác nhau, KHÔNG phủ định nhau, hành động phân bổ vẫn theo lộ trình. Nêu 2-3 rủi ro chính CÓ TRONG data (vĩ mô/kỹ thuật/tin) khiến band có thể đổi kỳ tới. Nếu data có block "🗣 Phản biện": PHẢI đối diện TỪNG luận điểm — mỗi luận điểm 1 câu đồng ý/bác bỏ kèm lý do bám số liệu (không in nguyên văn block, không bịa số mới). KHÔNG bịa.]

Giới hạn 350 từ. Viết THUẦN tiếng Việt — KHÔNG chèn từ tiếng Anh hay ký tự Trung/Nhật/Hàn; thuật ngữ chuẩn (RSI, MA20, D/E, GTGD…) giữ nguyên. Số giữ định dạng EN như data (phẩy ngăn nghìn, chấm thập phân). Nếu data thiếu mục nào → ghi "Chưa có dữ liệu", KHÔNG suy đoán.
"""


# ── Agent base class ───────────────────────────────────────────────────────
class BriefAgent(ABC):
    """Abstract market brief generator. Subclass to add a new AI provider."""
    name: str
    agent_type: str

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        """Generate brief text.
        Returns (text, error_message). error is None on success.
        """

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True if the required API key is set in environment."""

    def ping(self) -> tuple[bool, str]:
        """Quick connectivity check. Returns (ok, message)."""
        if not self.is_available:
            return False, "API key chưa thiết lập"
        _, err = self.generate("Trả lời đúng 2 từ: 'OK hoạt động'", max_tokens=20)
        return (True, "✅ Kết nối OK") if err is None else (False, f"❌ {err[:120]}")


def _ledger_record(provider: str, model: str, ok: bool,
                   usage: "dict | None" = None,
                   error: "str | None" = None) -> None:
    """Ghi sổ call LLM (vnstock_llm_ledger) — best-effort, không bao giờ raise.
    Trước 22/07 brief KHÔNG ghi sổ → ledger mù call trả phí của agent."""
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


# ── Concrete agents ────────────────────────────────────────────────────────
class ClaudeAgent(BriefAgent):
    """Anthropic Messages API."""
    agent_type = "claude"
    _ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-haiku-4-5-20251001",
                 name: str = "Claude Haiku"):
        self.model = model
        self.name = name

    @property
    def is_available(self) -> bool:
        return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())

    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            return "", "ANTHROPIC_API_KEY chưa được thiết lập trong .env"
        try:
            import requests as _req
            resp = _req.post(
                self._ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "temperature": _BRIEF_TEMPERATURE,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("stop_reason") == "max_tokens":
                # Output bị CẮT — bản cụt lên Telegram tệ hơn lỗi (bài close
                # 06/08 06:53): coi là LỖI để generate_brief lấy dự phòng.
                _ledger_record("Anthropic", self.model, ok=False,
                               error="stop_reason=max_tokens (output cụt)")
                return "", ("Claude API: output bị cắt (stop_reason="
                            "max_tokens — đụng trần budget)")
            _ledger_record("Anthropic", self.model, ok=True,
                           usage=body.get("usage"))
            return body["content"][0]["text"], None
        except Exception as e:
            _ledger_record("Anthropic", self.model, ok=False,
                           error=f"{type(e).__name__}: {str(e)[:120]}")
            return "", f"Claude API lỗi: {type(e).__name__}: {str(e)[:160]}"


class _OpenAICompatAgent(BriefAgent):
    """Base for any provider that uses the OpenAI chat-completions wire format."""
    agent_type = "openai"
    _ENDPOINT: str = "https://api.openai.com/v1/chat/completions"
    _ENV_KEY: str = "OPENAI_API_KEY"
    _ERR_PREFIX: str = "API"
    _LEDGER: str = "OpenAI"          # nhãn provider trong llm_ledger

    def __init__(self, model: str, name: str):
        self.model = model
        self.name = name

    @property
    def is_available(self) -> bool:
        return bool((os.environ.get(self._ENV_KEY) or "").strip())

    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        api_key = (os.environ.get(self._ENV_KEY) or "").strip()
        if not api_key:
            return "", f"{self._ENV_KEY} chưa được thiết lập trong .env"
        sys_end = prompt.find("\n\nDữ liệu thị trường")
        system_part = prompt[:sys_end].strip() if sys_end > 0 else _SYSTEM
        user_part = prompt[sys_end:].strip() if sys_end > 0 else prompt
        try:
            import requests as _req
            resp = _req.post(
                self._ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "temperature": _BRIEF_TEMPERATURE,
                    "messages": [
                        {"role": "system", "content": system_part},
                        {"role": "user", "content": user_part},
                    ],
                },
                timeout=90,
            )
            resp.raise_for_status()
            body = resp.json()
            choice = (body.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                # Output bị CẮT vì đụng trần max_tokens nhưng HTTP 200 —
                # bài close 06/08 06:53: Gemini flash "suy nghĩ" ~5k token,
                # content đứt giữa câu vẫn được tính THÀNH CÔNG → bản cụt
                # thắng bản trọn vẹn của agent yếu hơn và lên Telegram.
                # Coi là LỖI agent → cơ chế "(dự phòng)" kích hoạt.
                _ledger_record(self._LEDGER, self.model, ok=False,
                               error="finish_reason=length (output cụt)")
                return "", (f"{self._ERR_PREFIX}: output bị cắt (finish_"
                            "reason=length — đụng trần budget/thinking)")
            _ledger_record(self._LEDGER, self.model, ok=True,
                           usage=body.get("usage"))
            return choice["message"]["content"], None
        except Exception as e:
            _ledger_record(self._LEDGER, self.model, ok=False,
                           error=f"{type(e).__name__}: {str(e)[:120]}")
            detail = ""
            try:
                detail = " | " + str(resp.json())[:300]
            except Exception:
                pass
            return "", f"{self._ERR_PREFIX} lỗi: {type(e).__name__}: {str(e)[:200]}{detail}"


class OpenAIAgent(_OpenAICompatAgent):
    """OpenAI Chat Completions."""
    agent_type = "openai"
    _ENDPOINT = "https://api.openai.com/v1/chat/completions"
    _ENV_KEY = "OPENAI_API_KEY"
    _ERR_PREFIX = "OpenAI API"

    def __init__(self, model: str = "gpt-4o-mini", name: str = "GPT-4o mini"):
        super().__init__(model, name)


class GroqAgent(_OpenAICompatAgent):
    """Groq Cloud — OpenAI-compatible endpoint (very fast inference)."""
    agent_type = "groq"
    _ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
    _ENV_KEY = "GROQ_API_KEY"
    _ERR_PREFIX = "Groq API"
    _LEDGER = "Groq"

    def __init__(self, model: str = "qwen/qwen3.6-27b", name: str = "Groq Qwen3.6-27B"):
        # llama-3.3-70b-versatile deprecated 17/06/2026 — qwen3.6-27b là slug
        # Groq chỉ định thay (probe sống 22/07, scripts/probe_models.py)
        super().__init__(model, name)


class MistralAgent(_OpenAICompatAgent):
    """Mistral AI — OpenAI-compatible chat completions endpoint."""
    agent_type = "mistral"
    _ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
    _ENV_KEY = "MISTRAL_API_KEY"
    _ERR_PREFIX = "Mistral API"
    _LEDGER = "Mistral"

    def __init__(self, model: str = "mistral-small-latest", name: str = "Mistral Small"):
        super().__init__(model, name)


class DeepSeekAgent(_OpenAICompatAgent):
    """DeepSeek — excellent code generation, very cheap pricing."""
    agent_type = "deepseek"
    _ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
    _ENV_KEY = "DEEPSEEK_API_KEY"
    _ERR_PREFIX = "DeepSeek API"
    _LEDGER = "DeepSeek"

    def __init__(self, model: str = "deepseek-chat", name: str = "DeepSeek Chat"):
        super().__init__(model, name)


class CerebrasAgent(_OpenAICompatAgent):
    """Cerebras Cloud — ultra-fast inference (2000+ tok/s), Llama models."""
    agent_type = "cerebras"
    _ENDPOINT = "https://api.cerebras.ai/v1/chat/completions"
    _ENV_KEY = "CEREBRAS_API_KEY"
    _ERR_PREFIX = "Cerebras API"
    _LEDGER = "Cerebras"

    # Try models in order; Cerebras occasionally renames or deprecates.
    # 22/07/2026: toàn bộ họ llama đã bị GỠ (probe: catalog chỉ còn
    # gpt-oss-120b / gemma-4-31b / zai-glm-4.7 sắp dep 17/08).
    _MODEL_FALLBACKS: list[str] = [
        "gpt-oss-120b",    # mạnh nhất còn lại (digest đạt 14/07)
        "gemma-4-31b",     # non-reasoning, nhanh
    ]

    def __init__(self, model: str = "gpt-oss-120b", name: str = "Cerebras GPT-OSS-120B"):
        super().__init__(model, name)

    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        api_key = (os.environ.get(self._ENV_KEY) or "").strip()
        if not api_key:
            return "", f"{self._ENV_KEY} chưa được thiết lập trong .env"
        sys_end = prompt.find("\n\nDữ liệu thị trường")
        system_part = prompt[:sys_end].strip() if sys_end > 0 else _SYSTEM
        user_part = prompt[sys_end:].strip() if sys_end > 0 else prompt

        candidates: list[str] = [self.model]
        for fb in self._MODEL_FALLBACKS:
            if fb != self.model and fb not in candidates:
                candidates.append(fb)

        import requests as _req
        last_err = ""
        last_detail = ""
        for idx, model in enumerate(candidates):
            resp = None
            try:
                resp = _req.post(
                    self._ENDPOINT,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "temperature": _BRIEF_TEMPERATURE,
                        "messages": [
                            {"role": "system", "content": system_part},
                            {"role": "user", "content": user_part},
                        ],
                    },
                    timeout=90,
                )
                resp.raise_for_status()
                body = resp.json()
                choice = (body.get("choices") or [{}])[0]
                if choice.get("finish_reason") == "length":
                    # Output cụt (xem _OpenAICompatAgent) — kiểu "suy nghĩ"
                    # mỗi model khác nhau → thử model kế trong danh sách.
                    _ledger_record(self._LEDGER, model, ok=False,
                                   error="finish_reason=length (output cụt)")
                    last_err = "output bị cắt (finish_reason=length)"
                    last_detail = ""
                    continue
                _ledger_record(self._LEDGER, model, ok=True,
                               usage=body.get("usage"))
                content = choice["message"]["content"]
                if idx > 0:
                    content = f"_(fallback: {model})_\n\n{content}"
                return content, None
            except Exception as e:
                _ledger_record(self._LEDGER, model, ok=False,
                               error=f"{type(e).__name__}: {str(e)[:120]}")
                detail = ""
                if resp is not None:
                    try:
                        detail = " | " + str(resp.json())[:300]
                    except Exception:
                        pass
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                last_detail = detail
                status = getattr(resp, "status_code", None)
                # Only fallback on model-not-found (404) or server errors
                if status not in (404, 429, 502, 503, 504):
                    break
        return "", f"{self._ERR_PREFIX} lỗi: {last_err}{last_detail}"


class OpenRouterAgent(_OpenAICompatAgent):
    """OpenRouter — single key to access 100+ models, several free tiers."""
    agent_type = "openrouter"
    _ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    _MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"
    _ENV_KEY = "OPENROUTER_API_KEY"
    _ERR_PREFIX = "OpenRouter API"
    _LEDGER = "OpenRouter"

    # Process-level cache of free model slugs fetched from /api/v1/models
    _free_model_cache: list[str] = []

    def __init__(
        self,
        model: str = "nvidia/nemotron-3-super-120b-a12b:free",
        name: str = "OpenRouter Nemotron Super",
    ):
        # llama-3.3-70b hết bản :free (probe 22/07) — nemotron-3-super-120b
        # là model :free tầm 70-120B mạnh + nhanh nhất catalog hiện tại
        super().__init__(model, name)

    @classmethod
    def _fetch_free_models(cls, api_key: str) -> list[str]:
        """Fetch available free model slugs from OpenRouter /api/v1/models."""
        if cls._free_model_cache:
            return cls._free_model_cache
        try:
            import requests as _req
            resp = _req.get(
                cls._MODELS_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
            free = [m["id"] for m in models if str(m.get("id", "")).endswith(":free")]
            # Prefer larger (70b) models first, then smaller ones
            free.sort(key=lambda x: ("70b" not in x, "8b" not in x, x))
            cls._free_model_cache = free
            return free
        except Exception:
            return []

    def _post_one(self, model: str, system_part: str, user_part: str,
                  api_key: str, max_tokens: int):
        import requests as _req
        return _req.post(
            self._ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/pichu124/vnstock-dashboard",
                "X-Title": "VNStock Dashboard",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": _BRIEF_TEMPERATURE,
                "messages": [
                    {"role": "system", "content": system_part},
                    {"role": "user", "content": user_part},
                ],
            },
            timeout=90,
        )

    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        api_key = (os.environ.get(self._ENV_KEY) or "").strip()
        if not api_key:
            return "", f"{self._ENV_KEY} chưa được thiết lập trong .env"
        sys_end = prompt.find("\n\nDữ liệu thị trường")
        system_part = prompt[:sys_end].strip() if sys_end > 0 else _SYSTEM
        user_part = prompt[sys_end:].strip() if sys_end > 0 else prompt

        # Build candidate list: configured model first, then all available free
        # models fetched dynamically from OpenRouter so slugs are always valid
        free_models = self._fetch_free_models(api_key)
        candidates: list[str] = [self.model]
        for m in free_models:
            if m != self.model and m not in candidates:
                candidates.append(m)
        candidates = candidates[:12]  # cap to avoid burning too many API calls

        last_err = ""
        last_detail = ""
        for idx, model in enumerate(candidates):
            resp = None
            try:
                resp = self._post_one(model, system_part, user_part, api_key, max_tokens)
                resp.raise_for_status()
                body = resp.json()
                choice = (body.get("choices") or [{}])[0]
                if choice.get("finish_reason") == "length":
                    # Output cụt (xem _OpenAICompatAgent) → thử model kế.
                    _ledger_record(self._LEDGER, model, ok=False,
                                   error="finish_reason=length (output cụt)")
                    last_err = "output bị cắt (finish_reason=length)"
                    last_detail = ""
                    continue
                _ledger_record(self._LEDGER, model, ok=True,
                               usage=body.get("usage"))
                content = choice["message"]["content"]
                if idx > 0:
                    content = f"_(fallback: {model})_\n\n{content}"
                return content, None
            except Exception as e:
                _ledger_record(self._LEDGER, model, ok=False,
                               error=f"{type(e).__name__}: {str(e)[:120]}")
                detail = ""
                if resp is not None:
                    try:
                        detail = " | " + str(resp.json())[:200]
                    except Exception:
                        pass
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                last_detail = detail
                status = getattr(resp, "status_code", None)
                if status not in (404, 429, 502, 503, 504):
                    break
        return "", f"{self._ERR_PREFIX} lỗi: {last_err}{last_detail}"


class GeminiAgent(_OpenAICompatAgent):
    """Google AI Studio (Gemini) — endpoint OpenAI-compatible. Agent CHÍNH
    cho brief từ 22/07/2026 (user chốt all-free): gemini-3.5-flash mạnh +
    đa ngữ tốt nhất nhóm khả dụng, TPM 1M nuốt gọn prompt brief ~10K token
    (Groq TPM 8K là biên rủi ro 413), free tier 1,500 req/ngày."""
    agent_type = "gemini"
    _ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    _ENV_KEY = "GEMINI_API_KEY"
    _ERR_PREFIX = "Gemini API"
    _LEDGER = "Gemini"

    # flash SUY NGHĨ mặc định — thinking ăn budget completion; không nới thì
    # content bị cụt dưới _BRIEF_MAX_TOKENS (bài học sentiment max_tokens=10).
    # 3000 KHÔNG đủ (close 06/08 06:53: ngày data phức tạp flash nghĩ ~5k
    # token → content đứt giữa câu "Tổng kết phiên") → 8000. Đây là TRẦN,
    # không phải chi phí — không nghĩ nhiều thì không tốn; free tier chịu được.
    _THINK_HEADROOM = 8000

    def __init__(self, model: str = "gemini-3.5-flash", name: str = "Gemini 3.5 Flash"):
        super().__init__(model, name)

    def generate(self, prompt: str, max_tokens: int = 1200) -> tuple[str, str | None]:
        return super().generate(prompt, max_tokens=max_tokens + self._THINK_HEADROOM)


# ── Agent registry ─────────────────────────────────────────────────────────
AGENT_REGISTRY: dict[str, type[BriefAgent]] = {
    "gemini": GeminiAgent,
    "claude": ClaudeAgent,
    "openai": OpenAIAgent,
    "groq": GroqAgent,
    "mistral": MistralAgent,
    "deepseek": DeepSeekAgent,
    "cerebras": CerebrasAgent,
    "openrouter": OpenRouterAgent,
}


# Obsolete model names → current model names (auto-migrate on load).
# "Bảng đổi số" 22/07/2026: config đã lưu trên máy user (brief_agents.json)
# KHÔNG tự đổi khi sửa default trong code — bảng này vá tận nơi, đúng 1 lần,
# giữ nguyên enabled/thứ tự/tên; provider khai tử model lần tới chỉ cần thêm
# 1 dòng map + 1 dòng test (slug mới đều đã probe sống — scripts/probe_models.py).
_MODEL_MIGRATIONS: dict[tuple[str, str], str] = {
    # Groq deprecate 17/06/2026
    ("groq", "llama-3.3-70b-versatile"): "qwen/qwen3.6-27b",
    ("groq", "llama-3.1-8b-instant"):    "openai/gpt-oss-20b",
    # Cerebras đã gỡ toàn bộ họ llama (probe 22/07: catalog còn 3 model)
    ("cerebras", "llama-3.3-70b"):       "gpt-oss-120b",
    ("cerebras", "llama3.3-70b"):        "gpt-oss-120b",
    ("cerebras", "llama3.1-70b"):        "gpt-oss-120b",
    ("cerebras", "llama3.1-8b"):         "gpt-oss-120b",
    # OpenRouter gỡ bản :free của llama 3.3/3.1
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"):
        "nvidia/nemotron-3-super-120b-a12b:free",
    ("openrouter", "meta-llama/llama-3.1-8b-instruct:free"):
        "openai/gpt-oss-20b:free",
}


# ── Config helpers ─────────────────────────────────────────────────────────
def _default_agent_name(agent_type: "str | None") -> "str | None":
    for c in _DEFAULT_AGENT_CONFIGS:
        if c.get("type") == agent_type:
            return c.get("name")
    return None


def _name_mentions_model(name: str, model: str) -> bool:
    """Tên hiển thị có đang MÔ TẢ model không (họ model xuất hiện trong tên)?
    Dùng khi migration đổi model: tên mặc định kiểu "Groq Llama-3.3-70B" nhắc
    họ "llama" → stale, cần thay; tên user tự đặt không nhắc → giữ nguyên."""
    low = (name or "").lower()
    toks = [t for t in _re.split(r"[^a-z]+", (model or "").lower())
            if len(t) >= 4]
    return any(t in low for t in toks)


# Agent brief bị TẮT CHỦ ĐỘNG theo (type, model) — khác _MODEL_MIGRATIONS
# (đổi slug chết sang slug sống): đây là ghế NGỒI NHẦM CHỖ, model sống nhưng
# không gánh nổi VIỆC NÀY. Tắt đúng MỘT lần qua marker `auto_disabled` —
# user bật lại trong ⚙️ là chủ đích, load sau không giành tay lái nữa.
_BRIEF_AGENT_DISABLES: dict[tuple, str] = {
    # 413 CẤU TRÚC (bằng chứng 11/08 qua memory CLI): prompt brief ~10K token
    # > trần 8K/request Groq free — rủi ro notes 22/07 đã ghi, thành hiện
    # thực từ ngày migrate llama→qwen, fail 100% suốt 3 tuần (không log nên
    # không ai biết). qwen vẫn phục vụ [2][3-6][8] bình thường (prompt nhỏ).
    ("groq", "qwen/qwen3.6-27b"):
        "413 Payload Too Large — prompt brief ~10K > trần 8K/request Groq free",
}


def load_agent_configs() -> list[dict]:
    """Load agent configs from JSON, merging in any new providers from defaults
    and migrating obsolete model names."""
    saved: list[dict] = []
    if AGENTS_CONFIG_PATH.exists():
        try:
            saved = json.loads(AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not saved:
        return [c.copy() for c in _DEFAULT_AGENT_CONFIGS]

    # Auto-migrate obsolete model names so users don't get stuck on 404s
    changed = False
    for cfg in saved:
        key = (cfg.get("type"), cfg.get("model"))
        if key in _MODEL_MIGRATIONS:
            cfg["model"] = _MODEL_MIGRATIONS[key]
            # Tên hiển thị mô tả model CŨ mà giữ nguyên thì dashboard A/B
            # gây nhầm (lộ 30/07: 3 dòng "Llama-3.3-70B" nhưng model thật
            # đã là qwen/gpt-oss). Chỉ thay khi tên đang NHẮC model cũ —
            # tên user tự đặt ("Bản nháp của tôi") không đụng.
            new_name = _default_agent_name(cfg.get("type"))
            if new_name and _name_mentions_model(cfg.get("name", ""), key[1]):
                cfg["name"] = new_name
            changed = True

    # Sửa tên NÓI DỐI — trạng thái nửa-migrate (lộ 11/08 qua memory CLI):
    # config đổi model TRƯỚC khi f13a33f thêm rename → "Cerebras Llama-3.3-70B"
    # chạy gpt-oss-120b, key migration không còn khớp nên rename không bao giờ
    # re-fire. Chỉ thay tên đang NHẮC một model đã migrate đi của cùng type;
    # tên user tự đặt ("Bản nháp của tôi") không nhắc model nào → giữ nguyên.
    for cfg in saved:
        t, model, name = cfg.get("type"), cfg.get("model", ""), cfg.get("name", "")
        if not (t and model and name) or _name_mentions_model(name, model):
            continue
        if any(k[0] == t and _name_mentions_model(name, k[1])
               for k in _MODEL_MIGRATIONS):
            new_name = _default_agent_name(t)
            if new_name and new_name != name:
                cfg["name"] = new_name
                changed = True

    # Tắt agent ngồi nhầm chỗ (xem _BRIEF_AGENT_DISABLES) — một lần duy nhất
    for cfg in saved:
        why = _BRIEF_AGENT_DISABLES.get((cfg.get("type"), cfg.get("model")))
        if why and cfg.get("enabled") and not cfg.get("auto_disabled"):
            cfg["enabled"] = False
            cfg["auto_disabled"] = why
            changed = True
            print(f"[brief] tự tắt agent {cfg.get('name')}: {why} "
                  f"(bật lại trong ⚙️ nếu muốn — sẽ không tự tắt nữa)")

    # Merge: add any provider types from defaults that are absent in saved file
    saved_types = {c.get("type") for c in saved}
    merged = list(saved)
    for default in _DEFAULT_AGENT_CONFIGS:
        if default.get("type") not in saved_types:
            merged.append(default.copy())
            changed = True

    if changed:
        try:
            save_agent_configs(merged)
        except Exception:
            pass
    return merged


def save_agent_configs(configs: list[dict]) -> None:
    # Nguyên tử: đây là LỰA CHỌN CỦA USER (bật/tắt agent, tên tự đặt) — mất
    # là user phải chỉnh lại tay, khác cache dựng lại được. Ghi thẳng thì
    # crash giữa chừng để lại file JSON cụt, load sau parse hỏng → rơi về
    # _DEFAULT_AGENT_CONFIGS, im lặng mất hết tuỳ chỉnh.
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(configs, AGENTS_CONFIG_PATH)


def build_agents(configs: list[dict] | None = None) -> list[BriefAgent]:
    """Instantiate all enabled agents from config."""
    if configs is None:
        configs = load_agent_configs()
    agents: list[BriefAgent] = []
    for cfg in configs:
        if not cfg.get("enabled", False):
            continue
        cls = AGENT_REGISTRY.get(cfg.get("type", ""))
        if cls:
            agents.append(cls(
                model=cfg.get("model", ""),
                name=cfg.get("name", cfg.get("type", "")),
            ))
    return agents


# Thứ tự SỨC MẠNH agent (user chốt 22/07: chạy/chọn bản chính từ agent mạnh
# trước, yếu dần khi lỗi). gemini-3.5-flash đứng đầu nhóm khả dụng; claude/
# openai là nấc trả phí opt-in (có key sẽ được ưu tiên ngay sau); openrouter
# :free cuối vì quota 50 req/ngày + catalog churn. Type lạ (agent user tự
# thêm) xếp sau cùng, giữ thứ tự config (sort ổn định).
_AGENT_STRENGTH: tuple = ("gemini", "claude", "openai", "deepseek",
                          "groq", "mistral", "cerebras", "openrouter")


def _strength_sorted(agents: list[BriefAgent]) -> list[BriefAgent]:
    """Sắp agent theo _AGENT_STRENGTH (mạnh → yếu), sort ổn định."""
    def _rank(a: BriefAgent) -> int:
        t = getattr(a, "agent_type", "")
        return _AGENT_STRENGTH.index(t) if t in _AGENT_STRENGTH else len(_AGENT_STRENGTH)
    return sorted(agents, key=_rank)


def _brief_alert_down(context: str) -> None:
    """Brief không có bản nào thành công → báo Telegram (throttle/kill-switch
    ở vnstock_llm_ledger.alert_ladder_down). Best-effort tuyệt đối."""
    try:
        from vnstock_llm_ledger import alert_ladder_down
        alert_ladder_down(context)
    except Exception:
        pass


# ── Effective trading date ─────────────────────────────────────────────────
def effective_trading_date(vnindex_tech: dict | None = None) -> str:
    """Return the ISO date of the latest trading session the brief describes.

    Prefers the last VNINDEX bar date in the warehouse, falls back to the most
    recent session-stats key, then to calendar today. Use this (not
    date.today()) so a brief pushed on a weekend / early morning is labelled
    with the actual session it analyses, e.g. data from Fri 05/06 when pushed
    on Sun 07/06.

    Pass a pre-computed `vnindex_tech` dict to avoid recomputing it.
    """
    vt = vnindex_tech if vnindex_tech is not None else _vnindex_technicals()
    data_date = (vt or {}).get("data_date")

    if not data_date:
        try:
            from vnstock_session_stats import load_session_stats_history as _lssh
            _hist = _lssh()
            if _hist:
                data_date = max(_hist.keys())
        except Exception:
            pass

    return data_date or date.today().isoformat()


# ── Data freshness: breadth/movers/regime lag behind intraday VNINDEX ───────
#
# market_overview.json (độ rộng A/D, % trên MA200, VN30 movers, dòng tiền
# ngành) and the regime it feeds are refreshed only by the screener
# (vnstock_runner). The live WSS pipeline updates VNINDEX/GTGD but NOT these.
# So once a morning brief folds in today's intraday VNINDEX, those blocks can
# silently lag a session. These helpers detect and (optionally) heal that.
def _market_overview_data_date(path: "str | Path | None" = None) -> "str | None":
    """Return the trading date of the DATA inside market_overview.json.

    Prefers the explicit `data_date` field (the latest stock bar actually used);
    falls back to the `generated_at` date for older files written before that
    field existed. This — not the file's write time — is what tells us whether
    breadth/movers/regime trail the brief's session.
    """
    p = Path(path) if path else Path("data_warehouse/_meta/market_overview.json")
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        dd = data.get("data_date")
        if dd:
            return str(dd)
        # No data_date field (file written before it existed): the breadth was
        # computed from the daily warehouse, so its true data date is the
        # warehouse EOD date — NOT generated_at (wall clock), which would look
        # falsely fresh and suppress the staleness warning.
        eod = _warehouse_eod_date()
        if eod:
            return eod
        gen = str(data.get("generated_at", ""))  # last-resort backward-compat
        return gen.split(" ")[0] if gen else None
    except Exception:
        return None


def _warehouse_eod_date() -> "str | None":
    """Latest VNINDEX daily bar date in the warehouse (NO intraday augmentation).

    Used to decide whether re-running the screener would actually surface newer
    data — recomputing can't conjure intraday stock breadth, so we only refresh
    when the overview genuinely trails the EOD warehouse.
    """
    try:
        df = _load_vnindex_df(augment=False)
        if df is None or df.empty or "close" not in df.columns:
            return None
        return df.loc[df["close"].notna(), "time"].iloc[-1].date().isoformat()
    except Exception:
        return None


def _bias_floor_dir(momentum: "int | None", regime_score: "int | None") -> "str | None":
    """Force a TLDR Bias direction when the headline signals are strongly
    one-sided and not in conflict.

    Inputs are the two signals shown in the brief header: Tâm lý `momentum`
    (-100..100) and Regime `score` (signed, out of ~7). Returns "GIẢM", "TĂNG",
    or None (let the agent decide). Thresholds: momentum ±50 or regime ±3.
    """
    bear = (momentum is not None and momentum <= -50) or \
           (regime_score is not None and regime_score <= -3)
    bull = (momentum is not None and momentum >= 50) or \
           (regime_score is not None and regime_score >= 3)
    if bear and not bull:
        return "GIẢM"
    if bull and not bear:
        return "TĂNG"
    return None


# Mốc coi PHIÊN ĐÃ ĐÓNG (user chốt 19/08) — khớp mốc screener đang dùng.
# Dưới mốc này, `market_overview` chỉ mới thấy MỘT PHẦN phiên.
SESSION_CLOSE_CUTOFF = time(15, 5)


def _market_overview_generated_at(
        path: "str | Path | None" = None) -> "datetime | None":
    """`generated_at` ĐẦY ĐỦ (có giờ) của market_overview.json.

    Vì sao cần cả GIỜ, không chỉ ngày: `_market_overview_data_date` trả về NGÀY
    nên "độ rộng chốt lúc 11:00" và "độ rộng chốt phiên" trông y hệt nhau —
    `stale` = False cho cả hai, và brief chiều mô tả cả phiên trong khi độ rộng
    / VN30 movers / dòng tiền ngành mới thấy nửa buổi sáng. Đó là lỗ hổng độ
    tươi phải kiểm bằng TAY suốt (mục "Bước 2" trong sổ việc).

    Chấp nhận cả `"%Y-%m-%d %H:%M:%S"` (định dạng `vnstock_runner` đang ghi),
    bản không giây, và ISO có `T`. Không parse được → None (chỗ gọi tự lo).
    """
    p = Path(path) if path else Path("data_warehouse/_meta/market_overview.json")
    if not p.exists():
        return None
    try:
        raw = str(json.loads(p.read_text(encoding="utf-8"))
                  .get("generated_at", "")).strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def market_data_freshness(
    data_date: str | None = None,
    overview_path: "str | Path | None" = None,
) -> dict:
    """Compare the screener-produced blocks' DATA date to the session date.

    Trả `{"data_date", "overview_date", "stale", "stale_blocks", "reason",
    "overview_time"}`. HAI kiểu cũ (`reason`):

    * `prev_session` — overview từ phiên TRƯỚC. Luật cũ, so NGÀY.
    * `intraday` — overview CÙNG phiên nhưng chốt TRƯỚC `SESSION_CLOSE_CUTOFF`
      ⇒ nó mới thấy một phần phiên. Luật này thêm 19/08: so ngày là không đủ,
      "độ rộng lúc 11:00" và "độ rộng chốt phiên" cùng một `data_date`, nên lỗ
      hổng phải kiểm bằng tay suốt.

    Mốc so là GIỜ GHI của overview, KHÔNG phải giờ hiện tại — nên hàm vẫn
    thuần theo file, chạy lúc nào cũng ra cùng kết quả.
    """
    dd = data_date or effective_trading_date()
    ov = _market_overview_data_date(overview_path)
    stale = bool(ov and dd and ov < dd)
    reason = "prev_session" if stale else ""
    gen = _market_overview_generated_at(overview_path)
    if not stale and ov and dd and ov == dd and gen is not None:
        # Chỉ tính là "giữa phiên" khi overview được ghi ĐÚNG trong ngày phiên
        # đó. Ghi ở ngày SAU (chạy bù sáng hôm sau từ data EOD) thì nó đã thấy
        # trọn phiên — cờ ở đây là báo động giả.
        if gen.date().isoformat() == dd and gen.time() < SESSION_CLOSE_CUTOFF:
            stale, reason = True, "intraday"
    blocks = (
        ["độ rộng", "VN30 movers", "dòng tiền ngành", "regime"] if stale else []
    )
    return {"data_date": dd, "overview_date": ov, "stale": stale,
            "stale_blocks": blocks, "reason": reason,
            "overview_time": gen.strftime("%H:%M") if gen else None}


def _auto_refresh_market_overview() -> bool:
    """Recompute + save market_overview.json when it trails the EOD warehouse.

    Best-effort and heavy (re-aggregates the whole market), so it only runs when
    the warehouse actually holds newer daily data than the overview — never just
    to re-stamp the same intraday-stale breadth. Disable with
    VNSTOCK_BRIEF_AUTO_REFRESH=0. Returns True if a refresh ran and saved.
    """
    if os.environ.get("VNSTOCK_BRIEF_AUTO_REFRESH", "1") == "0":
        return False
    ov = _market_overview_data_date()
    eod = _warehouse_eod_date()
    if ov is None and eod is None:
        return False  # nothing to compute from
    if ov is not None and eod is not None and not (ov < eod):
        return False  # overview already at the latest available data
    try:
        from vnstock_runner import compute_market_overview, save_market_overview
        data = compute_market_overview()
        if data and (data.get("tickers") or data.get("sectors")):
            save_market_overview(data)
            return True
    except Exception:
        pass
    return False


def _maybe_reconcile_overdue() -> int:
    """Close recommendations past their horizon so the brief doesn't surface
    zombies (e.g. covered warrants stuck at "ngày 34/5").

    Best-effort: only runs when an overdue open rec exists, so a fresh book
    costs nothing. Disable with VNSTOCK_BRIEF_AUTO_RECONCILE=0. Returns the
    number of recs closed.
    """
    if os.environ.get("VNSTOCK_BRIEF_AUTO_RECONCILE", "1") == "0":
        return 0
    try:
        import vnstock_memory as _mem
        now = datetime.now()
        has_overdue = False
        for r in _mem.open_recommendations():
            horizon = int(r.get("horizon_days") or 5)
            try:
                age = (now - datetime.fromisoformat(r["created_at"])).days
            except Exception:
                age = 0
            if age > _horizon_calendar_days(horizon):
                has_overdue = True
                break
        if not has_overdue:
            return 0
        from vnstock_train import reconcile_recommendations
        summary = reconcile_recommendations(verbose=False)
        return int(summary.get("closed", 0)) + int(summary.get("stale", 0))
    except Exception:
        return 0


# Cap on liquid mid-cap movers added to the daily events auto-refresh (beyond
# VN30). The refresh runs inside generate_brief and blocks it (~1 API call per
# ticker), so the universe is VN30 ∪ top-N movers by GTGD — not every liquid
# name — to keep the once-a-day refresh fast while covering anything that can
# realistically enter the watchlist/movers blocks.
_EVENTS_REFRESH_MAX_MOVERS: int = 40


def _events_universe(max_movers: int = _EVENTS_REFRESH_MAX_MOVERS,
                     overview_path: "str | Path | None" = None) -> list[str]:
    """VN30 ∪ top liquid movers (by avg GTGD) — the tickers whose corp-action
    events the brief may surface. Falls back to VN30 alone when the screener
    overview isn't available."""
    uni = set(VN30_TICKERS)
    try:
        p = Path(overview_path) if overview_path else Path(
            "data_warehouse/_meta/market_overview.json")
        rows = json.loads(p.read_text(encoding="utf-8")).get("tickers") or []
        _g, _l, liquid = _select_liquid_movers(rows)
        gtgd = {str(r.get("Mã", "")).upper(): (r.get("GTGD TB (tỷ)") or 0)
                for r in rows}
        movers = sorted((t for t in liquid if t not in uni),
                        key=lambda t: gtgd.get(t, 0), reverse=True)[:max_movers]
        uni |= set(movers)
    except Exception:
        pass
    return sorted(uni)


def _maybe_refresh_events() -> int:
    """Refresh the upcoming-events cache when it's missing or not from today, so
    the brief's "📅 Sự kiện sắp tới" block isn't empty just because the daily
    refresh hasn't run yet. Universe = VN30 ∪ top liquid movers (mid-caps that
    can enter the watchlist get their GDKHQ events too — previously VN30-only,
    so mid-cap events appeared only after a manual --tickers run). Best-effort,
    at most once/day. Disable with VNSTOCK_BRIEF_AUTO_EVENTS=0. Returns number
    of events saved.
    """
    if os.environ.get("VNSTOCK_BRIEF_AUTO_EVENTS", "1") == "0":
        return 0
    try:
        from vnstock_events import UPCOMING_EVENTS_PATH, refresh_upcoming
        p = UPCOMING_EVENTS_PATH
        if p.exists():
            mtime = datetime.fromtimestamp(p.stat().st_mtime).date()
            if mtime >= date.today():
                return 0  # already refreshed today
        return len(refresh_upcoming(tickers=_events_universe()))
    except Exception:
        return 0


def _maybe_refresh_macro() -> int:
    """Refresh the macro cache (lãi suất & tỷ giá) when it's missing or not from
    today, so the brief's "🌐 Vĩ mô" block reflects the latest reading even if the
    daily pipeline step hasn't run. Best-effort, at most once/day; a blocked FX
    fetch leaves the prior cache intact (never a fabricated number). Disable with
    VNSTOCK_BRIEF_AUTO_MACRO=0. Returns the number of indicators with a reading.
    """
    if os.environ.get("VNSTOCK_BRIEF_AUTO_MACRO", "1") == "0":
        return 0
    try:
        from vnstock_macro import _CACHE, load_macro, refresh
        if _CACHE.exists():
            mtime = datetime.fromtimestamp(_CACHE.stat().st_mtime).date()
            if mtime >= date.today():
                return len(load_macro())   # already refreshed today
        refresh()
        return len(load_macro())
    except Exception:
        return 0


def _maybe_refresh_market_news() -> int:
    """Refresh the broad economic/political news cache (RSS) when it isn't from
    today, so the brief's "📰 Tin kinh tế/chính trị" block is current. Best-effort,
    at most once/day; blocked feeds are skipped (never fabricated). Disable with
    VNSTOCK_BRIEF_AUTO_MARKET_NEWS=0. Returns number of cached items.
    """
    if os.environ.get("VNSTOCK_BRIEF_AUTO_MARKET_NEWS", "1") == "0":
        return 0
    try:
        from vnstock_news_feeds import _CACHE, load_market_news, refresh
        if _CACHE.exists():
            mtime = datetime.fromtimestamp(_CACHE.stat().st_mtime).date()
            if mtime >= date.today():
                return len(load_market_news())   # already refreshed today
        refresh()
        return len(load_market_news())
    except Exception:
        return 0


# ── VN30 fundamentals (debt/equity, ROE, operating cash flow) ───────────────
def _load_vn30_fundamentals(
    path: str | Path | None = None,
    vn30: set[str] | None = None,
) -> dict[str, dict]:
    """Load VN30 fundamentals from the weekly fundamentals.parquet cache.

    Returns {ticker: {"de", "roe", "ocf", "updated"}} for VN30 constituents
    that have a row. Empty dict if the cache is missing or holds no VN30 rows.
    Produced by vnstock_fundamental_updater.py (run weekly).
    """
    import pandas as pd
    try:
        import pyarrow.parquet as _pq
    except ImportError:
        return {}

    p = Path(path) if path else (
        Path(__file__).parent / "data_warehouse" / "_meta" / "fundamentals.parquet"
    )
    if not p.exists():
        return {}
    try:
        df = _pq.read_table(str(p)).to_pandas()
    except Exception:
        return {}
    if df.empty or "ticker" not in df.columns:
        return {}

    universe = vn30 or VN30_TICKERS
    df = df[df["ticker"].isin(universe)]
    if df.empty:
        return {}

    def _num(row, col):
        v = row.get(col) if hasattr(row, "get") else None
        try:
            return None if (v is None or pd.isna(v)) else float(v)
        except Exception:
            return None

    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        metrics = {
            "de":      _num(row, "debt_to_equity"),
            "roe":     _num(row, "roe"),
            "ocf":     _num(row, "operating_cf"),
            "updated": str(row.get("updated_at", "") or ""),
        }
        # Skip tickers with no usable fundamental at all
        if any(metrics[k] is not None for k in ("de", "roe", "ocf")):
            out[str(row["ticker"])] = metrics
    return out


def _vn30_fund_block(funds: dict[str, dict], extra_financial: "set[str] | None" = None,
                     realestate: "set[str] | None" = None) -> str:
    """Render a compact VN30 fundamentals block for the prompt.

    Shows VN30 medians plus the few names that actually matter for risk —
    highest leverage and weakest/negative operating cash flow — instead of
    dumping all 30 rows (token-efficient and more actionable).
    """
    if not funds:
        return ""
    try:
        import statistics as _st

        # D/E and Op.CF risk rankings cover NON-FINANCIALS only — bank/securities/
        # insurance leverage and cash-flow scales are not comparable. Exclude the
        # static list AND any ticker classified as financial by industry (covers
        # mid-cap banks/securities like BVB/VPX not in the static list).
        _excl = _FINANCIAL_TICKERS | (extra_financial or set())
        nonfin = {t: m for t, m in funds.items() if t not in _excl}

        des  = [(t, m["de"])  for t, m in nonfin.items() if m.get("de")  is not None]
        roes = [m["roe"]      for m in funds.values()    if m.get("roe") is not None]
        ocfs = [(t, m["ocf"]) for t, m in nonfin.items() if m.get("ocf") is not None]

        if not (des or roes or ocfs):
            return ""

        updated = next((m["updated"] for m in funds.values() if m.get("updated")), "")
        lines = [
            f"\n## Cơ bản nhóm theo dõi (VN30 + mid-cap) — D/E, ROE, Lưu chuyển tiền HĐKD"
            f"{f' (cập nhật {updated})' if updated else ''}"
        ]

        med_parts = []
        if des:
            med_parts.append(f"D/E={_st.median(v for _, v in des):.2f}")
        if roes:
            med_parts.append(f"ROE={_st.median(roes):.1f}%")
        if ocfs:
            med_parts.append(f"Op.CF={_st.median(v for _, v in ocfs):,.0f} tỷ")
        if med_parts:
            lines.append(f"- Trung vị nhóm ({len(funds)} mã có data): " + " | ".join(med_parts))

        if des:
            top_de = sorted(des, key=lambda x: x[1], reverse=True)[:3]
            lines.append(
                "- Đòn bẩy cao nhất (D/E, phi tài chính): "
                + ", ".join(f"{t} {v:.2f}" for t, v in top_de)
            )

        _re = realestate or set()
        if ocfs:
            weak = sorted(ocfs, key=lambda x: x[1])[:3]
            n_neg = sum(1 for _, v in ocfs if v < 0)
            lines.append(
                "- Lưu chuyển tiền HĐKD thấp nhất (phi tài chính): "
                + ", ".join(f"{t} {v:,.0f} tỷ{' (BĐS)' if t in _re else ''}"
                            for t, v in weak)
                + (f" ({n_neg} mã âm)" if n_neg else "")
            )

        lines.append(
            "→ DÙNG các chỉ số này khi nhận xét rủi ro cơ bản/đòn bẩy/dòng tiền; "
            "ngân hàng/CK/bảo hiểm đã loại khỏi xếp hạng D/E & dòng tiền (đặc thù "
            "ngành, không so sánh được); KHÔNG bịa số liệu tài chính khác."
        )
        if any(t in _re for t, _ in (ocfs or [])):
            lines.append(
                "→ Mã gắn (BĐS): dòng tiền HĐKD âm CHỦ YẾU do tích lũy quỹ đất / "
                "hàng tồn kho dự án (thay đổi vốn lưu động), KHÔNG phải lỗ HĐKD → "
                "diễn giải kèm D/E & nợ vay, TUYỆT ĐỐI KHÔNG gọi là 'kiệt quệ "
                "tiền mặt'."
            )
        return "\n".join(lines)
    except Exception:
        return ""


def _sector_flow_block(sectors: list[dict], nn_data_date: str | None = None,
                       session_date: str | None = None) -> str:
    """Render sector money-flow: foreign net flow (1 tuần) + liquidity by sector.

    Reads the pre-aggregated per-sector fields already in market_overview.json
    (NN 1T (tỷ), GTGD TB (tỷ)) — no extra fetching. Shows the strongest
    inflow/outflow sectors plus the most liquid ones so the agent can talk
    about rotation without inventing numbers. When the foreign-flow feed lags
    the session (nn_data_date < session_date) the window is labelled with its
    real end date so the brief doesn't present stale NN as current.
    """
    if not sectors:
        return ""
    try:
        rows = []
        for s in sectors:
            name = s.get("Ngành")
            if not name:
                continue
            nn = s.get("NN 1T (tỷ)")
            rows.append({
                "name": name,
                "nn":   float(nn) if nn is not None else 0.0,
                "gtgd": float(s.get("GTGD TB (tỷ)") or 0),
            })
        inflow  = sorted((r for r in rows if r["nn"] > 0), key=lambda r: r["nn"], reverse=True)[:3]
        outflow = sorted((r for r in rows if r["nn"] < 0), key=lambda r: r["nn"])[:3]
        top_gtgd = sorted(rows, key=lambda r: r["gtgd"], reverse=True)[:3]
        if not (inflow or outflow or any(r["gtgd"] for r in top_gtgd)):
            return ""

        _stale = (nn_data_date and session_date and nn_data_date < session_date)
        _hdr_win = (f"NN ròng 5 phiên đến {nn_data_date}" if _stale
                    else "NN ròng 1 tuần")
        lines = [f"\n## Dòng tiền ngành ({_hdr_win} + thanh khoản GTGD TB)"]
        if _stale:
            lines.append(
                f"⚠️ Dữ liệu khối ngoại MỚI ĐẾN {nn_data_date} (chưa có phiên "
                f"{session_date}); khi nêu NN ròng ghi rõ 'đến {nn_data_date}', "
                f"KHÔNG nói 'hôm nay'/'phiên này'.")
        if inflow:
            lines.append("- 🟢 NN mua ròng: " + ", ".join(
                f"{r['name']} {r['nn']:+,.0f} tỷ (GTGD {r['gtgd']:,.0f})" for r in inflow))
        if outflow:
            lines.append("- 🔴 NN bán ròng: " + ", ".join(
                f"{r['name']} {r['nn']:+,.0f} tỷ (GTGD {r['gtgd']:,.0f})" for r in outflow))
        if top_gtgd and any(r["gtgd"] for r in top_gtgd):
            lines.append("- 💧 Thanh khoản cao nhất: " + ", ".join(
                f"{r['name']} {r['gtgd']:,.0f} tỷ" for r in top_gtgd if r["gtgd"]))
        lines.append(
            "→ DÙNG khi nhận xét luân chuyển dòng tiền/thanh khoản ngành; KHÔNG bịa số."
        )
        return "\n".join(lines)
    except Exception:
        return ""


def _upcoming_events_block(events: list[dict]) -> str:
    """Render upcoming corporate events (cổ tức/chia tách/ĐHCĐ/phát hành).

    `events` comes from vnstock_events.load_upcoming(); each carries ticker,
    ex_date (ISO) and a rich Vietnamese `title`. Empty string when none.
    """
    if not events:
        return ""

    def _fmt(e: dict) -> str:
        title = str(e.get("title") or "Sự kiện DN")
        return f"- {e.get('ticker','?')}: {title} — ngày {e.get('ex_date','?')}"

    lines = ["\n## 📅 Sự kiện sắp tới (cổ tức/chia tách/ĐHCĐ/phát hành — mã trong nhóm theo dõi)"]
    lines += [_fmt(e) for e in events[:12]]
    lines.append(
        "→ Nếu mã đang giữ/watchlist có GDKHQ sắp tới, LƯU Ý nhắc (giá tự điều "
        "chỉnh giảm trong ngày GDKHQ — không phải giảm do thị trường). DÙNG ĐÚNG "
        "ngày + số, KHÔNG bịa."
    )
    return "\n".join(lines)






def _macro_block(macro: list[dict], macro_news: "list[dict] | None" = None) -> str:
    """Render the macro context block (lãi suất & tỷ giá) for the prompt.

    `macro` comes from vnstock_macro.load_macro(); each carries label/value/unit
    /as_of and an optional change. Empty string when there are no readings.
    """
    if not macro:
        return ""
    latest = max((m.get("as_of", "") for m in macro), default="")
    header = f"\n## 🌐 Vĩ mô: lãi suất & tỷ giá (tính đến {latest})"
    return "\n".join([header] + _macro_body_lines(macro, macro_news))






def _market_news_block(items: list[dict]) -> str:
    """Render the broad economic/political news block (RSS, market-moving) for the
    prompt. `items` from vnstock_news_feeds.load_market_news(). Empty when none.
    """
    if not items:
        return ""
    header = "\n## 📰 Tin kinh tế/chính trị nổi bật (ảnh hưởng thị trường)"
    return "\n".join([header] + _market_news_body_lines(items))


# ── 📚 Báo cáo vĩ mô & band phân bổ (P4) ─────────────────────────────────────



def _macro_reports_block(ctx: dict) -> str:
    """Render mục 📚 cho prompt (band tháng + digest báo cáo + consensus).
    Empty khi chưa có gì tươi (chỉ-khi-tươi: load_for_analysis đã lọc ≤90 ngày)."""
    body = _macro_reports_body_lines(ctx, directive=True)
    if not body:
        return ""
    header = "\n## 📚 Báo cáo vĩ mô & phân bổ (khung THÁNG — trung hạn)"
    return "\n".join([header] + body)




def _reflections_block(lessons: list[dict]) -> str:
    """Block 🧠 bài học từ quyết định đã đóng (vnstock_reflection) — CHỈ ở
    PROMPT làm ngữ cảnh mềm, model bị cấm tạo mục/chép nguyên văn vào brief.
    (Ý tưởng reflection-sau-outcome từ khảo sát TradingAgents 14/07.)"""
    if not lessons:
        return ""
    lines = ["\n## 🧠 Bài học từ quyết định đã đóng (NỘI BỘ — không phải mục brief)"]
    for e in lessons:
        lines.append(f"- [{e.get('date', '?')}] {e.get('label', '')}: "
                     f"{e.get('lesson', '')}")
    lines.append(
        "→ DÙNG các bài học trên để tránh lặp lỗi nhận định cũ (điều chỉnh mức "
        "thận trọng/lạc quan cho tình huống tương tự). TUYỆT ĐỐI KHÔNG chép "
        "nguyên văn, KHÔNG tạo mục 'Bài học' trong brief, KHÔNG nhắc tới block "
        "nội bộ này.")
    return "\n".join(lines)


def _debate_block(debate: "dict | None") -> str:
    """Block 🗣 phản biện band (vnstock_debate) — CHỈ vào prompt brief
    ALLOCATION; mục ⚠️ của brief phải đối diện từng luận điểm. Không splice
    vào output nên không cần guard riêng (band/% đã có enforce_allocation_table)."""
    if not debate or not debate.get("points"):
        return ""
    lines = [f"\n## 🗣 Phản biện band {debate.get('band', '?')} "
             f"(devil's advocate — NỘI BỘ, phiên {debate.get('as_of', '?')})"]
    lines += [f"- {p}" for p in debate["points"]]
    lines.append(
        "→ Trong mục '⚠️ Rủi ro & lưu ý khung thời gian' PHẢI đối diện các "
        "phản biện trên: mỗi luận điểm 1 câu đồng ý/bác bỏ kèm lý do bám số "
        "liệu đã cho. KHÔNG bịa số mới, KHÔNG in nguyên văn block này.")
    return "\n".join(lines)


def _allocation_state_block(alloc: dict) -> str:
    """Data block cho brief_type='allocation': bảng % + lý do từng input
    (nguồn + as_of) từ allocation_state — nguồn duy nhất của band/%."""
    table = _allocation_table_lines(alloc)
    if not table:
        return ""
    lines = ["\n## 🧭 Phân bổ hiện hành (từ vnstock_allocation — data, KHÔNG đổi số)"]
    lines += table
    rt = alloc.get("report_tilt") or {}
    if rt.get("tilt"):
        lines.append(f"- Tilt từ báo cáo: {rt['tilt']:+d} band "
                     f"(band data {alloc.get('band_data')}, stance CP "
                     f"{rt.get('stance_cp')}, {rt.get('n_reports')} báo cáo)")
    for r in alloc.get("inputs") or []:
        lines.append(f"- Lý do: {r.get('label')}: {r.get('value')} "
                     f"(điểm {r.get('score', 0):+.2f} × trọng số {r.get('weight')})"
                     f" — nguồn {r.get('source')}, as_of {r.get('as_of')}")
    return "\n".join(lines)


# ── Danh mục đang giữ (position-aware brief) ────────────────────────────────

def _portfolio_last_close(ticker: str, prices_dir: Path) -> float:
    """Last close for a held ticker from the newest year file (warehouse units)."""
    import pyarrow.parquet as pq
    tdir = prices_dir / f"ticker={ticker.upper()}"
    if not tdir.exists():
        return 0.0
    try:
        for ydir in sorted(tdir.glob("year=*"), reverse=True):
            for f in sorted(ydir.glob("*.parquet"), reverse=True):
                s = pq.read_table(str(f), columns=["close"]).to_pandas()["close"]
                if not s.empty:
                    return float(s.iloc[-1])
    except Exception:
        return 0.0
    return 0.0


def load_portfolio_positions(warehouse: "Path | None" = None) -> list[dict]:
    """Read the dashboard portfolio (_meta/portfolio.json, written by
    dashboard/portfolio_tab) and enrich with last close + unrealised PnL%.

    Prices are normalised to nghìn đồng (warehouse convention): the tab stores
    buy_price in raw VND (e.g. 90,000) while warehouse closes are thousands —
    the >500 threshold reconciles (same convention as _normalize_price_units).
    Best-effort: [] when the file is missing/corrupt; malformed positions are
    skipped. Kill-switch: VNSTOCK_BRIEF_PORTFOLIO=0.
    """
    if os.environ.get("VNSTOCK_BRIEF_PORTFOLIO", "1") == "0":
        return []
    root = Path(warehouse) if warehouse else Path(__file__).parent / "data_warehouse"
    try:
        raw = json.loads((root / "_meta" / "portfolio.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict] = []
    for pos in raw if isinstance(raw, list) else []:
        try:
            tk = str(pos.get("ticker", "")).strip().upper()
            qty = float(pos.get("quantity", 0))
            buy = float(pos.get("buy_price", 0))
            if not tk or qty <= 0 or buy <= 0:
                continue
            last = _portfolio_last_close(tk, root / "prices")
            if buy > 500:      # raw VND → nghìn đồng
                buy = buy / 1000.0
            if last > 500:     # defensive — warehouse already in thousands
                last = last / 1000.0
            pnl = (last / buy - 1) * 100 if last > 0 else None
            out.append({
                "ticker": tk, "qty": qty, "buy_price": round(buy, 2),
                "last_close": round(last, 2) if last > 0 else None,
                "pnl_pct": round(pnl, 1) if pnl is not None else None,
            })
        except Exception:
            continue
    return out




def _portfolio_block(positions: list[dict]) -> str:
    """Render the held-positions block for the prompt. Empty when no positions."""
    if not positions:
        return ""
    lines = [f"\n## 📌 Danh mục đang giữ ({len(positions)} vị thế — SỐ THẬT, dùng đúng)"]
    lines += [_portfolio_fact_line(p) for p in positions]
    lines.append(
        "→ Với MỖI mã: chép nguyên dòng dữ kiện trên rồi nối ' → ' + hành động "
        "(GIỮ / GIA TĂNG / GIẢM TỶ TRỌNG / CANH BÁN) + 1 lý do ngắn neo theo "
        "Stance/regime/tin trong prompt. TUYỆT ĐỐI không đổi số, không thêm mã "
        "ngoài danh sách."
    )
    return "\n".join(lines)


def _market_sentiment_block(ms: dict) -> str:
    """Render the composite market-sentiment block for the prompt."""
    if not ms:
        return ""
    try:
        _arrow = {1: "🟢", -1: "🔴", 0: "⚪"}
        lines = [
            f"\n## Tâm lý thị trường (tổng hợp) — {ms.get('mood', '—')} "
            f"| momentum {ms.get('momentum', 0):+d}/100"
        ]
        for s in ms.get("signals", []):
            lines.append(f"- {_arrow.get(s.get('dir', 0), '⚪')} {s['name']}: {s['value']}")
        lines.append(
            "→ DÙNG nhãn tâm lý + các tín hiệu trên khi đánh giá xu hướng NGẮN HẠN; "
            "momentum dương = thiên về tích cực, âm = thiên về tiêu cực. "
            "KHÔNG bịa thêm chỉ số tâm lý khác."
        )
        return "\n".join(lines)
    except Exception:
        return ""


# ── Context collection ─────────────────────────────────────────────────────

_log = logging.getLogger(__name__)


def _note_loader_error(ctx: dict, loader: str, exc: Exception) -> None:
    """Ghi vết một nguồn dữ liệu hỏng, thay cho `except Exception: pass`.

    `collect_context` gọi ~15 nguồn, nguồn nào cũng best-effort — đúng như
    thiết kế: một nguồn chết KHÔNG được kéo sập cả brief. Nhưng nuốt trọn lỗi
    thì khi brief thiếu hẳn một mục, không ai biết vì sao, cũng không biết là
    nguồn nào (quét 12/08: 13 chỗ nuốt im, và `ctx["quant_error"]` viết ra rồi
    KHÔNG AI ĐỌC).

    Hai thứ nhỏ nhưng đủ dùng: một dòng WARNING (từ 13/08 chảy vào
    `run_daily.log` THẬT qua tee của run.py — trước đó file này chưa từng
    tồn tại, xem entry 13/08 (j)) và một breadcrumb trong ctx để test/UI soi.

    KHÔNG đổi luồng: vẫn nuốt lỗi, vẫn chạy tiếp. Thiếu data thì prompt đã có
    sentinel "KHÔNG CÓ …" lo phần chống bịa (xem `tests/test_prompt_sentinels.py`).
    """
    ctx.setdefault("loader_errors", {})[loader] = f"{type(exc).__name__}: {exc}"
    _log.warning("collect_context: nguồn '%s' hỏng — %s: %s",
                 loader, type(exc).__name__, exc)
def _leadlag_candidates(sector_weights: dict) -> list[tuple[str, float]]:
    """Ứng viên (ngành, đóng góp pp 1 tuần) cho lead/lag, có SANITY GATE:
    contrib/weight ≡ "Giá 1T %" của row (by construction) — |%đổi tuần| > 35
    vượt trần vật lý sàn (HOSE ±7%/phiên → ±30%/tuần) = member data hỏng
    (close 14/07: Họ VIN 1.6%VNI với -0.873pp ⇒ -55%/tuần — chg5 rác của 1
    thành viên kéo mean cộng đều sập) → loại khỏi ứng viên, không cho lên
    headline Dẫn dắt/Tụt hậu."""
    items: list[tuple[str, float]] = []
    for name, v in (sector_weights or {}).items():
        c = (v or {}).get("_1d_contrib", 0) or 0
        w = (v or {}).get("_weight", 0) or 0
        if w > 0 and abs(c / w) > 35:
            continue
        items.append((name, c))
    return items


def _select_liquid_movers(
    tickers: list[dict],
    min_gtgd_ty: float = _LIQUID_GTGD_MIN_TY,
    min_price_ty: float = _LIQUID_PRICE_MIN_TY,
    n: int = 5,
) -> tuple[list[dict], list[dict], set[str]]:
    """Whole-market top movers, liquidity-filtered (not just VN30).

    Scans ALL tickers in market_overview, keeps those with avg trading value
    ≥ `min_gtgd_ty` tỷ (VN30 always kept — index drivers + always liquid), then
    returns the top `n` gainers / losers by 1-week % change plus the liquid
    universe (for expanding the fundamentals/risk pool). This surfaces liquid
    mid-cap movers while excluding penny/illiquid names. Returns ([], [], set())
    when the data is unavailable.
    """
    import pandas as pd

    df = pd.DataFrame(tickers)
    price_col = "Giá 1T %"
    if df.empty or price_col not in df.columns or "Mã" not in df.columns:
        return [], [], set()
    df = df.dropna(subset=[price_col])
    if df.empty:
        return [], [], set()

    if "GTGD TB (tỷ)" in df.columns:
        liquid = df[df["GTGD TB (tỷ)"].fillna(0) >= min_gtgd_ty]
        if "last" in liquid.columns:   # drop sub-floor penny/distressed names
            liquid = liquid[liquid["last"].fillna(0) >= min_price_ty]
        vn = df[df["Mã"].isin(VN30_TICKERS)]
        df = pd.concat([liquid, vn]).drop_duplicates(subset=["Mã"])
    if df.empty:
        return [], [], set()

    cols = ["Mã", price_col, "Ngành"] + (["last"] if "last" in df.columns else [])
    if "GTGD TB (tỷ)" in df.columns:   # carried through so the renderer can tag
        cols.append("GTGD TB (tỷ)")    # watchlist-eligible (≥ _WATCHLIST_GTGD_MIN_TY) movers
    gainers_df = df.nlargest(n, price_col)
    losers_df = df.nsmallest(n, price_col)

    # Guarantee ≥1 watchlist-eligible (⭐ = VN30 or GTGD ≥ threshold) name across
    # the two lists so the watchlist always has a setup anchor. Top-% movers are
    # often thin non-⭐ names (VN30 stays in `df` but rarely cracks the top-n by
    # weekly move) — observed 11/06: zero ⭐ in the block → empty watchlist +
    # the model rambling "VIW không có trong danh sách". Swap the weakest pick
    # for the strongest eligible mover, placed in the direction of its sign.
    if "GTGD TB (tỷ)" in df.columns:
        _elig = df[df["Mã"].isin(VN30_TICKERS)
                   | (df["GTGD TB (tỷ)"].fillna(0) >= _WATCHLIST_GTGD_MIN_TY)]
        _shown = set(gainers_df["Mã"]) | set(losers_df["Mã"])
        if not _elig.empty and not _elig["Mã"].isin(_shown).any():
            _e = _elig.loc[_elig[price_col].abs().idxmax()]
            _row = _elig.loc[[_e.name]]
            if _e[price_col] >= 0:
                gainers_df = pd.concat([gainers_df.head(n - 1), _row]).drop_duplicates("Mã")
            else:
                losers_df = pd.concat([losers_df.head(n - 1), _row]).drop_duplicates("Mã")

    gainers = gainers_df[cols].to_dict("records")
    losers = losers_df[cols].to_dict("records")
    universe = {str(m) for m in df["Mã"].tolist()}
    return gainers, losers, universe


def _wallclock_intraday(data_date_str: str, now: "datetime | None" = None) -> bool:
    """True when the data date IS today and the session hasn't closed (< 15:05).

    The intraday flag normally comes from folding live 1m bars in — but a
    mid-session updater run leaves a partial DAILY bar in the warehouse with no
    live file, so the system believed the session was closed (observed 13:25:
    close brief pinned the in-progress 5,921.8 tỷ as "GTGD cả ngày" and the
    morning brief leaked "sáng chiếm 88% cả ngày"). Wall-clock closes that hole.
    """
    now = now or datetime.now()
    return data_date_str == now.date().isoformat() and now.time() < time(15, 5)


def _full_wss_baselines(hist: dict, data_date: str) -> "dict | None":
    """{today, prev, avg5, avg20} cho GTGD CẢ NGÀY khung WSS (cửa sổ ``9h-15h``
    của session_stats_history) — mirror ``morning_gtgd`` để close brief so
    cả-ngày-với-cả-ngày CÙNG KHUNG ĐO (fix 21/07: số WSS từng bị gắn % tính
    trên baseline EOD — hai khung lệch hệ thống ~20-40%). Ngày capture chết
    giữa phiên (full ≤ sáng×1.05) bị loại khỏi cả today lẫn baseline.
    None khi hôm nay không có capture cả-ngày hợp lệ."""

    def _win(dstr: str, window: str):
        w = (hist.get(dstr, {}) or {}).get(window, {}) or {}
        v = (w.get("VNINDEX", {}) or {}).get("gtgd")
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    def _full(dstr: str):
        f = _win(dstr, "9h-15h")
        if not f:
            return None
        m = _win(dstr, "9h-11h30")
        if m and f <= m * 1.05:        # capture dừng giữa phiên ≠ cả ngày
            return None
        return f

    today = _full(data_date)
    if not today:
        return None
    prev_days = [d for d in sorted(hist) if d < data_date]

    def _avg(days):
        vals = [v for d in days if (v := _full(d)) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {"today": today,
            "prev": _full(prev_days[-1]) if prev_days else None,
            "avg5": _avg(prev_days[-5:]),
            "avg20": _avg(prev_days[-20:])}




_GTGD_COVERAGE_MIN_RATIO = 0.7   # ngày có count < 70% median(count) = thiếu coverage


def _gtgd_baselines(byd: dict, data_date: str) -> "dict | None":
    """full_day_gtgd_cmp {prev, avg5[, avg20]} từ map ``gtgd_by_date`` của
    runner, LOẠI các ngày under-covered khỏi baseline.

    Map per-date được cộng dồn từ 22 bar cuối CỦA TỪNG MÃ (vnstock_runner)
    → ngày nào rơi ngoài cửa sổ của các mã sync trễ / mã thiếu bar sẽ HỤT
    TỔNG một cách hệ thống, kéo baseline TB5/TB20 lệch theo trạng thái kho
    tại thời điểm chạy screener (thấy thật 21/07: bản 01:22 ra "+28% vs
    TB20" còn bản 16:18 ra "+0%" cho cùng dữ liệu — không thể cùng đúng).
    ``count`` per-date là proxy coverage: count < 70% median(count) → loại
    (phiên trầm lắng THẬT vẫn có ~hầu hết mã in ≥1 lệnh — count thấp là
    thiếu DATA, không phải thị trường vắng). prev = phiên gần nhất ĐÃ QUA
    GATE; avg20 chỉ xuất khi ≥15 phiên gated (giữ ngưỡng cũ "đủ phiên cho
    baseline TB20 thật"). Map cũ không có count → giữ hành vi cũ (không
    gate). None khi không còn phiên nào dùng được."""
    entries: list[tuple[str, float, int]] = []
    for k in sorted(byd or {}, reverse=True):
        if k >= data_date:
            continue
        e = byd.get(k) or {}
        t = e.get("total")
        if isinstance(t, (int, float)) and t > 0:
            entries.append((k, float(t), int(e.get("count") or 0)))
    if not entries:
        return None
    counts = [c for _, _, c in entries if c > 0]
    if counts:
        import statistics as _st
        _floor = _GTGD_COVERAGE_MIN_RATIO * _st.median(counts)
        gated = [t for _, t, c in entries if c >= _floor]
    else:                          # map cũ không có count → không gate
        gated = [t for _, t, _ in entries]
    if not gated:
        return None
    cmp: dict = {"prev": gated[0],
                 "avg5": round(sum(gated[:5]) / len(gated[:5]), 1)}
    if len(gated) >= 15:
        cmp["avg20"] = round(sum(gated[:20]) / len(gated[:20]), 1)
    return cmp


def collect_context(brief_type: str = "morning", auto_refresh: bool = False) -> dict:
    """Collect all available market data for brief generation.

    When `auto_refresh` is set, the screener-produced market_overview is
    recomputed first if it lags the session date (so breadth/movers/regime
    don't silently trail the intraday VNINDEX). Always records ctx["freshness"].
    """
    # Determine effective trading date: use the last bar date from VNINDEX
    # warehouse instead of calendar today. Avoids "no data" briefs when called
    # early morning (market not open yet) or on weekends/holidays.
    _vt_early = _vnindex_technicals()
    _data_date_str = effective_trading_date(_vt_early)

    _today_str = date.today().isoformat()
    _is_stale = _data_date_str < _today_str  # data is from a prior trading day

    # Wall-clock intraday override: today's bar + session not closed yet →
    # PHIÊN ĐANG DỞ even without live 1m bars (e.g. a mid-session updater run
    # left a partial daily bar). Downstream this suppresses the morning-share
    # signal and the full-day GTGD pin (both meaningless mid-session).
    if _vt_early and _wallclock_intraday(_data_date_str):
        _vt_early["intraday"] = True

    # Heal stale breadth/movers/regime before reading them (best-effort).
    if auto_refresh:
        _auto_refresh_market_overview()

    ctx: dict = {
        "brief_type": brief_type,
        "date": _data_date_str,
        "time": datetime.now().strftime("%H:%M"),
        "sectors": [],
        "breadth": {},
        "tickers": [],
    }
    if _is_stale:
        ctx["date_note"] = (
            f"(dữ liệu ngày {_data_date_str} — ngày giao dịch gần nhất; "
            f"hôm nay {_today_str} chưa có data)"
        )

    # 1. Market overview (pre-computed by runner)
    _ov = Path("data_warehouse/_meta/market_overview.json")
    if _ov.exists():
        try:
            data = json.loads(_ov.read_text(encoding="utf-8"))
            ctx["sectors"] = data.get("sectors", [])
            ctx["breadth"] = data.get("breadth", {})
            ctx["tickers"] = data.get("tickers", [])
            # Full-day GTGD (matching value) derived from the EOD bars — present
            # right after the screener runs, even when the live WSS session
            # capture (session_stats) is empty. Look up the per-date map by THIS
            # brief's effective trading date. Validity comes from the runner's
            # _pick_gtgd_session (gtgd_date = latest COMPLETE session): a brief
            # date ≤ gtgd_date is a closed session → authoritative; a brief
            # date NEWER than gtgd_date is the in-progress day the picker
            # rejected → expose as partial only ("chưa đủ dữ liệu"). NOTE: do
            # NOT gate on count/universe — only ~60% of classified names trade
            # on any given day (observed 808/1388 on a normal session).
            ctx["nn_data_date"] = data.get("nn_data_date")
            _byd = data.get("gtgd_by_date") or {}
            _gd = data.get("gtgd_date")
            _entry = _byd.get(_data_date_str)
            if _entry is None and _gd == _data_date_str:
                _entry = {"total": data.get("total_gtgd_day"),
                          "count": data.get("gtgd_ticker_count") or 0}
            _tg = (_entry or {}).get("total")
            if isinstance(_tg, (int, float)) and _tg > 0:
                _tc = int((_entry or {}).get("count") or 0)
                ctx["full_day_gtgd_count"] = _tc
                ctx["full_day_gtgd_universe"] = len(ctx.get("tickers") or [])
                if _gd and _data_date_str <= _gd:
                    ctx["full_day_gtgd"] = float(_tg)
                    # Full-day-VS-full-day comparison so the close brief doesn't
                    # borrow the morning's sáng-với-sáng % (observed: "GTGD
                    # 11,929 tỷ, giảm 43% so với sáng phiên trước" — the -43%
                    # belongs to the morning figure, not the full-day total).
                    # Baseline qua _gtgd_baselines: loại ngày under-covered
                    # (count thấp = mã sync trễ làm hụt tổng, review 21/07).
                    _cmp = _gtgd_baselines(_byd, _data_date_str)
                    if _cmp:
                        ctx["full_day_gtgd_cmp"] = _cmp
                else:
                    ctx["full_day_gtgd_partial"] = float(_tg)
        except Exception as _e:
            _note_loader_error(ctx, "market_overview", _e)

    # Record freshness of the screener-produced blocks vs the session date so
    # the prompt/header can warn when they trail the intraday VNINDEX.
    ctx["freshness"] = market_data_freshness(_data_date_str)

    # 2. Quant scores + regime
    if ctx["sectors"]:
        try:
            import pandas as pd
            from vnstock_market_analyzer import (
                compute_scores, rank, market_regime, compute_index_returns,
            )
            df = pd.DataFrame(ctx["sectors"])
            scores = compute_scores(df)
            ranked = rank(df, scores, name_col="Ngành")
            regime = market_regime(scores, ctx["breadth"])
            ctx["quant_regime"] = regime
            ctx["quant_top"] = ranked.get("top", [])[:3]
            ctx["quant_avoid"] = ranked.get("avoid", [])[:3]
            ctx["quant_rotation"] = ranked.get("rotation", [])[:3]
            ctx["quant_stealth"] = ranked.get("stealth", [])[:2]
            ctx["quant_distribution"] = ranked.get("distribution", [])[:2]
            ctx["vol_regime"] = scores["_vol_regime"].mode().iloc[0] if "_vol_regime" in scores.columns else "normal"
        except Exception as e:
            ctx["quant_error"] = str(e)      # giữ khoá cũ
            _note_loader_error(ctx, "quant_scores", e)

    # 3. Session stats (intraday GTGD profile)
    # Use effective data date — falls back to latest available day when today
    # has no data yet (early morning / weekend).
    try:
        from vnstock_session_stats import load_session_stats_history
        from vnstock_market_analyzer import session_timing_signal
        _hist = load_session_stats_history()
        _day_stats = _hist.get(_data_date_str, {})
        if not _day_stats and _hist:
            # _data_date_str not in history — pick the most recent key
            _day_stats = _hist.get(max(_hist.keys()), {})
        if _day_stats:
            ctx["session_stats"] = _day_stats
            ctx["session_timing"] = session_timing_signal(_day_stats, _hist, "VNINDEX")

            # Morning-session GTGD baselines (like-for-like: sáng vs sáng) so the
            # brief compares against the right benchmark instead of the degenerate
            # intraday "GTGD sáng = 100% cả ngày".
            def _morn(dstr: str):
                w = (_hist.get(dstr, {}) or {}).get("9h-11h30", {}) or {}
                v = (w.get("VNINDEX", {}) or {}).get("gtgd")
                try:
                    return float(v) if v else None
                except Exception:
                    return None

            _prev_days = [d for d in sorted(_hist.keys()) if d < _data_date_str]
            _today_m = _morn(_data_date_str)
            if _today_m:
                def _avg(days):
                    vals = [m for d in days if (m := _morn(d)) is not None]
                    return round(sum(vals) / len(vals), 1) if vals else None
                ctx["morning_gtgd"] = {
                    "today": _today_m,
                    "prev": _morn(_prev_days[-1]) if _prev_days else None,
                    "avg5": _avg(_prev_days[-5:]),
                    "avg20": _avg(_prev_days[-20:]),
                }

            # Full-day WSS baselines (cửa sổ 9h-15h) — cùng khung với capture
            # hiển thị, để close so cả-ngày-với-cả-ngày KHÔNG mượn khung EOD
            # (fix 21/07, xem _gtgd_close_frame).
            if _fw := _full_wss_baselines(_hist, _data_date_str):
                ctx["full_wss_gtgd"] = _fw
    except Exception as _e:
        _note_loader_error(ctx, "session_stats", _e)

    # 4. Top movers — whole-market scan, liquidity-filtered (not just VN30) so
    #    the brief can surface liquid mid-cap movers, not only index members.
    #    Keys stay vn30_gainers/losers for back-compat; content is now broader.
    if ctx["tickers"]:
        try:
            _g, _l, _uni = _select_liquid_movers(ctx["tickers"])
            ctx["vn30_gainers"] = _g
            ctx["vn30_losers"] = _l
            ctx["mover_universe"] = _uni
        except Exception as _e:
            _note_loader_error(ctx, "movers", _e)

    # 5. Market-cap weights + intraday contributions (sector & ticker level)
    if ctx["tickers"] and ctx["sectors"]:
        try:
            import pandas as pd
            tick_df = pd.DataFrame(ctx["tickers"])
            sec_df  = pd.DataFrame(ctx["sectors"])

            # Ticker weights relative to total market cap
            if "Vốn hoá (tỷ)" in tick_df.columns:
                total_mcap = tick_df["Vốn hoá (tỷ)"].fillna(0).sum()
                if total_mcap > 0:
                    tick_df["_weight"] = tick_df["Vốn hoá (tỷ)"].fillna(0) / total_mcap
                    if "Giá 1T %" in tick_df.columns:
                        tick_df["_1d_contrib"] = tick_df["_weight"] * tick_df["Giá 1T %"].fillna(0)
                    if "Ngành" in tick_df.columns:
                        keep = [c for c in ["Mã", "Vốn hoá (tỷ)", "_weight", "Giá 1T %", "_1d_contrib"]
                                if c in tick_df.columns]
                        ctx["top_stocks_per_sector"] = {
                            str(sec): grp.nlargest(3, "Vốn hoá (tỷ)")[keep].to_dict("records")
                            for sec, grp in tick_df.groupby("Ngành")
                        }

            # Sector weights relative to total sector market cap
            if "Vốn hoá (tỷ)" in sec_df.columns and "Ngành" in sec_df.columns:
                sec_total = sec_df["Vốn hoá (tỷ)"].fillna(0).sum()
                if sec_total > 0:
                    sec_df["_weight"] = sec_df["Vốn hoá (tỷ)"].fillna(0) / sec_total
                    if "Giá 1T %" in sec_df.columns:
                        sec_df["_1d_contrib"] = sec_df["_weight"] * sec_df["Giá 1T %"].fillna(0)
                    keep = [c for c in ["_weight", "_1d_contrib"] if c in sec_df.columns]
                    ctx["sector_weights"] = sec_df.set_index("Ngành")[keep].to_dict("index")
        except Exception as _e:
            _note_loader_error(ctx, "sector_weights", _e)

    # Deterministically pick the strongest +/- sector contributor (1 tuần) so the
    # brief can't dress up a negligible (+0.02pp) sector as a leader. build_prompt
    # injects these as the ONLY allowed leader/laggard.
    if _sw := ctx.get("sector_weights"):
        _items = _leadlag_candidates(_sw)
        if _items:
            _lead = max(_items, key=lambda x: x[1])
            _lag = min(_items, key=lambda x: x[1])
            ctx["max_sector_contrib"] = _lead[1]
            ctx["lead_sector"] = {"name": _lead[0], "contrib": _lead[1]}
            ctx["lag_sector"] = {"name": _lag[0], "contrib": _lag[1]}

    # 6. VNINDEX technical levels — already fetched above to determine the
    # effective date; reuse the result instead of calling again.
    ctx["vnindex_tech"] = _vt_early

    # 7. Fundamentals (D/E, ROE, operating cash flow) from weekly cache — VN30
    #    plus the liquid mid-cap movers so the risk section can flag mid-cap
    #    leverage/cash-flow too, not only index members.
    _fund_universe = set(VN30_TICKERS) | (ctx.get("mover_universe") or set())
    _vn30_fund = _load_vn30_fundamentals(vn30=_fund_universe)
    if _vn30_fund:
        ctx["vn30_fundamentals"] = _vn30_fund

    # Financials by INDUSTRY (robust beyond the static _FINANCIAL_TICKERS list) so
    # mid-cap banks/securities (e.g. BVB, VPX) don't leak into the D/E & Op.CF
    # risk ranking after the universe was broadened to mid-caps.
    _fin = {
        str(_t.get("Mã", "")).upper()
        for _t in (ctx.get("tickers") or [])
        if any(k in str(_t.get("Ngành", "")).lower()
               for k in ("ngân hàng", "chứng khoán", "bảo hiểm", "tài chính"))
    }
    if _fin:
        ctx["financial_tickers"] = _fin

    # Real-estate developers by INDUSTRY. Their operating cash flow is dominated
    # by land-bank / project-inventory build (working-capital swings), so a large
    # negative OCF (e.g. KBC -17,344 tỷ in FY2025, all from WC — op. profit was
    # positive) is NOT distress. Keep them in the ranking but tag them so the
    # brief adds context (soi D/E/nợ vay) instead of calling it "kiệt quệ".
    _re = {
        str(_t.get("Mã", "")).upper()
        for _t in (ctx.get("tickers") or [])
        if "bất động sản" in str(_t.get("Ngành", "")).lower()
    }
    if _re:
        ctx["realestate_tickers"] = _re

    # 7b. Upcoming corporate events (ex-dividend / split / bonus) for the tracked
    #     universe so the brief can flag ngày GDKHQ (giá tự điều chỉnh).
    try:
        from vnstock_events import load_upcoming
        _ev = load_upcoming(within_days=14, tickers=_fund_universe)
        if _ev:
            ctx["upcoming_events"] = _ev
    except Exception as _e:
        _note_loader_error(ctx, "upcoming_events", _e)

    # 8. Composite market sentiment (tâm lý thị trường) — synthesises breadth +
    # NN flow + index momentum + news sentiment into one short-term mood.
    try:
        from vnstock_market_sentiment import load_market_sentiment
        _ms = load_market_sentiment(vnindex_tech=_vt_early, breadth=ctx.get("breadth"))
        if _ms:
            ctx["market_sentiment"] = _ms
    except Exception as _e:
        _note_loader_error(ctx, "market_sentiment", _e)

    # 8b. Macro context (lãi suất & tỷ giá) — current levels + change detection
    # so the brief can frame the session against monetary conditions and ĐÓN ĐẦU
    # shifts. Levels read for THIS brief's effective date (last reading on/before
    # it); the related-news scan reuses the existing news cache (no new fetch).
    try:
        from vnstock_macro import load_macro, macro_news
        _macro = load_macro(_data_date_str)
        if _macro:
            ctx["macro"] = _macro
            ctx["macro_news"] = macro_news()
    except Exception as _e:
        _note_loader_error(ctx, "macro", _e)

    # 8c. Broad economic/political news (RSS, market-moving) with LLM sentiment +
    # impact — surfaces macro/geopolitical context beyond per-ticker corporate news.
    try:
        from vnstock_news_feeds import load_market_news
        # drop_no_impact: hide items the LLM judged irrelevant to VN equities
        # (e.g. pure geopolitics) so the brief block stays market-focused.
        _mkt_news = load_market_news(within_days=3, limit=6, drop_no_impact=True)
        if _mkt_news:
            ctx["market_news"] = _mkt_news
    except Exception as _e:
        _note_loader_error(ctx, "market_news", _e)

    # 8d. Held positions (dashboard portfolio) so the brief ties Rủi ro /
    # hành động vào các mã user thực sự đang cầm (position-aware analysis).
    try:
        if _pf := load_portfolio_positions():
            ctx["portfolio"] = _pf
    except Exception as _e:
        _note_loader_error(ctx, "portfolio", _e)

    # 8e. Báo cáo vĩ mô + band phân bổ (P4) — digest đã cache (P3) + state
    # allocation (P1) cho mục "📚" (brief ngày: 1 dòng band + tóm tắt báo cáo;
    # brief allocation: cả bảng %). Đọc cache THUẦN — zero LLM/zero fetch tại
    # đây. Tắt: VNSTOCK_BRIEF_REPORTS=0.
    if os.environ.get("VNSTOCK_BRIEF_REPORTS", "1") != "0":
        try:
            from vnstock_reports import load_for_analysis as _rp_lfa
            _reps = [r for r in _rp_lfa(as_of=_data_date_str) if r.get("digest")]
            if _reps:
                ctx["macro_reports"] = _reps[:3]
                from vnstock_report_digest import consensus as _rd_consensus
                if _cons := _rd_consensus(as_of=_data_date_str):
                    ctx["reports_consensus"] = _cons
        except Exception as _e:
            _note_loader_error(ctx, "macro_reports", _e)
        try:
            from vnstock_allocation import load_state as _alloc_state
            if _st := _alloc_state():
                # bỏ history (nặng, không cần cho prompt); giữ bảng % + inputs
                ctx["allocation"] = {k: v for k, v in _st.items()
                                     if k != "history"}
        except Exception as _e:
            _note_loader_error(ctx, "allocation", _e)

    # 8f. Bài học reflection (rec đã đóng / kỳ band đã khép) — ngữ cảnh mềm
    # giúp brief tránh lặp lỗi nhận định cũ (vnstock_reflection — ý tưởng
    # TradingAgents). Đọc cache thuần. Tắt: VNSTOCK_BRIEF_REFLECTIONS=0.
    if os.environ.get("VNSTOCK_BRIEF_REFLECTIONS", "1") != "0":
        try:
            from vnstock_reflection import load_lessons
            if _lessons := load_lessons(limit=3):
                ctx["reflections"] = _lessons
        except Exception as _e:
            _note_loader_error(ctx, "reflections", _e)

    # 9. Deterministic bias floor from the two headline signals the user sees in
    # the header (Tâm lý momentum + Regime score) — so the TLDR Bias can't soften
    # a strongly one-sided market (e.g. momentum -67 → not "Trung tính").
    _mom = (ctx.get("market_sentiment") or {}).get("momentum")
    _reg_score = None
    try:
        from vnstock_regime import load_regime as _load_reg
        _reg_score = _load_reg().get("score")
    except Exception as _e:
        _note_loader_error(ctx, "regime", _e)
    if _fl := _bias_floor_dir(_mom, _reg_score):
        ctx["bias_floor"] = {"dir": _fl, "momentum": _mom, "regime_score": _reg_score}

    return ctx


def _augment_with_live_vnindex(
    df: "pd.DataFrame",
    *,
    live_dir: "Path | None" = None,
    today: "date | None" = None,
) -> "pd.DataFrame":
    """Fold today's live 1m VNINDEX bars into a provisional current-day bar.

    The daily VNINDEX parquet is EOD-only (written by vnstock_updater); the live
    rollup deliberately SKIPS indices (vnstock_rollup._should_rollup_to_warehouse
    excludes VNINDEX). So a morning/intraday brief would otherwise always
    describe the PRIOR session even after live capture ran. When today's WSS
    capture is active, data_warehouse/_live/bars_{today}.parquet holds 1m
    VNINDEX bars — aggregate them into one daily OHLC row so the brief reflects
    the in-progress session. Marks df.attrs["intraday"]=True. Best-effort:
    returns df unchanged on any problem.
    """
    import pandas as pd
    try:
        today = today or date.today()
        # Already have today's bar (post-EOD update) → nothing to add.
        if not df.empty and "time" in df.columns:
            last_date = pd.to_datetime(df["time"]).dt.date.max()
            if last_date is not None and last_date >= today:
                return df

        base = Path(live_dir) if live_dir else (
            Path(__file__).parent / "data_warehouse" / "_live")
        live_path = base / f"bars_{today.isoformat()}.parquet"
        if not live_path.exists():
            return df
        try:
            import pyarrow.parquet as _pq
            bars = _pq.read_table(str(live_path)).to_pandas()
        except Exception:
            return df
        if bars.empty or "ticker" not in bars.columns or "close" not in bars.columns:
            return df

        bars["ticker"] = bars["ticker"].astype(str).str.upper()
        vni = bars[bars["ticker"].isin({"VNINDEX", "VN-INDEX", "^VNINDEX"})].copy()
        if vni.empty or "time" not in vni.columns:
            return df
        vni["time"] = pd.to_datetime(vni["time"])
        vni = vni[vni["time"].dt.date == today].sort_values("time")
        if vni.empty:
            return df

        c = float(vni["close"].iloc[-1])
        o = float(vni["open"].iloc[0]) if "open" in vni.columns else c
        h = float(vni["high"].max()) if "high" in vni.columns else float(vni["close"].max())
        l = float(vni["low"].min())  if "low"  in vni.columns else float(vni["close"].min())
        v = int(vni["volume"].sum()) if "volume" in vni.columns else 0
        # Same unit normalisation as the daily reader (index never > 5000 pts).
        if c > 5000:
            o, h, l, c = o / 1000, h / 1000, l / 1000, c / 1000
        if not (c > 0):
            return df

        row = {"time": pd.Timestamp(today), "open": o, "high": h,
               "low": l, "close": c, "volume": v}
        out = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        out = out.sort_values("time").reset_index(drop=True)
        out.attrs["intraday"] = True
        return out
    except Exception:
        return df


def _load_vnindex_df(augment: bool = True) -> "pd.DataFrame":
    """Read VNINDEX price history directly from parquet — no Streamlit cache.

    Works both inside Streamlit and from the CLI (run.py push_close_brief).
    load_price_history() in vnstock_dashboard.py is decorated with
    @st.cache_data and fails when called outside a Streamlit session.

    The VNINDEX parquet may use either "time" or "trading_date" as the date
    column (depending on which fetcher wrote it). Both are tried.
    Values may be stored in index-points (~1 300) or raw VND (>5 000);
    normalization threshold is 5 000 (index never exceeds 5 000 points).
    """
    import pandas as pd
    try:
        import pyarrow.parquet as _pq
    except ImportError:
        return pd.DataFrame()

    prices_dir = Path(__file__).parent / "data_warehouse" / "prices"

    df = pd.DataFrame()
    for sym in ("VNINDEX", "VN-INDEX", "^VNINDEX"):
        ticker_dir = prices_dir / f"ticker={sym}"
        if not ticker_dir.exists():
            continue
        frames = []
        for yd in sorted(ticker_dir.glob("year=*")):
            try:
                for pf in yd.glob("*.parquet"):
                    frames.append(_pq.read_table(str(pf)).to_pandas())
            except Exception:
                continue
        if not frames:
            continue

        _df = pd.concat(frames, ignore_index=True)
        _df.columns = [str(c).lower() for c in _df.columns]

        # Normalise date column → "time"
        for date_col in ("time", "trading_date", "date"):
            if date_col in _df.columns:
                _df = _df.rename(columns={date_col: "time"})
                break
        if "time" not in _df.columns:
            continue

        _df["time"] = pd.to_datetime(_df["time"])
        _df = _df.sort_values("time").reset_index(drop=True)

        if "close" not in _df.columns:
            continue

        # Normalise units: VNINDEX is ~1300 pts; if stored >5000 → divide by 1000
        for col in ("open", "high", "low", "close"):
            if col in _df.columns:
                vals = _df[col].astype(float)
                if vals.iloc[-1] > 5000:
                    _df[col] = vals / 1000

        df = _df
        break

    return _augment_with_live_vnindex(df) if augment else df


# S/R quality floors (fraction of close). A pivot must sit ≥ _SR_MIN_DIST_PCT
# away from the current price to be actionable (VNINDEX daily swing ~1% → a
# level 0.03% away is noise, observed S1=1,798.05 vs close 1,798.61), and two
# levels on the same side must be ≥ _SR_MIN_GAP_PCT apart (observed R1→R2 =
# 0.05% → "vượt R1 test R2" meaningless). Tune here.
_SR_MIN_DIST_PCT: float = 0.005
_SR_MIN_GAP_PCT: float = 0.008


def _select_sr_levels(cands: "list[float]", last: float) -> "list[float]":
    """Pick up to 2 actionable S/R levels from candidates sorted nearest-first
    (ascending for resistance, descending for support): skip levels within
    _SR_MIN_DIST_PCT of the price, BEYOND _SR_MAX_MOVE_PCT of the price, and
    within _SR_MIN_GAP_PCT of an already picked level.

    TRẦN khoảng cách (fix close 23:18 20/07 — user chốt "soi mức hỗ trợ gần
    và hợp lý hơn"): thị trường thủng đáy 60 phiên → ứng viên dưới giá chỉ
    còn S1 sát giá và đáy 52w → "S2=1,457.31" cách close ~16% được chào mời
    làm mục tiêu kịch bản — vai S/R phải actionable trong 1-2 phiên (biên độ
    HOSE 7%/ngày là trần vật lý). Mức xa vẫn hiện trong data block dưới nhãn
    THẬT của nó (đáy 52 tuần/tháng…), chỉ không được ĐÓNG VAI S1/S2/R1/R2;
    canon vai 2 rỗng → enforce_sr_direction tầng 3 (17/07) tự kéo mục tiêu
    LLM viết về mức known kế tiếp trong tầm / cắt vế khi không còn mức nào.
    """
    out: list[float] = []
    for v in cands:
        if not v or abs(v / last - 1) < _SR_MIN_DIST_PCT:
            continue
        if abs(v / last - 1) > _SR_MAX_MOVE_PCT:
            continue
        if out and abs(v / out[-1] - 1) < _SR_MIN_GAP_PCT:
            continue
        out.append(v)
        if len(out) == 2:
            break
    return out


def _vnindex_technicals() -> dict:
    """Compute VNINDEX close, MAs, day/52w range, and pivot levels.

    Best-effort — returns {} on any failure. The brief prompt then renders a
    "data not available" fallback instead of letting the LLM hallucinate.

    Levels:
      - close, prev_close, day_change_pct
      - day_high/low, week_high/low, month_high/low, high_52w/low_52w
      - ma20, ma50, ma200, ma20_slope_pct (5-bar)
      - support_1, support_2, resistance_1, resistance_2 (recent swing lows/highs)
      - rsi14
    """
    try:
        import pandas as pd
        import numpy as np
    except Exception:
        return {}

    df = _load_vnindex_df()
    if df is None or df.empty or "close" not in df.columns:
        return {}

    try:
        close = df["close"].astype(float).dropna()
        if len(close) < 30:
            return {}
        high = df.get("high", close).astype(float)
        low  = df.get("low", close).astype(float)
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) >= 2 else last
        day_chg = (last / prev - 1.0) * 100 if prev else 0.0

        def _ma(n: int) -> float | None:
            if len(close) < n:
                return None
            v = close.rolling(n).mean().iloc[-1]
            return None if pd.isna(v) else float(v)

        ma20  = _ma(20)
        ma50  = _ma(50)
        ma200 = _ma(200)
        ma20_slope_pct = None
        if ma20 and len(close) >= 25:
            prev_ma20 = close.rolling(20).mean().iloc[-6]
            if not pd.isna(prev_ma20) and prev_ma20:
                ma20_slope_pct = (ma20 / float(prev_ma20) - 1.0) * 100

        # 52w + intraday ranges (computed BEFORE pivots — they extend the
        # candidate pool when price sits near a 60-bar extreme)
        n252 = min(len(close), 252)
        high_52w = float(high.tail(n252).max())
        low_52w  = float(low.tail(n252).min())
        week_high = float(high.tail(5).max())
        week_low  = float(low.tail(5).min())
        month_high = float(high.tail(20).max())
        month_low  = float(low.tail(20).min())
        try:
            day_high = float(high.iloc[-1])
            day_low  = float(low.iloc[-1])
        except Exception:
            day_high = day_low = last

        # Recent swing lows/highs as dynamic S/R — pivots over last 60 bars
        # excluding the last 2 bars (avoid using "today" as its own pivot),
        # plus month/52w extremes as far candidates. Filtered for actionability:
        # ≥ _SR_MIN_DIST_PCT from price, ≥ _SR_MIN_GAP_PCT between levels.
        last60_high = high.tail(62).iloc[:-2] if len(high) >= 62 else high.iloc[:-2]
        last60_low  = low.tail(62).iloc[:-2]  if len(low)  >= 62 else low.iloc[:-2]

        above = sorted({round(float(v), 2) for v in last60_high if v > last}
                       | {round(v, 2) for v in (month_high, high_52w) if v > last})
        below = sorted({round(float(v), 2) for v in last60_low if v < last}
                       | {round(v, 2) for v in (month_low, low_52w) if v < last},
                       reverse=True)
        res = _select_sr_levels(above, last)
        sup = _select_sr_levels(below, last)
        res1, res2 = (res + [None, None])[:2]
        sup1, sup2 = (sup + [None, None])[:2]

        # RSI(14) via EWM (same formula as ticker indicators)
        rsi14 = None
        try:
            delta = close.diff(1)
            up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
            dn = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
            rs = up / dn.replace(0, np.nan)
            v = (100.0 - 100.0 / (1.0 + rs)).iloc[-1]
            rsi14 = None if pd.isna(v) else float(v)
        except Exception:
            pass

        # CHOP(14) + mẫu nến (khảo sát StockSharp 15/07) — ngữ cảnh
        # display-only, KHÔNG vào regime score. Mẫu nến bỏ qua khi bar cuối
        # là bar intraday chưa chốt (thân/râu còn đổi tới khi đóng phiên).
        chop14 = None
        try:
            from vnstock_indicators import choppiness_index
            v = choppiness_index(high.values, low.values, close.values)
            chop14 = round(float(v), 1) if v is not None else None
        except Exception:
            pass
        candle_patterns = []
        ha_streak = 0
        if not bool(df.attrs.get("intraday", False)):
            try:
                from vnstock_candle_patterns import detect_df, pattern_labels
                candle_patterns = pattern_labels(detect_df(df))
            except Exception:
                pass
            # Heikin-Ashi streak (quant-trading 15/07) — cùng luật skip
            # intraday như mẫu nến (HA của bar chưa chốt còn đổi).
            try:
                from vnstock_indicators import ha_trend_streak
                if "open" in df.columns:
                    ha_streak = ha_trend_streak(
                        df["open"].astype(float).values, high.values,
                        low.values, close.values)
            except Exception:
                pass

        return {
            "close":          last,
            "prev_close":     prev,
            "day_change_pct": round(day_chg, 2),
            "day_high":       day_high,
            "day_low":        day_low,
            "week_high":      week_high,
            "week_low":       week_low,
            "month_high":     month_high,
            "month_low":      month_low,
            "high_52w":       high_52w,
            "low_52w":        low_52w,
            "ma20":           ma20,
            "ma50":           ma50,
            "ma200":          ma200,
            "ma20_slope_pct": round(ma20_slope_pct, 2) if ma20_slope_pct is not None else None,
            "rsi14":          round(rsi14, 1) if rsi14 is not None else None,
            "chop14":         chop14,
            "candle_patterns": candle_patterns,
            "ha_streak":      int(ha_streak),
            "support_1":      sup1,
            "support_2":      sup2,
            "resistance_1":   res1,
            "resistance_2":   res2,
            # Date of the last bar with valid close — used by collect_context()
            # to set the "effective" brief date when today has no data yet
            # (e.g. early morning before market opens, or weekends).
            "data_date": df.loc[df["close"].notna(), "time"].iloc[-1].date().isoformat(),
            # True when the last bar is a provisional intraday bar folded in from
            # today's live WSS capture (session not yet closed).
            "intraday": bool(df.attrs.get("intraday", False)),
        }
    except Exception:
        return {}


# ── Prompt builder ─────────────────────────────────────────────────────────
def build_prompt(ctx: dict, brief_type: str = "morning",
                 few_shot: str = "", rec_block: str = "",
                 news_block: str = "") -> str:
    """Construct the full Vietnamese prompt from market context.

    Optional `few_shot` / `rec_block` are injected by the train loop / memory layer
    to nudge the model toward higher quality and surface validated trade ideas.
    `news_block` injects latest market news so the agent can factor them in.
    """
    lines: list[str] = []

    _date_line = f"Ngày: {ctx['date']} | Thời điểm: {ctx['time']}"
    if note := ctx.get("date_note"):
        _date_line += f"  ⚠️ {note}"
    lines.append(_date_line)

    # Freshness warning: VNINDEX is intraday/fresh but the screener-produced
    # blocks (breadth / movers / sector flow / regime) trail a session.
    if (fr := ctx.get("freshness")) and fr.get("stale"):
        if fr.get("reason") == "intraday":
            # Cùng phiên nhưng overview chốt GIỮA phiên — khối độ rộng mới thấy
            # một phần. Câu cảnh báo phải nói ĐÚNG chuyện đó, không được mượn
            # câu "phiên trước" (sai sự thật và người đọc sẽ bỏ qua).
            lines.append(
                f"\n## ⚠️ Độ tươi dữ liệu — KHÔNG BỎ QUA\n"
                f"VNINDEX là phiên {fr.get('data_date')} (đã chốt), NHƯNG độ rộng, "
                f"VN30 movers, dòng tiền ngành và regime lấy từ market_overview "
                f"chốt lúc {fr.get('overview_time')} — GIỮA PHIÊN, chưa thấy hết "
                f"phiên. BẮT BUỘC: thêm 1 câu nói rõ các khối này tính đến "
                f"{fr.get('overview_time')} chứ không phải cuối phiên, và khi "
                f"mâu thuẫn thì ƯU TIÊN tín hiệu giá VNINDEX chốt phiên."
            )
        else:
            lines.append(
                f"\n## ⚠️ Độ tươi dữ liệu — KHÔNG BỎ QUA\n"
                f"VNINDEX là phiên {fr.get('data_date')} (mới/intraday), NHƯNG độ rộng, "
                f"VN30 movers, dòng tiền ngành và regime lấy từ market_overview ngày "
                f"{fr.get('overview_date')} (PHIÊN TRƯỚC). BẮT BUỘC: thêm 1 câu cảnh báo "
                f"các khối này từ phiên trước, và khi mâu thuẫn thì ƯU TIÊN tín hiệu giá "
                f"VNINDEX hiện tại — đừng kết luận xu hướng dựa trên độ rộng/regime cũ."
            )

    # Deterministic leader/laggard: the strongest +/- sector contributor (1 tuần)
    # is computed in collect_context. Inject it as the ONLY allowed choice so the
    # model can't cite a negligible-contribution sector as a leader.
    _lead = ctx.get("lead_sector")
    _lag = ctx.get("lag_sector")
    if _lead and _lag:
        _lc, _gc = _lead.get("contrib", 0), _lag.get("contrib", 0)
        _b = ["\n## 🎯 Dẫn dắt/Tụt hậu — CHỐT THEO DATA (DÙNG ĐÚNG, KHÔNG CHỌN NGÀNH KHÁC)"]
        if _lc >= 0.05:
            _b.append(f"- Tích luỹ/Mua: CHỈ {_lead['name']} (đóng góp {_lc:+.3f}pp, 1 tuần — mạnh nhất).")
        else:
            _b.append(f"- Tích luỹ/Mua: GHI 'Chưa có nhóm dẫn dắt rõ ràng' (đóng góp +pp lớn nhất chỉ {_lc:+.3f}pp < 0.05).")
        if _gc <= -0.05:
            _b.append(f"- Tránh/Bán: CHỈ {_lag['name']} (đóng góp {_gc:+.3f}pp, 1 tuần — yếu nhất).")
        else:
            _b.append(f"- Tránh/Bán: GHI 'Chưa có nhóm tụt hậu rõ rệt' (đóng góp -pp yếu nhất chỉ {_gc:+.3f}pp > -0.05).")
        _b.append("TUYỆT ĐỐI không chọn ngành khác làm dẫn dắt/tụt hậu.")
        lines.append("\n".join(_b))
    else:
        # Template có mục BẮT BUỘC "## 🏆 Dẫn dắt & Tụt hậu" và bảo model
        # "DÙNG ĐÚNG block 🎯 ... ở trên". Block biến mất âm thầm = model được
        # trỏ tới một block không tồn tại nhưng vẫn phải nộp mục đó.
        lines.append(
            "\n## 🎯 Dẫn dắt/Tụt hậu — KHÔNG CÓ DỮ LIỆU\n"
            "⚠️ Chưa tính được đóng góp ngành hôm nay. BẮT BUỘC: mục "
            "'Dẫn dắt & Tụt hậu' ghi 'Chưa có nhóm dẫn dắt rõ ràng' và "
            "'Chưa có nhóm tụt hậu rõ rệt'. TUYỆT ĐỐI KHÔNG tự chọn ngành nào "
            "làm dẫn dắt/tụt hậu."
        )

    # Deterministic bias floor: when the headline signals are strongly one-sided,
    # the TLDR Bias must follow them (no softening to "Trung tính"/opposite).
    # Worded per brief_type: morning's scenario section is "Kịch bản phiên chiều",
    # the close's directional call lives in "Stance ngày mai" (TLDR).
    if bf := ctx.get("bias_floor"):
        _sig = []
        if bf.get("momentum") is not None:
            _sig.append(f"momentum {bf['momentum']:+d}/100")
        if bf.get("regime_score") is not None:
            _sig.append(f"regime score {bf['regime_score']:+d}")
        _dir_phr = "thủng hỗ trợ/đi xuống" if bf["dir"] == "GIẢM" else "vượt kháng cự/đi lên"
        if brief_type == "morning":
            _scenario = (
                f"Ở 'Kịch bản phiên chiều', kịch bản CHÍNH (xác suất cao nhất) "
                f"PHẢI là kịch bản {bf['dir']} ({_dir_phr}); kịch bản chiều ngược "
                f"chỉ được là kịch bản PHỤ."
            )
        else:
            _scenario = (
                f"Ở 'Stance ngày mai' (TLDR), setup ưu tiên PHẢI cùng chiều {bf['dir']} "
                f"({_dir_phr}); KHÔNG đưa setup chiều ngược làm setup chính."
            )
        lines.append(
            f"\n## 🧭 RÀNG BUỘC BIAS (BẮT BUỘC)\n"
            f"Tín hiệu tổng hợp một chiều mạnh ({', '.join(_sig) or 'n/a'}). "
            f"TLDR **Bias BẮT BUỘC = {bf['dir']}** — TUYỆT ĐỐI KHÔNG ghi 'Trung tính' "
            f"hay chiều ngược lại. {_scenario} "
            f"(Lưu ý: 'BẮT BUỘC' là chỉ thị nội bộ cho bạn — TUYỆT ĐỐI KHÔNG in chữ "
            f"'bắt buộc' vào brief; chỉ ghi bias {bf['dir']} kèm lý do số liệu.)"
        )
        if bf["dir"] == "GIẢM":
            _where = "Watchlist sáng mai" if brief_type != "morning" else "Trọng tâm theo dõi / Kịch bản"
            lines.append(
                f"Ở '{_where}' (bias GIẢM): TUYỆT ĐỐI KHÔNG đưa setup "
                "\"MUA vùng [giá dưới thị trường]\" kiểu bắt dao rơi. Mẫu MUA "
                "CHỈ được dạng CÓ ĐIỀU KIỆN \"canh MUA NẾU vượt lại [kháng cự "
                "của CHÍNH MÃ]\" (xác nhận sức mạnh trước), và ưu tiên ít nhất "
                "1 hướng phòng thủ (GIẢM TỶ TRỌNG/TRÁNH nếu thủng hỗ trợ)."
            )

    # Market sentiment (tâm lý thị trường) — composite mood from breadth, NN
    # flow, index momentum and news. Emitted high so the agent frames the
    # short-term trend around it.
    if ms := ctx.get("market_sentiment"):
        block = _market_sentiment_block(ms)
        if block:
            lines.append(block)

    # Regime
    if r := ctx.get("quant_regime"):
        vr = ctx.get("vol_regime", "normal")
        vr_note = " | ⚡ Biên độ cao — high-vol regime" if vr == "high" else ""
        lines.append(f"\n## Quant Market Regime\n{r['regime']} | conviction={r['conviction']:+.2f}"
                     f"{vr_note} | {r['detail']}")
    else:
        # Template nhắc "regime" ở nhiều chỗ ràng buộc (stance, hướng setup,
        # lý do phân bổ). Không có block = model tự đặt ra một regime.
        lines.append(
            "\n## Quant Market Regime\n"
            "⚠️ KHÔNG CÓ quant regime hôm nay — TUYỆT ĐỐI KHÔNG nêu tên regime "
            "hay conviction; nếu cần nhắc thì ghi 'chưa có regime hôm nay'."
        )

    # VNINDEX technical levels — emit BEFORE breadth/sectors so the LLM
    # treats these as the canonical reference numbers instead of making up
    # stale levels from training data.
    #
    # CRITICAL anti-hallucination invariant: if the loader returned {}, we
    # STILL emit the section header with an explicit "no data" sentinel —
    # otherwise the prompt downstream tells the LLM to "extract from the
    # VNINDEX block" and a missing block leaves a vacuum the LLM fills from
    # training data (the original 1.240 hallucination bug).
    vt = ctx.get("vnindex_tech") or {}
    if vt:
        def _f(v) -> str:
            return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"

        _intraday_tag = (
            " — ⚠️ PHIÊN ĐANG DIỄN RA (dữ liệu intraday, CHƯA chốt phiên)"
            if vt.get("intraday") else ""
        )
        vt_lines = [f"\n## VNINDEX kỹ thuật (số liệu hiện tại — DÙNG CHÍNH XÁC, KHÔNG ĐƯỢC THAY){_intraday_tag}"]
        vt_lines.append(
            f"- {'Giá hiện tại' if vt.get('intraday') else 'Giá đóng cửa'}: **{_f(vt.get('close'))}** "
            f"(prev {_f(vt.get('prev_close'))}, "
            f"thay đổi phiên {vt.get('day_change_pct', 0):+.2f}%)"
        )
        vt_lines.append(
            f"- Range hôm nay: {_f(vt.get('day_low'))} – {_f(vt.get('day_high'))} | "
            f"Tuần: {_f(vt.get('week_low'))} – {_f(vt.get('week_high'))} | "
            f"Tháng: {_f(vt.get('month_low'))} – {_f(vt.get('month_high'))}"
        )
        # Pre-compute where close sits in the weekly range so the agent doesn't
        # mis-state "nửa trên/dưới" (observed: 18.7% mislabelled "nửa trên").
        _wl, _wh, _cl = vt.get("week_low"), vt.get("week_high"), vt.get("close")
        if all(isinstance(x, (int, float)) for x in (_wl, _wh, _cl)) and _wh > _wl:
            _pos = (_cl - _wl) / (_wh - _wl) * 100
            _zone = ("gần đáy" if _pos < 33 else "gần đỉnh" if _pos > 67 else "giữa")
            vt_lines.append(
                f"- Vị trí range tuần: {_pos:.0f}% (0%=đáy, 100%=đỉnh) → {_zone} range"
            )
        vt_lines.append(
            f"- 52w: {_f(vt.get('low_52w'))} – {_f(vt.get('high_52w'))}"
        )
        ma_parts = []
        for k, label in (("ma20", "MA20"), ("ma50", "MA50"), ("ma200", "MA200")):
            v = vt.get(k)
            if v is not None:
                close_v = vt.get("close") or 0
                vs = ((close_v / v) - 1) * 100 if v else 0
                ma_parts.append(f"{label}={_f(v)} ({vs:+.1f}%)")
        if ma_parts:
            vt_lines.append("- " + " | ".join(ma_parts))
        if (slope := vt.get("ma20_slope_pct")) is not None:
            slope_tag = "↗ tăng" if slope > 0.2 else ("↘ giảm" if slope < -0.2 else "→ đi ngang")
            vt_lines.append(f"- MA20 slope (5 phiên): {slope:+.2f}% {slope_tag}")
        if (rsi := vt.get("rsi14")) is not None:
            rsi_tag = "quá mua" if rsi > 70 else ("quá bán" if rsi < 30 else "trung tính")
            vt_lines.append(f"- RSI(14): {rsi:.1f} ({rsi_tag})")
        if (chop := vt.get("chop14")) is not None:
            chop_tag = ("đi ngang/choppy" if chop > 61.8
                        else "có xu hướng rõ" if chop < 38.2 else "trung gian")
            vt_lines.append(
                f"- CHOP(14): {chop:.1f} ({chop_tag} — đo độ choppy, KHÔNG chỉ hướng)"
            )
        if pats := vt.get("candle_patterns"):
            vt_lines.append(
                "- Mẫu nến phiên gần nhất: " + "; ".join(pats)
                + " (tín hiệu nến tham khảo, cần nến xác nhận)"
            )
        if abs(streak := int(vt.get("ha_streak") or 0)) >= 2:
            _ha_dir = "xanh (tăng)" if streak > 0 else "đỏ (giảm)"
            vt_lines.append(
                f"- Heikin-Ashi: {abs(streak)} nến {_ha_dir} sạch liên tiếp"
                " — lọc nhiễu trend, chỉ ngữ cảnh"
            )
        sr_parts = []
        if vt.get("support_2") is not None:
            sr_parts.append(f"S2={_f(vt['support_2'])}")
        if vt.get("support_1") is not None:
            sr_parts.append(f"S1={_f(vt['support_1'])}")
        if vt.get("resistance_1") is not None:
            sr_parts.append(f"R1={_f(vt['resistance_1'])}")
        if vt.get("resistance_2") is not None:
            sr_parts.append(f"R2={_f(vt['resistance_2'])}")
        if sr_parts:
            vt_lines.append(
                "- Pivots (60-bar swing): " + " | ".join(sr_parts)
                + "  ← DÙNG ĐÚNG CÁC MỨC NÀY khi viết hỗ trợ/kháng cự"
            )
        lines.append("\n".join(vt_lines))
    else:
        lines.append(
            "\n## VNINDEX kỹ thuật\n"
            "⚠️ KHÔNG CÓ DỮ LIỆU VNINDEX hôm nay (loader thất bại hoặc warehouse trống). "
            "BẮT BUỘC: trong phần 'Mức kỹ thuật' của brief PHẢI viết "
            "'Chưa có dữ liệu VNINDEX hôm nay — không phân tích mức cụ thể'. "
            "TUYỆT ĐỐI KHÔNG suy đoán giá/MA/hỗ trợ/kháng cự VNINDEX từ trí nhớ."
        )

    # Session timing — explicit empty marker when warehouse missing,
    # so the LLM doesn't fabricate GTGD numbers.
    _is_morning_brief = (brief_type == "morning")
    if timing := ctx.get("session_timing"):
        # Intraday (live bar folded in = session in progress): the morning-share
        # signal/detail (institutional vs retail = morning/full) is meaningless
        # because full-day = morning + partial afternoon. Suppress it — that
        # detail string is the real source of "sáng chiếm 78% cả ngày".
        # The MORNING brief is written from the 11:30 viewpoint: it must never
        # see the afternoon/full-day either (observed on an EOD re-run: "Phiên
        # chiều chiếm 56% GTGD, thiên bias retail" inside the MORNING overview).
        _intraday = bool((ctx.get("vnindex_tech") or {}).get("intraday"))
        if _is_morning_brief:
            line = ("\n## Session Timing\n⚠️ MORNING brief — góc nhìn 11:30: CHỈ dùng "
                    "GTGD SÁNG bên dưới; TUYỆT ĐỐI KHÔNG bàn về phiên chiều / GTGD cả "
                    "ngày / tỷ trọng sáng-chiều (institutional vs retail) — các thông "
                    "tin đó thuộc CLOSE brief.")
        elif _intraday:
            line = ("\n## Session Timing\n⚠️ Phiên ĐANG diễn ra — CHƯA đánh giá được "
                    "tỷ trọng sáng/chiều (institutional vs retail); TUYỆT ĐỐI KHÔNG nói "
                    "'sáng chiếm X% GTGD cả ngày' hay suy ra institutional/retail từ đó.")
        else:
            line = f"\n## Session Timing\n{timing['signal']} | {timing['detail']}"
        if ss := ctx.get("session_stats"):
            morn_gtgd = (ss.get("9h-11h30", {}).get("VNINDEX", {}) or {}).get("gtgd", 0) or 0
            full_gtgd = (ss.get("9h-15h",  {}).get("VNINDEX", {}) or {}).get("gtgd", 0) or 0
            mg = ctx.get("morning_gtgd") or {}
            if morn_gtgd:
                line += f"\nGTGD sáng (9h-11h30): {morn_gtgd:,.1f} tỷ"
                # Like-for-like morning baselines (sáng vs sáng).
                cmp_parts = []
                if mg.get("prev"):
                    cmp_parts.append(
                        f"sáng phiên trước {mg['prev']:,.1f} tỷ ({(morn_gtgd/mg['prev']-1)*100:+.0f}%)")
                if mg.get("avg5"):
                    cmp_parts.append(
                        f"TB sáng 5 phiên {mg['avg5']:,.1f} tỷ ({(morn_gtgd/mg['avg5']-1)*100:+.0f}%)")
                if mg.get("avg20"):
                    cmp_parts.append(f"TB sáng ~20 phiên {mg['avg20']:,.1f} tỷ")
                if cmp_parts:
                    line += "\nSo sánh ĐỒNG DẠNG (sáng-với-sáng): " + " | ".join(cmp_parts)
            # Full-day GTGD (only when session CLOSED, and NEVER for the morning
            # brief — its template compares sáng-với-sáng only). SỐ và % đi
            # CÙNG MỘT KHUNG qua _gtgd_close_frame (WSS-với-WSS khi có capture
            # + baseline lịch sử cùng cửa sổ; ngược lại EOD-với-EOD trọn bộ) —
            # fix 21/07: cấm số WSS 20,453.9 gắn % tính trên khung EOD 14,878.9.
            _F = None
            _fcmp: dict = {}
            _frame = ""
            if not _intraday and not _is_morning_brief:
                _F, _fcmp, _frame = _gtgd_close_frame(ctx)
            if _F:
                _src = ""
                if _frame == "eod":
                    _n = ctx.get("full_day_gtgd_count")
                    _src = (f" (ước tính từ EOD: Σ giá×KLGD của {_n} mã có data phiên"
                            if _n else " (ước tính từ EOD: Σ giá×KLGD")
                    _src += ", xấp xỉ — có thể thấp hơn tổng sàn nếu kho chưa đủ mã)"
                line += (f"\nGTGD cả ngày: {_F:,.1f} tỷ{_src} → DÙNG ĐÚNG SỐ NÀY cho "
                         f"'GTGD' trong TLDR/Tổng kết phiên; TUYỆT ĐỐI KHÔNG nhặt số khác "
                         f"(GTGD sáng, GTGD theo ngành, v.v.) làm GTGD cả ngày.")
                if _fcmp.get("prev") or _fcmp.get("avg5"):
                    _parts = []
                    if _fcmp.get("prev"):
                        _parts.append(f"phiên trước {_fcmp['prev']:,.1f} tỷ "
                                      f"({(_F / _fcmp['prev'] - 1) * 100:+.0f}%)")
                    for _k, _lbl in (("avg5", "TB5 phiên"), ("avg20", "TB20 phiên")):
                        if _fcmp.get(_k):
                            _parts.append(f"{_lbl} {_fcmp[_k]:,.1f} tỷ "
                                          f"({(_F / _fcmp[_k] - 1) * 100:+.0f}%)")
                    line += ("\nSo sánh CẢ-NGÀY-với-CẢ-NGÀY (cùng khung đo): "
                             + " | ".join(_parts) +
                             ". DÙNG % NÀY cho GTGD cả ngày; CHỈ baseline đã cho (KHÔNG "
                             "tự suy TB khác), TUYỆT ĐỐI KHÔNG gán % 'so với sáng phiên "
                             "trước' cho số cả ngày.")
            elif (not _is_morning_brief) and ctx.get("full_day_gtgd_partial") \
                    and not (morn_gtgd or full_gtgd):
                # The session's bars are incomplete (in-progress day / EOD batch
                # not fully landed) → the partial sum must NOT pose as the
                # market figure.
                _n = ctx.get("full_day_gtgd_count")
                line += (f"\n⚠️ GTGD cả ngày CHƯA ĐỦ DỮ LIỆU — phiên đang dở hoặc batch EOD "
                         f"chưa về đủ (mới {_n} mã có bar). TRONG TLDR/Tổng kết ghi 'GTGD: chưa đủ "
                         f"dữ liệu', TUYỆT ĐỐI KHÔNG bịa, KHÔNG dùng số một phần làm GTGD toàn sàn.")
            elif not morn_gtgd and not full_gtgd:
                # No GTGD anywhere (WSS didn't run AND no EOD total) → say so.
                line += ("\n⚠️ KHÔNG có dữ liệu GTGD hôm nay → trong TLDR/Tổng kết ghi "
                         "'GTGD: chưa có dữ liệu', TUYỆT ĐỐI KHÔNG bịa con số GTGD nào.")
        lines.append(line)
    else:
        _eod_full = ctx.get("full_day_gtgd")
        _intraday = bool((ctx.get("vnindex_tech") or {}).get("intraday"))
        _l = ("\n## Session Timing\n⚠️ KHÔNG CÓ session stats hôm nay — "
              "KHÔNG được suy đoán tỷ trọng sáng/chiều (institutional/retail).")
        if _is_morning_brief:
            _l += (" MORNING brief: KHÔNG có GTGD sáng → ghi 'Chưa có GTGD phiên "
                   "sáng', KHÔNG bàn phiên chiều/GTGD cả ngày.")
        elif (not _intraday) and isinstance(_eod_full, (int, float)) and _eod_full > 0:
            _l += (f"\nGTGD cả ngày: {_eod_full:,.1f} tỷ (ước tính từ EOD: Σ giá×KLGD) → "
                   f"DÙNG ĐÚNG SỐ NÀY cho 'GTGD' trong TLDR/Tổng kết phiên.")
            _cmp = ctx.get("full_day_gtgd_cmp") or {}
            if _cmp.get("prev"):
                _pct = (float(_eod_full) / _cmp["prev"] - 1) * 100 if _cmp["prev"] else 0
                _parts = [f"phiên trước {_cmp['prev']:,.1f} tỷ ({_pct:+.0f}%)"]
                for _k, _lbl in (("avg5", "TB5 phiên"), ("avg20", "TB20 phiên")):
                    if _cmp.get(_k):
                        _parts.append(f"{_lbl} {_cmp[_k]:,.1f} tỷ "
                                      f"({(float(_eod_full) / _cmp[_k] - 1) * 100:+.0f}%)")
                _l += ("\nSo sánh cả-ngày-với-cả-ngày: " + " | ".join(_parts) +
                       ". CHỈ baseline đã cho (KHÔNG tự suy TB khác), KHÔNG gán % "
                       "so-với-sáng cho số cả ngày.")
        else:
            _l += " GTGD: viết 'chưa có dữ liệu', KHÔNG bịa số."
        lines.append(_l)

    # Breadth — same pattern
    if b := ctx.get("breadth"):
        _ad = b.get("ad_ratio", 0) or 0
        _ma200 = b.get("above_ma200_pct", 0) or 0
        # Deterministic breadth label so the agent can't mislabel A/D (observed:
        # A/D 0.90 wrongly called "tích cực" — 0.90 < 1.0 is NEGATIVE breadth).
        _bl = "tích cực" if _ad > 1.05 else "tiêu cực" if _ad < 0.95 else "cân bằng"
        _sign = ">" if _ad > 1 else "<" if _ad < 1 else "≈"
        _weak = " · ít mã trên MA200 → thị trường yếu" if _ma200 < 30 else ""
        lines.append(f"\n## Market Breadth\n"
                     f"Trên MA200: {_ma200:.0f}% | "
                     f"A/D ratio: {_ad:.2f} | "
                     f"Net new highs: {b.get('net_new_highs',0):+d} | "
                     f"RSI oversold: {b.get('rsi_oversold',0)} mã | RSI overbought: {b.get('rsi_overbought',0)} mã"
                     f"\n→ ĐỘ RỘNG: {_bl.upper()} (A/D {_sign} 1.0{_weak}) — DÙNG ĐÚNG nhãn này, KHÔNG tự suy ngược (A/D<1 = tiêu cực).")
    else:
        lines.append(
            "\n## Market Breadth\n⚠️ KHÔNG CÓ breadth data — "
            "KHÔNG được nêu % trên MA200 / A-D ratio / RSI counts."
        )

    # Sector analysis — with market-cap weights + stock breakdown
    _sw = ctx.get("sector_weights", {})
    _ts = ctx.get("top_stocks_per_sector", {})

    def _composite_tag(r: dict) -> str:
        """Plain-Vietnamese label for the internal quant 'composite' score so the
        brief reads "tín hiệu phân phối" not "composite=-0.76"."""
        v = r.get("composite")
        if not isinstance(v, (int, float)):
            return ""
        lbl = ("phân phối mạnh" if v <= -0.6 else "phân phối" if v <= -0.2
               else "tích luỹ mạnh" if v >= 0.6 else "tích luỹ" if v >= 0.2
               else "trung tính")
        return f" tín hiệu {lbl}"

    def _sector_lines(r: dict) -> list[str]:
        sector_name = r.get("Ngành", "?")
        sw = _sw.get(sector_name, {})
        weight = sw.get("_weight", 0) * 100
        contrib = sw.get("_1d_contrib", 0)

        # Header: name [weight, contribution] composite + performance
        header = f"**{sector_name}**"
        if weight > 0:
            header += f" [{weight:.1f}%VNI"
            if contrib != 0:
                header += f", đóng góp {contrib:+.2f}pp (1 tuần)"
            header += "]"
        header += _composite_tag(r)

        meta: list[str] = []
        g1t = r.get("Giá 1T %")
        g1m = r.get("Giá 1M %")
        a1m = r.get("alpha_1M")
        rot = r.get("rotation")
        nn  = r.get("NN 1M (tỷ)")
        nbs = r.get("Net BS 1M")
        if g1t is not None:
            meta.append(f"1T {g1t:+.1f}%")
        if g1m is not None:
            meta.append(f"1M {g1m:+.1f}%" + (f" (α {a1m:+.1f}pp vs VNI)" if a1m is not None else ""))
        if rot is not None and abs(rot) > 3:
            meta.append(f"rotation {rot:+.1f}pp")
        if nn is not None and abs(nn) > 50:
            meta.append(f"NN 1M {nn:+,.0f}tỷ")
        if nbs is not None:
            meta.append(f"NetBS {nbs:+,.0f}M")

        result = ["- " + header + (" | " + " | ".join(meta) if meta else "")]

        # Top 3 stocks in sector: mcap, weight vs VNI, 1-week return, contribution
        for s in _ts.get(sector_name, [])[:3]:
            ticker  = s.get("Mã", "?")
            mcap    = s.get("Vốn hoá (tỷ)", 0) or 0
            stk_w   = s.get("_weight", 0) * 100
            ret_1t  = s.get("Giá 1T %")
            stk_c   = s.get("_1d_contrib", 0) or 0
            if ret_1t is not None:
                result.append(
                    f"  → {ticker}"
                    + (f" {mcap:,.0f}tỷ" if mcap else "")
                    + (f" ({stk_w:.2f}%VNI)" if stk_w else "")
                    + f" 1T {ret_1t:+.1f}%"
                    + (f" ≈ {stk_c:+.3f}pp" if stk_c else "")
                )

        flags = r.get("red_flags", []) or []
        cats  = r.get("catalysts", []) or []
        if flags:
            result.append(f"  ⚠ {flags[0][:80]}")
        if cats:
            result.append(f"  ✦ {cats[0][:80]}")
        return result

    # Sector rankings — explicit "no data" when quant pipeline failed,
    # so the LLM doesn't list sectors from training data.
    _has_quant = any(ctx.get(k) for k in
                     ("quant_top", "quant_avoid", "quant_rotation",
                      "quant_stealth", "quant_distribution"))
    if not _has_quant:
        lines.append(
            "\n## Phân loại ngành\n⚠️ KHÔNG CÓ quant scores hôm nay — "
            "KHÔNG được liệt kê 'ngành tích cực/tiêu cực', chỉ phân tích từ data có sẵn."
        )

    if top := ctx.get("quant_top"):
        lines.append("\n## Ngành tích cực nhất")
        for r in top:
            lines.extend(_sector_lines(r))

    if avoid := ctx.get("quant_avoid"):
        lines.append("\n## Ngành tiêu cực nhất")
        for r in avoid:
            lines.extend(_sector_lines(r))

    if rotation := ctx.get("quant_rotation"):
        lines.append("\n## Rotation signal (alpha 1M > alpha 3M — warming up)")
        for r in rotation:
            sw = _sw.get(r.get("Ngành", ""), {})
            lines.append(
                f"- **{r.get('Ngành','?')}** rotation={r.get('rotation',0):+.1f}pp"
                f" |{_composite_tag(r)}"
                + (f" | {sw.get('_weight',0)*100:.1f}%VNI" if sw.get("_weight") else "")
            )

    if stealth := ctx.get("quant_stealth"):
        lines.append("\n## Stealth accumulation (tích luỹ ngầm)")
        for r in stealth:
            lines.append(f"- **{r.get('Ngành','?')}** — giá đi ngang nhưng Net BS dương + turnover cao")

    if dist := ctx.get("quant_distribution"):
        lines.append("\n## Distribution warning (giá xanh, tiền đang thoát)")
        for r in dist:
            lines.append(f"- **{r.get('Ngành','?')}** —{_composite_tag(r)}")
        lines.append("→ Khi nhắc các tín hiệu trên, DÙNG nhãn chữ (phân phối/tích luỹ…), "
                     "TUYỆT ĐỐI KHÔNG in 'composite=<số>' vào brief.")

    # VN30 movers + contribution to VNINDEX
    def _vn30_line(g: dict) -> str:
        ticker = g.get("Mã", "?")
        ret    = g.get("Giá 1T %", 0)
        sector = g.get("Ngành", "")
        price  = g.get("last")
        contrib = next(
            (s.get("_1d_contrib", 0) or 0
             for s in _ts.get(sector, []) if s.get("Mã") == ticker),
            0.0,
        )
        line = f"- {ticker} {ret:+.1f}% (1 tuần/5 phiên) [{sector}]"
        if price not in (None, "") and not (isinstance(price, float) and price != price):
            # "last" is in thousand VND → render absolute VND as the watchlist anchor.
            line += f" | Giá {float(price) * 1000:,.0f}"
        if contrib != 0:
            line += f" ≈ {contrib:+.3f}pp VNI (1 tuần)"
        # ⭐ = thanh khoản đủ cao để làm SETUP watchlist (VN30 hoặc GTGD ≥ ngưỡng);
        # mã không ⭐ chỉ dùng để phân tích biến động, không đưa vào setup giao dịch.
        _gtgd = g.get("GTGD TB (tỷ)")
        _eligible = ticker in VN30_TICKERS or (
            _gtgd is not None and not (isinstance(_gtgd, float) and _gtgd != _gtgd)
            and float(_gtgd) >= _WATCHLIST_GTGD_MIN_TY
        )
        if _eligible and price not in (None, ""):
            # ⭐ + dải tham chiếu tính từ GIÁ của chính mã (±3%), để watchlist
            # neo setup vào đây thay vì vơ S/R của VNINDEX (bug lặp lại "CII
            # canh mua nếu vượt R1=1,800.80" → watchlist rỗng sau guard vệ sinh).
            #
            # ⚠️ GỌI ĐÚNG TÊN. Nhãn cũ là "hỗ trợ ~X / kháng cự ~Y" — mà X,Y
            # chỉ là giá ×0,97 và ×1,03, KHÔNG đo từ đỉnh/đáy nào cả. Model
            # chép lại y nguyên nên brief close 21/08 viết "giữ vững trên hỗ
            # trợ 81,000 và hướng tới kháng cự 86,000" cho GAS: nghe như mốc
            # kỹ thuật đo được, thực chất là 83.500 ±3%. Đây KHÔNG phải model
            # bịa — chính chỗ này bịa hộ nó, đều đặn mọi phiên. Repo có sẵn
            # pivot thật (`vnstock_strategy._ticker_pivots`) nhưng chưa nối
            # vào đường này; chừng nào chưa nối thì nhãn phải nói thật.
            _p = float(price) * 1000
            line += (f" ⭐ [dải ±3% quanh giá: {_round_tick(_p * 0.97, _p):,} – "
                     f"{_round_tick(_p * 1.03, _p):,} — mốc THAM CHIẾU tính từ "
                     f"giá, KHÔNG phải hỗ trợ/kháng cự đo được]")
        return line

    if gainers := ctx.get("vn30_gainers"):
        lines.append("\n## Top Gainers thanh khoản cao (VN30 + mid-cap; thay đổi 1 TUẦN/5 phiên — KHÔNG phải 1 phiên, với đóng góp vào VNINDEX)")
        for g in gainers:
            lines.append(_vn30_line(g))

    if losers := ctx.get("vn30_losers"):
        lines.append("\n## Top Losers thanh khoản cao (VN30 + mid-cap; thay đổi 1 TUẦN/5 phiên — KHÔNG phải 1 phiên, với đóng góp vào VNINDEX)")
        for g in losers:
            lines.append(_vn30_line(g))

    # Cùng bất biến chống bịa với block VNINDEX/breadth ở trên, và đây là ca
    # NẶNG NHẤT: template bảo model "CHỈ chọn mã trong block Top Gainers/Losers
    # CÓ DẤU ⭐" và còn nói block đó "BÌNH THƯỜNG có sẵn vài mã". Khối biến mất
    # âm thầm = model được lệnh chọn từ một danh sách KHÔNG TỒN TẠI, trong khi
    # vẫn phải nộp tối đa 3 setup → nó bịa mã + bịa giá.
    if not gainers and not losers:
        lines.append(
            "\n## Top Gainers/Losers thanh khoản cao\n"
            "⚠️ KHÔNG CÓ dữ liệu movers hôm nay (loader thất bại hoặc kho trống). "
            "BẮT BUỘC: mục 'Đề xuất giao dịch' viết 'Chưa có dữ liệu mã đủ thanh khoản "
            "hôm nay — không đề xuất setup'. TUYỆT ĐỐI KHÔNG nêu tên mã, giá, "
            "hỗ trợ/kháng cự của bất kỳ mã nào từ trí nhớ."
        )

    # Sector money flow (foreign net flow + liquidity by sector) so the agent
    # can describe rotation / where smart money is going.
    if _sectors := ctx.get("sectors"):
        block = _sector_flow_block(_sectors, nn_data_date=ctx.get("nn_data_date"),
                                   session_date=ctx.get("date"))
        if block:
            lines.append(block)

    # VN30 fundamentals (debt-to-equity, ROE, operating cash flow) so the agent
    # can ground "rủi ro cơ bản" comments in real leverage / cash-flow numbers.
    if funds := ctx.get("vn30_fundamentals"):
        block = _vn30_fund_block(funds, extra_financial=ctx.get("financial_tickers"),
                                 realestate=ctx.get("realestate_tickers"))
        if block:
            lines.append(block)

    # Upcoming corporate events (ex-dividend / split / bonus) so the brief can
    # flag ngày GDKHQ for held/watchlist tickers.
    if _ev := ctx.get("upcoming_events"):
        block = _upcoming_events_block(_ev)
        if block:
            lines.append(block)

    # Macro context (lãi suất & tỷ giá) so the brief frames Bias/Rủi ro against
    # monetary conditions and flags shifts (đón đầu).
    if _macro := ctx.get("macro"):
        block = _macro_block(_macro, ctx.get("macro_news"))
        if block:
            lines.append(block)

    # Broad economic/political news (RSS) so the brief reflects market-moving
    # macro/geopolitical headlines, not just per-ticker corporate news.
    if _mkt_news := ctx.get("market_news"):
        block = _market_news_block(_mkt_news)
        if block:
            lines.append(block)

    # Macro reports + band phân bổ (P4) — bối cảnh KHUNG THÁNG (cap ~5 dòng,
    # chỉ-khi-tươi). Brief allocation nhận thêm block state đầy đủ (bảng % +
    # lý do input) vì đó là chủ đề chính của nó.
    if ctx.get("macro_reports") or ctx.get("allocation"):
        block = _macro_reports_block(ctx)
        if block:
            lines.append(block)
    if brief_type == "allocation" and (_alloc := ctx.get("allocation")):
        block = _allocation_state_block(_alloc)
        if block:
            lines.append(block)
    # Phản biện band (devil's advocate) — chỉ brief allocation mang block này.
    if brief_type == "allocation" and (_deb := ctx.get("allocation_debate")):
        block = _debate_block(_deb)
        if block:
            lines.append(block)

    # Bài học reflection — mọi brief_type (ngữ cảnh mềm, không phải mục brief).
    if _lessons := ctx.get("reflections"):
        block = _reflections_block(_lessons)
        if block:
            lines.append(block)

    # Held positions — per-position facts so the brief can advise theo vị thế.
    if _pf := ctx.get("portfolio"):
        block = _portfolio_block(_pf)
        if block:
            lines.append(block)

    # Recommendation + news blocks — explicit empty markers so the LLM
    # cannot invent trade ideas or news headlines from training data.
    if rec_block:
        lines.append(rec_block)
    else:
        lines.append(
            "\n## Khuyến nghị từ chiến lược đã backtest\n"
            "⚠️ KHÔNG có khuyến nghị nào hôm nay — phần 'Đề xuất giao dịch' "
            "trong brief PHẢI bỏ qua hoặc viết 'Không có khuyến nghị từ strategy'. "
            "TUYỆT ĐỐI KHÔNG bịa entry/TP/SL cho bất kỳ mã nào."
        )

    if news_block:
        lines.append(news_block)
    else:
        lines.append(
            "\n## Tin tức thị trường\n"
            "⚠️ KHÔNG CÓ tin tức trong cache hôm nay — KHÔNG được nhắc tên tin/headline. "
            "Phần 'Tin tức ảnh hưởng' trong brief viết 'Không có tin tức mới trong cache'."
        )

    data_block = "\n".join(lines)
    if few_shot:
        data_block = data_block + "\n" + few_shot

    tmpl = {"morning": _MORNING_TEMPLATE,
            "allocation": _ALLOCATION_TEMPLATE}.get(brief_type,
                                                    _AFTERNOON_TEMPLATE)
    return tmpl.format(system=_SYSTEM, data=data_block)


# ── Hệ guard hậu kiểm → `vnstock_brief_guards` ─────────────────────────────
# 44 guard + chuỗi `apply_brief_guards` (ĐIỂM PARITY sáng/chiều) đã tách ra
# module riêng. Re-export nguyên tên: rất nhiều test và vnstock_telegram
# import trực tiếp `from vnstock_brief import enforce_...`.
from vnstock_brief_guards import (  # noqa: F401  (re-export: giữ nguyên đường import cũ)
    _ALLOC_HORIZON_CAVEAT,
    _BUY_BIAS_CAVEAT,
    _CJK_RE,
    _CONSTRAINT_NOTATION_RE,
    _COMPOSITE_LEAK_RE,
    _GTGD_CTX_RE,
    _GTGD_SUBJECT_RE,
    _INSTR_LEAK_RE,
    _MOOD_EMOJIS,
    _MOOD_WORDS,
    _MA200_CALL_IT_WEAK,
    _MORNING_CMP_RE,
    _MORNING_LABEL_CLAUSE,
    _MORNING_LABEL_CMP_RE,
    _PIVOT_LABEL_RE,
    _PLACEHOLDER_LEAK_RE,
    _SECTION_EMOJIS,
    _STANCE_CAUTION_MARK,
    _STANCE_CAUTION_MOMENTUM,
    _VNI_CONTEXT_RE,
    _VNI_MAGNITUDE_RE,
    _adjusted_ref_price,
    _EXDATE_MARK,
    _EXDATE_REC_DAYS,
    _EXDATE_WL_DAYS,
    _WL_META_RE,
    _exdate_map,
    _canonical_risk_lines,
    _is_section_start,
    _parse_vn_number,
    apply_brief_guards,
    brief_section,
    enforce_allocation_table,
    enforce_breadth_label,
    enforce_breadth_quality,
    enforce_buy_vs_bias_caveat,
    enforce_change_verb_sign,
    enforce_compare_direction,
    enforce_composite_rotation_hygiene,
    enforce_gtgd_baseline_pct,
    enforce_gtgd_compare_frame,
    enforce_gtgd_total,
    enforce_lead_lag,
    enforce_liquidity_label,
    enforce_macro,
    enforce_macro_fx_pct,
    enforce_macro_reports,
    enforce_market_news,
    enforce_money_flow_two_sides,
    enforce_net_flow_label,
    enforce_nn_frame_labels,
    enforce_nn_window_label,
    enforce_no_bias_directive_leak,
    enforce_no_cjk,
    enforce_no_composite_jargon,
    enforce_no_constraint_notation,
    enforce_no_duplicate_momentum,
    enforce_no_instruction_leak,
    enforce_no_placeholder_leak,
    enforce_no_record_superlative,
    enforce_number_format,
    enforce_pivot_labels,
    enforce_portfolio_facts,
    enforce_range_position,
    enforce_realestate_ocf_context,
    enforce_risk_numbers,
    enforce_risk_section,
    enforce_scenario_levels,
    enforce_sector_nn_figures,
    enforce_sentiment_consistency,
    enforce_session_direction,
    enforce_sr_direction,
    enforce_stance_sentiment_caution,
    enforce_unvalidated_strategy_caveat,
    enforce_upcoming_events,
    enforce_vnindex_change,
    _ADVERB,
    enforce_exdate_levels,
    enforce_reference_band_wording,
    _reference_bands,
    _BAND_WORDS,
    _BAND_SAFE,
    enforce_watchlist_eligibility,
    enforce_watchlist_hygiene,
    validate_brief_factuality,
)


# ── Main entry point ───────────────────────────────────────────────────────
def generate_brief(
    brief_type: str = "morning",
    agents: list[BriefAgent] | None = None,
    force: bool = False,
) -> dict[str, tuple[str, str | None]]:
    """Generate market brief using all enabled agents.

    Args:
        brief_type: "morning" | "afternoon"
        agents:     list of BriefAgent; if None, load from config file
        force:      skip time-of-day check

    Returns:
        {agent_name: (text, error_or_None)}
        Special key "_timing" if called too early (force=False)
    """
    # Ensure API keys from .env are in os.environ BEFORE agents check
    # is_available. When called from the CLI (run.py telegram close) the
    # process hasn't loaded .env yet — _brief_snippet runs before
    # send_message() (the first thing that loads .env), so without this every
    # agent would read an empty os.environ and report "no key available".
    _ensure_env_loaded()

    if not force:
        now = datetime.now().time()
        if brief_type == "morning" and now < time(11, 30):
            return {"_timing": ("", f"Morning brief khả dụng sau 11:30 (hiện tại {now.strftime('%H:%M')})")}
        if brief_type == "afternoon" and now < time(15, 0):
            return {"_timing": ("", f"Afternoon brief khả dụng sau 15:00 (hiện tại {now.strftime('%H:%M')})")}

    if agents is None:
        agents = build_agents()
    # Ưu tiên agent MẠNH trước (22/07) — quyết định cả thứ tự chọn bản chính
    agents = _strength_sorted(agents)

    if not agents:
        return {"_no_agent": (
            "",
            "Không có AI agent nào được bật. Vào ⚙️ Cài đặt Agent → chọn agent và điền API key.",
        )}

    # Close overdue/zombie recs first so the brief's recommendation blocks
    # reflect the live book (best-effort).
    _maybe_reconcile_overdue()
    # Refresh the upcoming-events cache if it isn't from today (best-effort) so
    # the "📅 Sự kiện sắp tới" block isn't empty due to run ordering.
    _maybe_refresh_events()
    # Refresh macro (lãi suất & tỷ giá) the same way so the "🌐 Vĩ mô" block is
    # current; best-effort, FX-fetch failure keeps the prior cache.
    _maybe_refresh_macro()
    # Refresh broad economic/political news (RSS) for the "📰 Tin kinh tế/chính trị"
    # block; best-effort, blocked feeds skipped.
    _maybe_refresh_market_news()

    ctx = collect_context(brief_type, auto_refresh=True)

    # Phản biện band (devil's advocate — 1 call/kỳ, cache theo as_of+band) —
    # CHỈ brief phân bổ (cadence tháng nên +1 call chấp nhận được). Best-effort:
    # LLM chết/tắt (VNSTOCK_ALLOC_DEBATE=0) → brief chạy như không có phản biện.
    if brief_type == "allocation":
        try:
            from vnstock_debate import run_debate
            if _deb := run_debate(ctx.get("allocation") or {},
                                  ctx.get("reports_consensus")):
                ctx["allocation_debate"] = _deb
        except Exception:
            pass

    # Inject few-shot golden examples + open recommendations (best-effort)
    few_shot  = _few_shot_block(brief_type)
    rec_block = _recommendation_block(ctx)
    news_block = _news_block()

    prompt = build_prompt(ctx, brief_type, few_shot=few_shot,
                          rec_block=rec_block, news_block=news_block)

    results: dict[str, tuple[str, str | None]] = {}
    brief_ids: dict[str, int] = {}

    # Skip Cerebras when VNINDEX context is missing — the 70B model often
    # rate-limits and falls back to llama3.1-8b, which ignores the
    # "TUYỆT ĐỐI KHÔNG suy đoán" sentinel and hallucinates VNINDEX levels
    # (1.815, R1=1.813, etc.). Layer 2 validator catches it but it's better
    # to skip the agent entirely than display a 🚨-flagged brief.
    #
    # BUT never skip if Cerebras is the ONLY agent with a working key —
    # a validated (🚨-flagged) brief beats no brief at all. Otherwise the
    # whole list would empty out and generation would have nothing to run.
    _vnindex_missing = not (ctx.get("vnindex_tech") or {}).get("close")
    if _vnindex_missing:
        _non_cerebras_available = [
            a for a in agents
            if getattr(a, "agent_type", "") != "cerebras" and a.is_available
        ]
        if _non_cerebras_available:
            _skipped = [a for a in agents if getattr(a, "agent_type", "") == "cerebras"]
            for agent in _skipped:
                results[agent.name] = ("", "Bỏ qua Cerebras khi không có data VNINDEX — fallback model có xu hướng hallucinate.")
            agents = [a for a in agents if getattr(a, "agent_type", "") != "cerebras"]

    available = [a for a in agents if a.is_available]
    unavailable = [a for a in agents if not a.is_available]
    for agent in unavailable:
        results[agent.name] = ("", f"API key chưa thiết lập cho {agent.name}")

    # No agent left to run → return a precise diagnostic instead of crashing
    # on ThreadPoolExecutor(max_workers=0). Enumerate every enabled agent and
    # WHY it isn't running (no key / skipped) so the cause is unambiguous —
    # "no API key" alone is misleading when agents normally work.
    if not available:
        _lines = ["⚠️ Brief không chạy được — không có agent khả dụng:"]
        for agent in agents:
            # ClaudeAgent reads ANTHROPIC_API_KEY directly; the rest expose _ENV_KEY
            _env_var = getattr(
                agent, "_ENV_KEY",
                "ANTHROPIC_API_KEY" if getattr(agent, "agent_type", "") == "claude" else "?",
            )
            _lines.append(
                f"  • {agent.name}: thiếu key (env {_env_var} chưa set)"
            )
        # Agents that were intentionally skipped (e.g. Cerebras) also count.
        for _name, (_t, _err) in results.items():
            if _name.startswith("_"):
                continue
            if _err and "Bỏ qua" in _err:
                _lines.append(f"  • {_name}: {_err}")
        _lines.append(
            "→ Kiểm tra .env (GROQ_API_KEY / CEREBRAS_API_KEY / ANTHROPIC_API_KEY…) "
            "đã được load chưa, hoặc bật agent trong ⚙️ Cài đặt Agent."
        )
        results["_no_available"] = ("", "\n".join(_lines))
        _brief_alert_down("brief: không agent nào khả dụng (thiếu key?)")
        return results

    # Run available agents in parallel to cut wall-clock time from N*T → T
    def _call(agent: BriefAgent) -> tuple[str, tuple[str, str | None]]:
        return agent.name, agent.generate(prompt, max_tokens=_BRIEF_MAX_TOKENS)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=min(len(available), 8)) as pool:
        futures = {pool.submit(_call, a): a for a in available}
        for fut in as_completed(futures):
            try:
                name, result = fut.result()
            except Exception as exc:
                agent = futures[fut]
                name, result = agent.name, ("", str(exc))
            results[name] = result

    # Bản CHÍNH = agent mạnh nhất thành công → sắp results theo thứ tự sức
    # mạnh. Trước 22/07 thứ tự = as_completed (agent nào XONG TRƯỚC đứng
    # đầu) → bản gửi Telegram không tất định khi bật >1 agent.
    _ordered: dict = {}
    for agent in available:
        if agent.name in results:
            _ordered[agent.name] = results[agent.name]
    for _k, _v in results.items():
        if _k not in _ordered:
            _ordered[_k] = _v
    results = _ordered

    # Auto-fallback (user chốt 22/07): MỌI agent đang bật đều lỗi → thử tuần
    # tự agent CÓ KEY nhưng chưa bật (mạnh → yếu), lấy bản đầu tiên thành
    # công, gắn nhãn "(dự phòng)". Vẫn trắng tay → alert Telegram.
    def _ok_any() -> bool:
        return any(t and not e for t, e in
                   (results.get(a.name, ("", None)) for a in available))

    if not _ok_any():
        try:
            _enabled_types = {getattr(a, "agent_type", "") for a in agents}
            _reserves = []
            for _cfg in load_agent_configs():
                _cls = AGENT_REGISTRY.get(_cfg.get("type", ""))
                if _cls is None or _cfg.get("type") in _enabled_types:
                    continue
                _cand = _cls(model=_cfg.get("model", ""),
                             name=_cfg.get("name", _cfg.get("type", "")))
                if _cand.is_available:
                    _reserves.append(_cand)
            for _cand in _strength_sorted(_reserves):
                _text, _rerr = _cand.generate(prompt, max_tokens=_BRIEF_MAX_TOKENS)
                if _text and not _rerr:
                    _cand.name = f"{_cand.name} (dự phòng)"
                    results[_cand.name] = (_text, None)
                    available.append(_cand)   # guard/validator/memory áp như thường
                    break
        except Exception:
            pass
        if not _ok_any():
            _brief_alert_down("brief sáng/chiều — mọi agent đều lỗi")

    # Deterministic fixups the LLM is known to flub: restore the upcoming-events
    # list when the model claims "Không có sự kiện đáng chú ý" despite the data,
    # and re-attach the land-bank context when a BĐS ticker is cited for weak
    # Op.CF without it.
    for agent in available:
        text, _err = results.get(agent.name, ("", None))
        if text:
            fixed = apply_brief_guards(text, ctx)
            if fixed != text:
                results[agent.name] = (fixed, _err)

    # Defensive layer: scan each agent's output for hallucinated VNINDEX
    # numbers. Stored in results["_warnings"] so the UI can surface them.
    warnings_by_agent: dict[str, list[str]] = {}
    for agent in available:
        text, _err = results.get(agent.name, ("", None))
        if text:
            wlist = validate_brief_factuality(text, ctx)
            if wlist:
                warnings_by_agent[agent.name] = wlist

    # Persist to memory sequentially (SQLite is not thread-safe for writes)
    try:
        import vnstock_memory as _mem
        from vnstock_train import auto_score_brief as _score
        ctx_small = {k: v for k, v in ctx.items() if k != "tickers"}
        for agent in available:
            text, err = results.get(agent.name, ("", None))
            score = _score(text) if text else 0.0
            bid = _mem.save_brief(
                brief_date=ctx.get("date", ""),
                brief_type=brief_type,
                agent_name=agent.name,
                agent_type=getattr(agent, "agent_type", ""),
                model=getattr(agent, "model", ""),
                prompt=prompt,
                output=text,
                error=err,
                context=ctx_small,
                auto_score=score,
            )
            brief_ids[agent.name] = bid
    except Exception:
        pass

    # Sổ theo dõi nghi ngờ (U22): nhặt bằng chứng cho hai mục CHƯA đủ căn cứ
    # để viết guard — Op.CF quá lớn so với quy mô, và câu viện dẫn dòng tiền
    # ngoại không có trong ctx. Best-effort tuyệt đối: brief KHÔNG được hỏng
    # vì cái sổ. Chỉ soi bản của agent ĐẦU TIÊN có text — cùng ctx thì bằng
    # chứng như nhau, ghi nhiều bản chỉ làm phồng sổ.
    try:
        import vnstock_brief_watch as _watch
        _first = next((t for t, _ in
                       (results.get(a.name, ("", None)) for a in available) if t), "")
        if _first:
            _watch.observe_brief(Path(__file__).parent / "data_warehouse",
                                 _first, ctx, today=ctx.get("date"))
    except Exception:
        pass

    if brief_ids:
        results["_brief_ids"] = brief_ids  # type: ignore[assignment]
    if warnings_by_agent:
        results["_warnings"] = warnings_by_agent  # type: ignore[assignment]
    return results

# ── Memory-backed helpers (lazy, all best-effort) ──────────────────────────
def _few_shot_block(brief_type: str, n: int = 2) -> str:
    """Pull top-rated past briefs to use as in-context examples."""
    try:
        import vnstock_memory as _mem
        rows = _mem.top_rated_briefs(brief_type, limit=n)
        if not rows:
            return ""
        rated = [r for r in rows if (r.get("user_rating") or 0) >= 4]
        if not rated:
            return ""
        parts = ["\n## Ví dụ brief chất lượng cao trước đây (tham khảo phong cách)"]
        for r in rated:
            parts.append(f"\n--- Brief ngày {r.get('brief_date')}, "
                         f"{r.get('user_rating')}⭐ ---")
            parts.append((r.get("output") or "")[:1200])
        return "\n".join(parts)
    except Exception:
        return ""


def _news_block(max_items: int = 15) -> str:
    """Pull latest news from vnstock_news cache for AI context injection."""
    try:
        import vnstock_news as _nn
        block = _nn.news_context_block(max_items=max_items)
        return block
    except Exception:
        return ""


def _fmt_rec_price(p: float) -> str:
    """Format a rec price (thousand VND) with adaptive precision.

    Integer thousands collapse low-priced instruments (CW, penny) and distort
    the implied TP/SL %, so keep decimals when the price is small.

    Ngưỡng "nhỏ" NỚI TỪ 10 LÊN 100 (19/08). Phần lớn cổ phiếu VN nằm trong dải
    10-100 nghìn đồng, mà bỏ hết thập phân ở đó sai tới ±0,5 nghìn: brief chiều
    19/08 in `SBT entry=24 TP=25 SL=23` trong khi sổ ghi TP +7,4% / SL −2,7%
    trên entry ≈ 23,5 — mốc TP thật ≈ 25,2. Sai số 0,5 trên một mục tiêu 7,4%
    là hơn một phần tư biên lợi nhuận, và lệch cả HAI chiều bất lợi cho người
    đọc (chốt lời sớm, cắt lỗ sát hơn ý đồ). Một chữ số thập phân đưa sai số
    xuống ≤0,5% ở đáy dải và ≤0,1% ở giữa dải. Bỏ đuôi ".0" để giá tròn vẫn
    đọc gọn ("13" chứ không "13.0").
    """
    a = abs(p)
    if a == 0:
        return "0"
    if a < 1:
        return f"{p:,.3f}"
    if a < 10:
        return f"{p:,.2f}"
    if a < 100:
        return f"{p:,.1f}".removesuffix(".0")
    return f"{p:,.0f}"


def _active_strategy_validation(ctx: dict | None = None) -> dict:
    """Kiểm định chống-ăn-may của chiến lược ĐANG HOẠT ĐỘNG.

    Trả `{"known": bool, "passed": bool, "p": float|None, "reasons": [...]}`.
    `known=False` khi chưa đọc được (chưa có chiến lược, chưa có backtest, DB
    lỗi) — và đó KHÔNG được coi là "trượt": không đo được khác đo ra kết quả
    xấu (họ lỗi đã vấp nhiều lần ở repo này), nên im lặng chứ không cảnh báo oan.

    Ghi vào `ctx["strategy_validation"]` để guard dùng lại, khỏi đọc DB hai lần.
    """
    out = {"known": False, "passed": True, "p": None, "reasons": []}
    try:
        import vnstock_memory as _mem
        active = _mem.get_active_family()
        if active:
            out = _validation_of_strategy(active["id"])
    except Exception as e:
        if ctx is not None:
            _note_loader_error(ctx, "strategy_validation", e)
    if ctx is not None:
        ctx["strategy_validation"] = out
    return out


def _horizon_calendar_days(horizon: int) -> int:
    """`horizon_days` là số PHIÊN → ngày lịch tương đương (một nơi định nghĩa
    ở `vnstock_strategy`, cùng nếp với `_evidence_floor`).

    So thẳng phiên với ngày là ẩn/đóng lệnh sớm ~30% (vết 19/08): lệnh 20 phiên
    biến mất khỏi brief sau 20 ngày lịch ≈ 14 phiên, trong khi sổ vẫn mở.
    """
    try:
        from vnstock_strategy import calendar_days_for_sessions
        return calendar_days_for_sessions(horizon)
    except Exception:
        import math as _m
        return max(int(horizon), _m.ceil(int(horizon) * 7 / 5))


def _evidence_floor() -> int:
    """Sàn số lệnh để một verdict "đạt" được phép mang tiền thật.

    Đọc từ `vnstock_strategy` để không nuôi hai bản; import hỏng thì dùng 30
    (đúng giá trị user chốt 13/08) thay vì tắt sàn.
    """
    try:
        from vnstock_strategy import MIN_TRADES_TO_VALIDATE
        return int(MIN_TRADES_TO_VALIDATE)
    except Exception:
        return 30


def _validation_of_strategy(strategy_id) -> dict:
    """Kiểm định của MỘT chiến lược theo id — cùng hợp đồng known/passed/p.

    Tách riêng (13/08) vì rec nay mang `strategy_id` của chính nó và hai tier
    chạy song song: rec của tầng vị thế phải được xử theo kiểm định của CHÍNH
    chiến lược vị thế, không phải của chiến lược 5 phiên đang active.
    Mọi lỗi đọc → unknown (không đo được ≠ trượt).

    SÀN BẰNG CHỨNG áp ở ĐIỂM ĐỌC (user chốt nâng 10→30, 13/08): `passed` lưu
    trong DB được tính theo luật tại thời điểm backtest — nếu chỉ sửa hằng số
    thì #32 (19 lệnh, passed=True đã lưu) tiếp tục phát rec cho tới khi có
    backtest MỚI, mà tune không lưu backtest khi không có ứng viên thắng. Áp
    tại điểm đọc = quyết định nâng sàn có hiệu lực NGAY với verdict cũ.
    Chỉ hạ verdict "đạt" xuống; validation vắng (backtest cũ) vẫn là unknown.
    """
    out = {"known": False, "passed": True, "p": None, "reasons": []}
    try:
        import json as _json

        import vnstock_memory as _mem
        bt = _mem.latest_backtest(strategy_id)
        if not bt or not bt.get("metrics_json"):
            return out
        mt = _json.loads(bt["metrics_json"])
        val = mt.get("validation")
        if not val:
            return out
        out = {
            "known": True,
            "passed": bool(val.get("passed")),
            # p hiệu chỉnh chọn-lọc nghiêm hơn p thô — ưu tiên như panel dashboard
            "p": val.get("p_value_adj", val.get("p_value_sharpe")),
            "reasons": list(val.get("reasons") or []),
        }
        n = int(bt.get("n_trades") or mt.get("n_trades") or 0)
        floor = _evidence_floor()
        if out["passed"] and n < floor:
            out["passed"] = False
            out["reasons"] = out["reasons"] + [
                f"mẫu quá mỏng (n={n} < {floor}) — thống kê đẹp trên ít lệnh "
                f"chưa đủ bằng chứng để phát khuyến nghị"]
        return out
    except Exception:
        return out


def split_recs_by_validation(recs: list, ctx: dict | None = None) -> tuple[list, list]:
    """Chia recs theo kiểm định chống-ăn-may của CHIẾN LƯỢC NGUỒN từng rec.

    Trả `(emitted, hidden_vals)`: `emitted` giữ nguyên thứ tự vào; `hidden_vals`
    là các validation-dict (dedup) của những chiến lược bị ẩn — đủ để chỗ gọi
    in p/lý do. Luật MỘT nơi (mục 10, 15/08) dùng chung brief + Telegram —
    hai kênh không được tự diễn giải "trượt" khác nhau:
      ẨN ⇔ `known` VÀ `not passed`; không đo được ≠ trượt (unknown vẫn phát).
    Rec mang `strategy_id` xử theo kiểm định của CHÍNH nó (hai tier song song,
    13/08); rec cũ không có `strategy_id` → kiểm định của active short.
    """
    _short_val = _active_strategy_validation(ctx)
    _val_cache: dict = {}

    def _val_of(rec) -> dict:
        sid = rec.get("strategy_id")
        if sid is None:
            return _short_val
        if sid not in _val_cache:
            _val_cache[sid] = _validation_of_strategy(sid)
        return _val_cache[sid]

    emitted, hidden_vals = [], []
    for r in recs:
        v = _val_of(r)
        if v["known"] and not v["passed"]:
            if v not in hidden_vals:
                hidden_vals.append(v)
            continue
        emitted.append(r)
    return emitted, hidden_vals


def _recommendation_block(ctx: dict | None = None) -> str:
    """Insert open recommendations from validated strategies.

    Overdue recs (held longer than their horizon) are excluded — they should be
    reconciled/closed, not re-surfaced as fresh actionable buys.

    Chiến lược TRƯỢT kiểm định chống-ăn-may → KHÔNG nêu khuyến nghị nào
    (user chốt 13/08, thay lựa chọn cảnh-báo-kèm-theo trước đó): thà không có
    còn hơn có mà phải kèm "đừng tin lắm". Thay danh sách bằng sentinel
    "KHÔNG CÓ" — cùng bất biến chống-khoảng-trống của build_prompt: block biến
    mất âm thầm thì template vẫn trỏ tới "block Khuyến nghị" và model tự bịa.

    Sổ khuyến nghị trong DB VẪN được ghi/đối soát bình thường (vnstock_train)
    — đó là cách chiến lược tự chứng minh bằng số liệu live để một ngày ĐẠT
    kiểm định; chỉ kênh brief tới user là đóng.
    """
    try:
        import vnstock_memory as _mem
        recs = _mem.open_recommendations()
        if not recs:
            return ""
        _now = datetime.now()
        fresh = []
        for r in recs:
            horizon = int(r.get("horizon_days") or 5)
            try:
                age = (_now - datetime.fromisoformat(r["created_at"])).days
            except Exception:
                age = 0
            if age <= _horizon_calendar_days(horizon):
                fresh.append(r)
        if not fresh:
            return ""

        # Gating THEO TỪNG CHIẾN LƯỢC (13/08, hai tier chạy song song) — luật
        # nằm ở split_recs_by_validation để Telegram dùng CHUNG (mục 10),
        # KHÔNG inline lại tại đây (cùng lý lẽ với điểm parity
        # apply_brief_guards: hai kênh một luật).
        emitted, hidden_vals = split_recs_by_validation(fresh, ctx)

        if not emitted:
            if ctx is not None:
                ctx["strategy_recs_in_prompt"] = False
            _p = next((v.get("p") for v in hidden_vals
                       if isinstance(v.get("p"), float)), None)
            _why = next((v["reasons"][0] for v in hidden_vals
                         if v.get("reasons")), None)
            # Kèm LÝ DO đầu tiên: từ khi có sàn bằng chứng, p có thể rất đẹp
            # (0.040) mà vẫn trượt vì mẫu mỏng — chỉ in p sẽ gây hiểu lầm.
            _ptxt = f" (p={_p:.3f})" if isinstance(_p, float) else ""
            if _why:
                _ptxt += f" — {_why}"
            return (
                "\n## Khuyến nghị từ chiến lược đã backtest (tự sinh)\n"
                f"⚠️ KHÔNG CÓ khuyến nghị hôm nay — chiến lược hiện tại CHƯA ĐẠT "
                f"kiểm định chống-ăn-may{_ptxt}. "
                "BẮT BUỘC: KHÔNG viết câu kiểu 'chiến lược khuyến nghị mua …'; "
                "mục 'Đề xuất giao dịch' CHỈ dùng mã ⭐ từ block Top Gainers/Losers "
                "(không có mã ⭐ thì ghi 'Chưa có setup đủ điều kiện')."
            )
        fresh = emitted
        # KL gợi ý fixed-risk (display-only, chỉ khi user đã cấu hình NAV).
        _sps = None
        try:
            from vnstock_strategy import load_sizing_config, suggest_position_size
            if load_sizing_config().get("nav_million"):
                _sps = suggest_position_size
        except Exception:
            _sps = None

        lines = ["\n## Khuyến nghị từ chiến lược đã backtest (tự sinh)"]
        for r in fresh[:5]:
            entry = float(r.get("entry_price") or 0)
            _h = int(r.get("horizon_days") or 5)
            tp    = float(r.get("take_profit") or 0)
            sl    = float(r.get("cut_loss") or 0)
            line = f"- {r['ticker']} {r['action'].upper()}"
            if _h >= 15:
                # Tầng vị thế: nhãn khung thời gian ghi RÕ (bài học "Giá 1T %"
                # — mọi nhãn phải nói nó thuộc khung nào).
                line += f" [vị thế ~{_h} phiên]"
            if entry > 0:
                line += f" entry={_fmt_rec_price(entry)}"
            if tp > 0:
                line += f" TP={_fmt_rec_price(tp)}"
            if sl > 0:
                line += f" SL={_fmt_rec_price(sl)}"
            if _sps and entry > 0 and sl > 0:
                _sz = _sps(entry, sl)
                if _sz:
                    line += (f" · KL gợi ý ~{_sz['qty']:,} cp"
                             f" (rủi ro {_sz['risk_pct']:g}% NAV)")
            if r.get("rationale"):
                _rat = str(r["rationale"]).strip()
                if len(_rat) > 80:                       # truncate on a WORD
                    _rat = _rat[:80].rsplit(" ", 1)[0].rstrip(" ,;:-(") + "…"
                line += f" — {_rat}"
            lines.append(line)

        if hidden_vals:
            # Một phần bị ẩn (tier trượt kiểm định) — nói ra để model không
            # tự bịa lý do "thiếu khuyến nghị", và không nhắc tier đó nữa.
            lines.append(
                "(Một phần khuyến nghị đã bị ẩn vì chiến lược sinh ra chúng "
                "CHƯA ĐẠT kiểm định — KHÔNG nhắc tới các mã ngoài danh sách trên.)")
        if ctx is not None:
            ctx["strategy_recs_in_prompt"] = True
            # 17/08 (brief #217): cờ recs_in_prompt từng ngầm định "rec trong
            # prompt = của chiến lược active tầng NGẮN". Hai tier (13/08) +
            # gate ở nguồn (15/08) làm ngầm định gãy: emitted sau splitter chỉ
            # còn passed/unknown và có thể thuộc tier KHÁC — đêm #32 [vị thế]
            # ĐẠT p=0.012 mà caveat dán (p=1.000) của tầng ngắn lên chính rec
            # của nó. Ghi kiểm định của CHÍNH recs vừa vào prompt để guard
            # caveat theo đúng nguồn.
            ctx["strategy_recs_validation"] = {
                "known": True, "passed": True, "p": None, "reasons": []}
        return "\n".join(lines)
    except Exception:
        return ""


# ── Consensus aggregation across multi-agent briefs ────────────────────────
#
# Extracts stance/sector/ticker signals from each agent's brief text and
# tallies them so the UI can show "5/6 agents: neutral, 4/6: Dầu khí dẫn dắt"
# instead of forcing the user to read every tab.
#
# Heuristic: briefs follow a templated structure (TLDR / Tổng kết / Dẫn dắt /
# Watchlist / Rủi ro), so regex-based extraction within section boundaries
# is reliable enough. Agents that diverge from the template just get
# stance="unknown" — they don't pollute the consensus.

_STANCE_BULL = (
    "tích cực", "tăng tốt", "phục hồi mạnh", "bullish", "tăng giá",
    "uptrend", "khả quan", "tăng điểm", "lên giá",
)
_STANCE_BEAR = (
    "tiêu cực", "giảm sâu", "rủi ro cao", "bearish", "đảo chiều giảm",
    "downtrend", "giảm điểm", "áp lực bán",
)
_STANCE_NEUT = (
    "trung tính", "đi ngang", "sideways", "thận trọng", "do dự",
    "phân hoá", "bias trung tính", "giằng co",
)

# Indicators / acronyms commonly mistaken for tickers (3-letter all-caps)
_TICKER_BLACKLIST: frozenset[str] = frozenset({
    # Indicators / technical terms
    "TLD", "TLDR", "USD", "VND", "EUR", "GBP", "RSI", "EMA", "SMA",
    "EPS", "ROE", "ROA", "ROI", "P/E", "PEG", "PEP", "VWA", "ATR",
    "MACD", "GTGD", "OHLC", "API", "SQL", "TPS", "POC", "VAL", "VAH",
    "ETF", "IPO", "MA", "AI", "OK", "USA", "VAT", "FED", "ECB",
    # Trade action verbs (appear in 'BUY khi...', 'SELL/HOLD/WAIT' setups)
    "BUY", "SELL", "HOLD", "WAIT", "CUT", "AVOID", "MUA", "BAN",
    "SHORT", "LONG", "OUT", "PASS", "STOP", "EXIT",
    # Common Vietnamese 3-letter words appearing in setups
    "TP1", "TP2", "TP3", "SL1", "SL2", "ATH", "ATL", "HOM", "CHO",
    "TLD", "MUC", "KQ1",
})


def _extract_section(text: str, header: str) -> str:
    """Return body of a markdown section by header keyword (case-insensitive)."""
    import re as _re
    # Match "## <header>...\n<body>" until next ## or EOF
    pattern = _re.compile(
        rf"##[^\n]*{_re.escape(header)}[^\n]*\n(.*?)(?=\n##|\Z)",
        _re.IGNORECASE | _re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


# Match canonical "Stance ngày mai: <X>" / "Stance: <X>" line in TLDR.
# Prompt template asks every agent to emit this exact pattern, so parsing
# it is far more reliable than counting keywords across the whole section.
_STANCE_LINE_RE = _re.compile(
    r"[Ss]tance(?:\s+(?:ngày\s+mai|sáng\s+mai|hôm\s+nay))?\s*[:：]\s*([^.\n]+)",
    _re.IGNORECASE,
)


def _detect_stance(tldr_text: str) -> str:
    """Classify TLDR as bullish/bearish/neutral/unknown.

    Strategy:
      1. If canonical 'Stance ngày mai: <X>' line is present, check the
         captured phrase first for canonical labels TĂNG/GIẢM/TRUNG TÍNH —
         this is what the prompt template instructs the agent to emit.
      2. Fall back to keyword vote across the full TLDR.
    """
    import re as _re_local
    m = _STANCE_LINE_RE.search(tldr_text)
    if m:
        captured = m.group(1).lower()
        # Canonical labels as whole-word tokens (avoid matching "tăng giá")
        if _re_local.search(r"\btrung\s*tính\b", captured):
            return "neutral"
        if _re_local.search(r"\b(tăng|bullish|uptrend)\b", captured):
            return "bullish"
        if _re_local.search(r"\b(giảm|bearish|downtrend)\b", captured):
            return "bearish"

    # Fallback: keyword vote over full TLDR
    target = tldr_text.lower()
    bull = sum(1 for kw in _STANCE_BULL if kw in target)
    bear = sum(1 for kw in _STANCE_BEAR if kw in target)
    neut = sum(1 for kw in _STANCE_NEUT if kw in target)

    if bull == 0 and bear == 0 and neut == 0:
        return "unknown"
    # Neutral beats other on tie — explicit "trung tính" is a stronger
    # signal than incidental "tích cực" / "giảm" elsewhere in the sentence.
    if neut >= bull and neut >= bear:
        return "neutral"
    if bull > bear:
        return "bullish"
    return "bearish"


def _extract_sectors(text: str) -> list[str]:
    """Extract sector names from 'Dẫn dắt' section. Returns up to 3 names."""
    import re as _re
    block = _extract_section(text, "Dẫn dắt")
    if not block:
        return []
    sectors: list[str] = []
    # Patterns like: "Ngành Dầu khí ...", "Dầu khí với đóng góp ..."
    # Terminator words mark end of sector name: với / dẫn / đóng / theo /
    # tụt / vẫn / chiếm / tăng / giảm / nắm — all common verbs that follow
    # a sector name in Vietnamese market commentary.
    pattern = _re.compile(
        r"[Nn]gành\s+([A-ZÀ-Ỹa-zà-ỹ&\s]{3,40}?)"
        r"(?=[,.\(]|\s+(?:với|dẫn|đóng|theo|tụt|vẫn|chiếm|tăng|giảm|nắm|là|hôm)\b|$)"
    )
    for m in pattern.finditer(block):
        name = m.group(1).strip().rstrip(",.")
        if 3 <= len(name) <= 30 and name not in sectors:
            sectors.append(name)
            if len(sectors) >= 3:
                break
    return sectors


def _extract_tickers(text: str) -> list[str]:
    """Extract VN tickers (3-letter codes) from Watchlist + Khuyến nghị sections."""
    import re as _re
    pool = []
    for header in ("Watchlist", "Đề xuất giao dịch", "Khuyến nghị"):
        block = _extract_section(text, header)
        if block:
            pool.append(block)
    if not pool:
        return []
    haystack = "\n".join(pool)
    tickers: list[str] = []
    for m in _re.finditer(r"\b([A-Z]{3})\b", haystack):
        tk = m.group(1)
        if tk in _TICKER_BLACKLIST or tk in tickers:
            continue
        tickers.append(tk)
        if len(tickers) >= 5:
            break
    return tickers


def derive_consensus(results: dict, ctx: dict | None = None) -> dict:
    """Aggregate stance/sector/ticker signals across multi-agent brief outputs.

    Args:
        results: {agent_name: (text, error_or_None)} from generate_brief()
        ctx:     optional context dict (currently unused; reserved for future)

    Returns:
        {
          "n_agents":       int   — count of agents with non-empty output
          "stance":         {"bullish": int, "neutral": int, "bearish": int,
                             "unknown": int}
          "top_sectors":    [(sector_name, agent_count), ...]   most-mentioned
          "top_tickers":    [(ticker, agent_count), ...]        most-mentioned
          "per_agent":      {agent_name: {"stance", "sectors", "tickers"}}
          "consensus_line": str — single-sentence summary for the UI banner
        }
    """
    from collections import Counter

    agent_briefs: dict[str, str] = {
        k: v[0] for k, v in results.items()
        if not k.startswith("_") and isinstance(v, tuple) and v[0]
    }
    if not agent_briefs:
        return {"n_agents": 0, "consensus_line": ""}

    stance_ct: Counter[str] = Counter()
    sector_ct: Counter[str] = Counter()
    ticker_ct: Counter[str] = Counter()
    per_agent: dict[str, dict] = {}

    for name, text in agent_briefs.items():
        tldr = _extract_section(text, "TLDR") or text[:400]
        stance = _detect_stance(tldr)
        sectors = _extract_sectors(text)
        tickers = _extract_tickers(text)

        per_agent[name] = {"stance": stance, "sectors": sectors, "tickers": tickers}
        stance_ct[stance] += 1
        for s in sectors:
            sector_ct[s] += 1
        for t in tickers:
            ticker_ct[t] += 1

    n = len(agent_briefs)
    top_stance, top_n = stance_ct.most_common(1)[0]
    top_sectors = sector_ct.most_common(5)
    top_tickers = ticker_ct.most_common(10)

    # Build a single human line for the consensus banner
    parts = [f"{top_n}/{n} agents: **{top_stance}**"]
    if top_sectors:
        # Only mention sectors agreed on by majority (≥ half)
        majority = [s for s, c in top_sectors if c >= max(2, n // 2)]
        if majority:
            parts.append(f"dẫn dắt: {', '.join(majority[:2])}")
    if top_tickers:
        consensus_tk = [t for t, c in top_tickers if c >= max(2, n // 2)]
        if consensus_tk:
            parts.append(f"watchlist chung: {', '.join(consensus_tk[:3])}")

    return {
        "n_agents": n,
        "stance": dict(stance_ct),
        "top_sectors": top_sectors,
        "top_tickers": top_tickers,
        "per_agent": per_agent,
        "consensus_line": " · ".join(parts),
    }


# ── Brief accuracy tracking (F1.c) ─────────────────────────────────────────
#
# Compare past brief stances against actual VNINDEX movement T+N trading
# days later. Lets users see which AI agent is reliably right vs wrong over
# time, instead of trusting / distrusting based on a single brief.

def _load_vnindex_closes() -> "pd.Series":
    """Return VNINDEX close indexed by trading_date (ascending). Empty on fail.

    Reads parquet partitions directly from data_warehouse/prices/ticker=VNINDEX/
    instead of importing vnstock_dashboard.load_price_history — the latter
    triggers the full Streamlit script at module load (pills nav, all tabs)
    when called outside the Streamlit runtime, which is both slow and noisy.
    """
    try:
        import pandas as pd
        import pyarrow.parquet as pq
    except Exception:
        try:
            import pandas as pd
            return pd.Series(dtype=float)
        except Exception:
            return None  # type: ignore[return-value]

    from pathlib import Path
    prices_dir = Path("data_warehouse/prices")
    if not prices_dir.exists():
        return pd.Series(dtype=float)

    for sym in ("VNINDEX", "VN-INDEX", "^VNINDEX"):
        ticker_dir = prices_dir / f"ticker={sym}"
        if not ticker_dir.exists():
            continue
        frames = []
        for yd in sorted(ticker_dir.glob("year=*")):
            for pf in yd.glob("*.parquet"):
                try:
                    frames.append(pq.read_table(
                        str(pf), columns=["time", "close"]
                    ).to_pandas())
                except Exception:
                    continue
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        if df.empty or "close" not in df.columns:
            continue
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").drop_duplicates(
            subset=["time"], keep="last"
        )
        # Normalize price units (warehouse stores VNINDEX in either index
        # points or thousand-points depending on source — values >5000
        # indicate /1000 scaling needed).
        if (df["close"] > 5000).mean() > 0.5:
            df["close"] = df["close"] / 1000.0
        s = df.set_index(df["time"].dt.date)["close"].astype(float)
        return s
    return pd.Series(dtype=float)


def evaluate_brief_accuracy(
    brief: dict,
    closes: "pd.Series | None" = None,
    horizon_days: int = 1,
    neutral_threshold_pct: float = 0.5,
) -> dict:
    """Score a single brief against actual VNINDEX move T+horizon trading days later.

    Args:
        brief:                 dict from vnstock_memory.recent_briefs() —
                               must have 'output' and 'brief_date'
        closes:                optional pre-loaded VNINDEX close Series
                               (date → close). Pass to avoid reloading per call.
        horizon_days:          look this many TRADING days ahead (default T+1)
        neutral_threshold_pct: |return| below this counts as 'flat'
                               (default 0.5%)

    Returns:
        {
          'stance':         predicted stance from brief
          'brief_date':     '2026-05-22'
          'baseline_date':  date of close used as baseline
          'eval_date':      date of close N trading days later (or None)
          'baseline_close': float (or None)
          'eval_close':     float (or None)
          'return_pct':     float (or None)
          'actual':         'up' / 'down' / 'flat' / None
          'match':          True / False / None — None when not evaluable
          'reason':         human-readable note for diagnostics
        }
    """
    import pandas as pd
    result = {
        "stance": "unknown", "brief_date": brief.get("brief_date"),
        "baseline_date": None, "eval_date": None,
        "baseline_close": None, "eval_close": None,
        "return_pct": None, "actual": None,
        "match": None, "reason": "",
    }

    # 1. Extract stance from brief output
    output = brief.get("output") or ""
    if not output:
        result["reason"] = "no brief output"
        return result
    tldr = _extract_section(output, "TLDR") or output[:400]
    stance = _detect_stance(tldr)
    result["stance"] = stance
    if stance == "unknown":
        result["reason"] = "stance unknown — cannot evaluate"
        return result

    # 2. Locate baseline and evaluation closes
    if closes is None:
        closes = _load_vnindex_closes()
    if closes is None or closes.empty:
        result["reason"] = "no VNINDEX warehouse data"
        return result

    try:
        brief_d = pd.to_datetime(brief.get("brief_date")).date()
    except Exception:
        result["reason"] = "bad brief_date"
        return result

    # Baseline = last available close on or before brief_date
    candidates_before = closes[closes.index <= brief_d]
    if candidates_before.empty:
        result["reason"] = f"no VNINDEX close on or before {brief_d}"
        return result
    base_date = candidates_before.index[-1]
    base_close = float(candidates_before.iloc[-1])
    result["baseline_date"] = base_date
    result["baseline_close"] = base_close

    # Eval = horizon_days-th trading close strictly AFTER base_date
    candidates_after = closes[closes.index > base_date]
    if len(candidates_after) < horizon_days:
        result["reason"] = (
            f"not enough trading days after {base_date} "
            f"(need {horizon_days}, have {len(candidates_after)})"
        )
        return result
    eval_date = candidates_after.index[horizon_days - 1]
    eval_close = float(candidates_after.iloc[horizon_days - 1])
    result["eval_date"] = eval_date
    result["eval_close"] = eval_close

    # 3. Compute return + classify actual
    ret_pct = (eval_close / base_close - 1.0) * 100.0
    result["return_pct"] = ret_pct
    if abs(ret_pct) < neutral_threshold_pct:
        actual = "flat"
    elif ret_pct > 0:
        actual = "up"
    else:
        actual = "down"
    result["actual"] = actual

    # 4. Match stance vs actual
    if stance == "bullish":
        result["match"] = (actual == "up")
    elif stance == "bearish":
        result["match"] = (actual == "down")
    elif stance == "neutral":
        result["match"] = (actual == "flat")

    result["reason"] = (
        f"{stance} vs {actual} ({ret_pct:+.2f}% over {horizon_days}d)"
    )
    return result


def agent_accuracy_summary(
    briefs: list[dict],
    horizon_days: int = 1,
    neutral_threshold_pct: float = 0.5,
) -> dict:
    """Aggregate per-agent accuracy across a list of past briefs.

    Returns:
        {
          agent_name: {
            'n_total':     count of briefs for this agent,
            'n_evaluated': count actually scored (stance + price data both available),
            'n_match':     count where stance matched actual move,
            'accuracy':    n_match / n_evaluated (or None if zero evaluated),
            'stance_dist': {'bullish': n, 'bearish': n, 'neutral': n, 'unknown': n},
          }
        }
    """
    closes = _load_vnindex_closes()

    by_agent: dict[str, dict] = {}
    for b in briefs:
        name = b.get("agent_name") or "?"
        if name not in by_agent:
            by_agent[name] = {
                "n_total": 0, "n_evaluated": 0, "n_match": 0,
                "stance_dist": {"bullish": 0, "bearish": 0,
                                "neutral": 0, "unknown": 0},
            }
        slot = by_agent[name]
        slot["n_total"] += 1
        ev = evaluate_brief_accuracy(b, closes=closes,
                                     horizon_days=horizon_days,
                                     neutral_threshold_pct=neutral_threshold_pct)
        slot["stance_dist"][ev["stance"]] = slot["stance_dist"].get(ev["stance"], 0) + 1
        if ev["match"] is not None:
            slot["n_evaluated"] += 1
            if ev["match"]:
                slot["n_match"] += 1

    for slot in by_agent.values():
        slot["accuracy"] = (
            slot["n_match"] / slot["n_evaluated"]
            if slot["n_evaluated"] > 0 else None
        )
        # Mẫu quá nhỏ thì con số KHÔNG nói lên điều gì — xem `format_accuracy`.
        slot["reliable"] = slot["n_evaluated"] >= _ACCURACY_MIN_SAMPLE
    return by_agent


# Số brief ĐÃ CHẤM tối thiểu để dám hiện một con số phần trăm. Dưới ngưỡng này
# "0%" đọc ra thành "agent sai hết", trong khi sự thật chỉ là "chưa đủ mẫu" —
# đúng họ lỗi đã vấp nhiều lần ở repo này: KHÔNG ĐO ĐƯỢC bị trình bày thành
# ĐO RA KẾT QUẢ XẤU (ca thật 13/08: Gemini 0/2 hiện "0%", Mistral 0/1 hiện
# "0%" — nhìn như hai agent tệ, thực ra chưa chấm nổi 2 brief).
# 5 là mức tối thiểu để một tỷ lệ bắt đầu có nghĩa; muốn phân biệt thật với
# tung đồng xu thì còn cần nhiều hơn.
_ACCURACY_MIN_SAMPLE: int = 5


def format_accuracy(slot: dict) -> str:
    """Chuỗi hiển thị độ chính xác của một agent.

    Ba trạng thái KHÁC NHAU, không được gộp:
      * chưa chấm được brief nào      → "—"
      * đã chấm nhưng chưa đủ mẫu     → "— (n=2)"  ← không phải "0%"
      * đủ mẫu                        → "40% (n=5)"
    """
    n = int(slot.get("n_evaluated") or 0)
    acc = slot.get("accuracy")
    if n <= 0 or acc is None:
        return "—"
    if n < _ACCURACY_MIN_SAMPLE:
        return f"— (n={n})"
    return f"{acc * 100:.0f}% (n={n})"

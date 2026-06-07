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
import os
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

# VN30 tickers — current composition (keep in sync with _VN30_FALLBACK in vnstock_news.py)
# Try dynamic fetch first; fall back to this set when vnstock API is unavailable.
VN30_TICKERS: set[str] = {
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
}


def get_vn30_live() -> set[str]:
    """Try to fetch current VN30 from vnstock API; fall back to VN30_TICKERS."""
    try:
        from vnstock_auth import get_vnstock
        df = get_vnstock("VCB", "VCI").listing.symbols_by_group("VN30")
        if df is not None and not df.empty:
            col = next((c for c in ("ticker", "symbol", "code") if c in df.columns), None)
            if col:
                tickers = {str(v).upper() for v in df[col] if v}
                if len(tickers) >= 20:
                    return tickers
    except Exception:
        pass
    return set(VN30_TICKERS)

_DEFAULT_AGENT_CONFIGS: list[dict] = [
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
        "model": "llama-3.3-70b-versatile",
        "name": "Groq Llama-3.3-70B",
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
        "model": "llama3.3-70b",
        "name": "Cerebras Llama-3.3-70B",
        "enabled": False,
        "max_tokens": 1200,
    },
    {
        "type": "openrouter",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "name": "OpenRouter Llama-3.3-70B",
        "enabled": False,
        "max_tokens": 1200,
    },
]

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

## 📈 Mức kỹ thuật quan trọng (VNINDEX)
TRÍCH XUẤT TỪ block "## VNINDEX kỹ thuật" — KHÔNG BỊA, KHÔNG dùng số trong training data.
**Đóng cửa hiện tại:** [chính xác con số `close` trong data, ví dụ "1.815,42"]
**Hỗ trợ gần:** [S1 và S2 từ Pivots — ghi cả số tuyệt đối]
**Kháng cự gần:** [R1 và R2 từ Pivots]
**Vị trí so với MA:** [chính xác số MA20/MA50/MA200 + % cách giá hiện tại từ data]
**Trigger breakout:** [vượt R1 → test R2; thủng S1 → về S2 — viết theo SỐ đã cho]
Nếu block "VNINDEX kỹ thuật" KHÔNG có trong data → viết "Chưa có dữ liệu VNINDEX hôm nay" (không bịa).

## 🎯 Trọng tâm theo dõi
**Tích luỹ/Mua:** [ngành hoặc mã VN30 + lý do cụ thể từ data — nêu trọng số %VNI và đóng góp pp]
**Tránh/Bán:** [ngành hoặc mã VN30 + lý do cụ thể]
**Theo dõi:** [rotation/stealth nếu có, bỏ dòng này nếu không có tín hiệu]

## ⚡ Biến động bất thường
[Mã/ngành tăng giảm đột biến + giải thích + BẮT BUỘC ghi rõ khung thời gian (ví dụ: "VIC -3.2% phiên sáng", "PLX -8.8% trong 5 phiên", "ACB +4.1% so với đóng cửa hôm qua"); "Không có biến động bất thường đáng chú ý" nếu phẳng]

## 🔮 Kịch bản phiên chiều
**Kịch bản chính ([X]% xác suất):** [điều kiện kích hoạt CỤ THỂ với mức giá/chỉ số — ví dụ "VNINDEX giữ trên 1.245, bank giữ đà → kỳ vọng đóng cửa +0.4-0.8%"]
**Kịch bản phụ:** [điều kiện ngược + ngưỡng cắt lỗ/đứng ngoài — ví dụ "VHM thủng 42.5 + GTGD chiều >70% sáng → áp lực phân phối, chuyển sang phòng thủ"]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã từ block "Khuyến nghị từ chiến lược đã backtest" với entry/TP/SL]
BẮT BUỘC: Nếu quyết định bị ảnh hưởng bởi tin tức trong block "Tin tức thị trường", PHẢI nêu rõ tên tiêu đề tin và giải thích tác động (ví dụ: "HPG: MUA — kỹ thuật vượt MA20 + tin [Hòa Phát ký hợp đồng thép 5.000 tỷ] hỗ trợ đà tăng"). Bỏ qua nếu không có khuyến nghị.

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[1 dữ liệu/chỉ số cần thêm để brief sau chính xác hơn — bỏ qua nếu không cần]

Giới hạn 450 từ. Chỉ đề cập mã trong VN30 khi nói về cổ phiếu cụ thể.
YÊU CẦU VỀ ĐỘ CỤ THỂ — KHÔNG ĐƯỢC VI PHẠM:
- Mọi nhận định PHẢI gắn với SỐ trong data, không nói "tích cực/tiêu cực" suông.
- Ngành được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp hôm nay.
- Mã được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có.
- Ưu tiên ngành/mã có đóng góp TUYỆT ĐỐI lớn nhất, không chỉ tăng % cao nhất.
- Kịch bản phải có TRIGGER (mức giá/chỉ số/% volume) — không viết "nếu thị trường tốt".
- Nếu không đủ data cho một mục → viết "Cần thêm [data X]", không bịa.
- MỌI % thay đổi giá PHẢI ghi rõ khung thời gian: "hôm nay", "phiên sáng", "5 phiên", "so với đóng cửa hôm qua", v.v. TUYỆT ĐỐI KHÔNG viết "X giảm Y%" mà không có khung thời gian.
"""

_AFTERNOON_TEMPLATE = """\
{system}

Dữ liệu thị trường kết thúc PHIÊN CHIỀU (15:00):

{data}

---
Viết AFTERNOON BRIEF tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 🎯 TLDR (2 dòng)
**Kết quả phiên:** [VNINDEX đóng cửa ±X% / GTGD Y tỷ — 1 câu nhận định bản chất]
**Stance ngày mai:** [TĂNG / GIẢM / TRUNG TÍNH bias + 1 setup ưu tiên hoặc cảnh báo]

## 📊 Tổng kết phiên
[2-3 câu: kết quả toàn ngày, GTGD vs trung bình, độ rộng thị trường (A/D, % trên MA200), so sánh với kỳ vọng sáng nếu có]

## 📈 Mức kỹ thuật chốt phiên (VNINDEX)
TRÍCH XUẤT TỪ block "## VNINDEX kỹ thuật" — KHÔNG BỊA.
**Đóng cửa:** [chính xác `close` từ data, ví dụ "1.815,42 (+0,38%)"]
**Vị trí trong range:** [đóng cửa nằm ở đâu trong range tuần/tháng — viết theo SỐ]
**Vs MA:** [trên/dưới MA20/MA50/MA200 + khoảng cách % theo data]
**Trigger ngày mai:** [vượt R1=[số] → test R2=[số]; thủng S1=[số] → về S2=[số]]
Nếu block "VNINDEX kỹ thuật" KHÔNG có → viết "Chưa có dữ liệu VNINDEX hôm nay".

## 🏆 Dẫn dắt & Tụt hậu
**Dẫn dắt:** [top 2-3 ngành/mã VN30 + đóng góp pp + % return cụ thể]
**Tụt hậu:** [ngành/mã yếu + lý do nếu rõ]

## 💰 Dòng tiền đáng chú ý
[NN mua/bán ròng đáng kể (số tỷ cụ thể) | smart money tích luỹ/phân phối | unusual volume; bỏ qua nếu phẳng]

## 📋 Watchlist sáng mai (3 setup cụ thể)
1. **[Mã/Ngành]** — [BUY ở X / WAIT khi vượt Y / SELL nếu thủng Z] — [trigger 1 dòng]
2. ...
3. ...

## ⚠️ Rủi ro cần lưu ý
[Red flags, distribution, macro risk với mức cảnh báo cụ thể; "Không có rủi ro đặc biệt" nếu thị trường ổn]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã với entry/TP/SL từ block "Khuyến nghị"]
BẮT BUỘC: Nếu có tin tức tác động → nêu rõ tiêu đề tin + ảnh hưởng. Bỏ qua nếu không có khuyến nghị.

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[1 dữ liệu/chỉ số cần thêm để brief sau chính xác hơn — bỏ qua nếu không cần]

Giới hạn 500 từ. Chỉ đề cập mã trong VN30. Nếu thị trường flat và không có signal rõ thì nói thẳng.
YÊU CẦU VỀ ĐỘ CỤ THỂ — KHÔNG ĐƯỢC VI PHẠM:
- Mọi nhận định PHẢI gắn với SỐ trong data.
- Ngành được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp hôm nay.
- Mã được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có.
- Ưu tiên ngành/mã có đóng góp TUYỆT ĐỐI lớn nhất, không chỉ tăng % cao nhất.
- Setup watchlist phải có TRIGGER (mức giá cụ thể) — không viết "nếu thị trường tích cực thì vào".
- Nếu không đủ data → viết "Cần thêm [data X]", không bịa.
- MỌI % thay đổi giá PHẢI ghi rõ khung thời gian: "hôm nay", "phiên sáng", "5 phiên", "so với đóng cửa hôm qua", v.v. TUYỆT ĐỐI KHÔNG viết "X giảm Y%" mà không có khung thời gian.
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
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"], None
        except Exception as e:
            return "", f"Claude API lỗi: {type(e).__name__}: {str(e)[:160]}"


class _OpenAICompatAgent(BriefAgent):
    """Base for any provider that uses the OpenAI chat-completions wire format."""
    agent_type = "openai"
    _ENDPOINT: str = "https://api.openai.com/v1/chat/completions"
    _ENV_KEY: str = "OPENAI_API_KEY"
    _ERR_PREFIX: str = "API"

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
                    "messages": [
                        {"role": "system", "content": system_part},
                        {"role": "user", "content": user_part},
                    ],
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"], None
        except Exception as e:
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

    def __init__(self, model: str = "llama-3.3-70b-versatile", name: str = "Groq Llama-3.3-70B"):
        super().__init__(model, name)


class MistralAgent(_OpenAICompatAgent):
    """Mistral AI — OpenAI-compatible chat completions endpoint."""
    agent_type = "mistral"
    _ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
    _ENV_KEY = "MISTRAL_API_KEY"
    _ERR_PREFIX = "Mistral API"

    def __init__(self, model: str = "mistral-small-latest", name: str = "Mistral Small"):
        super().__init__(model, name)


class DeepSeekAgent(_OpenAICompatAgent):
    """DeepSeek — excellent code generation, very cheap pricing."""
    agent_type = "deepseek"
    _ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
    _ENV_KEY = "DEEPSEEK_API_KEY"
    _ERR_PREFIX = "DeepSeek API"

    def __init__(self, model: str = "deepseek-chat", name: str = "DeepSeek Chat"):
        super().__init__(model, name)


class CerebrasAgent(_OpenAICompatAgent):
    """Cerebras Cloud — ultra-fast inference (2000+ tok/s), Llama models."""
    agent_type = "cerebras"
    _ENDPOINT = "https://api.cerebras.ai/v1/chat/completions"
    _ENV_KEY = "CEREBRAS_API_KEY"
    _ERR_PREFIX = "Cerebras API"

    # Try models in order; Cerebras occasionally renames or deprecates
    _MODEL_FALLBACKS: list[str] = [
        "llama3.3-70b",    # Llama 3.3 70B (preferred, no dash)
        "llama-3.3-70b",   # Legacy alias with dash
        "llama3.1-70b",    # Llama 3.1 70B (always available)
        "llama3.1-8b",     # Smallest, fastest fallback
    ]

    def __init__(self, model: str = "llama3.3-70b", name: str = "Cerebras Llama-3.3-70B"):
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
                        "messages": [
                            {"role": "system", "content": system_part},
                            {"role": "user", "content": user_part},
                        ],
                    },
                    timeout=90,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                if idx > 0:
                    content = f"_(fallback: {model})_\n\n{content}"
                return content, None
            except Exception as e:
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

    # Process-level cache of free model slugs fetched from /api/v1/models
    _free_model_cache: list[str] = []

    def __init__(
        self,
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
        name: str = "OpenRouter Llama-3.3-70B",
    ):
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
                content = resp.json()["choices"][0]["message"]["content"]
                if idx > 0:
                    content = f"_(fallback: {model})_\n\n{content}"
                return content, None
            except Exception as e:
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


# ── Agent registry ─────────────────────────────────────────────────────────
AGENT_REGISTRY: dict[str, type[BriefAgent]] = {
    "claude": ClaudeAgent,
    "openai": OpenAIAgent,
    "groq": GroqAgent,
    "mistral": MistralAgent,
    "deepseek": DeepSeekAgent,
    "cerebras": CerebrasAgent,
    "openrouter": OpenRouterAgent,
}


# Obsolete model names → current model names (auto-migrate on load)
_MODEL_MIGRATIONS: dict[tuple[str, str], str] = {
    # Cerebras renamed Llama from "llama-3.3-70b" (with dash) to "llama3.3-70b"
    ("cerebras", "llama-3.3-70b"): "llama3.3-70b",
}


# ── Config helpers ─────────────────────────────────────────────────────────
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
            changed = True

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
    AGENTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_CONFIG_PATH.write_text(
        json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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


# ── Context collection ─────────────────────────────────────────────────────
def collect_context(brief_type: str = "morning") -> dict:
    """Collect all available market data for brief generation."""
    # Determine effective trading date: use the last bar date from VNINDEX
    # warehouse instead of calendar today. Avoids "no data" briefs when called
    # early morning (market not open yet) or on weekends/holidays.
    _vt_early = _vnindex_technicals()
    _data_date_str = effective_trading_date(_vt_early)

    _today_str = date.today().isoformat()
    _is_stale = _data_date_str < _today_str  # data is from a prior trading day

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
        except Exception:
            pass

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
            ctx["quant_error"] = str(e)

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
    except Exception:
        pass

    # 4. VN30 movers (from ticker data)
    if ctx["tickers"]:
        try:
            import pandas as pd
            tick_df = pd.DataFrame(ctx["tickers"])
            price_col = "Giá 1T %" if "Giá 1T %" in tick_df.columns else None
            if price_col and "Mã" in tick_df.columns:
                vn30_df = tick_df[tick_df["Mã"].isin(VN30_TICKERS)].dropna(subset=[price_col])
                ctx["vn30_gainers"] = vn30_df.nlargest(5, price_col)[
                    ["Mã", price_col, "Ngành"]].to_dict("records") if not vn30_df.empty else []
                ctx["vn30_losers"] = vn30_df.nsmallest(5, price_col)[
                    ["Mã", price_col, "Ngành"]].to_dict("records") if not vn30_df.empty else []
        except Exception:
            pass

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
        except Exception:
            pass

    # 6. VNINDEX technical levels — already fetched above to determine the
    # effective date; reuse the result instead of calling again.
    ctx["vnindex_tech"] = _vt_early

    return ctx


def _load_vnindex_df() -> "pd.DataFrame":
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

    return df


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

        # Recent swing lows/highs as dynamic S/R — pivots over last 60 bars
        # excluding the last 2 bars (avoid using "today" as its own pivot)
        last60_high = high.tail(62).iloc[:-2] if len(high) >= 62 else high.iloc[:-2]
        last60_low  = low.tail(62).iloc[:-2]  if len(low)  >= 62 else low.iloc[:-2]

        # Resistance: 2 highest closes ABOVE current price; Support: 2 lowest BELOW
        above = sorted({round(float(v), 2) for v in last60_high if v > last}, reverse=False)
        below = sorted({round(float(v), 2) for v in last60_low  if v < last}, reverse=True)
        res1 = above[0] if len(above) >= 1 else None
        res2 = above[1] if len(above) >= 2 else None
        sup1 = below[0] if len(below) >= 1 else None
        sup2 = below[1] if len(below) >= 2 else None

        # 52w + intraday ranges
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
            "support_1":      sup1,
            "support_2":      sup2,
            "resistance_1":   res1,
            "resistance_2":   res2,
            # Date of the last bar with valid close — used by collect_context()
            # to set the "effective" brief date when today has no data yet
            # (e.g. early morning before market opens, or weekends).
            "data_date": df.loc[df["close"].notna(), "time"].iloc[-1].date().isoformat(),
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

    # Regime
    if r := ctx.get("quant_regime"):
        vr = ctx.get("vol_regime", "normal")
        vr_note = " | ⚡ Biên độ cao — high-vol regime" if vr == "high" else ""
        lines.append(f"\n## Quant Market Regime\n{r['regime']} | conviction={r['conviction']:+.2f}"
                     f"{vr_note} | {r['detail']}")

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

        vt_lines = ["\n## VNINDEX kỹ thuật (số liệu hiện tại — DÙNG CHÍNH XÁC, KHÔNG ĐƯỢC THAY)"]
        vt_lines.append(
            f"- Giá đóng cửa: **{_f(vt.get('close'))}** "
            f"(prev {_f(vt.get('prev_close'))}, "
            f"thay đổi phiên {vt.get('day_change_pct', 0):+.2f}%)"
        )
        vt_lines.append(
            f"- Range hôm nay: {_f(vt.get('day_low'))} – {_f(vt.get('day_high'))} | "
            f"Tuần: {_f(vt.get('week_low'))} – {_f(vt.get('week_high'))} | "
            f"Tháng: {_f(vt.get('month_low'))} – {_f(vt.get('month_high'))}"
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
    if timing := ctx.get("session_timing"):
        line = f"\n## Session Timing\n{timing['signal']} | {timing['detail']}"
        if ss := ctx.get("session_stats"):
            morn_gtgd = ss.get("9h-11h30", {}).get("VNINDEX", {}).get("gtgd", 0)
            full_gtgd = ss.get("9h-15h",  {}).get("VNINDEX", {}).get("gtgd", 0)
            if morn_gtgd:
                line += f"\nGTGD sáng: {morn_gtgd:.1f} tỷ"
            if full_gtgd:
                line += f" | GTGD cả ngày: {full_gtgd:.1f} tỷ"
        lines.append(line)
    else:
        lines.append(
            "\n## Session Timing\n⚠️ KHÔNG CÓ session stats hôm nay — "
            "KHÔNG được suy đoán GTGD/morning share, viết 'Chưa có dữ liệu phiên'."
        )

    # Breadth — same pattern
    if b := ctx.get("breadth"):
        lines.append(f"\n## Market Breadth\n"
                     f"Trên MA200: {b.get('above_ma200_pct',0):.0f}% | "
                     f"A/D ratio: {b.get('ad_ratio',0):.2f} | "
                     f"Net new highs: {b.get('net_new_highs',0):+d} | "
                     f"RSI oversold: {b.get('rsi_oversold',0)} mã | RSI overbought: {b.get('rsi_overbought',0)} mã")
    else:
        lines.append(
            "\n## Market Breadth\n⚠️ KHÔNG CÓ breadth data — "
            "KHÔNG được nêu % trên MA200 / A-D ratio / RSI counts."
        )

    # Sector analysis — with market-cap weights + stock breakdown
    _sw = ctx.get("sector_weights", {})
    _ts = ctx.get("top_stocks_per_sector", {})

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
                header += f", đóng góp {contrib:+.2f}pp hôm nay"
            header += "]"
        header += f" composite={r.get('composite', 0):+.2f}"

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

        # Top 3 stocks in sector: mcap, weight vs VNI, 1d return, contribution
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
                f" | composite={r.get('composite',0):+.2f}"
                + (f" | {sw.get('_weight',0)*100:.1f}%VNI" if sw.get("_weight") else "")
            )

    if stealth := ctx.get("quant_stealth"):
        lines.append("\n## Stealth accumulation (tích luỹ ngầm)")
        for r in stealth:
            lines.append(f"- **{r.get('Ngành','?')}** — giá đi ngang nhưng Net BS dương + turnover cao")

    if dist := ctx.get("quant_distribution"):
        lines.append("\n## Distribution warning (giá xanh, tiền đang thoát)")
        for r in dist:
            lines.append(f"- **{r.get('Ngành','?')}** — composite={r.get('composite',0):+.2f}")

    # VN30 movers + contribution to VNINDEX
    def _vn30_line(g: dict) -> str:
        ticker = g.get("Mã", "?")
        ret    = g.get("Giá 1T %", 0)
        sector = g.get("Ngành", "")
        contrib = next(
            (s.get("_1d_contrib", 0) or 0
             for s in _ts.get(sector, []) if s.get("Mã") == ticker),
            0.0,
        )
        line = f"- {ticker} {ret:+.1f}% [{sector}]"
        if contrib != 0:
            line += f" ≈ {contrib:+.3f}pp VNI"
        return line

    if gainers := ctx.get("vn30_gainers"):
        lines.append("\n## VN30 Top Gainers (1 phiên, với đóng góp vào VNINDEX)")
        for g in gainers:
            lines.append(_vn30_line(g))

    if losers := ctx.get("vn30_losers"):
        lines.append("\n## VN30 Top Losers (1 phiên, với đóng góp vào VNINDEX)")
        for g in losers:
            lines.append(_vn30_line(g))

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

    tmpl = _MORNING_TEMPLATE if brief_type == "morning" else _AFTERNOON_TEMPLATE
    return tmpl.format(system=_SYSTEM, data=data_block)


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

    if not agents:
        return {"_no_agent": (
            "",
            "Không có AI agent nào được bật. Vào ⚙️ Cài đặt Agent → chọn agent và điền API key.",
        )}

    ctx = collect_context(brief_type)

    # Inject few-shot golden examples + open recommendations (best-effort)
    few_shot  = _few_shot_block(brief_type)
    rec_block = _recommendation_block()
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
        return results

    # Run available agents in parallel to cut wall-clock time from N*T → T
    def _call(agent: BriefAgent) -> tuple[str, tuple[str, str | None]]:
        return agent.name, agent.generate(prompt)

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

    if brief_ids:
        results["_brief_ids"] = brief_ids  # type: ignore[assignment]
    if warnings_by_agent:
        results["_warnings"] = warnings_by_agent  # type: ignore[assignment]
    return results


# ── Runtime hallucination validator ────────────────────────────────────────
#
# Defensive layer: scans the LLM's brief output AFTER generation to detect
# numbers that look like hallucinated VNINDEX levels. Won't catch every
# hallucination but catches the most painful class — wrong index price.
#
# Strategy:
#   1. Find all VNINDEX-magnitude numbers (1.000-2.500 range) in the text
#      that appear within 25 chars of "VNINDEX" or "VNI" (context window)
#   2. Compare each to the real injected close from ctx["vnindex_tech"]
#   3. Flag if relative error > 5% (allows for daily move + S/R nearby)
#
# Returns list of warning strings; empty list = brief looks clean.
import re as _re

_VNI_MAGNITUDE_RE = _re.compile(r"\b([12][.,]?\d{3}(?:[.,]\d{1,2})?)\b")
_VNI_CONTEXT_RE = _re.compile(r"VN[\s\-]?INDEX|VN-?I(?![A-Z])|VNI(?![A-Z])", _re.IGNORECASE)


def _parse_vn_number(s: str) -> float | None:
    """Convert '1.815,42' / '1,815.42' / '1815' to float. None on failure."""
    s = s.strip()
    if not s:
        return None
    # Vietnamese: dot=thousand sep, comma=decimal. EN: comma=thousand, dot=decimal.
    # Heuristic: if both, the LAST occurrence is the decimal sep.
    has_dot   = "." in s
    has_comma = "," in s
    try:
        if has_dot and has_comma:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif has_comma:
            s = s.replace(",", ".") if s.count(",") == 1 and len(s.split(",")[1]) <= 2 else s.replace(",", "")
        elif has_dot and len(s.split(".")[1]) >= 3:
            # "1.815" with 3-digit suffix → thousand sep
            s = s.replace(".", "")
        return float(s)
    except (ValueError, IndexError):
        return None


def validate_brief_factuality(text: str, ctx: dict) -> list[str]:
    """Scan brief output for VNINDEX-magnitude numbers far from real close.

    Returns list of warning strings (empty if no flags found).
    Each warning is a Vietnamese-readable single line for UI display.

    Tolerance: 5% relative error is allowed because S/R levels and intraday
    extremes can legitimately deviate from the closing price.
    """
    if not text:
        return []
    vt = ctx.get("vnindex_tech") or {}
    real_close = vt.get("close")
    if not real_close or real_close <= 0:
        # Without ground truth we cannot validate VNINDEX numbers — but we
        # can still flag if the brief mentions a VNINDEX level despite the
        # context having NO data. That is itself a hallucination.
        if any(_VNI_CONTEXT_RE.search(line) for line in text.splitlines()):
            for line in text.splitlines():
                if _VNI_CONTEXT_RE.search(line):
                    nums = [_parse_vn_number(m.group(1))
                            for m in _VNI_MAGNITUDE_RE.finditer(line)]
                    nums = [n for n in nums if n and 800 <= n <= 2500]
                    if nums:
                        return [
                            f"⚠️ Brief nêu mức VNINDEX ({nums[0]:,.0f}) trong khi data "
                            "không có dữ liệu VNINDEX hôm nay → có thể là hallucination."
                        ]
        return []

    warnings: list[str] = []
    real_low  = real_close * 0.95
    real_high = real_close * 1.05
    seen: set[float] = set()
    for line in text.splitlines():
        if not _VNI_CONTEXT_RE.search(line):
            continue
        for m in _VNI_MAGNITUDE_RE.finditer(line):
            n = _parse_vn_number(m.group(1))
            if n is None or n in seen:
                continue
            # Filter to VNINDEX magnitude — avoid catching ticker prices,
            # weights, %, etc. that happen to look like 4-digit numbers.
            if not (800 <= n <= 2500):
                continue
            seen.add(n)
            if not (real_low <= n <= real_high):
                rel_err = (n / real_close - 1) * 100
                warnings.append(
                    f"⚠️ Brief nêu VNINDEX ≈ **{n:,.0f}** ({rel_err:+.1f}% lệch "
                    f"so với close thực {real_close:,.2f}) → khả năng hallucinate."
                )
                if len(warnings) >= 3:
                    return warnings
    return warnings


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


def _recommendation_block() -> str:
    """Insert open recommendations from validated strategies."""
    try:
        import vnstock_memory as _mem
        recs = _mem.open_recommendations()
        if not recs:
            return ""
        lines = ["\n## Khuyến nghị từ chiến lược đã backtest (tự sinh)"]
        for r in recs[:5]:
            entry = float(r.get("entry_price") or 0)
            tp    = float(r.get("take_profit") or 0)
            sl    = float(r.get("cut_loss") or 0)
            line = f"- {r['ticker']} {r['action'].upper()}"
            if entry > 0:
                line += f" entry={entry:,.0f}"
            if tp > 0:
                line += f" TP={tp:,.0f}"
            if sl > 0:
                line += f" SL={sl:,.0f}"
            if r.get("rationale"):
                line += f" — {r['rationale'][:80]}"
            lines.append(line)
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
    return by_agent

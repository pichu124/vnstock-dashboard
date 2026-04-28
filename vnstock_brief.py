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

# VN30 tickers (as of 2025 — update if index changes)
VN30_TICKERS = {
    "VCB","BID","CTG","TCB","MBB","VPB","ACB","HDB","VHM","VIC",
    "VRE","MSN","MWG","VNM","SAB","GAS","PLX","POW","REE","HPG",
    "NVL","PDR","DXG","KDH","BCM","SSI","HCM","VND","FPT","CMG",
}

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
    "dữ liệu cụ thể, phân biệt rõ tín hiệu mạnh và nhiễu, không dùng ngôn ngữ hoa mỹ."
)

_MORNING_TEMPLATE = """\
{system}

Dữ liệu thị trường kết thúc phiên SÁNG (11:30):

{data}

---
Viết MORNING BRIEF tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 📊 Tổng quan phiên sáng
[2-3 câu: diễn biến chính, GTGD so bình thường, tính chất phiên institutional/retail]

## 🎯 Trọng tâm theo dõi
**Tích luỹ/Mua:** [ngành hoặc mã VN30 + lý do cụ thể từ data]
**Tránh/Bán:** [ngành hoặc mã VN30 + lý do cụ thể từ data]
**Theo dõi:** [rotation/stealth nếu có, nếu không thì bỏ dòng này]

## ⚡ Biến động bất thường
[Mã/ngành tăng giảm đột biến + giải thích; nếu không có thì viết "Không có biến động bất thường đáng chú ý"]

## 🔮 Kịch bản phiên chiều
**Tích cực (>50% xác suất nếu...):** [điều kiện kích hoạt]
**Thận trọng:** [tín hiệu cần theo dõi để cắt lỗ / không vào hàng]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã từ block "Khuyến nghị từ chiến lược đã backtest" với entry/TP/SL; bỏ qua nếu không có]

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[1 dữ liệu/chỉ số bạn nghĩ cần thêm để brief sau chính xác hơn — ví dụ "cần GTGD bid/ask theo phút" — bỏ qua nếu không cần]

Giới hạn 400 từ. Chỉ đề cập mã trong VN30 khi nói về cổ phiếu cụ thể.
YÊU CẦU VỀ ĐỘ CỤ THỂ:
- Ngành nào được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp hôm nay (có trong data).
- Mã nào được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có trong data.
- Ưu tiên ngành/mã có đóng góp tuyệt đối lớn nhất, không chỉ tăng % cao nhất.
- Không dùng câu chung chung như "thị trường diễn biến tích cực" nếu có số liệu cụ thể hơn.
Nếu không đủ data cho một mục thì nói thẳng, không bịa.
"""

_AFTERNOON_TEMPLATE = """\
{system}

Dữ liệu thị trường kết thúc PHIÊN CHIỀU (15:00):

{data}

---
Viết AFTERNOON BRIEF tiếng Việt theo đúng format sau (không thêm phần nào khác):

## 📊 Tổng kết phiên
[2-3 câu: kết quả toàn ngày, GTGD, độ rộng thị trường, so sánh với kỳ vọng sáng]

## 🏆 Dẫn dắt & Tụt hậu
**Dẫn dắt:** [top 2-3 ngành/mã VN30 + composite/return cụ thể]
**Tụt hậu:** [ngành/mã yếu + lý do nếu rõ]

## 💰 Dòng tiền đáng chú ý
[NN mua/bán ròng đáng kể | smart money tích luỹ/phân phối | unusual volume | bỏ qua nếu không có tín hiệu rõ]

## 📋 Watchlist sáng mai
[2-3 ngành/mã + điều kiện cụ thể để vào lệnh hoặc theo dõi]

## ⚠️ Rủi ro cần lưu ý
[Red flags, distribution, macro risk; nếu thị trường ổn định thì viết "Không có rủi ro đặc biệt"]

## 💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)
[Liệt kê tối đa 3 mã từ block "Khuyến nghị từ chiến lược đã backtest" với entry/TP/SL; bỏ qua nếu không có]

## 🔧 Đề xuất bổ sung (1 dòng, optional)
[1 dữ liệu/chỉ số cần thêm để brief sau chính xác hơn — bỏ qua nếu không cần]

Giới hạn 450 từ. Chỉ đề cập mã trong VN30. Nếu thị trường flat và không có signal rõ thì nói thẳng.
YÊU CẦU VỀ ĐỘ CỤ THỂ:
- Ngành nào được đề cập → LUÔN nêu trọng số %VNI và đóng góp pp hôm nay (có trong data).
- Mã nào được đề cập → nêu mức đóng góp pp vào VNINDEX nếu có trong data.
- Ưu tiên ngành/mã có đóng góp tuyệt đối lớn nhất, không chỉ tăng % cao nhất.
- Không dùng câu chung chung nếu có số liệu cụ thể hơn.
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
    _ENV_KEY = "OPENROUTER_API_KEY"
    _ERR_PREFIX = "OpenRouter API"

    # Free fallback models tried in order when the primary model is rate-limited.
    # Slugs verified against openrouter.ai/models (filter: free).
    _FREE_FALLBACKS: list[str] = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1:free",
        "google/gemma-2-9b-it:free",
        "qwen/qwen-2.5-7b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
    ]

    def __init__(
        self,
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
        name: str = "OpenRouter Llama-3.3-70B",
    ):
        super().__init__(model, name)

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

        # Try the configured model first, then free fallbacks if rate-limited
        candidates: list[str] = [self.model]
        for fb in self._FREE_FALLBACKS:
            if fb != self.model and fb not in candidates:
                candidates.append(fb)

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
                        detail = " | " + str(resp.json())[:300]
                    except Exception:
                        pass
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                last_detail = detail
                # Fall back on rate-limit, model-not-found, or server errors
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


# ── Context collection ─────────────────────────────────────────────────────
def collect_context(brief_type: str = "morning") -> dict:
    """Collect all available market data for brief generation."""
    ctx: dict = {
        "brief_type": brief_type,
        "date": date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M"),
        "sectors": [],
        "breadth": {},
        "tickers": [],
    }

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
    try:
        from vnstock_session_stats import load_session_stats_history
        from vnstock_market_analyzer import session_timing_signal
        _hist = load_session_stats_history()
        _today = _hist.get(date.today().isoformat(), {})
        if _today:
            ctx["session_stats"] = _today
            ctx["session_timing"] = session_timing_signal(_today, _hist, "VNINDEX")
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

    return ctx


# ── Prompt builder ─────────────────────────────────────────────────────────
def build_prompt(ctx: dict, brief_type: str = "morning",
                 few_shot: str = "", rec_block: str = "") -> str:
    """Construct the full Vietnamese prompt from market context.

    Optional `few_shot` / `rec_block` are injected by the train loop / memory layer
    to nudge the model toward higher quality and surface validated trade ideas.
    """
    lines: list[str] = []

    lines.append(f"Ngày: {ctx['date']} | Thời điểm: {ctx['time']}")

    # Regime
    if r := ctx.get("quant_regime"):
        vr = ctx.get("vol_regime", "normal")
        vr_note = " | ⚡ Biên độ cao — high-vol regime" if vr == "high" else ""
        lines.append(f"\n## Quant Market Regime\n{r['regime']} | conviction={r['conviction']:+.2f}"
                     f"{vr_note} | {r['detail']}")

    # Session timing
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

    # Breadth
    if b := ctx.get("breadth"):
        lines.append(f"\n## Market Breadth\n"
                     f"Trên MA200: {b.get('above_ma200_pct',0):.0f}% | "
                     f"A/D ratio: {b.get('ad_ratio',0):.2f} | "
                     f"Net new highs: {b.get('net_new_highs',0):+d} | "
                     f"RSI oversold: {b.get('rsi_oversold',0)} mã | RSI overbought: {b.get('rsi_overbought',0)} mã")

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

    if rec_block:
        lines.append(rec_block)

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
    few_shot = _few_shot_block(brief_type)
    rec_block = _recommendation_block()

    prompt = build_prompt(ctx, brief_type, few_shot=few_shot, rec_block=rec_block)

    results: dict[str, tuple[str, str | None]] = {}
    brief_ids: dict[str, int] = {}
    for agent in agents:
        if not agent.is_available:
            results[agent.name] = ("", f"API key chưa thiết lập cho {agent.name}")
            continue
        text, err = agent.generate(prompt)
        results[agent.name] = (text, err)

        # Persist to memory (non-fatal if it fails)
        try:
            import vnstock_memory as _mem
            from vnstock_train import auto_score_brief as _score
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
                context={k: v for k, v in ctx.items() if k != "tickers"},
                auto_score=score,
            )
            brief_ids[agent.name] = bid
        except Exception:
            pass

    if brief_ids:
        results["_brief_ids"] = brief_ids  # type: ignore[assignment]
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

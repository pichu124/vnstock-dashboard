"""Sửa config agent brief theo 2 quyết định của user 11/08 (entry 11/08 (g)).

1. TẮT agent brief Groq trong code — 413 CẤU TRÚC: prompt brief ~10K token >
   trần 8K/request Groq free (rủi ro notes 22/07 đã ghi, thành hiện thực từ
   ngày migrate llama→qwen, fail 100% suốt 3 tuần không ai biết vì không log).
   Tắt MỘT LẦN qua marker `auto_disabled` — user bật lại trong ⚙️ là CHỦ
   ĐÍCH, load sau không được tắt nữa (không giành tay lái với người).

2. Sửa tên agent NÓI DỐI — trạng thái nửa-migrate (slug đổi trước khi
   f13a33f thêm rename): "Cerebras Llama-3.3-70B" chạy gpt-oss-120b. Chỉ
   thay tên đang NHẮC model đã migrate đi; tên user tự đặt không đụng.

Hermetic: AGENTS_CONFIG_PATH → tmp.
"""

import json

import pytest

import vnstock_brief as vb


@pytest.fixture()
def _tmp_cfg(tmp_path, monkeypatch):
    path = tmp_path / "brief_agents.json"
    monkeypatch.setattr(vb, "AGENTS_CONFIG_PATH", path)
    return path


def _write(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_groq_brief_agent_force_disabled_once(_tmp_cfg, capsys):
    _write(_tmp_cfg, [{"type": "groq", "model": "qwen/qwen3.6-27b",
                       "name": "Groq Llama-3.3-70B", "enabled": True,
                       "max_tokens": 1200}])
    out = vb.load_agent_configs()
    groq = next(c for c in out if c["type"] == "groq")
    assert groq["enabled"] is False
    assert "413" in groq["auto_disabled"]
    assert "413" in capsys.readouterr().out          # nói to, không tắt câm
    # và đã persist xuống file
    saved = json.loads(_tmp_cfg.read_text(encoding="utf-8"))
    assert next(c for c in saved if c["type"] == "groq")["enabled"] is False


def test_user_reenable_is_respected(_tmp_cfg):
    """User bật lại trong ⚙️ (marker auto_disabled còn đó) = chủ đích —
    load sau KHÔNG được tắt nữa. Code không giành tay lái với người."""
    _write(_tmp_cfg, [{"type": "groq", "model": "qwen/qwen3.6-27b",
                       "name": "Groq Qwen3.6-27B", "enabled": True,
                       "auto_disabled": "413 ...", "max_tokens": 1200}])
    out = vb.load_agent_configs()
    assert next(c for c in out if c["type"] == "groq")["enabled"] is True


def test_stale_llama_name_renamed_but_enabled_kept(_tmp_cfg):
    _write(_tmp_cfg, [{"type": "cerebras", "model": "gpt-oss-120b",
                       "name": "Cerebras Llama-3.3-70B", "enabled": True,
                       "max_tokens": 1200}])
    out = vb.load_agent_configs()
    cer = next(c for c in out if c["type"] == "cerebras")
    assert "llama" not in cer["name"].lower()        # hết nói dối
    assert cer["name"] == vb._default_agent_name("cerebras")
    assert cer["enabled"] is True                    # KHÔNG đụng enabled


def test_custom_name_untouched(_tmp_cfg):
    _write(_tmp_cfg, [{"type": "openrouter",
                       "model": "nvidia/nemotron-3-super-120b-a12b:free",
                       "name": "Bản nháp của tôi", "enabled": True,
                       "max_tokens": 1200}])
    out = vb.load_agent_configs()
    orow = next(c for c in out if c["type"] == "openrouter")
    assert orow["name"] == "Bản nháp của tôi"

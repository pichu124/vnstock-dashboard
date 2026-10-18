"""Expander **⚙️ Cài đặt AI Agent** — bật/tắt agent, đổi tên, chọn model.

Tách khỏi `dashboard/market_brief_panel.py` (12/08, mục ④ đợt cuối). Panel
brief từng là một khối 1.172 dòng; đo bằng AST thì 5 panel con chỉ dính nhau
qua `st` + vài tên import từ `vnstock_brief`, nên cắt được rời hẳn.

Lưu cấu hình đi qua `save_agent_configs` (ghi NGUYÊN TỬ — đây là lựa chọn của
user, mất là phải chỉnh tay lại).
"""
from __future__ import annotations


def render_agent_settings() -> None:
    """Render panel. Streamlit import LƯỜI để pytest import được module."""
    import streamlit as st  # noqa: F401
    from vnstock_brief import AGENT_REGISTRY, load_agent_configs, save_agent_configs

    # ── Agent settings expander ────────────────────────────────────
    with st.expander("⚙️ Cài đặt AI Agent", expanded=False):
        _agent_configs = load_agent_configs()
        _changed_configs: list[dict] = []

        import os as _os
        # Key theo CHỈ SỐ dòng: "➕ Thêm agent" luôn tạo type trùng ⇒ key theo
        # type nổ StreamlitDuplicateElementKey ở lượt rerun kế.
        for _i, _cfg in enumerate(_agent_configs):
            _atype = _cfg.get("type", "")
            _k = f"{_i}_{_atype}"
            _aname = _cfg.get("name", _atype)
            # Detect key status
            _cls = AGENT_REGISTRY.get(_atype)
            _env_key = getattr(_cls, "_ENV_KEY", "") if _cls else ""
            _key_ok = bool(_env_key and _os.environ.get(_env_key))
            if not _key_ok and _cls is not None and not _env_key:
                # Agent KHÔNG dùng key (Claude Code CLI): sẵn sàng = có CLI
                try:
                    _key_ok = bool(_cls().is_available)
                except Exception:
                    _key_ok = False
            _key_badge = (
                f'<span style="color:#10b981;font-size:12px">🔑 key OK</span>'
                if _key_ok else
                f'<span style="color:#ef4444;font-size:12px">🔑 chưa có key</span>'
            )
            st.markdown(
                f"**{_aname}** `{_atype}` &nbsp; {_key_badge}",
                unsafe_allow_html=True,
            )
            _col_en, _col_model, _col_test = st.columns([1, 3, 1])
            with _col_en:
                _enabled = st.checkbox(
                    "Bật", value=_cfg.get("enabled", False),
                    key=f"_brief_en_{_k}",
                    disabled=not _key_ok,
                    help="Cần điền API key vào .env trước" if not _key_ok else "",
                )
            with _col_model:
                _model = st.text_input(
                    "Model", value=_cfg.get("model", ""),
                    key=f"_brief_model_{_k}",
                    placeholder="e.g. claude-haiku-4-5-20251001",
                )
            with _col_test:
                st.markdown("<div style='margin-top:28px'></div>",
                            unsafe_allow_html=True)
                if st.button("🔌 Test", key=f"_brief_ping_{_k}",
                             disabled=not _key_ok,
                             help="Gửi tin nhắn ngắn để kiểm tra key và model"):
                    if _cls:
                        _agent_inst = _cls(
                            model=st.session_state.get(f"_brief_model_{_k}",
                                                        _cfg.get("model", "")),
                            name=_aname,
                        )
                        with st.spinner(f"Đang kiểm tra {_aname}…"):
                            _ping_ok, _ping_msg = _agent_inst.ping()
                        if _ping_ok:
                            st.success(_ping_msg)
                        else:
                            st.error(_ping_msg)
            _changed_configs.append({**_cfg, "enabled": _enabled, "model": _model})
            st.markdown("---")

        # Add new agent row
        st.markdown("**Thêm agent mới**")
        _new_col1, _new_col2, _new_col3 = st.columns([1, 2, 2])
        with _new_col1:
            _new_type = st.selectbox(
                "Loại", options=list(AGENT_REGISTRY.keys()),
                key="_brief_new_type",
            )
        with _new_col2:
            _new_name = st.text_input(
                "Tên hiển thị", key="_brief_new_name",
                placeholder="e.g. GPT-4o",
            )
        with _new_col3:
            _new_model = st.text_input(
                "Model", key="_brief_new_model",
                placeholder="e.g. gpt-4o",
            )
        _col_add, _col_save = st.columns([1, 1])
        with _col_add:
            if st.button("➕ Thêm agent", key="_brief_add_agent"):
                if _new_name and _new_model:
                    _changed_configs.append({
                        "type": _new_type,
                        "name": _new_name,
                        "model": _new_model,
                        "enabled": True,
                        "max_tokens": 1200,
                    })
                    save_agent_configs(_changed_configs)
                    st.success(f"Đã thêm {_new_name}!")
                    st.rerun()
                else:
                    st.warning("Vui lòng điền tên và model.")
        with _col_save:
            if st.button("💾 Lưu cài đặt", key="_brief_save_cfg"):
                save_agent_configs(_changed_configs)
                st.success("Đã lưu cài đặt agent!")

        st.caption(
            "API key đặt trong file `.env` ở thư mục gốc dự án:  \n"
            "`ANTHROPIC_API_KEY` (Claude) · "
            "`OPENAI_API_KEY` (OpenAI) · "
            "`GROQ_API_KEY` (Groq) · "
            "`MISTRAL_API_KEY` (Mistral) · "
            "`DEEPSEEK_API_KEY` (DeepSeek) · "
            "`CEREBRAS_API_KEY` (Cerebras) · "
            "`OPENROUTER_API_KEY` (OpenRouter) · "
            "`GEMINI_API_KEY` (Gemini — agent chính từ 22/07)  \n"
            "Sau khi điền key → restart Streamlit → quay lại đây bật ✅ agent tương ứng."
        )

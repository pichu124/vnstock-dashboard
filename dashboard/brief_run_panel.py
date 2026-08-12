"""Nút sinh brief + hiển thị kết quả (kèm banner đồng thuận nhiều agent).

Tách khỏi `dashboard/market_brief_panel.py` (12/08). Kết quả cache trong
`st.session_state["_brief_results"]` nên đổi tab rồi quay lại không phải sinh
lại (mỗi lần sinh là tốn quota LLM thật).
"""
from __future__ import annotations


def render_brief_runner() -> None:
    """Render panel. Streamlit import LƯỜI để pytest import được module."""
    import streamlit as st  # noqa: F401
    from vnstock_brief import build_agents, generate_brief, load_agent_configs

    # ── Brief controls ─────────────────────────────────────────────
    from datetime import datetime as _dt
    _now_time = _dt.now().time()
    _past_1130 = _now_time.hour > 11 or (_now_time.hour == 11 and _now_time.minute >= 30)
    _past_1500 = _now_time.hour >= 15

    _force_col, _btn_morn_col, _btn_aftn_col = st.columns([2, 1, 1])
    with _force_col:
        _force = st.checkbox(
            "🔓 Tạo ngay (bỏ qua giờ giao dịch)",
            key="_brief_force",
            help="Cho phép tạo brief bất kể thời điểm trong ngày.",
        )
    with _btn_morn_col:
        _morn_disabled = not (_past_1130 or _force)
        _morn_label = "🌅 Morning Brief" if (_past_1130 or _force) else "🌅 Morning (sau 11:30)"
        _gen_morning = st.button(_morn_label, key="_brief_gen_morning", disabled=_morn_disabled)
    with _btn_aftn_col:
        _aftn_disabled = not (_past_1500 or _force)
        _aftn_label = "🌆 Afternoon Brief" if (_past_1500 or _force) else "🌆 Afternoon (sau 15:00)"
        _gen_afternoon = st.button(_aftn_label, key="_brief_gen_afternoon", disabled=_aftn_disabled)

    # ── Generate and cache result ──────────────────────────────────
    if _gen_morning or _gen_afternoon:
        _brief_type = "morning" if _gen_morning else "afternoon"
        _agents = build_agents(load_agent_configs())
        with st.spinner(f"Đang tạo {_brief_type} brief..."):
            _results = generate_brief(
                brief_type=_brief_type,
                agents=_agents if _agents else None,
                force=_force,
            )
        st.session_state["_brief_results"] = _results
        st.session_state["_brief_type"] = _brief_type

    # ── Display results ────────────────────────────────────────────
    if "_brief_results" in st.session_state:
        _res = st.session_state["_brief_results"]
        _btype = st.session_state.get("_brief_type", "morning")
        _btype_label = "Morning" if _btype == "morning" else "Afternoon"

        if "_timing" in _res:
            st.info(_res["_timing"][1])
        elif "_no_agent" in _res:
            st.warning(_res["_no_agent"][1])
        else:
            st.markdown(f"**{_btype_label} Brief** — {_dt.now().strftime('%H:%M %d/%m/%Y')}")
            _agent_names = [k for k in _res if not k.startswith("_")]

            # ── Consensus banner (multi-agent only) ────────────────
            if len(_agent_names) >= 2:
                try:
                    from vnstock_brief import derive_consensus
                    _cons = derive_consensus(_res)
                    if _cons.get("n_agents", 0) >= 2 and _cons.get("consensus_line"):
                        _stance_top = max(_cons["stance"].items(),
                                          key=lambda kv: kv[1])[0]
                        _icon = {"bullish": "🟢", "bearish": "🔴",
                                 "neutral": "🟡", "unknown": "⚪"}.get(_stance_top, "🟡")
                        st.markdown(
                            f"### {_icon} Consensus — "
                            f"{_cons['consensus_line']}"
                        )
                        # Per-agent stance row
                        _stance_emoji = {"bullish": "🟢", "bearish": "🔴",
                                         "neutral": "🟡", "unknown": "⚪"}
                        _badges = [
                            f"{_stance_emoji.get(info['stance'], '⚪')} "
                            f"`{nm}` {info['stance']}"
                            for nm, info in _cons["per_agent"].items()
                        ]
                        st.caption(" · ".join(_badges))
                        # Sector + ticker breakdown
                        _c_sec, _c_tk = st.columns(2)
                        with _c_sec:
                            if _cons["top_sectors"]:
                                _sec_lines = " · ".join(
                                    f"**{s}** ({c}/{_cons['n_agents']})"
                                    for s, c in _cons["top_sectors"][:5]
                                )
                                st.caption(f"📊 Ngành: {_sec_lines}")
                        with _c_tk:
                            if _cons["top_tickers"]:
                                _tk_lines = " · ".join(
                                    f"**{t}** ({c})"
                                    for t, c in _cons["top_tickers"][:6]
                                )
                                st.caption(f"🎯 Tickers: {_tk_lines}")
                        st.divider()
                except Exception as _ce:
                    st.caption(f"⚠ consensus disabled: {type(_ce).__name__}: {_ce}")

            # 🎯 Track record của chính brief: Stance ngày mai vs chiều
            # VNINDEX phiên kế tiếp (AI-Trader prediction scoring)
            try:
                from vnstock_stance_track import summary_line as _stl
                _sline = _stl()
                if _sline:
                    st.caption(_sline)
            except Exception:
                pass

            def _rating_block(agent_name: str, brief_type_: str):
                try:
                    import vnstock_memory as _vm
                    _vm.init_db()
                    _today = _dt.now().date().isoformat()
                    with _vm._conn() as _c:
                        _row = _c.execute(
                            "SELECT id, user_rating FROM briefs "
                            "WHERE brief_date=? AND brief_type=? AND agent_name=? "
                            "ORDER BY created_at DESC LIMIT 1",
                            (_today, brief_type_, agent_name),
                        ).fetchone()
                    if not _row:
                        return
                    _bid = _row["id"]
                    _existing = _row["user_rating"]
                    _key_pref = f"_rate_{_bid}"
                    _cols = st.columns([2, 5, 2])
                    with _cols[0]:
                        _rate = st.select_slider(
                            "⭐ Đánh giá",
                            options=[1, 2, 3, 4, 5],
                            value=_existing or 3,
                            key=f"{_key_pref}_v",
                        )
                    with _cols[1]:
                        _fb = st.text_input(
                            "Feedback (optional)",
                            placeholder="Mô tả vấn đề / điểm cần cải thiện...",
                            key=f"{_key_pref}_fb",
                        )
                    with _cols[2]:
                        if st.button("💾 Lưu", key=f"{_key_pref}_save"):
                            _vm.update_rating(_bid, int(_rate), _fb or "")
                            st.success("Đã lưu", icon="✅")
                except Exception as _e:
                    st.caption(f"⚠ rating disabled: {type(_e).__name__}")

            # Hallucination warnings collected by validate_brief_factuality
            _warn_map = _res.get("_warnings") or {}

            def _render_warnings(agent_name: str) -> None:
                ws = _warn_map.get(agent_name) or []
                for w in ws:
                    st.error(w, icon="🚨")

            if len(_agent_names) == 1:
                _txt, _err = _res[_agent_names[0]]
                if _err:
                    st.error(f"**{_agent_names[0]}:** {_err}")
                else:
                    with st.expander(f"📄 {_agent_names[0]}", expanded=True):
                        _render_warnings(_agent_names[0])
                        st.markdown(_txt)
                        _rating_block(_agent_names[0], _btype)
            elif _agent_names:
                _tabs = st.tabs([f"📄 {n}" for n in _agent_names])
                for _tab, _aname in zip(_tabs, _agent_names):
                    with _tab:
                        _txt, _err = _res[_aname]
                        if _err:
                            st.error(_err)
                        else:
                            _render_warnings(_aname)
                            st.markdown(_txt)
                            _rating_block(_aname, _btype)

        st.caption("Brief được tạo bởi AI dựa trên dữ liệu quant — không phải khuyến nghị đầu tư.")

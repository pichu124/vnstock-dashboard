"""Expander **📜 Lịch sử brief** — xem lại brief cũ và chấm sao.

Tách khỏi `dashboard/market_brief_panel.py` (12/08). Đọc từ `vnstock_memory`
(SQLite); hỏng thì hạ xuống một dòng caption chứ không kéo sập cả tab.
"""
from __future__ import annotations


def render_brief_history() -> None:
    """Render panel. Streamlit import LƯỜI để pytest import được module."""
    import streamlit as st  # noqa: F401

    # ── Brief history viewer ────────────────────────────────────────
    with st.expander("📜 Lịch sử brief (rated & past)", expanded=False):
        try:
            import vnstock_memory as _vmh
            import json as _jsonh
            _vmh.init_db()
            _hc1, _hc2, _hc3 = st.columns([2, 2, 4])
            with _hc1:
                _hfilter = st.selectbox(
                    "Loại",
                    ["tất cả", "morning", "afternoon"],
                    key="_brief_hist_type",
                )
            with _hc2:
                _hlimit = st.number_input(
                    "Số lượng",
                    min_value=5, max_value=100, value=20, step=5,
                    key="_brief_hist_limit",
                )
            with _hc3:
                _hmin_rate = st.select_slider(
                    "Rating tối thiểu (0 = tất cả)",
                    options=[0, 1, 2, 3, 4, 5],
                    value=0,
                    key="_brief_hist_min_rate",
                )
            _btype_filter = None if _hfilter == "tất cả" else _hfilter
            _hist = _vmh.recent_briefs(_btype_filter, limit=int(_hlimit))
            if _hmin_rate > 0:
                _hist = [r for r in _hist
                         if (r.get("user_rating") or 0) >= _hmin_rate]
            if not _hist:
                st.info("Chưa có brief nào trong DB phù hợp filter.")
            else:
                # Per-agent accuracy summary (F1.c)
                try:
                    from vnstock_brief import (
                        agent_accuracy_summary as _aas,
                        _load_vnindex_closes as _lvc,
                        evaluate_brief_accuracy as _eba,
                    )
                    _closes = _lvc()
                    _hcols = st.columns([1, 1, 3])
                    with _hcols[0]:
                        _acc_horizon = st.selectbox(
                            "Đánh giá tại",
                            [1, 2, 3, 5],
                            format_func=lambda d: f"T+{d}",
                            key="_brief_acc_horizon",
                        )
                    with _hcols[1]:
                        _acc_thresh = st.selectbox(
                            "Ngưỡng flat",
                            [0.3, 0.5, 1.0],
                            index=1,
                            format_func=lambda p: f"±{p}%",
                            key="_brief_acc_thresh",
                        )
                    with _hcols[2]:
                        st.caption(
                            "**Cách tính**: stance của brief vs % thay đổi "
                            "VNINDEX T+horizon. |return| dưới ngưỡng = flat. "
                            "Brief 'unknown' bị bỏ qua khỏi mẫu."
                        )
                    _summary = _aas(
                        _hist,
                        horizon_days=int(_acc_horizon),
                        neutral_threshold_pct=float(_acc_thresh),
                    )
                    if _summary:
                        st.markdown("**📊 Độ chính xác per-agent**")
                        _rows = []
                        for _name, _slot in sorted(
                            _summary.items(),
                            key=lambda kv: -(kv[1].get("accuracy") or 0)
                        ):
                            _acc = _slot.get("accuracy")
                            _acc_str = (
                                f"{_acc*100:.0f}%" if _acc is not None else "—"
                            )
                            _sd = _slot.get("stance_dist", {})
                            _stance_str = (
                                f"🟢{_sd.get('bullish',0)} "
                                f"🟡{_sd.get('neutral',0)} "
                                f"🔴{_sd.get('bearish',0)} "
                                f"⚪{_sd.get('unknown',0)}"
                            )
                            _rows.append({
                                "Agent": _name,
                                "Accuracy": _acc_str,
                                "Match / Eval": f"{_slot.get('n_match',0)} / {_slot.get('n_evaluated',0)}",
                                "Total briefs": _slot.get("n_total", 0),
                                "Stance dist": _stance_str,
                            })
                        st.dataframe(_rows, hide_index=True,
                                     use_container_width=True)
                    st.divider()
                except Exception as _ae:
                    st.caption(f"⚠ accuracy summary disabled: {type(_ae).__name__}: {_ae}")
                    _closes = None
                    _eba = None  # type: ignore[assignment]

                # Group by date
                from collections import defaultdict as _dd
                _by_date: dict = _dd(list)
                for _b in _hist:
                    _by_date[_b.get("brief_date", "?")].append(_b)
                for _date in sorted(_by_date.keys(), reverse=True):
                    _bs = _by_date[_date]
                    _rates = [b.get("user_rating") for b in _bs
                              if b.get("user_rating")]
                    _avg = f"{sum(_rates)/len(_rates):.1f}⭐" if _rates else "—"
                    _types = sorted({b.get("brief_type", "?") for b in _bs})
                    st.markdown(
                        f"**{_date}** · {len(_bs)} briefs · "
                        f"{','.join(_types)} · avg {_avg}"
                    )
                    for _b in _bs:
                        _r = _b.get("user_rating")
                        _stars = "⭐" * _r if _r else "—"
                        _scr = _b.get("auto_score")
                        _scrs = f" · auto {_scr:.1f}" if isinstance(_scr, (int, float)) else ""
                        _err = _b.get("error") or ""
                        # Per-brief match indicator
                        _match_badge = ""
                        _eval_info = None
                        if _eba is not None and not _err:
                            try:
                                _eval_info = _eba(
                                    _b, closes=_closes,
                                    horizon_days=int(_acc_horizon),
                                    neutral_threshold_pct=float(_acc_thresh),
                                )
                                _m = _eval_info.get("match")
                                if _m is True:
                                    _match_badge = " · ✅ match"
                                elif _m is False:
                                    _match_badge = " · ❌ miss"
                                else:
                                    _match_badge = " · ⏳ pending"
                            except Exception:
                                _eval_info = None
                        _lbl = (f"{_b.get('brief_type','?')} · "
                                f"{_b.get('agent_name','?')} · "
                                f"{_stars}{_scrs}{_match_badge}"
                                f"{' · ⚠ error' if _err else ''}")
                        with st.expander(_lbl, expanded=False):
                            _ctx_raw = _b.get("context_json") or "{}"
                            try:
                                _cctx = _jsonh.loads(_ctx_raw)
                                _vt = (_cctx.get("vnindex_tech") or {})
                                _vclose = _vt.get("close")
                                if _vclose:
                                    st.caption(
                                        f"📌 VNINDEX lúc brief: {_vclose:,.2f}"
                                    )
                            except Exception:
                                pass
                            if _eval_info and _eval_info.get("eval_date"):
                                _ret = _eval_info.get("return_pct")
                                _ret_str = (
                                    f"{_ret:+.2f}%" if _ret is not None else "—"
                                )
                                st.caption(
                                    f"🎯 Stance **{_eval_info['stance']}** vs "
                                    f"actual **{_eval_info['actual']}** "
                                    f"({_eval_info['baseline_close']:,.2f} → "
                                    f"{_eval_info['eval_close']:,.2f} = {_ret_str} "
                                    f"trên {int(_acc_horizon)} phiên)"
                                )
                            elif _eval_info and _eval_info.get("reason"):
                                st.caption(
                                    f"🎯 _Chưa đánh giá được: {_eval_info['reason']}_"
                                )
                            if _err:
                                st.error(_err)
                            if _b.get("output"):
                                st.markdown(_b["output"])
                            if _b.get("user_feedback"):
                                st.caption(
                                    f"💬 Feedback: {_b['user_feedback']}"
                                )
        except Exception as _e:
            st.caption(f"⚠ history disabled: {type(_e).__name__}: {_e}")

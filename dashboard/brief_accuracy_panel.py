"""Widget gọn **bảng điểm độ chính xác brief** (F4).

Tách khỏi `dashboard/market_brief_panel.py` (12/08). Best-effort hoàn toàn:
chưa có lịch sử chấm điểm thì im lặng, không phải lỗi.
"""
from __future__ import annotations


def render_accuracy_widget() -> None:
    """Render panel. Streamlit import LƯỜI để pytest import được module."""
    import streamlit as st  # noqa: F401

    # ── F4: Brief accuracy leaderboard (compact widget) ──────────────
    try:
        import vnstock_memory as _vml
        from vnstock_brief import (
            _ACCURACY_MIN_SAMPLE as _min_n,
            agent_accuracy_summary as _aasl,
            format_accuracy as _fmt_acc,
        )
        _vml.init_db()
        _recent = _vml.recent_briefs(brief_type=None, limit=200)
        if _recent:
            _ldr = _aasl(_recent, horizon_days=1, neutral_threshold_pct=0.5)
            # Agent ĐỦ MẪU lên trước (như brief_history_panel) — không thì
            # agent 1/1 đứng trên agent đã chấm 20 brief.
            _ranked = sorted(
                [(n, s) for n, s in _ldr.items()
                 if (s.get("n_evaluated") or 0) > 0],
                key=lambda kv: (not kv[1].get("reliable"),
                                -(kv[1].get("accuracy") or 0),
                                -(kv[1].get("n_evaluated") or 0)),
            )
            if _ranked:
                st.markdown("**🏆 Bảng xếp hạng độ chính xác agent (T+1, 200 briefs gần nhất)**")
                _lc = st.columns(min(len(_ranked), 5))
                for _i, (_nm, _slot) in enumerate(_ranked[:5]):
                    _acc = _slot.get("accuracy") or 0
                    _ne  = _slot.get("n_evaluated") or 0
                    _ok = bool(_slot.get("reliable"))
                    _emoji = (("🥇", "🥈", "🥉")[_i] if _i < 3 else "🎖") if _ok else "⏳"
                    _color = (
                        "#9ca3af" if not _ok
                        else "#22c55e" if _acc >= 0.6
                        else "#fbbf24" if _acc >= 0.5
                        else "#ef4444"
                    )
                    with _lc[_i]:
                        st.markdown(
                            f"<div style='text-align:center;padding:8px;"
                            f"border:1px solid {_color};border-radius:6px;"
                            f"background:rgba(30,41,59,0.4)'>"
                            f"<div style='font-size:18px'>{_emoji} <b>{_nm}</b></div>"
                            f"<div style='font-size:24px;color:{_color};font-weight:700'>"
                            f"{_fmt_acc(_slot)}</div>"
                            f"<div style='font-size:11px;color:#9ca3af'>"
                            f"{_slot.get('n_match',0)} / {_ne} matched</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                st.caption(
                    "💡 Agent #1 nên dùng làm primary trong Consensus. "
                    f"Dưới {_min_n} brief đã chấm/agent hiện \"—\" (chưa đủ mẫu) "
                    "và không xếp hạng."
                )
    except Exception as _e:
        st.caption(f"⚠ Bảng xếp hạng accuracy disabled: {type(_e).__name__}: {_e}")

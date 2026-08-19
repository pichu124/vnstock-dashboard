"""Expander **🧪 Chiến lược & khuyến nghị (auto-trained)**.

Tách khỏi `dashboard/market_brief_panel.py` (12/08) — panel con lớn nhất:
chiến lược đang hoạt động, khuyến nghị đang mở, equity curve + phân tích lệnh
(F6), khuyến nghị đã đóng, kết quả training, và quét tín hiệu toàn thị trường.

Cả khối nằm trong MỘT `try/except` rộng có chủ ý: `vnstock_memory` /
`vnstock_train` hỏng thì panel này tự tắt bằng một dòng caption, phần còn lại
của tab Thị trường vẫn chạy.
"""
from __future__ import annotations


def render_strategy_panel() -> None:
    """Render panel. Streamlit import LƯỜI để pytest import được module."""
    import streamlit as st  # noqa: F401

    # ── Strategy & recommendations panel ───────────────────────────
    with st.expander("🧪 Chiến lược & khuyến nghị (auto-trained)", expanded=False):
        try:
            import vnstock_memory as _vm
            _vm.init_db()
            _active  = _vm.get_active_family()
            _bests   = _vm.best_strategies(limit=5)
            _opens   = _vm.open_recommendations()
            _perf    = _vm.recommendation_performance()

            _c1, _c2, _c3 = st.columns(3)
            _c1.metric("Active strategy", "✅" if _active else "—")
            _c2.metric("Open recommendations", len(_opens))
            _c3.metric(
                "Win rate (closed)",
                f"{_perf.get('win_rate', 0)*100:.0f}%" if _perf.get("n", 0) else "—",
                delta=f"n={_perf.get('n', 0)}",
            )

            # Always show the current active strategy
            if _active:
                import json as _json
                _fam = _active.get("family_id", "?")
                _tuned_by = _active.get("agent_name", "?")
                _stable = "✅ stable" if _active.get("is_core_stable") else "🔄 revising"
                _tuned_at = (_active.get("last_tuned_at") or _active.get("created_at", ""))[:10]

                st.markdown("**Chiến lược đang hoạt động**")
                _sa, _sb = st.columns([3, 2])
                with _sa:
                    st.write(
                        f"**{_active['name']}**  \n"
                        f"Family `{_fam}` · {_stable} · tuned {_tuned_at}"
                    )
                with _sb:
                    # Show latest backtest from family history
                    _hist = _vm.family_history(_fam, limit=1)
                    if _hist and _hist[0].get("n_trades") is not None:
                        _h = _hist[0]
                        _nt = _h.get("n_trades", 0)
                        _exp = _h.get("expectancy") or 0.0
                        _wr = (_h.get("win_rate") or 0.0) * 100
                        st.metric("Expectancy", f"{_exp:.2f}", delta=f"{_nt} trades")
                        if _nt == 0:
                            st.warning(
                                "⚠️ **0 trades** — strategy conditions chưa trigger được. "
                                "Nhấn **Fresh start** bên dưới để generate chiến lược mới.",
                                icon="⚠️",
                            )
                        elif _nt < 10:
                            st.warning(f"⚠️ Chỉ {_nt} trades — backtest window còn nhỏ, cần chạy Full training.", icon="⚠️")
                    else:
                        st.caption("Chưa có backtest metrics.")

                # Món 1: kiểm định thống kê chống-ăn-may (backtest gần nhất)
                try:
                    _bt0 = _vm.latest_backtest(_active["id"])
                    _bt_metrics = (
                        _json.loads(_bt0["metrics_json"])
                        if _bt0 and _bt0.get("metrics_json") else {}
                    )
                    _val = _bt_metrics.get("validation")
                    # Exit mix — "TP 0%" nói thẳng điều mà p-value nói vòng:
                    # chốt lời không với tới được thì R:R chỉ nằm trên giấy.
                    if _mix := _bt_metrics.get("exit_mix"):
                        _mix_txt = " · ".join(
                            f"{_lbl} {_mix.get(_k, 0):.0%}"
                            for _k, _lbl in (("tp", "🎯 TP"), ("sl", "🔴 SL"),
                                             ("expire", "⏳ hết hạn")))
                        st.caption(f"Exit mix (backtest): {_mix_txt}")
                        if _mix.get("tp", 0) < 0.05:
                            st.warning(
                                f"🎯 Chỉ {_mix.get('tp', 0):.0%} lệnh backtest chạm "
                                "chốt lời — TP nằm ngoài tầm với của horizon; "
                                "R:R trên giấy không thực hiện được.", icon="🎯")
                    if _val:
                        # p hiệu chỉnh chọn-lọc (Bonferroni × n ứng
                        # viên) nghiêm hơn p thô — ưu tiên hiện nó
                        _p = _val.get("p_value_adj",
                                      _val.get("p_value_sharpe"))
                        _ptxt = (f"p={_p:.3f}" if _p is not None else "p=—")
                        if _val.get("n_trials"):
                            _ptxt += f" · {_val['n_trials']} ứng viên"
                        # Sàn bằng chứng áp ở điểm đọc (user chốt 13/08) —
                        # verdict lưu theo luật cũ không được hiện "ĐẠT" nữa.
                        _n_bt = int(_bt0.get("n_trades")
                                    or _bt_metrics.get("n_trades") or 0)
                        try:
                            from vnstock_strategy import MIN_TRADES_TO_VALIDATE as _fl
                        except Exception:
                            _fl = 30
                        if _val.get("passed") and _n_bt < _fl:
                            st.warning(
                                f"🎲 Kiểm định: thống kê ĐẠT ({_ptxt}) nhưng mẫu "
                                f"quá mỏng (n={_n_bt} < {_fl}) → chưa đủ bằng chứng "
                                "— brief KHÔNG nhận khuyến nghị.", icon="🎲")
                        elif _val.get("passed"):
                            st.caption(f"🧪 Kiểm định chống-ăn-may: ĐẠT ({_ptxt})")
                        else:
                            st.warning(
                                f"🎲 Kiểm định chống-ăn-may KHÔNG đạt ({_ptxt}): "
                                + "; ".join(_val.get("reasons") or []),
                                icon="🎲",
                            )
                except Exception:
                    pass

                # Món 2: sức khỏe live (win-rate rec thật vs backtest)
                try:
                    from vnstock_strategy import strategy_health as _sh
                    _hl = _sh(_active["id"])
                    _hs = _hl.get("state")
                    if _hs == "healthy":
                        st.caption(
                            f"💚 Live khớp backtest (win-rate thật "
                            f"{(_hl.get('live_win_rate') or 0):.0%}, "
                            f"n={_hl.get('live_n')})"
                        )
                    elif _hs == "monitoring":
                        st.warning("🟡 " + "; ".join(_hl.get("reasons") or []),
                                   icon="🟡")
                    elif _hs == "decayed":
                        st.error(
                            "🔻 Chiến lược DECAY — sẽ tự demote ở lần "
                            "reconcile tới: " + "; ".join(_hl.get("reasons") or []),
                            icon="🔻",
                        )
                except Exception:
                    pass

                # Tầng vị thế 20 phiên (13/08) — chạy song song, ghế riêng.
                try:
                    _pos = _vm.get_active_family(tier="position")
                    if _pos:
                        _pv = None
                        _pbt = _vm.latest_backtest(_pos["id"])
                        if _pbt and _pbt.get("metrics_json"):
                            _pv = _json.loads(_pbt["metrics_json"]).get("validation")
                        _pn = int((_pbt or {}).get("n_trades") or 0)
                        try:
                            from vnstock_strategy import MIN_TRADES_TO_VALIDATE as _pfl
                        except Exception:
                            _pfl = 30
                        _pstate = ("✅ đạt kiểm định" if _pv and _pv.get("passed") and _pn >= _pfl
                                   else f"🎲 mẫu mỏng (n={_pn})" if _pv and _pv.get("passed")
                                   else "🎲 chưa đạt" if _pv else "⏳ chưa backtest")
                        st.caption(f"🕰 Tầng vị thế (~20 phiên): "
                                   f"**{_pos['name']}** · {_pstate}")
                    else:
                        st.caption(
                            "🕰 Tầng vị thế (~20 phiên): chưa có — tạo bằng "
                            "`python vnstock_train.py --strategy-only --tier position`")
                except TypeError:
                    pass    # vnstock_memory cũ chưa có tier — bỏ qua
                except Exception:
                    pass

                with st.expander("Xem params & code", expanded=False):
                    try:
                        _params = _json.loads(_active.get("params_json") or "{}")
                        st.code(_json.dumps(_params, indent=2, ensure_ascii=False), language="json")
                    except Exception:
                        pass
                    _code = _active.get("code") or ""
                    if _code:
                        st.code(_code[:1500] + ("…" if len(_code) > 1500 else ""), language="python")

                # ── F6: Equity Curve & Trade Analysis ─────────────
                with st.expander("📈 Equity Curve & Phân tích backtest", expanded=False):
                    try:
                        import plotly.graph_objects as _go
                        import numpy as _np

                        _bt_row = _vm.latest_backtest(_active["id"])
                        _bt_metrics = (
                            _json.loads(_bt_row["metrics_json"])
                            if _bt_row and _bt_row.get("metrics_json")
                            else {}
                        )
                        _trades_raw = _bt_metrics.get("trades", [])

                        if not _trades_raw:
                            st.info("Chưa có dữ liệu trades. Chạy training để tạo backtest.")
                        else:
                            _pnls  = [t["pnl"] for t in _trades_raw]
                            _cum   = _np.cumsum(_pnls).tolist()
                            _peak  = _np.maximum.accumulate(_cum).tolist()
                            _dd    = [c - p for c, p in zip(_cum, _peak)]
                            _n     = len(_pnls)
                            _idxs  = list(range(1, _n + 1))

                            _bar_colors = [
                                "#22c55e" if p > 0 else "#ef4444" if p < 0 else "#94a3b8"
                                for p in _pnls
                            ]

                            # Chart 1: PnL bar + equity line
                            _fig1 = _go.Figure()
                            _fig1.add_trace(_go.Bar(
                                x=_idxs, y=_pnls,
                                marker_color=_bar_colors,
                                name="PnL / lệnh (%)",
                                opacity=0.55,
                            ))
                            _fig1.add_trace(_go.Scatter(
                                x=_idxs, y=_cum,
                                mode="lines",
                                line=dict(color="#60a5fa", width=2),
                                name="Equity tích lũy (%)",
                                yaxis="y2",
                            ))
                            _fig1.update_layout(
                                title=f"Equity Curve — {_n} lệnh",
                                yaxis=dict(title="PnL / lệnh (%)", zeroline=True, zerolinecolor="#475569"),
                                yaxis2=dict(
                                    title="Cumulative PnL (%)",
                                    overlaying="y", side="right",
                                    zeroline=True, zerolinecolor="#475569",
                                ),
                                height=300,
                                legend=dict(orientation="h", y=1.12),
                                margin=dict(l=0, r=0, t=45, b=0),
                                plot_bgcolor="#0e1117",
                                paper_bgcolor="#0e1117",
                                font=dict(color="#f1f5f9"),
                            )
                            st.plotly_chart(_fig1, use_container_width=True)

                            # Chart 2: Drawdown
                            _fig2 = _go.Figure()
                            _fig2.add_trace(_go.Scatter(
                                x=_idxs, y=_dd,
                                fill="tozeroy",
                                fillcolor="rgba(239,68,68,0.20)",
                                line=dict(color="#ef4444", width=1.5),
                                name="Drawdown (%)",
                            ))
                            _fig2.update_layout(
                                title="Drawdown",
                                yaxis=dict(title="Drawdown (%)", zeroline=True, zerolinecolor="#475569"),
                                height=180,
                                margin=dict(l=0, r=0, t=40, b=0),
                                plot_bgcolor="#0e1117",
                                paper_bgcolor="#0e1117",
                                font=dict(color="#f1f5f9"),
                            )
                            st.plotly_chart(_fig2, use_container_width=True)

                            # Outcome breakdown metrics
                            _reasons = [t.get("reason", "?") for t in _trades_raw]
                            _r_tp = _reasons.count("tp")
                            _r_sl = _reasons.count("sl")
                            _r_ex = _reasons.count("expire")
                            _max_dd = min(_dd)
                            _final  = _cum[-1]
                            _mc1, _mc2, _mc3, _mc4, _mc5 = st.columns(5)
                            _mc1.metric("🎯 Hit TP",   _r_tp, f"{_r_tp/_n*100:.0f}%")
                            _mc2.metric("🛑 Hit SL",   _r_sl,
                                        f"-{_r_sl/_n*100:.0f}%", delta_color="inverse")
                            _mc3.metric("⏰ Hết hạn",  _r_ex, f"{_r_ex/_n*100:.0f}%")
                            _mc4.metric("Max Drawdown", f"{_max_dd:.1f}%")
                            _mc5.metric("Net Return",   f"{_final:+.1f}%",
                                        delta_color="normal" if _final >= 0 else "inverse")
                    except Exception as _e6:
                        st.caption(f"Equity curve không khả dụng: {_e6}")
            else:
                st.info("Chưa có chiến lược nào. Nhấn **Lite training** để bắt đầu.", icon="ℹ️")

            # Top strategies with enough trades
            if _bests:
                st.markdown("**Top strategies (n_trades ≥ 10)**")
                for _s in _bests:
                    st.write(
                        f"- #{_s['id']} {_s['name']}"
                        f" — exp={_s.get('expectancy', 0):.2f}"
                        f" | win={_s.get('win_rate', 0):.0%}"
                        f" | trades={_s.get('n_trades', 0)}"
                    )

            if _opens:
                st.markdown("**Open recommendations**")
                import pandas as _pd
                from datetime import datetime as _dt_cls
                _df_opens = _pd.DataFrame(_opens)
                # Add % vs entry next to each price target — easier
                # than mental math to gauge risk/reward at a glance.
                _entry = _df_opens["entry_price"].astype(float)
                _tp_pct = (_df_opens["take_profit"].astype(float) / _entry - 1) * 100
                _sl_pct = (_df_opens["cut_loss"].astype(float)    / _entry - 1) * 100
                _df_opens["TP (%)"] = _tp_pct.round(1).map(lambda v: f"{v:+.1f}%")
                _df_opens["SL (%)"] = _sl_pct.round(1).map(lambda v: f"{v:+.1f}%")
                _df_opens["R:R"] = (_tp_pct / _sl_pct.abs().replace(0, _pd.NA)).round(2)

                # Show age + horizon status so user sees what's expired
                def _age_status(row):
                    try:
                        created = _dt_cls.fromisoformat(str(row["created_at"]))
                    except Exception:
                        return "—"
                    age = (_dt_cls.now() - created).days
                    horizon = int(row.get("horizon_days") or 5)
                    # horizon = số PHIÊN; hiển thị theo ngày lịch tương đương
                    # để nhãn "đến hạn" không bật sớm ~30% (vết 19/08).
                    from vnstock_brief import _horizon_calendar_days
                    cal = _horizon_calendar_days(horizon)
                    if age >= cal:
                        return f"🕒 {age}d (đến hạn — bấm Cập nhật)"
                    return f"⏳ {age}/{cal}d ({horizon} phiên)"

                _df_opens["Trạng thái"] = _df_opens.apply(_age_status, axis=1)

                # MTM lãi/lỗ tạm tính (AI-Trader live scoring) —
                # lệnh đang xanh hay đỏ, không phải chờ reconcile.
                _open_cols = ["ticker", "action", "entry_price",
                              "take_profit", "TP (%)",
                              "cut_loss",    "SL (%)", "R:R",
                              "Trạng thái", "created_at"]
                _adv_by_ticker = {}
                try:
                    from vnstock_strategy import (
                        _load_history as _lh,
                        psar_stop_hint as _psh,
                        trailing_stop_hint as _tsh,
                        unrealized_pnl_pct as _upnl,
                    )

                    def _mtm(row):
                        # (giá HT, L/L tạm, ADV20 cp, SL trailing)
                        try:
                            h = _lh(str(row["ticker"]), days=35)
                            if h is None or h.empty:
                                return None, None, None, None
                            last = float(h["close"].iloc[-1])
                            pnl = _upnl(row["entry_price"], last,
                                        row.get("action", "buy"))
                            adv = None
                            try:
                                adv = float(h["volume"].tail(20).mean())
                            except Exception:
                                pass
                            trail = None
                            try:
                                # closes kể từ ngày mở rec → trailing
                                # stop (Lean); rec SELL không áp dụng.
                                # Kết hợp PSAR (quant-trading): lấy
                                # mức CAO hơn = khóa lời chặt hơn.
                                if str(row.get("action", "buy")).lower() != "sell":
                                    _created = str(row["created_at"])[:10]
                                    _closes = h.loc[
                                        h["time"].astype(str).str[:10]
                                        >= _created, "close"].tolist()
                                    trail = _tsh(row["cut_loss"], _closes)
                                    psar = _psh(row["cut_loss"],
                                                h["high"], h["low"],
                                                h["close"])
                                    cands = [x for x in (trail, psar)
                                             if x is not None]
                                    trail = max(cands) if cands else None
                            except Exception:
                                pass
                            return last, pnl, adv, trail
                        except Exception:
                            return None, None, None, None

                    _mtms = [_mtm(r) for _, r in _df_opens.iterrows()]
                    _adv_by_ticker = {
                        str(r["ticker"]): m[2]
                        for (_, r), m in zip(_df_opens.iterrows(), _mtms)
                        if m[2]}
                    _df_opens["Giá HT"] = [m[0] for m in _mtms]
                    _df_opens["L/L tạm"] = [
                        f"{m[1]:+.1f}%" if m[1] is not None else "—"
                        for m in _mtms]
                    _df_opens["SL trailing"] = [
                        f"{m[3]:,.2f}" if m[3] is not None else "—"
                        for m in _mtms]
                    _open_cols.insert(8, "Giá HT")
                    _open_cols.insert(9, "L/L tạm")
                    _open_cols.insert(10, "SL trailing")
                except Exception:
                    pass
                try:
                    from vnstock_strategy import (
                        load_sizing_config as _lsc,
                        suggest_position_size as _sps,
                    )
                    _scfg = _lsc()
                    if _scfg.get("nav_million"):
                        def _kl_hint(row):
                            s = _sps(row["entry_price"], row["cut_loss"],
                                     adv_shares=_adv_by_ticker.get(
                                         str(row["ticker"])))
                            if not s:
                                return "—"
                            _tag = (" (cap TK)" if s.get("capped_adv")
                                    else " (cap)" if s["capped"] else "")
                            return f"{s['qty']:,} cp{_tag}"
                        _df_opens["KL gợi ý"] = _df_opens.apply(_kl_hint, axis=1)
                        _open_cols.insert(8, "KL gợi ý")
                except Exception:
                    pass

                st.dataframe(
                    _df_opens[_open_cols],
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("⚖️ Cấu hình khối lượng gợi ý (risk cố định)",
                                 expanded=False):
                    try:
                        from vnstock_strategy import (
                            load_sizing_config as _lsc2,
                            save_sizing_config as _ssc,
                        )
                        _sc = _lsc2()
                        st.caption(
                            "KL gợi ý = (NAV × %rủi ro) / (entry − SL + phí), "
                            "tròn xuống lô 100, cap % NAV mỗi lệnh + cap "
                            "thanh khoản (% KLGD TB 20 phiên — '(cap TK)'). "
                            "SL trailing = đỉnh close từ ngày mở × 95%, chỉ "
                            "gợi ý — hệ vẫn chấm theo SL gốc. "
                            "Chỉ hiển thị — không tự đặt lệnh. Để NAV = 0 để tắt."
                        )
                        _sz1, _sz2, _sz3, _sz4 = st.columns(4)
                        _nav_in = _sz1.number_input(
                            "NAV (triệu đồng)", min_value=0.0, step=50.0,
                            value=float(_sc.get("nav_million") or 0.0),
                            key="_sizing_nav")
                        _risk_in = _sz2.number_input(
                            "Rủi ro mỗi lệnh (% NAV)", min_value=0.1,
                            max_value=10.0, step=0.5,
                            value=float(_sc.get("risk_pct") or 1.0),
                            key="_sizing_risk")
                        _cap_in = _sz3.number_input(
                            "Tối đa 1 lệnh (% NAV)", min_value=1.0,
                            max_value=100.0, step=5.0,
                            value=float(_sc.get("max_position_pct") or 25.0),
                            key="_sizing_cap")
                        _adv_in = _sz4.number_input(
                            "Cap thanh khoản (% ADV20)", min_value=1.0,
                            max_value=100.0, step=5.0,
                            value=float(_sc.get("max_adv_pct") or 10.0),
                            key="_sizing_adv")
                        if st.button("💾 Lưu cấu hình sizing",
                                     key="_sizing_save"):
                            _ssc(nav_million=_nav_in, risk_pct=_risk_in,
                                 max_position_pct=_cap_in,
                                 max_adv_pct=_adv_in)
                            st.success("Đã lưu — bảng KL gợi ý cập nhật ở lần rerun tới.")
                    except Exception as _e:
                        st.caption(f"⚠ sizing config lỗi: {type(_e).__name__}: {_e}")

                # Reconcile button — close expired recs by walking
                # forward from price history. Same logic as the daily
                # train script's reconcile_recommendations().
                _rc1, _rc2 = st.columns([1, 3])
                with _rc1:
                    if st.button("📊 Cập nhật kết quả",
                                 key="_reconcile_btn",
                                 help="Đóng các khuyến nghị đã quá horizon "
                                      "(walk-forward giá để check TP/SL/expire). "
                                      "Tự động chạy khi `vnstock_train.py --once`."):
                        with st.spinner("⏳ Đang reconcile..."):
                            try:
                                from vnstock_train import reconcile_recommendations as _rec_fn
                                _rc_summary = _rec_fn(verbose=False)
                                st.session_state["_reconcile_result"] = _rc_summary
                            except Exception as _e:
                                st.session_state["_reconcile_result"] = {
                                    "error": f"{type(_e).__name__}: {_e}"
                                }
                        st.rerun()
                with _rc2:
                    _rc_res = st.session_state.get("_reconcile_result")
                    if _rc_res:
                        if _rc_res.get("error"):
                            st.error(f"❌ {_rc_res['error']}")
                        else:
                            st.success(
                                f"✅ Đã đóng **{_rc_res.get('closed', 0)}** rec, "
                                f"còn **{_rc_res.get('still_open', 0)}** đang mở."
                            )

            # ── Closed recommendations + outcome breakdown ─────────
            try:
                _closed = _vm.recent_closed_recommendations(limit=20)
                _dist   = _vm.outcome_distribution()
            except Exception:
                _closed, _dist = [], {}

            # Filter out superseded entries from the visible table —
            # they're administrative closures, not real outcomes.
            _closed_real = [
                c for c in _closed
                if (c.get("hit_target") or "") != "superseded"
            ]

            if _dist or _closed_real:
                st.markdown("**📈 Kết quả khuyến nghị đã đóng**")
                _n_tp = _dist.get("tp", 0)
                _n_sl = _dist.get("sl", 0)
                _n_ex = _dist.get("expire", 0)
                _n_sup = _dist.get("superseded", 0)
                _n_real = _n_tp + _n_sl + _n_ex
                _o1, _o2, _o3, _o4 = st.columns(4)
                _o1.metric("🎯 Hit TP", _n_tp,
                           delta=f"{_n_tp/_n_real*100:.0f}%" if _n_real else None)
                _o2.metric("🛑 Hit SL", _n_sl,
                           delta=f"-{_n_sl/_n_real*100:.0f}%" if _n_real else None,
                           delta_color="inverse")
                _o3.metric("⏰ Hết hạn", _n_ex)
                _o4.metric("🔄 Bị thay thế", _n_sup,
                           help="Đóng khi scan mới ra khuyến nghị thay thế cho cùng mã.")

                if _closed_real:
                    import pandas as _pd
                    _df_cl = _pd.DataFrame(_closed_real)
                    _icon_map = {"tp": "🎯 TP", "sl": "🛑 SL", "expire": "⏰ Hết hạn"}
                    _df_cl["Kết quả"] = _df_cl["hit_target"].map(_icon_map).fillna(_df_cl["hit_target"])
                    _df_cl["P&L %"] = _df_cl["pnl_pct"].astype(float).round(2).map(
                        lambda v: f"{v:+.2f}%" if _pd.notna(v) else "—"
                    )
                    _df_cl["entry_price"] = _df_cl["entry_price"].astype(float).round(0)
                    _df_cl["exit_price"] = _df_cl["exit_price"].astype(float).round(0)
                    with st.expander(
                        f"Xem {len(_closed_real)} khuyến nghị gần đây nhất",
                        expanded=False,
                    ):
                        st.dataframe(
                            _df_cl[[
                                "ticker", "action", "entry_price",
                                "exit_price", "P&L %", "Kết quả",
                                "horizon_days", "created_at", "closed_at",
                            ]],
                            use_container_width=True,
                            hide_index=True,
                        )
                st.caption(
                    "💡 Hệ thống TỰ động đóng rec khi đến hạn (horizon ngày) — "
                    "walk-forward giá để check TP/SL/expire. "
                    "Reconcile chạy tự động mỗi khi gọi `python vnstock_train.py --once`, "
                    "hoặc bấm **📊 Cập nhật kết quả** ở trên để chạy ngay."
                )

            # ── Training result ────────────────────────────────────
            if st.session_state.get("_train_result"):
                _tr = st.session_state["_train_result"]
                if _tr.get("error"):
                    st.error(f"❌ {_tr['error']}")
                else:
                    _sl_r = _tr.get("strategy_loop", {})
                    _msg = (
                        f"✅ **Training xong** — "
                        f"agents={_sl_r.get('agents_run',0)} | "
                        f"mode={_sl_r.get('mode','?')} | "
                        f"n_trades={_tr.get('n_trades','?')} | "
                        f"expectancy={_tr.get('expectancy','?')}"
                    )
                    if _sl_r.get("errors"):
                        st.warning(f"⚠️ Có lỗi: {_sl_r['errors']}")
                    else:
                        st.success(_msg)

            st.divider()
            _train_col1, _train_col2 = st.columns(2)

            def _run_training(lite: bool, mode: str = "auto") -> None:
                """Chỉ train chiến lược — không emit recommendations."""
                try:
                    from vnstock_train import (
                        strategy_loop as _sl_fn,
                        brief_loop as _bl_fn,
                    )
                    _bl_fn(verbose=False)
                    _sl_out = _sl_fn(verbose=False, lite=lite, mode=mode)
                    _nt, _exp = "?", "?"
                    _nf = _vm.get_active_family()
                    if _nf:
                        _nh = _vm.family_history(_nf.get("family_id", ""), limit=1)
                        if _nh:
                            _nt  = _nh[0].get("n_trades", "?")
                            _exp = round(_nh[0].get("expectancy") or 0, 2)
                    st.session_state["_train_result"] = {
                        "strategy_loop": _sl_out,
                        "n_trades": _nt,
                        "expectancy": _exp,
                    }
                except Exception as _e:
                    import traceback as _tb
                    st.session_state["_train_result"] = {
                        "error": f"{type(_e).__name__}: {_e}\n{_tb.format_exc()[-800:]}"
                    }
                st.rerun()

            with _train_col1:
                if st.button("⚡ Lite training (~60-90s)", key="_train_lite",
                             help="17 mã (10 VN30 + 7 VNMID đa ngành), backtest nhanh."):
                    st.session_state["_train_result"] = None
                    with st.spinner("⏳ Đang chạy… (60-90s nếu cần revise code)"):
                        _run_training(lite=True, mode="auto")
            with _train_col2:
                if st.button("🚀 Full training (~15-25 min)", key="_train_full",
                             help="~50 mã (VN30 đủ + 20 VNMID), full walk-forward. CHẬM."):
                    st.session_state["_train_result"] = None
                    with st.spinner("⏳ Đang chạy full training… 15-25 phút"):
                        _run_training(lite=False, mode="auto")

            # Fresh start button — shown when strategy hasn't reached validation threshold
            _cur_nt = 0
            if _active:
                _fh = _vm.family_history(_active.get("family_id", ""), limit=1)
                _cur_nt = (_fh[0].get("n_trades") or 0) if _fh else 0
            if _cur_nt < 10:
                if st.button("🔄 Fresh start (generate chiến lược mới hoàn toàn)",
                             key="_train_fresh",
                             help="Generate code chiến lược hoàn toàn mới. "
                                  "Dùng khi strategy < 10 trades hoặc logic sai."):
                    st.session_state["_train_result"] = None
                    with st.spinner("⏳ Đang generate chiến lược mới… (15-30s API call)"):
                        _run_training(lite=True, mode="fresh")

            st.caption(
                "ℹ️ Lite: 10 VN30 + 7 VNMID = 17 mã, backtest nhanh (~60-90s). "
                "Full: VN30 đủ + 20 VNMID = ~50 mã (~15-25 phút, nên dùng Task Scheduler). "
                "Sau khi train, bấm **Quét tín hiệu** để tìm khuyến nghị."
            )

            # ── Scan recommendations (độc lập với training) ────────
            st.divider()
            st.markdown("**🔍 Quét tín hiệu toàn thị trường**")
            st.caption(
                "Áp chiến lược hiện có lên toàn bộ kho dữ liệu. "
                "Chỉ quét mã có khối lượng trung bình ≥ 100.000 cổ/ngày."
            )

            if st.session_state.get("_scan_result"):
                _sr = st.session_state["_scan_result"]
                if _sr.get("error"):
                    st.error(f"❌ {_sr['error']}")
                elif _sr.get("reason") == "no_validated_strategy":
                    st.warning("⚠️ Chưa có chiến lược validated. Chạy training thêm để đạt ≥ 10 trades.")
                else:
                    _n_recs = _sr.get("n_recs", 0)
                    _diag   = _sr.get("diag", {})
                    if _n_recs:
                        st.success(f"✅ Đã quét **{_sr.get('n_scanned',0)}** mã → **{_n_recs}** khuyến nghị mới")
                    else:
                        st.info(f"ℹ️ Quét **{_sr.get('n_scanned',0)}** mã → 0 khuyến nghị (điều kiện mua chưa kích hoạt hôm nay)")
                    if _diag:
                        _n_err = _diag.get('n_errors', 0)
                        _err_color = "🔴" if _n_err else "🟢"
                        st.caption(
                            f"📊 Không có data: **{_diag.get('n_no_data',0)}** · "
                            f"Dưới 100K vol: **{_diag.get('n_low_vol',0)}** · "
                            f"Chạy được: **{_diag.get('n_executed',0)}** · "
                            f"Hold/Sell: **{_diag.get('n_hold',0)}** · "
                            f"Buy signal: **{_diag.get('n_buy',0)}** · "
                            f"{_err_color} Errors: **{_n_err}**"
                        )
                        _samples = _diag.get('errors_sample') or []
                        if _samples:
                            with st.expander(
                                f"⚠️ {_n_err} mã throw exception — xem mẫu lỗi",
                                expanded=(_diag.get('n_executed', 0) == 0),
                            ):
                                st.caption(
                                    "Strategy code fail silent. Sửa code trong DB "
                                    "(`brief_memory.db` → `strategies.code`) hoặc "
                                    "Fresh start để generate lại."
                                )
                                for s in _samples:
                                    st.code(
                                        f"[{s.get('example_ticker','?')}] "
                                        f"{s.get('error','')}",
                                        language="text",
                                    )

            if st.button("🔍 Quét tín hiệu toàn thị trường", key="_scan_recs",
                         help="Quét toàn bộ kho, lọc vol ≥ 100K cổ/ngày, tối đa 5 recs."):
                st.session_state["_scan_result"] = None
                with st.spinner("⏳ Đang quét… (vài giây đến 1 phút tuỳ kho)"):
                    try:
                        from vnstock_train import _scan_universe as _su_fn
                        from vnstock_strategy import emit_recommendations as _emit_fn
                        _su = _su_fn()
                        _all = _emit_fn(_su, max_recs=5, min_avg_volume=100_000)
                        # Last element is always the _stats sentinel
                        _diag_item = _all[-1] if _all and _all[-1].get("_stats") else {}
                        _real_recs = [r for r in _all if not r.get("_stats")]
                        st.session_state["_scan_result"] = {
                            "n_scanned": len(_su),
                            "n_recs": len(_real_recs),
                            "diag": _diag_item,
                            "reason": _diag_item.get("reason", ""),
                        }
                    except Exception as _e:
                        import traceback as _tb
                        st.session_state["_scan_result"] = {
                            "error": f"{type(_e).__name__}: {_e}\n{_tb.format_exc()[-600:]}"
                        }
                st.rerun()
        except Exception as _e:
            st.caption(f"Strategy panel disabled: {type(_e).__name__}: {_e}")

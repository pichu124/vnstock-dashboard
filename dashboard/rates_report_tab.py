"""dashboard/rates_report_tab.py — sub-tab "📄 Báo cáo tuần" trong tab Tin tức.

Thuần HIỂN THỊ trên cache sẵn có (mirror macro_tab — KHÔNG fetch/LLM). Render
báo cáo tuần lãi suất & tiền tệ từ `vnstock_rates_report` (bảng lãi suất +
đường cong TPCP SVG + gauge + narrative) inline + nút tải HTML + nút đẩy
Telegram. Lazy-import streamlit trong render → smoke test import không cần st.
"""
from __future__ import annotations


def render_rates_report_subtab() -> None:
    import streamlit as st
    try:
        import vnstock_rates_report as rr
    except ImportError:
        st.error("Không tìm thấy `vnstock_rates_report.py`.")
        return

    st.markdown("##### 📄 Báo cáo tuần lãi suất & tiền tệ")
    st.caption("Sinh từ cache dashboard (macro + HNX + SBV) — zero fetch, "
               "không dự đoán tương lai. Refresh dữ liệu qua `run.py macro`.")

    try:
        data = rr.build_report_data()
    except Exception as e:                                    # noqa
        st.error(f"Không dựng được báo cáo: {e}")
        return
    if not data.get("rates") and not data.get("curve"):
        st.info("Cache vĩ mô/HNX rỗng — chạy `python run.py macro` để có dữ liệu.")
        return

    html = rr.render_html(data)
    try:
        import streamlit.components.v1 as components
        components.html(html, height=680, scrolling=True)
    except Exception:
        st.html(html)                                        # fallback

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Tải HTML", data=html,
                           file_name=f"bao_cao_lai_suat_{data['as_of']}.html",
                           mime="text/html", use_container_width=True)
    with c2:
        # Gửi ngay vào group ⇒ phải tick; gửi xong đổi key để ô tự bỏ tick.
        n = st.session_state.get("_rr_push_n", 0)
        sure = st.checkbox("Tôi chắc chắn gửi vào group Telegram", key=f"_rr_push_sure_{n}")
        if st.button("📤 Đẩy tóm tắt lên Telegram", use_container_width=True,
                     key="_rr_push", disabled=not sure) and sure:
            st.session_state["_rr_push_n"] = n + 1
            try:
                from vnstock_telegram import push_rates_weekly
                res = push_rates_weekly()
                if res.get("ok"):
                    st.success("Đã đẩy tóm tắt tuần lên Telegram.")
                else:
                    st.warning(f"Không đẩy được: {res.get('error', 'lỗi')}")
            except Exception as e:                            # noqa
                st.warning(f"Không đẩy được: {e}")

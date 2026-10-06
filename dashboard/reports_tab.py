"""dashboard/reports_tab.py — sub-tab "📚 Báo cáo" bên trong tab Tin tức (P5).

UI mỏng trên vnstock_reports (P2) + vnstock_report_digest (P3):
  * Ingest: upload PDF / dán URL / dán text — dedup sha256 nên Streamlit rerun
    không nhân bản (thiết kế P2); metadata report_date + source BẮT BUỘC để
    báo cáo vào phân tích, thiếu thì bổ sung bằng form bên dưới.
  * Digest: nút gọi LLM CÓ CHỦ ĐÍCH (1 call/báo cáo, chỉ báo cáo chưa có
    digest) — đây là chỗ DUY NHẤT của tab gọi LLM; mọi phần còn lại đọc cache.
  * Thư viện + digest + consensus: thuần hiển thị.

Streamlit lazy-import trong render (mirror money_flow_tab) để module import
được trong tests không cần streamlit.
"""
from __future__ import annotations

_STATUS = {"ok": "✅ vào phân tích", "meta": "📥 thiếu metadata",
           "scan": "🖼 không trích được chữ (scan/ảnh)"}   # PDF lẫn DOCX (04/10)


def _row_status(rp, rec: dict) -> str:
    if rp.in_analysis(rec):
        return _STATUS["ok"]
    if rec.get("no_text_layer"):
        return _STATUS["scan"]
    return _STATUS["meta"]


def render_reports_subtab() -> None:
    import streamlit as st
    try:
        import vnstock_reports as rp
    except ImportError:
        st.error("Không tìm thấy `vnstock_reports.py`.")
        return

    _render_ingest(st, rp)
    _render_library(st, rp)
    _render_digest(st, rp)


def _render_ingest(st, rp) -> None:
    st.markdown("##### 📥 Thêm báo cáo")
    st.caption("Metadata **ngày báo cáo + nguồn** là BẮT BUỘC để báo cáo vào "
               "phân tích — thiếu thì báo cáo chỉ nằm thư viện, bổ sung sau ở "
               "form dưới. Upload trùng nội dung không nhân bản (dedup sha256).")
    c1, c2 = st.columns(2)
    source = c1.text_input("Nguồn (CTCK/chuyên gia)", key="_rp_source")
    report_date = c2.text_input("Ngày báo cáo (YYYY-MM-DD)", key="_rp_date")
    title = st.text_input("Tiêu đề (tùy chọn)", key="_rp_title")
    meta = {"source": source or None, "report_date": report_date or None,
            "title": title or None}

    up = st.file_uploader("Upload báo cáo (PDF/DOCX)", type=["pdf", "docx"],
                          key="_rp_pdf")
    if up is not None and st.button("➕ Thêm file vào thư viện", key="_rp_add_pdf"):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / (up.name or "bao_cao.pdf")
            p.write_bytes(up.getvalue())
            rec = rp.add_pdf(p, **meta)
        _ingest_feedback(st, rp, rec)

    url = st.text_input("… hoặc dán URL báo cáo (fetch qua Jina Reader — cần mạng)",
                        key="_rp_url")
    if url and st.button("➕ Thêm từ URL", key="_rp_add_url"):
        _ingest_feedback(st, rp, rp.add_url(url, **meta))

    text = st.text_area("… hoặc dán thẳng nội dung báo cáo", key="_rp_text",
                        height=120)
    if text.strip() and st.button("➕ Thêm từ text", key="_rp_add_text"):
        _ingest_feedback(st, rp, rp.add_text(text, **meta))


def _ingest_feedback(st, rp, rec) -> None:
    if rec is None:
        st.error("Không thêm được — xem log terminal (URL bị chặn mạng / file rỗng?).")
        return
    st.success(f"Đã vào thư viện: `{rec['id']}` — {_row_status(rp, rec)}")
    if rec.get("no_text_layer"):
        st.info("File toàn ảnh/scan — chọn báo cáo này ở **Thư viện** bên dưới rồi "
                "bấm **👁 Cho Claude đọc ảnh**.")


def _render_library(st, rp) -> None:
    st.markdown("##### 📚 Thư viện")
    reports = rp.list_reports()
    if not reports:
        st.info("Thư viện trống — thêm báo cáo ở trên hoặc CLI "
                "`python vnstock_reports.py --add <pdf> --source X --report-date Y`.")
        return
    import pandas as pd
    st.dataframe(pd.DataFrame([{
        "ID": r["id"], "Ngày BC": r.get("report_date") or "—",
        "Nguồn": r.get("source") or "—",
        "Tiêu đề": r.get("title") or r.get("url") or "—",
        "Loại": r.get("kind"), "Ký tự": r.get("chars", 0),
        "Đọc ảnh": "👁" if r.get("text_via") else "",
        "Trạng thái": _row_status(rp, r),
        "Digest": "🧠" if r.get("digest") else "—",
    } for r in reports]), hide_index=True, use_container_width=True)

    # Bổ sung metadata / xóa — cho báo cáo đã ingest
    ids = [r["id"] for r in reports]
    rid = st.selectbox("Chọn báo cáo", options=ids, key="_rp_sel",
                       format_func=lambda i: next(
                           (f"{i} · {r.get('source') or '?'} · "
                            f"{r.get('report_date') or 'thiếu ngày'}"
                            for r in reports if r["id"] == i), i))
    c1, c2, c3 = st.columns([2, 2, 1])
    new_src = c1.text_input("Sửa nguồn", key="_rp_fix_src")
    new_date = c2.text_input("Sửa ngày (YYYY-MM-DD)", key="_rp_fix_date")
    if (new_src or new_date) and c3.button("💾 Lưu meta", key="_rp_save_meta"):
        rp.set_meta(rid, source=new_src or None, report_date=new_date or None)
        st.rerun()
    _render_vision(st, rp, next((r for r in reports if r["id"] == rid), None))
    if st.button("🗑 Xóa báo cáo đã chọn", key="_rp_remove"):
        rp.remove(rid)
        st.rerun()


def _render_vision(st, rp, rec) -> None:
    """04/10: báo cáo 🖼 (PDF scan / DOCX toàn ảnh) — Claude Code xem ảnh, chép
    thành text rồi báo cáo đi tiếp đường digest. Gọi CÓ CHỦ ĐÍCH, như 🧠."""
    if not rec or not rec.get("no_text_layer") or rp.original_path(rec["id"]) is None:
        return
    st.caption("🖼 Báo cáo này không có chữ trích được — Claude Code có thể xem từng "
               "ảnh/trang và chép lại (vài phút, tốn lượt Claude Code).")
    if not st.button("👁 Cho Claude đọc ảnh", key="_rp_vision"):
        return
    import vnstock_claude_cli as vcc
    import vnstock_report_vision as rv
    vcc.reset_dead_memo()        # bấm tay = muốn thử lại dù lượt trước treo
    logs: list[str] = []
    with st.spinner("Claude đang đọc ảnh…"):
        res = rv.read_report(rec["id"], log=logs.append)
    if res["ok"]:
        st.toast(f"👁 Đã chép {res['chars']:,} ký tự từ {res['n_units']} ảnh/trang "
                   f"(${res['cost_usd']:,.2f}).")
        st.rerun()
    st.error(f"Không đọc được: {res['error']}")
    if logs:
        st.code("\n".join(logs))


def _render_digest(st, rp) -> None:
    st.markdown("##### 🧠 Digest & consensus")
    try:
        import vnstock_report_digest as dg
    except ImportError:
        st.error("Không tìm thấy `vnstock_report_digest.py`.")
        return

    pending = [r for r in rp.load_for_analysis() if not r.get("digest")]
    if pending:
        st.caption(f"{len(pending)} báo cáo đủ điều kiện chưa có digest.")
        if st.button(f"🧠 Digest {len(pending)} báo cáo (gọi LLM — Claude Code "
                     "khi engine=claude, rồi key Claude/GPT, free fallback)", key="_rp_digest"):
            done = dg.refresh()
            st.success(f"Đã digest {len(done)} báo cáo.") if done else \
                st.error("Không digest được — kiểm tra key .env / mạng.")
            st.rerun()
    else:
        # 04/10: user tìm nút không thấy — nút chỉ hiện khi CÓ báo cáo chờ.
        st.caption("Không có báo cáo nào chờ digest — nút 🧠 chỉ hiện khi có báo cáo "
                   "✅ vào phân tích mà chưa digest (đủ ngày + nguồn + trích được chữ). "
                   "Chấm lại bản cũ: `python vnstock_report_digest.py --refresh --redigest`.")

    # Digest của báo cáo đã chọn (đọc cache)
    rid = st.session_state.get("_rp_sel")
    rec = next((r for r in rp.list_reports() if r["id"] == rid), None)
    if rec and rec.get("digest"):
        d = rec["digest"]
        seen = d.get("chars_seen")
        cut = (f", ⚠ chỉ đọc {seen:,}/{rec.get('chars', 0):,} ký tự"
               if isinstance(seen, int) and seen < rec.get("chars", 0) else "")
        st.markdown(f"**Tóm tắt** ({rec.get('source')}, {rec.get('report_date')}"
                    f", via {d.get('provider')}{cut}): {d.get('tom_tat')}")
        st.markdown("**Stance:** " + " · ".join(
            f"{cls} {v:+d}" for cls, v in (d.get("stance") or {}).items()))
        for c in d.get("claims") or []:
            flag = (" — ⚠ LỆCH registry "
                    f"({c.get('registry_value')}, as_of {c.get('registry_as_of')})"
                    if c.get("mismatch") else "")
            st.caption(f"• {c.get('key')}: {c.get('value')} {c.get('unit', '')} "
                       f"({c.get('period', '?')}) — {c.get('text', '')}{flag}")
        if d.get("risks"):
            st.caption("Rủi ro: " + " · ".join(d["risks"]))

    c = dg.consensus()
    if c:
        lab = {0: "không tilt", -1: "tilt −1 band (tấn công hơn)",
               1: "tilt +1 band (phòng thủ hơn)"}[c["tilt"]]
        st.info(f"🧭 Consensus {c['n_reports']} báo cáo: stance Cổ phiếu "
                f"{c['stance']['Cổ phiếu']:+.2f} → **{lab}** "
                f"(decay tuổi: đủ trọng số ≤30 ngày, về 0 ở 90 ngày)")

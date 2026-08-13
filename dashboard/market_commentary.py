"""Sinh "🧭 Nhận định tổng quan thị trường" — chữ tiếng Việt USER ĐỌC.

Tách khỏi `dashboard/market_tab.py` (12/08, mục ④ audit 06/08). Đây là 220
dòng SINH CHỮ cho user mà trước giờ chưa có lấy một test, vì nó là closure
lồng trong hàm render 2.544 dòng và còn bắt `st.session_state` + `idx_df` qua
closure. Nay hai thứ đó thành THAM SỐ, hàm hết dính Streamlit.

Chia ba tầng đúng ba mục nó vốn sinh ra:

* `index_strength_lines` — sức mạnh VNINDEX/VN30 (thuần, chỉ pandas)
* `breadth_lines`        — sức khỏe thị trường theo breadth (thuần, chỉ dict)
* `quant_lines`          — chấm điểm ngành/mã (gọi `vnstock_market_analyzer`)

`build_commentary` ghép ba tầng. Tầng 3 bọc `try/except` rộng CÓ CHỦ Ý: quant
score hỏng thì hai tầng đầu vẫn phải hiện — mất nhận định vì một module phụ
là đánh đổi tệ.

Ngưỡng đặt tên rõ ở đầu file: chúng là NHẬN ĐỊNH gửi tới user, không phải
hằng số kỹ thuật; sửa số ở đây là đổi lời khuyên.
"""
from __future__ import annotations

# Xu hướng chỉ số theo TB %/phiên của 5 phiên gần nhất
_TREND_STRONG_UP = 0.3        # trên mức này: "tăng tích cực"
_TREND_STRONG_DOWN = -0.3     # dưới mức này: "giảm rõ rệt"
_TREND_LOOKBACK = 5

# Breadth
_MA200_BROAD_UPTREND = 50     # % mã trên MA200
_MA200_MIXED = 30
_AD_DEMAND = 1.2              # A/D ratio
_AD_SUPPLY = 0.8
_RSI_OVERSOLD_WIDE = 50       # số mã RSI<30 đủ rộng để đáng nhắc
_RSI_OVERBOUGHT_WIDE = 30
_NET_NEW_HIGHS_STRONG = 10

_INDEXES = ("VNINDEX", "VN30")


def index_strength_lines(idx_data) -> list:
    """Mục 1 — sức mạnh chung. Không có data → chỉ trả tiêu đề (không bịa)."""
    lines = ["**📊 Sức mạnh chung**"]
    if idx_data is None or idx_data.empty:
        return lines

    for idx_name in _INDEXES:
        chg_col = f"{idx_name}_chg"
        if chg_col not in idx_data.columns:
            continue
        recent = idx_data[chg_col].dropna().head(_TREND_LOOKBACK)
        avg_chg = recent.mean()
        up_days = (recent > 0).sum()
        last_close = (idx_data[idx_name].dropna().iloc[0]
                      if idx_name in idx_data.columns else None)
        close_str = f" ({last_close:,.0f})" if last_close else ""

        if avg_chg > _TREND_STRONG_UP:
            trend, icon = "tăng tích cực", "🟢"
        elif avg_chg > 0:
            trend, icon = "đi ngang thiên tăng", "🟡"
        elif avg_chg > _TREND_STRONG_DOWN:
            trend, icon = "đi ngang thiên giảm", "🟠"
        else:
            trend, icon = "giảm rõ rệt", "🔴"

        lines.append(f"- {icon} **{idx_name}**{close_str}: {trend} — "
                     f"{_TREND_LOOKBACK} phiên gần nhất {up_days}/{_TREND_LOOKBACK} tăng, "
                     f"TB {avg_chg:+.2f}%/phiên")
    return lines


def breadth_lines(breadth_data) -> list:
    """Mục 2 — sức khỏe thị trường. Không có breadth → RỖNG, không in tiêu đề
    trống (tiêu đề không kèm nội dung khiến user tưởng data về 0)."""
    if not breadth_data:
        return []

    pct200 = breadth_data["above_ma200_pct"]
    ad = breadth_data["ad_ratio"]
    ov = breadth_data["rsi_oversold"]
    ob = breadth_data["rsi_overbought"]
    nnh = breadth_data["net_new_highs"]

    lines = ["", "**🌡️ Sức khỏe thị trường**"]
    if pct200 > _MA200_BROAD_UPTREND:
        lines.append(f"- 🟢 {pct200:.0f}% mã trên MA200 — thị trường trong xu hướng tăng rộng")
    elif pct200 > _MA200_MIXED:
        lines.append(f"- 🟡 {pct200:.0f}% mã trên MA200 — thị trường phân hóa, chọn lọc")
    else:
        lines.append(f"- 🔴 Chỉ {pct200:.0f}% mã trên MA200 — đa số cổ phiếu trong xu hướng giảm")

    if ad > _AD_DEMAND:
        lines.append(f"- A/D ratio {ad:.2f} — lực cầu chiếm ưu thế")
    elif ad < _AD_SUPPLY:
        lines.append(f"- A/D ratio {ad:.2f} — lực bán áp đảo")

    if ov > _RSI_OVERSOLD_WIDE:
        lines.append(f"- ⚠️ {ov} mã RSI<30 — vùng quá bán rộng, cơ hội nếu có tín hiệu đảo chiều")
    if ob > _RSI_OVERBOUGHT_WIDE:
        lines.append(f"- ⚠️ {ob} mã RSI>70 — nhiều mã quá mua, cẩn trọng đuổi giá")

    if nnh > _NET_NEW_HIGHS_STRONG:
        lines.append(f"- {nnh:+d} net new highs — thị trường tạo đỉnh mới tốt")
    elif nnh < -_NET_NEW_HIGHS_STRONG:
        lines.append(f"- {nnh:+d} net new highs — nhiều mã tạo đáy mới hơn đỉnh mới")
    return lines


def _bullet(line: str) -> str:
    """`format_row` trả cả dòng chính lẫn dòng phụ (thụt lề sẵn) — chỉ dòng
    chính mới gắn dấu đầu dòng."""
    return line if line.startswith("  ") else f"- {line}"


def _sector_block(title: str, rows, *, positive_only=False, negative_only=False,
                  format_row=None) -> list:
    """Một khối "ngành ..." trong nhận định.

    `positive_only`/`negative_only` DỪNG ở phần tử đầu tiên sai dấu — danh sách
    đã sắp xếp nên dừng sớm đúng hơn là lọc.

    Tiêu đề in RA TRƯỚC vòng lặp: giữ NGUYÊN hành vi bản gốc, kể cả cái wart
    "thị trường xấu toàn tập → tiêu đề 🎯 không có dòng nào bên dưới". Đổi
    output nhìn thấy được trong lúc refactor là cách nhanh nhất làm refactor
    mất tin cậy — muốn sửa wart thì sửa RIÊNG, có test đi kèm.
    """
    if not rows:
        return []
    out = ["", title]
    for row in rows:
        comp = row.get("composite", 0)
        if positive_only and comp <= 0:
            break
        if negative_only and comp >= 0:
            break
        out.extend(_bullet(ln) for ln in format_row(row, name_col="Ngành"))
    return out


def quant_lines(mkt_data, breadth_data, idx_long=None, tick_data=None) -> list:
    """Mục 3 — chấm điểm ngành + mã dẫn dắt/yếu nhất.

    `idx_long` (90 phiên chỉ số) và `tick_data` (bảng mã) trước đây lấy qua
    closure / `st.session_state`; nay là THAM SỐ nên hàm test được.
    """
    if mkt_data is None or mkt_data.empty or "Giá 1M %" not in mkt_data.columns:
        return []

    lines: list = []
    try:
        from vnstock_market_analyzer import (
            build_preset_sets, compute_index_returns, compute_scores, format_row,
            load_quarantine_tickers, load_recent_exdiv, market_regime, rank,
            session_timing_signal,
        )
        # Preset screener cho lớp phủ kỹ thuật ở cấp mã
        try:
            from vnstock_dashboard import load_screener_results
            preset_sets = build_preset_sets(load_screener_results())
        except Exception:
            preset_sets = None

        idx_ret = None
        try:
            if idx_long is not None and not idx_long.empty:
                idx_ret = compute_index_returns(idx_long, index_col="VNINDEX")
        except Exception:
            pass

        quar_set = load_quarantine_tickers()
        exdiv_map = load_recent_exdiv(days_back=7)

        scores = compute_scores(mkt_data, index_returns=idx_ret, exdiv_map=exdiv_map)
        regime = market_regime(scores, breadth_data)
        ranked = rank(mkt_data, scores, n_top=5, n_bot=5,
                      name_col="Ngành", quarantined=quar_set)

        lines.append("")
        lines.append(f"**🧠 Quant regime: {regime['regime']}**  · "
                     f"conviction `{regime['conviction']:+.2f}` · {regime['detail']}")
        if idx_ret:
            lines.append(f"  · **VNINDEX benchmark**: "
                         f"1T `{idx_ret['1T']:+.1f}%` · "
                         f"1M `{idx_ret['1M']:+.1f}%` · "
                         f"3M `{idx_ret['3M']:+.1f}%` "
                         f"— alpha dương = outperform")

        lines.extend(_session_timing_lines(session_timing_signal))

        lines.extend(_sector_block("**🎯 Ngành đáng quan tâm (composite cao nhất)**",
                                   ranked["top"], positive_only=True, format_row=format_row))
        lines.extend(_sector_block("**🔄 Sector rotation: ngành đang ấm lên (alpha 1M > 3M)**",
                                   ranked.get("rotation"), format_row=format_row))
        lines.extend(_sector_block("**🕵️ Stealth watch (tín hiệu ẩn, composite chưa mạnh)**",
                                   ranked["stealth"], format_row=format_row))
        lines.extend(_sector_block("**⚠️ Distribution watch (giá tăng nhưng dòng tiền thoát)**",
                                   ranked["distribution"], format_row=format_row))
        lines.extend(_sector_block("**⛔ Ngành nên tránh (composite thấp nhất)**",
                                   ranked["avoid"], negative_only=True, format_row=format_row))

        lines.extend(_ticker_lines(ranked, tick_data, compute_scores, rank,
                                   preset_sets, idx_ret, exdiv_map, quar_set))
    except Exception as e:
        # Rộng CÓ CHỦ Ý: quant hỏng thì mục 1+2 vẫn phải tới tay user.
        lines.append("")
        lines.append(f"⚠️ Không tính được quant score: `{e}`")
    return lines


def _session_timing_lines(session_timing_signal) -> list:
    """Tín hiệu institutional-vs-retail của phiên hôm nay. Không có phiên hôm
    nay (cuối tuần, chưa chạy stats) → im lặng, không phải lỗi."""
    try:
        from datetime import date as _date

        from vnstock_session_stats import load_session_stats_history
        hist = load_session_stats_history()
        today = hist.get(_date.today().isoformat())
        if not today:
            return []
        sig = session_timing_signal(today, hist, index_name="VNINDEX")
        if sig["signal"] == "N/A":
            return []
        return [f"  · **Session timing**: {sig['signal']} — {sig['detail']}"]
    except Exception:
        return []


def _ticker_lines(ranked, tick_data, compute_scores, rank,
                  preset_sets, idx_ret, exdiv_map, quar_set) -> list:
    """Mã dẫn dắt trong 3 ngành top + mã yếu nhất trong 2 ngành tệ nhất."""
    if tick_data is None or tick_data.empty or "Ngành" not in tick_data.columns:
        return []

    def _picks(sector_name, *, top):
        # Cùng lý do như drill-down bảng ngành: nhóm tuỳ biến ("Họ VIN", "Họ M")
        # không nằm trong cột `Ngành` của bảng mã, phải lọc theo danh sách mã.
        from vnstock_sectors import rows_for_sector
        sub = rows_for_sector(tick_data, sector_name).copy()
        if sub.empty:
            return []
        t_scores = compute_scores(sub, presets=preset_sets,
                                  index_returns=idx_ret, exdiv_map=exdiv_map)
        t_ranked = rank(sub, t_scores, n_top=3 if top else 0, n_bot=0 if top else 3,
                        name_col="Mã", quarantined=quar_set)
        out = []
        for tr in t_ranked["top" if top else "avoid"]:
            comp = tr.get("composite", 0)
            if (top and comp <= 0) or (not top and comp >= 0):
                continue
            flag = " 🚨" if (top and tr.get("red_flags")) else ""
            out.append(f"**{tr.get('Mã', '?')}** (`{comp:+.2f}`){flag}")
        return out

    # Tiêu đề in trước vòng lặp — giữ nguyên hành vi bản gốc (xem `_sector_block`).
    lines: list = []
    if ranked["top"]:
        lines += ["", "**⭐ Mã dẫn dắt trong ngành top (quant-ranked)**"]
        for sec_row in ranked["top"][:3]:
            if sec_row.get("composite", 0) <= 0:
                continue
            picks = _picks(sec_row["Ngành"], top=True)
            if picks:
                lines.append(f"- **{sec_row['Ngành']}**: " + " · ".join(picks))

    bad_secs = [r for r in ranked["avoid"] if r.get("composite", 0) < 0][:2]
    if bad_secs:
        lines += ["", "**💀 Mã yếu nhất trong ngành tệ nhất**"]
        for sec_row in bad_secs:
            flops = _picks(sec_row["Ngành"], top=False)
            if flops:
                lines.append(f"- **{sec_row['Ngành']}**: " + " · ".join(flops))
    return lines


def build_commentary(breadth_data, mkt_data, idx_data,
                     idx_long=None, tick_data=None) -> str:
    """Ghép cả ba mục thành markdown cho `st.markdown`."""
    lines = index_strength_lines(idx_data)
    lines += breadth_lines(breadth_data)
    lines += quant_lines(mkt_data, breadth_data,
                         idx_long=idx_long, tick_data=tick_data)
    return "\n".join(lines)

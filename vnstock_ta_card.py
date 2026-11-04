"""Thẻ kỹ thuật 3 khung (PTKT P2a) — LÕI THUẦN, không I/O.

Đặc tả: `docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §5 (dữ kiện thẻ), §10c (ba khung), §10d ("code nói
dữ kiện, model nói ý nghĩa"), §12 (dài hạn từng mã = TĂNG / ĐI NGANG / GIẢM, từ vựng giá), §15 (thủng
S1 là tín hiệu DUY NHẤT đo được có lợi thế), §16 (RSI > 70 = "đà mạnh", KHÔNG hàm ý cảnh báo: mã RSI
Wilder > 70 vượt VN-Index +1,75% T+20 giai đoạn 05–10/2026 — số đo MỘT giai đoạn).

CHƯA nối vào brief/prompt/guard/dashboard. Bản mẫu trên kho thật: `scripts/sample_ta_card.py`.

    card = ta_card(daily, sr={"support_1": …, "support_2": …, "resistance_1": …}, label="FPT")
    card_lines(card)   # VN-Index: nhiều dòng
    card_line(card)    # từng mã: 1 dòng nén

`daily` = DataFrame bar ngày `close` (+ `open/high/low`, `volume`, `time` nếu có). Thẻ chỉ đọc bar
có trong `daily`: bar CUỐI là phiên đánh giá — muốn đánh giá một phiên quá khứ thì cắt `daily` tới
phiên đó trước khi gọi. Thiếu bar cho chỉ báo nào thì trường đó None và dòng in `NO_DATA`; không ném.

Từ vựng in ra là các hằng ở đầu module (guard P3 sẽ so khớp đúng chuỗi). Ngưỡng có tên ``*_PCT``
CHƯA hiệu chỉnh — P2 đo bằng `ta-score` T4 rồi mới chốt.
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import pandas as pd

import vnstock_horizons as hz
from vnstock_brief_canon import RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_STRONG, RSI_WEAK
from vnstock_indicators import atr, ema, rsi_default, sma
from vnstock_ta_score import VOL_MULT

# ── Từ vựng cố định ──────────────────────────────────────────────────────
DIR_UP, DIR_FLAT, DIR_DOWN = (hz.MEDIUM_LABEL[hz.TANG], hz.MEDIUM_LABEL[hz.DI_NGANG],
                              hz.MEDIUM_LABEL[hz.GIAM])          # TĂNG / ĐI NGANG / GIẢM
RSI_MOMENTUM, RSI_STRONG_LBL, RSI_NEUTRAL, RSI_WEAK_LBL, RSI_OVERSOLD_LBL = (
    "đà mạnh", "mạnh", "trung tính", "yếu", "quá bán")
VOL_YES, VOL_NO = "xác nhận", "không xác nhận"
MACD_ABOVE, MACD_BELOW = "trên tín hiệu", "dưới tín hiệu"
CROSS_UP, CROSS_DOWN = "cắt lên", "cắt xuống"
NO_DATA = "chưa đủ dữ liệu"
NO_DATES = "không có cột ngày"
BROKE_SUPPORT_TEXT = "thủng hỗ trợ — nguy cơ về S2"

CONFLICT_BREAKOUT_NO_VOL = "giá vượt MA20 mà KL không xác nhận"
CONFLICT_SHORT_UP_MEDIUM_DOWN = "ngắn hạn tăng mà trung hạn giảm"
CONFLICT_SHORT_DOWN_MEDIUM_UP = "ngắn hạn giảm mà trung hạn tăng"
CONFLICT_RSI_STRONG_BELOW_SMA200 = "RSI đà mạnh mà giá dưới SMA200"
CONFLICT_MACD_UP_BELOW_MA20 = "MACD mới cắt lên mà giá dưới MA20"
CONFLICT_MACD_DOWN_ABOVE_MA20 = "MACD mới cắt xuống mà giá trên MA20"

# ── Tham số (chưa hiệu chỉnh — P2 đo bằng ta-score T4) ──────────────────
MA_SHORT = 20
SHORT_SLOPE_BARS = 5
SHORT_SLOPE_FLAT_PCT = 0.3       # |độ dốc MA20 5 phiên| ≤ 0,3% là phẳng
MA_LONG = 200
LONG_SLOPE_BARS = 20
LONG_SLOPE_FLAT_PCT = 0.5        # |độ dốc SMA200 20 phiên| ≤ 0,5% (~6%/năm) là phẳng
WEEKS52_BARS = 250
VOL_AVG_BARS = 20                # TB20 = 20 phiên TRƯỚC phiên đánh giá, như ta-score T2
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
MACD_CROSS_BARS = 3              # "mới cắt" = histogram đổi dấu trong 3 phiên gần nhất
ATR_BARS = 14


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _last(s: pd.Series, back: int = 0) -> float | None:
    return _num(s.iloc[-1 - back]) if len(s) > back else None


def _pct(a: float | None, b: float | None) -> float | None:
    return (a / b - 1) * 100 if a is not None and b else None


def rsi_label(rsi: float | None) -> str | None:
    """≥70 đà mạnh · [60, 70) mạnh · [40, 60) trung tính · [30, 40) yếu · <30 quá bán.
    "Đà mạnh" KHÔNG phải cảnh báo quá mua (§16)."""
    rsi = _num(rsi)
    if rsi is None:
        return None
    if rsi >= RSI_OVERBOUGHT:
        return RSI_MOMENTUM
    if rsi >= RSI_STRONG:
        return RSI_STRONG_LBL
    if rsi >= RSI_WEAK:
        return RSI_NEUTRAL
    if rsi >= RSI_OVERSOLD:
        return RSI_WEAK_LBL
    return RSI_OVERSOLD_LBL


def direction(close: float | None, ma: float | None, slope_pct: float | None,
              flat_pct: float) -> str | None:
    """TĂNG = giá > MA và MA dốc lên > ``flat_pct``%; GIẢM = giá < MA và MA dốc xuống quá
    ``flat_pct``%; còn lại ĐI NGANG. Thiếu số nào ⇒ None. Dùng cho ngắn hạn (MA20, 5 phiên)
    và dài hạn (SMA200, 20 phiên)."""
    if close is None or ma is None or slope_pct is None:
        return None
    if close > ma and slope_pct > flat_pct:
        return DIR_UP
    if close < ma and slope_pct < -flat_pct:
        return DIR_DOWN
    return DIR_FLAT


def _prep(daily: pd.DataFrame | None) -> pd.DataFrame:
    if daily is None or not isinstance(daily, pd.DataFrame) or "close" not in daily.columns:
        return pd.DataFrame(columns=["close"])
    d = daily.copy()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    d = d[d["close"] > 0]
    if "time" in d.columns:
        d["time"] = pd.to_datetime(d["time"]).dt.normalize()
        d = d.sort_values("time").drop_duplicates("time", keep="last")
    for c in ("open", "high", "low"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(d["close"]) if c in d.columns \
            else d["close"]
    return d.reset_index(drop=True)


def _short(d: pd.DataFrame) -> dict:
    c = d["close"]
    close = _last(c)
    ma = sma(c, MA_SHORT)
    ma20, ma20_prev = _last(ma), _last(ma, 1)
    slope = _pct(ma20, _last(ma, SHORT_SLOPE_BARS))
    prev_close = _last(c, 1)
    crossed_up = (None if ma20 is None or ma20_prev is None or prev_close is None
                  else prev_close <= ma20_prev and close > ma20)
    rsi = _last(rsi_default(c))
    out = {"ma20": ma20, "ma20_dist_pct": _pct(close, ma20), "ma20_slope_pct": slope,
           "crossed_ma20_up": crossed_up, "rsi": rsi, "rsi_label": rsi_label(rsi),
           "label": direction(close, ma20, slope, SHORT_SLOPE_FLAT_PCT)}
    out.update(_macd(c))
    out.update(_volume(d))
    return out


def _macd(c: pd.Series) -> dict:
    line = ema(c, MACD_FAST) - ema(c, MACD_SLOW)
    hist = (line - line.ewm(span=MACD_SIGNAL, adjust=False, min_periods=MACD_SIGNAL).mean()
            ).to_numpy(dtype=float)
    out = {"macd_above": None, "macd_cross": None, "macd_cross_ago": None}
    if not len(hist) or not np.isfinite(hist[-1]):
        return out
    out["macd_above"] = bool(hist[-1] > 0)
    for ago in range(MACD_CROSS_BARS):
        i = len(hist) - 1 - ago
        if i < 1 or not np.isfinite(hist[i - 1]):
            break
        if hist[i] > 0 >= hist[i - 1]:
            out.update(macd_cross=CROSS_UP, macd_cross_ago=ago)
            break
        if hist[i] < 0 <= hist[i - 1]:
            out.update(macd_cross=CROSS_DOWN, macd_cross_ago=ago)
            break
    return out


def _volume(d: pd.DataFrame) -> dict:
    out = {"vol_ratio": None, "vol_confirmed": None}
    if "volume" not in d.columns or len(d) <= VOL_AVG_BARS:
        return out
    v = pd.to_numeric(d["volume"], errors="coerce").to_numpy(dtype=float)
    prev = v[-1 - VOL_AVG_BARS:-1]
    if not np.isfinite(v[-1]) or v[-1] <= 0 or not np.isfinite(prev).all() or (prev <= 0).any():
        return out
    ratio = float(v[-1] / prev.mean())
    return {"vol_ratio": ratio, "vol_confirmed": ratio >= VOL_MULT}


def _medium(d: pd.DataFrame) -> dict:
    """Trung hạn = ĐÚNG máy trạng thái tuần của `vnstock_horizons.medium_series` (MA10w/MA40w
    ±2%, lên 2 tuần, cầu chì 8%), tuần chốt gần nhất — không luật mới. Tham số hiệu chỉnh trên
    VN-Index; áp cho từng mã thì cầu chì 8% bật thường hơn (mã biến động mạnh hơn chỉ số)."""
    out = {"label": None, "week_end": None, "week_close": None, "ma10w": None, "ma40w": None,
           "reason": NO_DATA}
    if "time" not in d.columns:
        return {**out, "reason": NO_DATES}
    if d.empty:
        return out
    dates, closes = hz.dedupe_daily([t.date() for t in d["time"]], d["close"].tolist())
    weeks = hz.medium_series(dates, closes)
    if not weeks or weeks[-1].reading is None:
        return out
    w = weeks[-1]
    return {"label": hz.MEDIUM_LABEL[w.state], "week_end": w.week_end.isoformat(),
            "week_close": w.close, "ma10w": w.ma_short, "ma40w": w.ma_long, "reason": None}


def _long(d: pd.DataFrame) -> dict:
    c = d["close"]
    close = _last(c)
    ma = sma(c, MA_LONG)
    sma200 = _last(ma)
    slope = _pct(sma200, _last(ma, LONG_SLOPE_BARS))
    pos = None
    if len(d) >= WEEKS52_BARS:
        hi, lo = float(d["high"].iloc[-WEEKS52_BARS:].max()), float(d["low"].iloc[-WEEKS52_BARS:].min())
        pos = (close - lo) / (hi - lo) * 100 if hi > lo else None
    return {"sma200": sma200, "sma200_dist_pct": _pct(close, sma200), "sma200_slope_pct": slope,
            "pos_52w_pct": pos, "label": direction(close, sma200, slope, LONG_SLOPE_FLAT_PCT)}


def _levels(sr: Mapping | None, close: float | None, atr_v: float | None) -> dict | None:
    if not sr:
        return None
    lv = {k: _num(sr.get(k)) for k in ("support_1", "support_2", "resistance_1", "resistance_2")}
    lv = {k: (v if v is not None and v > 0 else None) for k, v in lv.items()}
    if all(v is None for v in lv.values()):
        return None
    s1, r1 = lv["support_1"], lv["resistance_1"]
    ok = close is not None and atr_v
    lv["s1_atr"] = (close - s1) / atr_v if ok and s1 is not None else None
    lv["r1_atr"] = (r1 - close) / atr_v if ok and r1 is not None else None
    return lv


def find_conflicts(card: Mapping) -> list[str]:
    """Tín hiệu lệch nhau, đúng thứ tự cố định:
      - hôm nay đóng cửa vượt lên MA20 (hôm qua ≤ MA20) mà KL < 1,2× TB20;
      - ngắn hạn TĂNG mà trung hạn GIẢM (và ngược lại);
      - RSI đà mạnh (≥70) mà giá dưới SMA200;
      - MACD mới cắt lên (≤3 phiên) mà giá dưới MA20; mới cắt xuống mà giá trên MA20.
    Thiếu dữ kiện của luật nào ⇒ luật đó không phát."""
    sh, md, lg = card.get("short") or {}, card.get("medium") or {}, card.get("long") or {}
    close, ma20, sma200 = card.get("close"), sh.get("ma20"), lg.get("sma200")
    out = []
    if sh.get("crossed_ma20_up") and sh.get("vol_confirmed") is False:
        out.append(CONFLICT_BREAKOUT_NO_VOL)
    if sh.get("label") == DIR_UP and md.get("label") == DIR_DOWN:
        out.append(CONFLICT_SHORT_UP_MEDIUM_DOWN)
    if sh.get("label") == DIR_DOWN and md.get("label") == DIR_UP:
        out.append(CONFLICT_SHORT_DOWN_MEDIUM_UP)
    if sh.get("rsi_label") == RSI_MOMENTUM and close is not None and sma200 is not None \
            and close < sma200:
        out.append(CONFLICT_RSI_STRONG_BELOW_SMA200)
    if close is not None and ma20 is not None:
        if sh.get("macd_cross") == CROSS_UP and close < ma20:
            out.append(CONFLICT_MACD_UP_BELOW_MA20)
        if sh.get("macd_cross") == CROSS_DOWN and close > ma20:
            out.append(CONFLICT_MACD_DOWN_ABOVE_MA20)
    return out


def ta_card(daily: pd.DataFrame | None, *, sr: Mapping | None = None, label: str = "") -> dict:
    """Thẻ kỹ thuật của bar CUỐI ``daily``.

    ``sr`` = mức S/R ĐÃ CÔNG BỐ TRƯỚC phiên đánh giá (khoá ``support_1/support_2/resistance_1/
    resistance_2`` như `vnstock_brief._vnindex_technicals`; module KHÔNG tự tính S/R — P2b chọn
    phương pháp). Đóng cửa < S1 ⇒ ``broke_support`` (§15: thủng S1 ⇒ chạm S2 91% vs mốc 69%).
    Ngắn hạn = `direction` trên MA20 dốc 5 phiên; dài hạn = `direction` trên SMA200 dốc 20 phiên.
    """
    d = _prep(daily)
    close = _last(d["close"]) if len(d) else None
    as_of = None
    if close is not None and "time" in d.columns:
        as_of = d["time"].iloc[-1].date().isoformat()
    atr_v = _last(atr(d["high"], d["low"], d["close"], ATR_BARS)) if len(d) else None
    card = {
        "label": label, "as_of": as_of, "close": close, "n_bars": int(len(d)),
        "short": _short(d), "medium": _medium(d), "long": _long(d),
        "volatility": {"atr": atr_v, "atr_pct": atr_v / close * 100 if atr_v and close else None},
        "levels": _levels(sr, close, atr_v),
    }
    lv = card["levels"] or {}
    card["broke_support"] = bool(close is not None and lv.get("support_1") is not None
                                 and close < lv["support_1"])
    card["conflicts"] = find_conflicts(card)
    return card


# ── In ra ────────────────────────────────────────────────────────────────

def _f(x: float) -> str:
    return f"{x:,.2f}"


def _sp(x: float) -> str:
    return f"{x:+,.2f}%"


def _side(close: float | None, ma: float | None, name: str) -> str:
    if close is None or ma is None:
        return f"{name} {NO_DATA}"
    word = "trên" if close > ma else "dưới" if close < ma else "ngang"
    return f"{word} {name} {_sp(_pct(close, ma))}"


def _rsi_txt(sh: Mapping) -> str:
    return f"RSI {_f(sh['rsi'])} {sh['rsi_label']}" if sh.get("rsi") is not None \
        else f"RSI {NO_DATA}"


def _vol_txt(sh: Mapping) -> str:
    if sh.get("vol_ratio") is None:
        return f"KL {NO_DATA}"
    return f"KL {_f(sh['vol_ratio'])}× TB20 {VOL_YES if sh['vol_confirmed'] else VOL_NO}"


def _macd_txt(sh: Mapping) -> str:
    if sh.get("macd_above") is None:
        return f"MACD {NO_DATA}"
    s = f"MACD {MACD_ABOVE if sh['macd_above'] else MACD_BELOW}"
    if sh.get("macd_cross"):
        ago = sh["macd_cross_ago"]
        s += f", mới {sh['macd_cross']} {'hôm nay' if ago == 0 else f'{ago} phiên trước'}"
    return s


def _short_line(card: Mapping) -> str:
    sh = card["short"]
    head = sh.get("label") or NO_DATA
    slope = (f" (MA20 dốc {_sp(sh['ma20_slope_pct'])}/{SHORT_SLOPE_BARS} phiên)"
             if sh.get("ma20_slope_pct") is not None else "")
    return (f"Ngắn hạn: {head} — {_side(card['close'], sh.get('ma20'), 'MA20')}{slope} · "
            f"{_rsi_txt(sh)} · {_macd_txt(sh)} · {_vol_txt(sh)}")


def _medium_line(md: Mapping) -> str:
    if md.get("label") is None:
        return f"Trung hạn: {md.get('reason') or NO_DATA}"
    return (f"Trung hạn: {md['label']} — đóng tuần {_f(md['week_close'])} (tuần chốt "
            f"{md['week_end']}) · MA10w {_f(md['ma10w'])} · MA40w {_f(md['ma40w'])}")


def _long_facts(card: Mapping) -> str:
    lg = card["long"]
    parts = [_side(card["close"], lg.get("sma200"), "SMA200")]
    if lg.get("sma200_slope_pct") is not None:
        parts.append(f"SMA200 dốc {_sp(lg['sma200_slope_pct'])}/{LONG_SLOPE_BARS} phiên")
    parts.append(f"vị trí 52 tuần {_f(lg['pos_52w_pct'])}%" if lg.get("pos_52w_pct") is not None
                 else f"vị trí 52 tuần {NO_DATA}")
    return " · ".join(parts)


def _level_txt(lv: Mapping) -> str:
    parts = []
    for key, atr_key, name in (("support_1", "s1_atr", "S1"), ("resistance_1", "r1_atr", "R1")):
        if lv.get(key) is not None:
            dist = f" ({_f(lv[atr_key])} ATR)" if lv.get(atr_key) is not None else ""
            parts.append(f"{name} {_f(lv[key])}{dist}")
    return " · ".join(parts)


def _broke_txt(card: Mapping) -> str:
    lv = card["levels"]
    s2 = lv.get("support_2")
    target = _f(s2) if s2 is not None else "(chưa có mức S2)"
    return f"đóng cửa dưới S1 {_f(lv['support_1'])}: {BROKE_SUPPORT_TEXT} {target}"


def card_lines(card: Mapping) -> list[str]:
    """Thẻ nhiều dòng (VN-Index). Dòng dài hạn chỉ in DỮ KIỆN, không nhãn: nhãn dài hạn của
    VN-Index do 5 trụ vĩ mô quyết (§12), SMA200/52 tuần chỉ là bối cảnh."""
    name = card.get("label") or "?"
    if card.get("close") is None:
        return [f"📈 Kỹ thuật {name}: {NO_DATA}"]
    head = f"📈 Kỹ thuật {name}" + (f" — phiên {card['as_of']}" if card.get("as_of") else "")
    lines = [f"{head}, đóng cửa {_f(card['close'])}",
             f"- {_short_line(card)}",
             f"- {_medium_line(card['medium'])}",
             f"- Dài hạn (bối cảnh): {_long_facts(card)}"]
    atr_pct = card["volatility"].get("atr_pct")
    lines.append(f"- Biến động: ATR({ATR_BARS}) {_f(atr_pct)}% giá" if atr_pct is not None
                 else f"- Biến động: ATR({ATR_BARS}) {NO_DATA}")
    if card.get("levels") and _level_txt(card["levels"]):
        lines.append(f"- Mức giá: {_level_txt(card['levels'])}")
    if card.get("broke_support"):
        lines.append(f"- ⚠️ {_broke_txt(card)}")
    if card.get("conflicts"):
        lines.append(f"- Tín hiệu lệch nhau: {'; '.join(card['conflicts'])}")
    return lines


def card_line(card: Mapping) -> str:
    """Một dòng nén cho từng mã: nhãn 3 khung (dài hạn kèm % cách SMA200) · RSI · KL · S1/R1
    theo bội ATR · thủng hỗ trợ · tín hiệu lệch nhau."""
    name = card.get("label") or "?"
    if card.get("close") is None:
        return f"{name}: {NO_DATA}"
    sh, md, lg = card["short"], card["medium"], card["long"]
    long_txt = lg.get("label") or NO_DATA
    if lg.get("sma200_dist_pct") is not None:
        long_txt += f" (SMA200 {_sp(lg['sma200_dist_pct'])})"
    parts = [f"{name} {_f(card['close'])}: ngắn {sh.get('label') or NO_DATA}",
             f"tuần {md.get('label') or md.get('reason') or NO_DATA}",
             f"dài {long_txt}", _rsi_txt(sh), _vol_txt(sh)]
    if card.get("levels") and _level_txt(card["levels"]):
        parts.append(_level_txt(card["levels"]).replace(" · ", " / "))
    if card.get("broke_support"):
        parts.append(f"⚠️ {_broke_txt(card)}")
    if card.get("conflicts"):
        parts.append(f"lệch: {'; '.join(card['conflicts'])}")
    return " · ".join(parts)

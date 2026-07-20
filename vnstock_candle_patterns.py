"""
vnstock_candle_patterns.py — Nhận diện mẫu nến bằng biểu thức thuần
====================================================================
Port từ StockSharp `CandlePatternRegistry` (khảo sát 2026-07-15 — mượn Ý
TƯỞNG, không copy code; LGPL). Mỗi pattern = hàm thuần trên 1-5 nến cuối
với biến O/H/L/C + dẫn xuất:

  B   = |O - C|            (thân nến)
  LEN = H - L              (chiều dài nến)
  TS  = H - max(O, C)      (râu trên)
  BS  = min(O, C) - L      (râu dưới)

Deterministic thuần, zero LLM/fetch, zero dependency (stdlib; pandas chỉ
cần cho `detect_df`). Hai bẫy đã xử theo ghi chú khảo sát:

1. `==` trên giá (Tweezer "H == pH", Marubozu "LEN == B", On-Neck) →
   tolerance tương đối `_REL_TOL` (bước giá HOSE 10/50/100 đồng ≈ ≤0.2%
   giá — equality float sẽ không bao giờ khớp).
2. Nến 1 giá LEN=0 (trần/sàn VN hay gặp) → mẫu hình-dạng đơn (Hammer,
   Doji…) yêu cầu LEN > tolerance, tránh 0<=0 luôn-đúng (Dragonfly +
   Gravestone cùng lúc = vô nghĩa).

Bổ sung ngoài bản gốc (StockSharp KHÔNG gate — họ để user tự đặt vào
ngữ cảnh): cặp mẫu SONG SINH cùng hình dạng nhưng ngược nghĩa theo vị trí
(Hammer↔Hanging Man, Inverted Hammer↔Shooting Star, Dragonfly↔Gravestone
gần giống) được gate bằng XU HƯỚNG 5 phiên trước mẫu — búa chỉ có nghĩa
sau nhịp GIẢM, người-treo-cổ sau nhịp TĂNG; thiếu trend rõ → bỏ cả hai
(tránh cùng lúc phát "bull" lẫn "bear" cho 1 bar).

Dùng:
  from vnstock_candle_patterns import detect, detect_df, pattern_labels
  hits = detect_df(df)          # df có open/high/low/close, bar cuối = mới nhất
  # hits = [{"key","name","name_vi","n","direction"}, ...] — mẫu KẾT THÚC ở bar cuối
"""

from __future__ import annotations

from typing import Iterable, Optional

# Tolerance equality: bước giá HOSE (nghìn đồng) 0.01 / 0.05 / 0.1 theo dải
# giá — 0.2% tương đối (floor nửa tick nhỏ nhất) phủ cả 3 dải.
_REL_TOL = 0.002
_ABS_TOL_MIN = 0.005

# Gate xu hướng cho cặp mẫu song sinh: % đổi giá 5 phiên TRƯỚC mẫu.
_TREND_LOOKBACK = 5
_TREND_MIN_PCT = 1.0

# Chuỗi giá trộn đơn vị (per-bar normalize chia 1000 quanh mốc 500 VND —
# bẫy đã ghi ở vnstock_preset_score._stitch_units): bước nhảy ×≥200 giữa 2
# bar liền kề là phi vật lý (trần/sàn ±15%/phiên) → không nhận diện.
_UNIT_BREAK_RATIO = 200.0


def _tol(*prices: float) -> float:
    ref = max((abs(p) for p in prices), default=0.0)
    return max(ref * _REL_TOL, _ABS_TOL_MIN)


def _eq(a: float, b: float) -> bool:
    return abs(a - b) <= _tol(a, b)


class _C:
    """Một nến với các dẫn xuất StockSharp (B/LEN/TS/BS)."""

    __slots__ = ("o", "h", "l", "c")

    def __init__(self, o: float, h: float, l: float, c: float):
        self.o, self.h, self.l, self.c = float(o), float(h), float(l), float(c)

    @property
    def b(self) -> float:      # thân
        return abs(self.o - self.c)

    @property
    def length(self) -> float:  # H - L
        return self.h - self.l

    @property
    def ts(self) -> float:      # râu trên
        return self.h - max(self.o, self.c)

    @property
    def bs(self) -> float:      # râu dưới
        return min(self.o, self.c) - self.l

    @property
    def white(self) -> bool:
        return self.o < self.c

    @property
    def black(self) -> bool:
        return self.o > self.c

    def has_range(self) -> bool:
        return self.length > _tol(self.h, self.l)


# ── Định nghĩa pattern — mirror biểu thức CandlePatternRegistry ─────────────
# Mỗi fn nhận list nến [cũ → mới] đúng độ dài n; nến cuối là bar đang xét.

def _no_shadows(x: "_C") -> bool:
    # "LEN == B" gốc — tolerance theo THANG GIÁ (râu tổng ≤ ~0.2% giá),
    # không theo độ dài đem so (thân nến nhỏ sẽ ép tolerance về ~0).
    return (x.length - x.b) <= _tol(x.h, x.l)


def _white_marubozu(cs):
    (x,) = cs
    return x.white and _no_shadows(x)


def _black_marubozu(cs):
    (x,) = cs
    return x.black and _no_shadows(x)


def _spinning_top(cs):
    (x,) = cs
    return x.b < x.length * 0.5 and abs(x.bs - x.ts) <= x.length * 0.1


def _hammer(cs):
    (x,) = cs
    return x.b <= x.bs and x.ts <= x.length * 0.2


def _inverted_hammer(cs):
    (x,) = cs
    return x.b <= x.ts and x.bs <= x.length * 0.2


def _dragonfly(cs):
    (x,) = cs
    return abs(x.o - x.c) <= x.length * 0.1 and x.ts <= x.length * 0.1


def _gravestone(cs):
    (x,) = cs
    return abs(x.o - x.c) <= x.length * 0.1 and x.bs <= x.length * 0.1


def _hanging_man(cs):
    (x,) = cs
    return x.b < x.bs * 0.5 and x.ts <= x.length * 0.2


def _shooting_star(cs):
    (x,) = cs
    return x.b < x.ts * 0.5 and x.bs <= x.length * 0.2


def _piercing(cs):
    p, x = cs
    return p.black and x.white and x.c > (p.b / 2 + p.c)


def _bullish_engulfing(cs):
    p, x = cs
    return p.black and x.white and x.o < p.c and x.c > p.o


def _bearish_engulfing(cs):
    p, x = cs
    return p.white and x.black and x.o > p.c and x.c < p.o


def _bullish_harami(cs):
    p, x = cs
    return p.black and x.white and x.o > p.c and x.c < p.o


def _bearish_harami(cs):
    p, x = cs
    return p.white and x.black and x.o < p.c and x.c > p.o


def _on_neck(cs):
    p, x = cs
    return p.black and x.white and _eq(p.l, x.c)


def _tweezer_top(cs):
    p, x = cs
    return p.white and x.black and _eq(x.h, p.h)


def _tweezer_bottom(cs):
    p, x = cs
    return p.black and x.white and _eq(x.l, p.l)


def _morning_star(cs):
    a, b, x = cs
    return a.black and b.b < a.b * 0.5 and x.white


def _evening_star(cs):
    a, b, x = cs
    return a.white and b.b < a.b * 0.5 and x.black and x.b > b.b * 2


def _three_white_soldiers(cs):
    a, b, x = cs
    return a.white and b.white and b.o > a.o and x.white and x.o > b.o


def _three_black_crows(cs):
    a, b, x = cs
    return a.black and b.black and b.o < a.o and x.black and x.o < b.o


def _three_inside_up(cs):
    a, b, x = cs
    return (a.black and b.white and b.o > a.c and b.c < a.o
            and x.white and x.o > b.o and x.b > b.b)


def _three_inside_down(cs):
    a, b, x = cs
    return (a.white and b.black and b.o < a.c and b.c > a.o
            and x.black and x.o < b.o and x.b > b.b)


def _three_outside_up(cs):
    a, b, x = cs
    return (a.black and b.white and b.o <= a.c and b.c >= a.o
            and x.white and x.c > b.c)


def _three_outside_down(cs):
    a, b, x = cs
    return (a.white and b.black and b.o > a.c and b.c < a.o
            and x.black and x.o < b.o and x.c < b.c)


def _falling_three_methods(cs):
    a, b, c_, d, x = cs
    return (a.black
            and b.white and b.b < a.b * 0.5
            and c_.white and c_.b < a.b * 0.5
            and d.white and d.b < a.b * 0.5
            and x.black and x.b > d.b * 2)


def _rising_three_methods(cs):
    a, b, c_, d, x = cs
    return (a.white
            and b.black and b.b < a.b * 0.5
            and c_.black and c_.b < a.b * 0.5
            and d.black and d.b < a.b * 0.5
            and x.white and x.b > d.b * 2)


# key, tên VN (giữ tên Anh chuẩn trong ngoặc — thuật ngữ, hợp luật
# thuần-tiếng-Việt của brief), số nến, hướng, fn, trend gate
# (None / "down" = cần nhịp giảm trước / "up" = cần nhịp tăng trước).
_P = [
    ("white_marubozu",       "Marubozu tăng",                    1, "bull",    _white_marubozu,       None),
    ("black_marubozu",       "Marubozu giảm",                    1, "bear",    _black_marubozu,       None),
    ("spinning_top",         "Con xoay (Spinning Top)",          1, "neutral", _spinning_top,         None),
    ("hammer",               "Nến búa (Hammer)",                 1, "bull",    _hammer,               "down"),
    ("inverted_hammer",      "Búa ngược (Inverted Hammer)",      1, "bull",    _inverted_hammer,      "down"),
    ("dragonfly",            "Doji chuồn chuồn (Dragonfly)",     1, "bull",    _dragonfly,            "down"),
    ("gravestone",           "Doji bia mộ (Gravestone)",         1, "bear",    _gravestone,           "up"),
    ("hanging_man",          "Người treo cổ (Hanging Man)",      1, "bear",    _hanging_man,          "up"),
    ("shooting_star",        "Sao băng (Shooting Star)",         1, "bear",    _shooting_star,        "up"),
    ("piercing",             "Nến xuyên thấu (Piercing)",        2, "bull",    _piercing,             None),
    ("bullish_engulfing",    "Bao phủ tăng (Bullish Engulfing)", 2, "bull",    _bullish_engulfing,    None),
    ("bearish_engulfing",    "Bao phủ giảm (Bearish Engulfing)", 2, "bear",    _bearish_engulfing,    None),
    ("bullish_harami",       "Harami tăng",                      2, "bull",    _bullish_harami,       None),
    ("bearish_harami",       "Harami giảm",                      2, "bear",    _bearish_harami,       None),
    ("on_neck",              "On-Neck (tiếp diễn giảm)",         2, "bear",    _on_neck,              None),
    ("tweezer_top",          "Đỉnh nhíp (Tweezer Top)",          2, "bear",    _tweezer_top,          None),
    ("tweezer_bottom",       "Đáy nhíp (Tweezer Bottom)",        2, "bull",    _tweezer_bottom,       None),
    ("morning_star",         "Sao Mai (Morning Star)",           3, "bull",    _morning_star,         None),
    ("evening_star",         "Sao Hôm (Evening Star)",           3, "bear",    _evening_star,         None),
    ("three_white_soldiers", "Ba chàng lính trắng",              3, "bull",    _three_white_soldiers, None),
    ("three_black_crows",    "Ba con quạ đen",                   3, "bear",    _three_black_crows,    None),
    ("three_inside_up",      "Three Inside Up",                  3, "bull",    _three_inside_up,      None),
    ("three_inside_down",    "Three Inside Down",                3, "bear",    _three_inside_down,    None),
    ("three_outside_up",     "Three Outside Up",                 3, "bull",    _three_outside_up,     None),
    ("three_outside_down",   "Three Outside Down",               3, "bear",    _three_outside_down,   None),
    ("falling_three_methods", "Falling Three Methods (tiếp diễn giảm)", 5, "bear", _falling_three_methods, None),
    ("rising_three_methods", "Rising Three Methods (tiếp diễn tăng)",   5, "bull", _rising_three_methods,  None),
]

PATTERNS = {key: {"key": key, "name_vi": name_vi, "n": n,
                  "direction": direction, "fn": fn, "trend": trend}
            for key, name_vi, n, direction, fn, trend in _P}

# Mẫu trung tính chỉ-nhiễu bị loại khỏi output mặc định (significant_only).
_NOISE_KEYS = {"spinning_top"}


def _to_candle(row) -> Optional[_C]:
    try:
        if isinstance(row, dict):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        else:
            o, h, l, c = row[0], row[1], row[2], row[3]
        cd = _C(o, h, l, c)
    except Exception:
        return None
    if not all(v > 0 for v in (cd.o, cd.h, cd.l, cd.c)):
        return None
    if cd.h < max(cd.o, cd.c) - _tol(cd.h) or cd.l > min(cd.o, cd.c) + _tol(cd.l):
        return None  # bar hỏng (high < body / low > body)
    return cd


def _trend_ok(closes: list, need: Optional[str]) -> bool:
    """Gate xu hướng 5 phiên TRƯỚC bar cuối cho cặp mẫu song sinh."""
    if need is None:
        return True
    if len(closes) < _TREND_LOOKBACK + 2:
        return False  # không đủ lịch sử đo trend → bỏ (tránh bull+bear cùng bar)
    ref, last_prev = closes[-2 - _TREND_LOOKBACK], closes[-2]
    if ref <= 0:
        return False
    chg = (last_prev / ref - 1.0) * 100.0
    return chg <= -_TREND_MIN_PCT if need == "down" else chg >= _TREND_MIN_PCT


def _has_unit_break(closes: Iterable[float]) -> bool:
    prev = None
    for v in closes:
        if v and v > 0:
            if prev is not None and (v / prev >= _UNIT_BREAK_RATIO
                                     or prev / v >= _UNIT_BREAK_RATIO):
                return True
            prev = v
    return False


def detect(candles, significant_only: bool = True) -> list:
    """Mẫu nến KẾT THÚC ở bar cuối của ``candles``.

    ``candles``: sequence bar [cũ → mới], mỗi bar là dict có
    open/high/low/close hoặc tuple (o, h, l, c). Trả list hit
    {"key","name_vi","n","direction"} — mẫu nhiều nến (đặc hiệu hơn) xếp trước.
    """
    parsed = [_to_candle(r) for r in candles]
    if not parsed or parsed[-1] is None:
        return []
    closes = [c.c for c in parsed if c is not None]
    if _has_unit_break(closes):
        return []

    hits = []
    for spec in PATTERNS.values():
        if significant_only and spec["key"] in _NOISE_KEYS:
            continue
        n = spec["n"]
        if len(parsed) < n:
            continue
        window = parsed[-n:]
        if any(c is None for c in window):
            continue
        # Mẫu hình-dạng đơn cần range thật (bẫy nến 1 giá trần/sàn)
        if n == 1 and not window[0].has_range():
            continue
        if not _trend_ok(closes, spec["trend"]):
            continue
        try:
            if spec["fn"](window):
                hits.append({"key": spec["key"], "name_vi": spec["name_vi"],
                             "n": n, "direction": spec["direction"]})
        except Exception:
            continue
    hits.sort(key=lambda h: -h["n"])  # đặc hiệu (nhiều nến) trước
    return hits


def detect_df(df, significant_only: bool = True) -> list:
    """Convenience cho pandas DataFrame có cột open/high/low/close
    (bar cuối = mới nhất). Chỉ cần ~10 bar cuối."""
    try:
        cols = ("open", "high", "low", "close")
        if df is None or len(df) == 0 or any(c not in df.columns for c in cols):
            return []
        tail = df[list(cols)].tail(_TREND_LOOKBACK + 7).astype(float)
        candles = list(tail.itertuples(index=False, name=None))
        return detect(candles, significant_only=significant_only)
    except Exception:
        return []


def pattern_labels(hits: list, limit: int = 3) -> list:
    """Nhãn hiển thị tiếng Việt cho brief/UI (cap ``limit`` mẫu)."""
    return [h["name_vi"] for h in hits[:limit]]


if __name__ == "__main__":
    # Smoke nhanh trên dữ liệu tự chế
    demo = [
        (100, 101, 99, 100.5), (100.5, 101, 98, 98.5), (98.5, 99, 96, 96.5),
        (96.5, 97, 94, 94.5), (94.5, 95, 92, 92.5), (92.5, 93, 90, 90.5),
        (90.5, 91, 88, 88.5),   # nhịp giảm
        (88, 89, 86, 86.5),     # nến đen
        (85.5, 90, 85, 89.5),   # bao phủ tăng
    ]
    for h in detect(demo):
        print(f"{h['key']:24s} {h['direction']:8s} {h['name_vi']}")

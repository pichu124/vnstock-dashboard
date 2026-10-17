#!/usr/bin/env python3
"""vnstock_futures_foreign_view.py — số vị thế ròng khối ngoại HĐTL VN30 (thuần, có test).

Đọc DataFrame kho `vnstock_futures_foreign.load()`; không gọi mạng, không ghi gì. Dùng chung cho
mục 📑 của brief (CODE dựng mọi số — guard `enforce_futures_foreign_section` chép nguyên dòng) và
tab dashboard 📑 Phái sinh NN.

Định nghĩa:
- dòng lệnh ròng một phiên = KL mua − KL bán của khối ngoại (HĐ); trường thiếu tính 0.
- vị thế ròng một hợp đồng = Σ dòng lệnh ròng từ phiên niêm yết (nguồn không có OI theo nhà đầu tư —
  đây là cách dựng lại vị thế từ dòng lệnh; đúng khi không thiếu phiên).
- tổng = Σ các hợp đồng đang lưu hành; "sau đáo hạn" bỏ hợp đồng đáo hạn ĐÚNG phiên đó (tất toán
  tiền mặt cuối phiên). Phiên ĐỦ khi có đúng 4 hợp đồng lưu hành (2 tháng gần + 2 quý gần) — phiên
  thiếu không dùng cho chuỗi/cực trị, brief nói "chưa đủ hợp đồng" thay vì in tổng sai.
- sai số ước tính (95%) của tổng: mỗi dòng nguồn thiếu trường khối ngoại góp ±KL × tỷ lệ |ròng|/KL
  phân vị 95 đo trên 1.756 dòng đủ số (15/10: 6% khi KL ≥ 20.000 HĐ, 46% khi nhỏ hơn), cộng căn bậc
  hai tổng bình phương trên các hợp đồng đang mở. "Chưa chắc" khi sai số > max(1.000 HĐ, 25% |vị
  thế|) — trên seed chỉ đúng tuần chuyển hệ KRX 05–14/05/2025 (VN30F2505 mất 4 phiên, ±18k HĐ); dòng
  thiếu lẻ tẻ của hợp đồng quý xa cộng lại ±300–900 HĐ, brief chỉ nhắc khi ≥ 500 HĐ.
"""
from __future__ import annotations

from datetime import date

import vnstock_futures_foreign as ff
from vnstock_brief_canon import _FUTURES_FOREIGN_SECTION_TITLE as SECTION_TITLE  # dùng chung với guard

LIVE_CONTRACTS = 4
EXPIRY_SHIFT_MAX_DAYS = 7          # đáo hạn lùi vì nghỉ lễ (Tết 2026: 13/02 thay 19/02)
ERR_BIG_VOLUME = 20_000            # dòng KL lớn (hợp đồng tháng gần) — tỷ lệ |ròng|/KL thấp
ERR_RATIO_BIG, ERR_RATIO_SMALL = 0.06, 0.46   # phân vị 95 |ròng|/KL, đo 15/10 trên seed
ERR_FLOOR, ERR_REL = 1_000.0, 0.25
ERR_SHOW = 500.0                   # sai số dưới mức này không nhắc trong brief
ENV_BRIEF = "VNSTOCK_BRIEF_FUTURES_FOREIGN"


def brief_enabled() -> bool:
    import os
    return (os.environ.get(ENV_BRIEF) or "1").strip().lower() not in ("0", "false", "off", "no")


def _expiry_day(contract: str, last: str, max_date: str) -> "str | None":
    """Phiên đáo hạn của hợp đồng nếu đã thấy: phiên cuối có số = thứ Năm tuần 3, hoặc (đã có
    phiên sau đó trong kho) phiên cuối nằm trong 7 ngày trước thứ Năm tuần 3 (lùi vì nghỉ lễ)."""
    tt = ff.third_thursday(*ff.contract_ym(contract))
    lt = date.fromisoformat(last)
    if lt == tt or (last < max_date and 0 <= (tt - lt).days <= EXPIRY_SHIFT_MAX_DAYS):
        return last
    return None


def positions(df):
    """Một dòng/phiên (index = ngày ISO): total (gồm HĐ đáo hạn phiên đó), after (sau tất toán),
    flow/buy/sell (tổng các HĐ có dòng phiên đó), n_live, complete, expiring, front, front_close,
    next_front, next_close, err95, uncertain + một cột vị thế lũy kế mỗi hợp đồng (NaN ngoài kỳ lưu
    hành)."""
    import numpy as np
    import pandas as pd
    if df is None or not len(df):
        return pd.DataFrame()
    d = df.copy()
    d["net"] = d["buy"].fillna(0) - d["sell"].fillna(0)
    vol = d["volume"].fillna(0)
    ratio = np.where(vol >= ERR_BIG_VOLUME, ERR_RATIO_BIG, ERR_RATIO_SMALL)
    d["err2"] = np.where(d["ff"] == "ok", 0.0, (vol * ratio) ** 2)
    d = d.sort_values(["contract", "date"])
    d["cum"] = d.groupby("contract")["net"].cumsum()
    d["cum_err2"] = d.groupby("contract")["err2"].cumsum()
    dates = sorted(d["date"].unique())
    max_date = dates[-1]
    contracts = sorted(d["contract"].unique(), key=ff.contract_ym)
    span = d.groupby("contract")["date"].agg(["min", "max"])
    expiry = {c: _expiry_day(c, span.at[c, "max"], max_date) for c in contracts}

    def grid(col):
        g = d.pivot_table(index="date", columns="contract", values=col, aggfunc="last")
        g = g.reindex(index=dates, columns=contracts).ffill()
        for c in contracts:
            g.loc[(g.index < span.at[c, "min"]) | (g.index > span.at[c, "max"]), c] = np.nan
        return g

    cum, cerr2 = grid("cum"), grid("cum_err2")
    close = d.pivot_table(index="date", columns="contract", values="close", aggfunc="last") \
        .reindex(index=dates, columns=contracts)
    live = cum.notna()
    exp_mask = pd.DataFrame(False, index=dates, columns=contracts)
    for c, e in expiry.items():
        if e:
            exp_mask.loc[e, c] = True
    after_mask = live & ~exp_mask
    out = pd.DataFrame(index=pd.Index(dates, name="date"))
    out["total"] = cum.where(live).sum(axis=1)
    out["after"] = cum.where(after_mask).sum(axis=1)
    day = d.groupby("date")[["net", "buy", "sell"]].sum(min_count=1).reindex(dates)
    out["flow"] = day["net"].fillna(0)
    out["buy"] = day["buy"].fillna(0)
    out["sell"] = day["sell"].fillna(0)
    out["n_live"] = live.sum(axis=1).astype(int)
    out["complete"] = out["n_live"] == LIVE_CONTRACTS
    out["expiring"] = [next((c for c in contracts if exp_mask.at[x, c]), "") for x in dates]
    out["front"] = [next((c for c in contracts if live.at[x, c]), "") for x in dates]
    out["next_front"] = [next((c for c in contracts if after_mask.at[x, c]), "") for x in dates]
    out["front_close"] = [close.at[x, c] if c else np.nan for x, c in zip(dates, out["front"])]
    out["next_close"] = [close.at[x, c] if c else np.nan for x, c in zip(dates, out["next_front"])]
    out["err95"] = np.sqrt(cerr2.where(after_mask).sum(axis=1))
    out["uncertain"] = out["err95"] > np.maximum(ERR_FLOOR, ERR_REL * out["after"].abs())
    for c in contracts:
        out[c] = cum[c]
    return out


def streaks(series) -> "list[dict]":
    """Chuỗi phiên liên tiếp cùng dấu (0 cắt chuỗi): {sign, start, end, n, extreme, extreme_date}."""
    runs: list = []
    for d, v in series.items():
        s = 1 if v > 0 else (-1 if v < 0 else 0)
        if runs and runs[-1]["sign"] == s and s != 0:
            r = runs[-1]
            r.update(end=d, n=r["n"] + 1)
            if abs(v) > abs(r["extreme"]):
                r.update(extreme=float(v), extreme_date=d)
        elif s != 0:
            runs.append({"sign": s, "start": d, "end": d, "n": 1, "extreme": float(v), "extreme_date": d})
        else:
            runs.append({"sign": 0, "start": d, "end": d, "n": 1, "extreme": 0.0, "extreme_date": d})
    return [r for r in runs if r["sign"] != 0]


def _back(ser, n: int):
    return float(ser.iloc[-1] - ser.iloc[-1 - n]) if len(ser) > n else None


def summary(df=None, *, as_of: "str | None" = None, pos=None) -> "dict | None":
    """Số cho brief + ô số dashboard ở phiên cuối ≤ `as_of`. None khi kho trống."""
    if pos is None:
        if df is None:
            df = ff.load()
        pos = positions(df)
    if not len(pos):
        return None
    if as_of:
        pos = pos[pos.index <= as_of]
        if not len(pos):
            return None
    d = pos.index[-1]
    row = pos.iloc[-1]
    valid = pos[pos["complete"]]
    s: dict = {"date": d, "complete": bool(row["complete"]), "n_live": int(row["n_live"]),
               "after": float(row["after"]), "total": float(row["total"]), "flow": float(row["flow"]),
               "buy": float(row["buy"]), "sell": float(row["sell"]), "expiring": row["expiring"] or None,
               "uncertain": bool(row["uncertain"]), "err95": float(row["err95"]),
               "data_from": valid.index[0] if len(valid) else None}
    close = row["next_close"] if row["next_close"] == row["next_close"] else row["front_close"]
    s["front"] = row["next_front"] or row["front"]
    s["front_close"] = float(close) if close == close else None
    s["notional_bn"] = (abs(s["after"]) * s["front_close"] * ff.MULTIPLIER / 1e9
                        if s["front_close"] else None)
    contracts = [c for c in pos.columns if str(c).startswith("VN30F") and row[c] == row[c]]
    if df is None:
        df = ff.load()
    today = df[df["date"] == d].set_index("contract") if len(df) else None
    rows = []
    for c in contracts:
        r = today.loc[c] if today is not None and c in today.index else None
        rows.append({"contract": c, "pos": float(row[c]), "expiring": c == s["expiring"],
                     "flow": (None if r is None else float((r["buy"] if r["buy"] == r["buy"] else 0)
                                                           - (r["sell"] if r["sell"] == r["sell"] else 0))),
                     "buy": None if r is None or r["buy"] != r["buy"] else float(r["buy"]),
                     "sell": None if r is None or r["sell"] != r["sell"] else float(r["sell"]),
                     "close": None if r is None or r["close"] != r["close"] else float(r["close"]),
                     "volume": None if r is None or r["volume"] != r["volume"] else float(r["volume"]),
                     "ff": None if r is None else r["ff"], "symbol": None if r is None else r["symbol"]})
    s["contracts"] = rows
    s["has_flow"] = any(r["ff"] in ("ok", "partial") for r in rows)
    s["missing_today"] = [r["contract"] for r in rows if r["ff"] is None]
    if s["complete"] and len(valid) >= 1:
        after = valid["after"]
        s["chg1"], s["chg5"], s["chg20"] = _back(after, 1), _back(after, 5), _back(after, 20)
        runs = streaks(after)
        cur = runs[-1] if runs and runs[-1]["end"] == d else None
        s["streak"] = cur
        if cur:
            same = [r for r in runs if r["sign"] == cur["sign"]]
            best = max(same, key=lambda r: (r["n"], r["start"]))
            s["streak_record"] = {**best, "ties": sum(1 for r in same if r["n"] == best["n"])}
        hi, lo = after.idxmax(), after.idxmin()
        s["max_long"] = {"value": float(after[hi]), "date": hi} if after[hi] > 0 else None
        s["max_short"] = {"value": float(after[lo]), "date": lo} if after[lo] < 0 else None
        s["pct_rank"] = float((after <= after.iloc[-1]).mean() * 100)
        s["n_sessions"] = int(len(after))
        s["n_short"] = int((after < 0).sum())
    return s


# ── Dòng brief (CODE dựng) ───────────────────────────────────────────────────
def _dmy(iso: "str | None") -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "—"


def _dm(iso: "str | None") -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "—"


def side(v: float) -> str:
    """'short 1,881 HĐ' / 'long 11,004 HĐ' / 'cân bằng (0 HĐ)'."""
    return ("long" if v > 0 else "short") + f" {abs(v):,.0f} HĐ" if v else "cân bằng (0 HĐ)"


def _short(c: str) -> str:
    return "F" + str(c)[5:]


def _sgn(v) -> str:
    return "—" if v is None else f"{v:+,.0f}"


def brief_lines(s: "dict | None", *, expect: "str | None" = None) -> "list[str]":
    """Thân mục 📑 (KHÔNG có tiêu đề). Dòng code né mẫu mà guard khác sửa nhầm: không 'mua ròng'/
    'bán ròng' (guard NN cổ phiếu), không 'tăng/giảm X%', không 'kỷ lục'. `expect` = phiên brief
    mô tả — số cũ hơn thì nói rõ đang dùng phiên nào."""
    if not s:
        return []
    lines = []
    stale = bool(expect and s["date"] < expect)
    if not s["complete"]:
        have = ", ".join(_short(r["contract"]) for r in s["contracts"]) or "không có"
        return [f"- Phiên {_dmy(s['date'])}: kho mới có {s['n_live']}/{LIVE_CONTRACTS} hợp đồng lưu "
                f"hành ({have}) — chưa đủ để tính tổng vị thế ròng khối ngoại."]
    head = f"- Vị thế ròng khối ngoại sau phiên {_dmy(s['date'])}: {side(s['after'])}"
    if s.get("notional_bn"):
        head += f" (≈ {s['notional_bn']:,.0f} tỷ đ danh nghĩa)"
    if s["expiring"]:
        head += f" · tính cả {_short(s['expiring'])} đáo hạn phiên này: {side(s['total'])}"
    lines.append(head)
    chg = [f"so phiên trước {_sgn(s.get('chg1'))} HĐ"]
    if s.get("chg5") is not None:
        chg.append(f"5 phiên {_sgn(s['chg5'])} HĐ")
    if s.get("chg20") is not None:
        chg.append(f"20 phiên {_sgn(s['chg20'])} HĐ")
    if s["has_flow"]:
        lines.append(f"- Dòng lệnh phiên: {_sgn(s['flow'])} HĐ (mua {s['buy']:,.0f} · bán {s['sell']:,.0f})"
                     f" · vị thế đổi {', '.join(chg)}")
    else:
        lines.append(f"- Dòng lệnh phiên: nguồn không có số khối ngoại phiên này · vị thế đổi {', '.join(chg)}")
    keep = [r for r in s["contracts"] if not r["expiring"]]
    parts = [f"{_short(r['contract'])} {_sgn(r['pos'])}" for r in keep]
    exp = next((r for r in s["contracts"] if r["expiring"]), None)
    tail = f" · {_short(exp['contract'])} đáo hạn phiên này {_sgn(exp['pos'])} (tất toán)" if exp else ""
    lines.append("- Theo kỳ hạn: " + " · ".join(parts) + tail)
    cur, rec = s.get("streak"), s.get("streak_record")
    if cur:
        word = "long" if cur["sign"] > 0 else "short"
        since = _dm(cur["start"]) if cur["start"][:4] == s["date"][:4] else _dmy(cur["start"])
        txt = f"- Chuỗi: {word} ròng {cur['n']} phiên liên tiếp (từ {since})"
        if cur["start"] == s["data_from"]:
            txt = (f"- Chuỗi: {word} ròng suốt {cur['n']} phiên từ đầu dữ liệu ({_dmy(s['data_from'])}) "
                   "— chưa biết chuỗi bắt đầu từ khi nào")
        elif rec and rec["start"] == cur["start"]:
            txt += (f" — dài nhất phía {word} từ {_dmy(s['data_from'])}"
                    + (f" (bằng {rec['ties'] - 1} chuỗi khác)" if rec["ties"] > 1 else ""))
        elif rec and rec["n"] == cur["n"]:
            txt += f" — bằng chuỗi {word} dài nhất từ {_dmy(s['data_from'])}"
        elif rec:
            at_start = "≥" if rec["start"] == s["data_from"] else ""
            first = _dm(rec["start"]) if rec["start"][:4] == rec["end"][:4] else _dmy(rec["start"])
            txt += (f" · chuỗi {word} dài nhất từ {_dmy(s['data_from'])}: {at_start}{rec['n']} phiên "
                    f"({first}–{_dmy(rec['end'])})")
        lines.append(txt)
    ext = []
    if s.get("max_long"):
        ext.append(f"long lớn nhất {s['max_long']['value']:,.0f} HĐ ({_dmy(s['max_long']['date'])})")
    if s.get("max_short"):
        ext.append(f"short lớn nhất {abs(s['max_short']['value']):,.0f} HĐ ({_dmy(s['max_short']['date'])})")
    if ext:
        lines.append(f"- Mốc từ {_dmy(s['data_from'])}: " + " · ".join(ext))
    warn = []
    if stale:
        warn.append(f"chưa lấy được số phiên {_dmy(expect)} — đang dùng phiên {_dmy(s['date'])}")
    if s["missing_today"]:
        warn.append("thiếu dòng phiên này của " + ", ".join(_short(c) for c in s["missing_today"])
                    + " (vị thế giữ số phiên trước)")
    if s["uncertain"] or (s["err95"] >= ERR_SHOW and s["err95"] >= 0.1 * abs(s["after"])):
        warn.append(f"nguồn thiếu số khối ngoại vài phiên ⇒ sai số ước tính ±{s['err95']:,.0f} HĐ"
                    + (" — tổng CHƯA CHẮC" if s["uncertain"] else ""))
    if warn:
        lines.append("- Lưu ý dữ liệu: " + "; ".join(warn))
    return lines


def prompt_block(lines: "list[str]") -> str:
    """Khối DỮ KIỆN cho prompt — guard thay thân mục 📑 bằng đúng `lines`."""
    if not lines:
        return ""
    return "\n".join([f"\n{SECTION_TITLE}"] + lines + [
        "→ Mục 📑 do HỆ THỐNG dựng từ dữ liệu: chỉ in tiêu đề mục, KHÔNG tự viết số. Vị thế phái "
        "sinh tính bằng HỢP ĐỒNG (HĐ) — KHÔNG đổi ra tỷ đồng mua/bán ròng, KHÔNG cộng hay so với NN "
        "ròng cổ phiếu. Muốn nhắc hàm ý ở mục khác thì 1 câu, chỉ dùng số trong khối này: short ròng "
        "phái sinh có thể là PHÒNG HỘ danh mục cổ phiếu hoặc đặt cược giảm — KHÔNG khẳng định là cái nào."])


# ── Bảng cho dashboard ───────────────────────────────────────────────────────
ROLES = ("Gần nhất", "Thứ 2", "Thứ 3", "Xa nhất")


def role_frame(pos):
    """Vị thế từng phiên theo THỨ TỰ kỳ hạn (sau đáo hạn): hợp đồng gần nhất … xa nhất — một chuỗi
    liền mạch qua các lần cuộn kỳ, để thấy vị thế dồn ở kỳ hạn nào (cột chồng trên dashboard)."""
    import numpy as np
    import pandas as pd
    if pos is None or not len(pos):
        return pd.DataFrame(columns=list(ROLES))
    contracts = sorted((c for c in pos.columns if str(c).startswith("VN30F")), key=ff.contract_ym)
    out = []
    for d, r in pos.iterrows():
        vals = [r[c] for c in contracts if r[c] == r[c] and c != r["expiring"]][:len(ROLES)]
        out.append(vals + [np.nan] * (len(ROLES) - len(vals)))
    return pd.DataFrame(out, index=pos.index, columns=list(ROLES))


def contract_table(s: dict):
    """Bảng theo kỳ hạn ở phiên cuối: vị thế, dòng lệnh, mua/bán, giá, KL, tỷ trọng khối ngoại."""
    import pandas as pd
    rows = []
    for r in (s or {}).get("contracts") or []:
        y, m = ff.contract_ym(r["contract"])
        vol, b, sl = r["volume"], r["buy"], r["sell"]
        rows.append({"Hợp đồng": r["contract"] + (" (đáo hạn phiên này)" if r["expiring"] else ""),
                     "Mã SSI": r["symbol"] or ff.krx_symbol(y, m),
                     "Đáo hạn (luật)": ff.third_thursday(y, m).isoformat(),
                     "Vị thế ròng (HĐ)": r["pos"], "Dòng lệnh phiên (HĐ)": r["flow"],
                     "Mua (HĐ)": b, "Bán (HĐ)": sl, "Giá đóng cửa": r["close"], "KL khớp": vol,
                     "Khối ngoại % KL": (((b or 0) + (sl or 0)) / (2 * vol) * 100) if vol else None})
    return pd.DataFrame(rows)


def month_end_table(pos):
    """Cuối mỗi tháng (phiên đủ cuối cùng): vị thế sau đáo hạn, đổi so tháng trước, giá HĐ tháng gần."""
    import pandas as pd
    v = pos[pos["complete"]]
    if not len(v):
        return pd.DataFrame()
    g = v.groupby(v.index.str[:7]).tail(1)
    out = pd.DataFrame({"Tháng": [f"{x[5:7]}/{x[:4]}" for x in g.index], "Phiên": list(g.index),
                        "Vị thế ròng (HĐ)": g["after"].values,
                        "Đổi trong tháng (HĐ)": g["after"].diff().values,
                        "Giá HĐ tháng gần": g["next_close"].values})
    return out.iloc[::-1].reset_index(drop=True)


def streak_table(pos, sign: int = -1, top: int = 10):
    """Các chuỗi cùng dấu (mặc định short) — dài nhất trước."""
    import pandas as pd
    v = pos[pos["complete"]]
    runs = [r for r in streaks(v["after"]) if r["sign"] == sign] if len(v) else []
    runs = sorted(runs, key=lambda r: (-r["n"], r["start"]))[:top]
    return pd.DataFrame([{"Từ": r["start"], "Đến": r["end"], "Số phiên": r["n"],
                          "Sâu nhất (HĐ)": r["extreme"], "Ngày sâu nhất": r["extreme_date"]}
                         for r in runs])


def quality_table(df):
    """Dòng thiếu trường khối ngoại theo hợp đồng: số dòng, KL các dòng đó, % KL hợp đồng."""
    import pandas as pd
    if df is None or not len(df):
        return pd.DataFrame()
    g = df.assign(miss=df["ff"] != "ok", mv=df["volume"].where(df["ff"] != "ok", 0)).groupby("contract")
    t = pd.DataFrame({"Dòng thiếu": g["miss"].sum(), "KL dòng thiếu": g["mv"].sum(),
                      "KL hợp đồng": g["volume"].sum()})
    t["% KL thiếu"] = (t["KL dòng thiếu"] / t["KL hợp đồng"].replace(0, float("nan")) * 100).round(2)
    t = t[t["Dòng thiếu"] > 0].sort_values("% KL thiếu", ascending=False)
    return t.reset_index().rename(columns={"contract": "Hợp đồng"})


def main() -> int:
    s = summary()
    print("\n".join([SECTION_TITLE] + brief_lines(s)) if s else "(kho trống — python run.py futures-foreign --seed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

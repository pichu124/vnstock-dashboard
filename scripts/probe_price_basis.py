"""So kho giá với NGUỒN quanh một vách đứt — kho lệch cơ sở, hay nguồn sai?

Vì sao có file này (18/08, ca VVS): `check_unit_continuity` chỉ ra VVS có vách
−36.7% ngày 2026-06-15 mà KHÔNG trùng sự kiện quyền nào (div_check: 0 gap thô).
Hai giả thuyết còn lại đòi cách chữa NGƯỢC NHAU, nên phải phân định trước khi
sửa bất cứ thứ gì:

* **Kho lệch CƠ SỞ ĐIỀU CHỈNH** — nguồn đã rebase toàn chuỗi sau một sự kiện,
  còn sync chỉ nối bar mới lên lịch sử cũ (`update_ticker` luôn fetch từ
  `last_date`, KHÔNG có đường nạp lại lịch sử). Dấu hiệu: nguồn LIỀN MẠCH ở
  đúng quãng kho gãy, và tỉ lệ kho/nguồn ĐỔI BẬC tại ngày vách.
  → chữa: ghi đè phần lịch sử bằng dữ liệu nguồn.
* **Nguồn sai** — nguồn cũng gãy y hệt, kho chỉ chép lại trung thực.
  → chữa ở nguồn/quarantine, ghi đè kho vô ích.

Chỉ ĐỌC: fetch qua đúng đường của updater (`_fetch_prices`, cùng chuẩn hoá đơn
vị) rồi in đối chiếu. KHÔNG ghi gì vào kho — quyết định sửa là của người.

Dùng
----
    python scripts/probe_price_basis.py --ticker VVS            # tự tìm ngày vách
    python scripts/probe_price_basis.py --ticker VHM --ticker PNJ --ticker GEX
    python scripts/probe_price_basis.py --ticker VVS --break-date 2026-06-15

Exit: 0 in được đối chiếu · 2 không lấy được data một bên.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hai chuỗi coi là CÙNG cơ sở khi tỉ lệ nằm trong ±1,2% (làm tròn giá, tick
# size). HẠ TỪ 2% xuống 19/08: chế độ --sweep gắn cờ từ 1,5%, nên mọi mã lệch
# trong dải 1,5-2% bị gắn cờ rồi lại bị chính công cụ chữa TỪ CHỐI vì probe
# phán "aligned" — đúng 5 ca CTG/DPG/MWG/NLG/VPB (1,52-1,93%) trong lượt chạy
# thử 70 mã. Hai ngưỡng phải khớp, nếu không danh sách có mã không ai chữa nổi.
# Vẫn để trên mức nhiễu làm tròn (~0,8%, có test canh).
SAME_BASIS_TOL = 0.012
# Ngưỡng coi là CÓ VÁCH tại ngày chỉ định — giống check_unit_continuity.
BREAK_PCT = 0.30


def load_wh(prices_dir: Path, ticker: str, d0: date, d1: date) -> pd.DataFrame:
    tdir = prices_dir / f"ticker={ticker.upper()}"
    frames = []
    for pq in sorted(tdir.glob("year=*/*.parquet")) if tdir.exists() else []:
        try:
            frames.append(pd.read_parquet(pq, columns=["time", "close"]))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["time", "close"])
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"]).dt.date
    return (df[(df["time"] >= d0) & (df["time"] <= d1)]
            .sort_values("time").reset_index(drop=True))


def fetch_source(ticker: str, d0: date, d1: date) -> pd.DataFrame:
    """Fetch qua ĐÚNG đường updater dùng — cùng chuẩn hoá đơn vị, khỏi so lệch
    vì hai lối normalize khác nhau."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from vnstock_updater import _fetch_prices
    df = _fetch_prices(ticker.upper(), d0.isoformat(), d1.isoformat())
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "close"])
    out = df[["time", "close"]].copy()
    out["time"] = pd.to_datetime(out["time"]).dt.date
    return out.sort_values("time").reset_index(drop=True)


def basis_report(wh: pd.DataFrame, src: pd.DataFrame, break_date: date) -> dict:
    """Hàm THUẦN (test được offline): tỉ lệ kho/nguồn hai bên ngày vách.

    Trả verdict:
      * `aligned`       — cùng bậc VÀ không có vách ⇒ kho khớp nguồn, xong.
      * `source_error`  — cùng bậc NHƯNG vẫn có vách ⇒ nguồn cũng gãy.
      * `warehouse_basis` — bậc ĐỔI tại ngày vách ⇒ kho giữ cơ sở cũ ở lịch sử.
      * `no_overlap` / `inconclusive` — không đủ dữ liệu để phán.
    """
    m = wh.merge(src, on="time", suffixes=("_wh", "_src"))
    m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
    if m.empty:
        return {"verdict": "no_overlap", "n": 0}
    m["ratio"] = m["close_wh"] / m["close_src"]
    before = m[m["time"] < break_date]["ratio"]
    after = m[m["time"] >= break_date]["ratio"]
    if before.empty or after.empty:
        return {"verdict": "inconclusive", "n": len(m),
                "n_before": len(before), "n_after": len(after),
                "rows": m}
    r_before, r_after = float(before.median()), float(after.median())
    same = abs(r_before - r_after) <= SAME_BASIS_TOL * max(r_after, 1e-9)
    # "Cùng bậc hai bên" CHƯA đủ để kết tội nguồn: phải CÓ VÁCH THẬT tại ngày
    # đó đã. Không có vách mà vẫn hô "NGUỒN CŨNG GÃY" là báo động giả — ca
    # PNJ 18/08: kho đã khớp nguồn 1.0000× toàn dải, không còn gì để chữa,
    # mà tool vẫn phán nguồn gãy.
    mm = m.reset_index(drop=True)
    pos = mm.index[mm["time"] >= break_date]
    has_break = False
    if len(pos) and pos[0] > 0:
        i = int(pos[0])
        prev, cur = float(mm.at[i - 1, "close_wh"]), float(mm.at[i, "close_wh"])
        has_break = prev > 0 and abs(cur / prev - 1) >= BREAK_PCT
    if same:
        verdict = "source_error" if has_break else "aligned"
    else:
        verdict = "warehouse_basis"
    return {
        "verdict": verdict, "has_break": has_break,
        "n": len(m), "n_before": len(before), "n_after": len(after),
        "ratio_before": r_before, "ratio_after": r_after,
        "shift": r_before / r_after if r_after else float("nan"),
        "rows": m,
    }


# ── Quét LỆCH CƠ SỞ theo universe (thêm 19/08 sau ca VNM) ──────────────────
#
# Vì sao cần thêm một chế độ nữa: `check_unit_continuity` nhìn VÁCH GIÁ, nên nó
# chỉ thấy lệch cơ sở đủ LỚN (≥30%). Ca VNM 19/08 lệch 3,27% — cỡ một lần cổ
# tức tiền mặt — và hoàn toàn vô hình với nó: giá liền mạch, khớp giá live, mã
# được báo sạch, trong khi TOÀN BỘ lịch sử trước 23/06 ở cơ sở cũ. Backtest
# tầng vị thế (lookback 730 ngày) thì mọi cửa sổ đều bắc qua các mốc cổ tức.
#
# Lớp lỗi này chỉ hiện qua TỈ LỆ kho/nguồn, mà tỉ lệ thì cần fetch nguồn —
# đắt hơn nhiều so với quét kho. Nên quét theo UNIVERSE THANH KHOẢN chứ không
# cả kho: mã GTGD < ngưỡng không lọt vào universe chiến lược thì lệch cơ sở ở
# đó không đổi quyết định nào.

# Bậc tỉ lệ nhỏ hơn mức này coi như nhiễu làm tròn/bước giá, không phải đổi cơ
# sở. Cổ tức tiền mặt VN nhỏ nhất đáng kể ~1,5% giá.
BASIS_STEP_TOL = 0.015
# Mỗi phía của bậc phải có đủ bar thì trung vị mới có nghĩa.
BASIS_MIN_SIDE = 5


def find_basis_step(wh: pd.DataFrame, src: pd.DataFrame,
                    tol: float = BASIS_STEP_TOL) -> "dict | None":
    """Tỉ lệ kho/nguồn có ĐỔI BẬC ở đâu đó trong cửa sổ không?

    Hàm THUẦN (test được offline). Hai bước, cố ý tách:
      1. tìm điểm tỉ lệ nhảy mạnh nhất giữa hai bar kề nhau — rẻ, O(n);
      2. XÁC NHẬN bằng trung vị hai phía. Một bar lỗi đơn lẻ làm bước 1 kêu
         nhưng không đổi được trung vị, nên bước 2 loại nó.
    """
    m = wh.merge(src, on="time", suffixes=("_wh", "_src"))
    m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)].sort_values("time")
    if len(m) < 2 * BASIS_MIN_SIDE:
        return None
    r = (m["close_wh"] / m["close_src"]).to_numpy()
    times = m["time"].tolist()
    jumps = np.abs(r[1:] / r[:-1] - 1.0)
    i = int(np.argmax(jumps)) + 1
    if jumps[i - 1] < tol:
        return None
    if i < BASIS_MIN_SIDE or len(r) - i < BASIS_MIN_SIDE:
        return None
    before, after = float(np.median(r[:i])), float(np.median(r[i:]))
    if before <= 0 or after <= 0:
        return None
    shift = before / after
    if abs(shift - 1.0) < tol:
        return None                      # bar lỗi đơn lẻ, không đổi bậc thật
    return {"break": times[i], "ratio_before": before, "ratio_after": after,
            "shift": shift, "n": len(m)}


def strategy_universe() -> set:
    """Mã mà BACKTEST thật sự chạy trên đó — VN30 + VNMID.

    Vì sao cần: ngưỡng GTGD của bộ quét chỉ là PHỎNG ĐOÁN cho "mã nào quan
    trọng", còn universe huấn luyện lại chọn theo THÀNH PHẦN CHỈ SỐ. Mã nằm
    trong VN30/VNMID mà GTGD20 tình cờ dưới ngưỡng thì không bao giờ được quét
    — trong khi nó VẪN vào backtest. Đúng ca NTP (19/08): lệch cơ sở từ
    06/2026, chỉ lộ ra khi thanh khoản nhích qua 5 tỷ và rơi vào tầm quét.

    Lấy được thì trả set; hỏng thì trả rỗng (chỗ gọi tự lo) — KHÔNG đoán.
    """
    import sys as _sys
    _root = str(REPO_ROOT)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    for get in (lambda: __import__("vnstock_train")._training_universe(lite=False),
                lambda: __import__("vnstock_brief").VN30_TICKERS):
        try:
            out = {str(t).upper() for t in (get() or []) if str(t).strip()}
            if out:
                return out
        except Exception:
            continue
    return set()


def _sweep_universe(wh_root: Path, min_gtgd: float, since_days: int,
                    limit: int, delay: float,
                    with_universe: bool = True) -> int:
    """Quét universe thanh khoản, chỉ in mã ĐỔI BẬC tỉ lệ."""
    import time as _time

    import sys as _sys
    _scripts = str(Path(__file__).resolve().parent)
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    from check_unit_continuity import _is_equity, load_bars

    prices_dir = wh_root / "prices"
    every = sorted(p.name.removeprefix("ticker=")
                   for p in prices_dir.glob("ticker=*") if p.is_dir())
    equities = [t for t in every if _is_equity(t)]

    _uni = strategy_universe() if with_universe else set()
    if with_universe and not _uni:
        print("[basis] ⚠️ không lấy được universe backtest — chỉ quét theo "
              "ngưỡng GTGD, mã trong VN30/VNMID dưới ngưỡng sẽ BỊ BỎ SÓT")
    ranked, forced = [], []
    for tk in equities:
        df = load_bars(prices_dir, tk, since_days=since_days)
        if df.empty:
            continue
        tail = df.tail(20)
        try:
            g = float((pd.to_numeric(tail["close"], errors="coerce")
                       * pd.to_numeric(tail["volume"], errors="coerce")
                       / 1e6).median())
        except Exception:
            g = 0.0
        if g >= min_gtgd:
            ranked.append((g, tk))
        elif with_universe and tk in _uni:
            # Dưới ngưỡng thanh khoản NHƯNG nằm trong universe backtest ⇒ vẫn
            # phải soi: lệch cơ sở ở đây vào thẳng backtest.
            forced.append((g, tk))
    ranked.sort(reverse=True)
    dropped_liq = len(equities) - len(ranked) - len(forced)
    if forced:
        forced.sort(reverse=True)
        print(f"[basis] + {len(forced)} mã DƯỚI ngưỡng nhưng nằm trong universe "
              f"backtest (VN30/VNMID) — vẫn soi: "
              + ", ".join(t for _, t in forced[:10])
              + (" …" if len(forced) > 10 else ""))
        ranked = ranked + forced
    if limit and len(ranked) > limit:
        print(f"[basis] ⚠️ CẮT còn {limit}/{len(ranked)} mã theo --limit — "
              f"{len(ranked) - limit} mã thanh khoản thấp hơn KHÔNG được soi")
        ranked = ranked[:limit]

    print(f"[basis] quét {len(ranked):,} mã (GTGD20 ≥ {min_gtgd:,.1f} tỷ) · "
          f"bỏ {dropped_liq:,} mã dưới ngưỡng · "
          f"{len(every) - len(equities):,} CW/trái phiếu/chỉ số · "
          f"cửa sổ {since_days} ngày · mỗi mã 1 lần gọi nguồn")

    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    hits, errs, scanned = [], [], 0
    for n, (g, tk) in enumerate(ranked, 1):
        try:
            wh = load_wh(prices_dir, tk, d0, d1)
            src = fetch_source(tk, d0, d1)
            if wh.empty or src.empty:
                errs.append((tk, "không có bar một bên"))
                continue
            step = find_basis_step(wh, src)
            scanned += 1
            if step:
                step["ticker"], step["gtgd20"] = tk, g
                hits.append(step)
                print(f"  ⚠️ {tk:<8} {step['break']} · {step['shift']:.4f}× "
                      f"· GTGD20 ~{g:,.1f} tỷ")
        except Exception as e:
            errs.append((tk, f"{type(e).__name__}: {e}"))
        if delay:
            _time.sleep(delay)
        if n % 25 == 0:
            print(f"  … {n}/{len(ranked)} mã")

    print()
    if errs:
        # KHÔNG im lặng bỏ qua: mã không soi được ≠ mã sạch (vết 18/08).
        print(f"[basis] ⬜ {len(errs)} mã KHÔNG soi được (chưa kết luận gì): "
              + ", ".join(t for t, _ in errs[:12])
              + (" …" if len(errs) > 12 else ""))
    if not hits:
        print(f"[basis] ✅ {scanned:,} mã: tỉ lệ kho/nguồn KHÔNG đổi bậc")
    else:
        hits.sort(key=lambda h: -h["gtgd20"])
        print(f"[basis] ⚠️ {len(hits)}/{scanned:,} mã LỆCH CƠ SỞ, xếp theo "
              f"thanh khoản giảm dần:")
        for h in hits:
            print(f"   {h['ticker']:<8} vách {h['break']} · lệch "
                  f"{h['shift']:.4f}× · GTGD20 ~{h['gtgd20']:,.1f} tỷ")
        print("        Chữa từng mã: python scripts/rebase_ticker_history.py "
              "--ticker <MÃ> --break-date <ngày vách>")
    _write_sweep_stamp(wh_root, scanned, [h["ticker"] for h in hits],
                       [t for t, _ in errs])
    return 1 if hits else 0


def _write_sweep_stamp(wh_root: Path, scanned: int, suspect: list,
                       unchecked: list) -> None:
    """Ghi vết để badge doctor đọc được — cùng hợp đồng với bộ quét kia."""
    out = wh_root / "_meta" / "basis_sweep_check.json"
    payload = {"checked_at": datetime.now().isoformat(timespec="seconds"),
               "scanned": scanned, "suspect": sorted(suspect),
               "unchecked": sorted(unchecked)}
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, out)
    except Exception as e:
        print(f"[basis] (không ghi được vết quét: {e})")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ticker", action="append",
                    help="lặp lại được: --ticker VHM --ticker PNJ")
    ap.add_argument("--break-date",
                    help="ngày vách (YYYY-MM-DD); bỏ trống = tự tìm vách nặng nhất")
    ap.add_argument("--from", dest="d_from", help="mặc định: vách − 30 ngày")
    ap.add_argument("--to", dest="d_to", help="mặc định: vách + 30 ngày")
    ap.add_argument("--warehouse", default="data_warehouse")
    ap.add_argument("--sweep", action="store_true",
                    help="QUÉT universe thanh khoản tìm mã lệch cơ sở cỡ cổ "
                         "tức (2-5%%) — lớp lỗi mà check_unit_continuity mù "
                         "hoàn toàn vì nó nhìn vách giá, không nhìn tỉ lệ "
                         "kho/nguồn. Mỗi mã 1 lần gọi nguồn.")
    ap.add_argument("--no-universe", action="store_true",
                    help="CHỈ quét theo ngưỡng GTGD, bỏ luật 'mã trong universe "
                         "backtest luôn được soi'. Nhanh hơn, nhưng bỏ sót đúng "
                         "lớp mã mà backtest thật sự chạy trên đó.")
    ap.add_argument("--min-gtgd", type=float, default=5.0, metavar="TY",
                    help="sweep: ngưỡng GTGD20 (tỷ VND, mặc định 5) — dưới "
                         "ngưỡng thì mã không lọt universe chiến lược nên "
                         "lệch cơ sở ở đó không đổi quyết định nào")
    ap.add_argument("--since", type=int, default=365, metavar="N",
                    help="sweep: cửa sổ soi, mặc định 365 ngày")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="sweep: chỉ soi N mã thanh khoản nhất (0 = tất cả); "
                         "cắt bao nhiêu sẽ được IN RA, không cắt im lặng")
    ap.add_argument("--delay", type=float, default=0.3, metavar="S",
                    help="sweep: nghỉ giữa hai lần gọi nguồn (mặc định 0.3s)")
    args = ap.parse_args(argv)

    wh_root = Path(args.warehouse)
    if not wh_root.is_absolute():
        wh_root = REPO_ROOT / wh_root

    if args.sweep:
        return _sweep_universe(wh_root, args.min_gtgd, args.since,
                               args.limit, args.delay,
                               with_universe=not args.no_universe)
    if not args.ticker:
        ap.error("cần --ticker hoặc --sweep")

    worst = 0
    for _tk in args.ticker:
        rc = _probe_one(_tk.upper(), wh_root, args)
        worst = max(worst, rc)
    return worst


def _find_break(prices_dir: Path, ticker: str) -> "date | None":
    """Tự tìm ngày vách nặng nhất — khỏi bắt người dùng chép tay từ bảng quét.

    Dùng lại `find_jumps` của `check_unit_continuity` để hai công cụ không bao
    giờ bất đồng về "đâu là vách" (một nơi định nghĩa, hai nơi dùng).
    """
    import sys
    _scripts = str(Path(__file__).resolve().parent)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    # KHÔNG bọc try/except quanh cả hàm (vết 18/08): nuốt lỗi rồi trả None
    # khiến "kho sạch" và "tìm hỏng" in ra Y HỆT NHAU — người đọc tưởng đã
    # chữa xong trong khi thực ra chưa soi được gì. Lỗi phải NỔI LÊN.
    from check_unit_continuity import find_jumps, load_bars
    df = load_bars(prices_dir, ticker, since_days=365)
    if df.empty:
        raise RuntimeError(
            f"{ticker}: không đọc được bar nào trong 365 ngày từ {prices_dir} "
            f"— kho thiếu mã này, hay sai đường dẫn --warehouse?")
    hot = [j for j in find_jumps(df) if j["suspect"]]
    if not hot:
        return None
    return date.fromisoformat(max(hot, key=lambda j: abs(j["pct"]))["time"])


def _clamp_today(d: date) -> date:
    """Không bao giờ hỏi nguồn giá về NGÀY MAI.

    Vết 19/08: vách càng gần hôm nay thì `brk + 30 ngày` càng vượt quá hôm nay
    — VNM/2026-08-01 sinh ra khoảng tới 2026-08-31 và nguồn nổ
    `UnboundLocalError` (bọc trong RetryError), một lỗi vô nghĩa với người đọc.
    Xin dữ liệu tương lai là vô nghĩa dù thư viện có xử lý êm hay không.
    """
    today = date.today()
    return d if d <= today else today


def _probe_one(tk: str, wh_root: Path, args) -> int:
    if args.break_date:
        brk = date.fromisoformat(args.break_date)
    elif args.d_from:
        brk = date.fromisoformat(args.d_from)
    else:
        brk = _find_break(wh_root / "prices", tk)
        if brk is None:
            print(f"\n[basis] ⬜ {tk}: không tìm thấy vách nghi vấn trong 365 "
                  f"ngày — không có gì để phân định")
            return 0
        print(f"\n[basis] {tk}: vách tự tìm được = {brk}")
    d0 = date.fromisoformat(args.d_from) if args.d_from else brk - timedelta(days=30)
    d1 = date.fromisoformat(args.d_to) if args.d_to else brk + timedelta(days=30)
    d1 = _clamp_today(d1)
    wh = load_wh(wh_root / "prices", tk, d0, d1)
    print(f"[basis] {tk} · {d0} → {d1} · kho {len(wh)} bar")
    if wh.empty:
        print("[basis] ✗ kho không có bar nào trong khoảng — dừng")
        return 2
    try:
        src = fetch_source(tk, d0, d1)
    except Exception as e:
        print(f"[basis] ✗ không fetch được nguồn: {type(e).__name__}: {e}")
        return 2
    print(f"[basis] nguồn {len(src)} bar")
    if src.empty:
        print("[basis] ✗ nguồn trả rỗng — dừng")
        return 2

    rep = basis_report(wh, src, brk)
    rows = rep.get("rows")
    if rows is not None and not rows.empty:
        show = rows.copy()
        show["ratio"] = show["ratio"].round(4)
        print(show.to_string(index=False))
    print()
    if rep["verdict"] == "warehouse_basis":
        print(f"[basis] ⚠️ KHO LỆCH CƠ SỞ: kho/nguồn = {rep['ratio_before']:.4f}× "
              f"TRƯỚC {brk} nhưng {rep['ratio_after']:.4f}× TỪ {brk} "
              f"(đổi bậc {rep['shift']:.3f}×).")
        print("        Nguồn liền mạch còn kho gãy ⇒ lịch sử kho giữ cơ sở CŨ.")
        print("        Chữa: ghi đè phần lịch sử bằng dữ liệu nguồn "
              "(updater chỉ fetch từ bar cuối nên KHÔNG tự sửa được).")
    elif rep["verdict"] == "aligned":
        print(f"[basis] ✅ KHO KHỚP NGUỒN: tỉ lệ ≈ {rep['ratio_after']:.4f}× ở "
              f"cả hai phía {brk} và KHÔNG có vách tại ngày đó — không còn gì "
              f"để chữa ở mã này.")
    elif rep["verdict"] == "source_error":
        print(f"[basis] ⚠️ NGUỒN CŨNG GÃY: kho/nguồn ≈ {rep['ratio_after']:.4f}× "
              f"ở cả hai phía {brk} — kho chép đúng nguồn.")
        print("        Ghi đè kho VÔ ÍCH; chữa ở nguồn / cách ly bar hỏng.")
    else:
        print(f"[basis] ⬜ chưa kết luận ({rep['verdict']}): "
              f"{rep.get('n_before', 0)} bar trước · {rep.get('n_after', 0)} bar sau "
              f"— nới --from/--to rồi chạy lại.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

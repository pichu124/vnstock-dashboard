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
    python scripts/probe_price_basis.py --ticker VVS --break-date 2026-06-15
    python scripts/probe_price_basis.py --ticker VVS --from 2026-05-01 --to 2026-07-15

Exit: 0 in được đối chiếu · 2 không lấy được data một bên.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hai chuỗi coi là CÙNG cơ sở khi tỉ lệ nằm trong ±2% (làm tròn giá, tick size).
SAME_BASIS_TOL = 0.02


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
      * `source_error`  — hai bên cùng bậc ở CẢ HAI phía ⇒ nguồn cũng gãy.
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
    return {
        "verdict": "source_error" if same else "warehouse_basis",
        "n": len(m), "n_before": len(before), "n_after": len(after),
        "ratio_before": r_before, "ratio_after": r_after,
        "shift": r_before / r_after if r_after else float("nan"),
        "rows": m,
    }


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--break-date", help="ngày vách (YYYY-MM-DD)")
    ap.add_argument("--from", dest="d_from", help="mặc định: vách − 30 ngày")
    ap.add_argument("--to", dest="d_to", help="mặc định: vách + 30 ngày")
    ap.add_argument("--warehouse", default="data_warehouse")
    args = ap.parse_args(argv)

    if not args.break_date and not (args.d_from and args.d_to):
        ap.error("cần --break-date, hoặc cả --from và --to")
    brk = (date.fromisoformat(args.break_date) if args.break_date
           else date.fromisoformat(args.d_from))
    d0 = date.fromisoformat(args.d_from) if args.d_from else brk - timedelta(days=30)
    d1 = date.fromisoformat(args.d_to) if args.d_to else brk + timedelta(days=30)

    wh_root = Path(args.warehouse)
    if not wh_root.is_absolute():
        wh_root = REPO_ROOT / wh_root
    tk = args.ticker.upper()
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

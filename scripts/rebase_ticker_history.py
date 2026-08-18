"""Chữa KHO LỆCH CƠ SỞ: đưa lịch sử một mã về cùng cơ sở điều chỉnh với nguồn.

Bối cảnh (18/08): `probe_price_basis` chứng minh kho giữ CƠ SỞ CŨ ở phần lịch
sử — nguồn rebase cả chuỗi sau sự kiện quyền, còn `update_ticker` chỉ fetch từ
bar cuối nên không bao giờ sửa lại quá khứ. Đo được trên máy thật: VHM 2.0000×,
PNJ 1.4999×, GEX 1.4498×, GEE 1.7593×, PVD 1.6692×, VVS 1.6543× — 149 mã có
vách, trong đó VHM/PNJ nằm trong VN30.

Cách chữa, ưu tiên ĐÚNG hơn TIỆN:
1. Ngày nào NGUỒN CÓ → lấy thẳng giá nguồn (chính xác tuyệt đối, khỏi nhân chia).
2. Ngày nào nguồn KHÔNG có (cũ hơn độ phủ của nguồn) → nhân theo hệ số ĐO ĐƯỢC
   từ vùng chồng lấn, cho giá lẫn khối lượng (chia tách đổi cả hai).
Giữ nguyên độ sâu lịch sử của kho — backtest tầng vị thế cần 730 ngày, ghi đè
cụt bằng độ phủ nguồn là mất dữ liệu.

An toàn — ghi kho là việc khó lùi:
* MẶC ĐỊNH CHẠY THỬ. Phải `--apply` mới ghi thật.
* Từ chối chạy nếu `probe_price_basis` KHÔNG phán `warehouse_basis`.
* Sao lưu nguyên thư mục mã trước khi ghi (`_meta/backup_rebase/<mã>_<lúc>`).
* Ghi nguyên tử từng file (tmp + os.replace) — đúng bất biến `_MUST_BE_ATOMIC`.
* Ghi xong TỰ KIỂM: đọc lại, vách phải biến mất; còn thì báo đỏ.

Dùng
----
    python scripts/rebase_ticker_history.py --ticker VHM              # chạy thử
    python scripts/rebase_ticker_history.py --ticker VHM --apply      # ghi thật
    python scripts/rebase_ticker_history.py --ticker VHM --ticker PNJ --apply

Exit: 0 xong/sạch · 1 có mã không chữa được · 2 lỗi đọc kho/nguồn.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(Path(__file__).resolve().parent)
for _p in (str(REPO_ROOT), _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OHLC = ("open", "high", "low", "close")
# Vùng chồng lấn tối thiểu để tin hệ số đo được. Dưới mức này thì một vài bar
# lẻ có thể kéo trung vị đi — thà không chữa còn hơn chữa sai cả lịch sử.
MIN_OVERLAP = 5


def _probe(tk: str, wh_root: Path, brk: date, win: int = 30) -> dict:
    from probe_price_basis import basis_report, fetch_source, load_wh
    d0, d1 = brk - timedelta(days=win), brk + timedelta(days=win)
    wh = load_wh(wh_root / "prices", tk, d0, d1)
    src = fetch_source(tk, d0, d1)
    if wh.empty or src.empty:
        return {"verdict": "no_overlap", "n": 0}
    return basis_report(wh, src, brk)


def _read_all(tdir: Path) -> "dict[Path, pd.DataFrame]":
    out = {}
    for pq in sorted(tdir.glob("year=*/*.parquet")):
        try:
            out[pq] = pd.read_parquet(pq)
        except Exception:
            continue
    return out


def _measure_volume_factor(wh: pd.DataFrame, src: pd.DataFrame) -> float:
    """Chia tách đổi CẢ số lượng cổ phiếu — khối lượng lịch sử cũng phải quy đổi.

    Đo thay vì suy: nguồn có thể điều chỉnh volume hoặc không. Không đo được
    (volume 0, không chồng lấn) → trả 1.0 và để nguyên, đừng đoán.
    """
    try:
        m = wh.merge(src, on="time", suffixes=("_wh", "_src"))
        m = m[(m["volume_wh"] > 0) & (m["volume_src"] > 0)]
        if len(m) < MIN_OVERLAP:
            return 1.0
        return float((m["volume_src"] / m["volume_wh"]).median())
    except Exception:
        return 1.0


def _volume_step(wh_head: pd.DataFrame, brk: date, n: int = 20) -> float:
    """Khối lượng có NHẢY BẬC tại ngày vách không (trung vị sau / trước).

    Vì sao phải hỏi: chia tách 1:1 làm SỐ CỔ PHIẾU gấp đôi, nên khối lượng
    sau vách tự nhiên gấp ~2× trước vách. Nếu nguồn chỉ điều chỉnh GIÁ mà
    không điều chỉnh KHỐI LƯỢNG (đo được hệ số volume ≈ 1.0), thì chữa giá
    xong sẽ tạo ra lỗi MỚI: giá lịch sử /2 mà khối lượng giữ nguyên ⇒ GTGD
    lịch sử còn một nửa, mà GTGD chính là thứ screener/strategy dùng để lọc
    thanh khoản. Đo rồi quyết, đừng mặc định.
    """
    try:
        before = wh_head[wh_head["time"].dt.date < brk].tail(n)["volume"]
        after = wh_head[wh_head["time"].dt.date >= brk].head(n)["volume"]
        b, a = float(before.median()), float(after.median())
        return a / b if b > 0 else float("nan")
    except Exception:
        return float("nan")


def _rebase_one(tk: str, wh_root: Path, apply: bool,
                volume_mode: str = "auto") -> int:
    from check_unit_continuity import find_jumps, load_bars
    from probe_price_basis import _find_break, fetch_source

    prices_dir = wh_root / "prices"
    tdir = prices_dir / f"ticker={tk}"
    if not tdir.exists():
        print(f"\n[rebase] ⬜ {tk}: không có trong kho")
        return 1

    brk = _find_break(prices_dir, tk)
    if brk is None:
        print(f"\n[rebase] ✅ {tk}: không còn vách nghi vấn trong 365 ngày")
        return 0
    print(f"\n[rebase] {tk} · vách {brk}")

    rep = _probe(tk, wh_root, brk)
    if rep.get("verdict") != "warehouse_basis":
        print(f"[rebase] ✗ TỪ CHỐI: probe phán '{rep.get('verdict')}' chứ không "
              f"phải 'warehouse_basis' — chữa kiểu này chỉ đúng khi NGUỒN liền "
              f"mạch mà KHO gãy. Soi tay: probe_price_basis --ticker {tk}")
        return 1
    factor = float(rep["shift"])
    print(f"[rebase] hệ số cơ sở đo được: {factor:.4f}× "
          f"({rep['n_before']} bar trước · {rep['n_after']} bar sau)")

    files = _read_all(tdir)
    if not files:
        print(f"[rebase] ✗ không đọc được parquet nào")
        return 1
    first = min(pd.to_datetime(df["time"]).min() for df in files.values()).date()

    # Nguồn cho TOÀN dải kho — ngày nào nguồn có thì lấy thẳng, khỏi nhân chia.
    try:
        src_full = fetch_source(tk, first, date.today())
    except Exception as e:
        print(f"[rebase] ✗ không fetch được nguồn: {type(e).__name__}: {e}")
        return 2
    src_all = None
    try:
        from vnstock_updater import _fetch_prices
        src_all = _fetch_prices(tk, first.isoformat(), date.today().isoformat())
        src_all["time"] = pd.to_datetime(src_all["time"]).dt.normalize()
    except Exception:
        src_all = None
    if src_all is None or src_all.empty:
        print(f"[rebase] ✗ nguồn trả rỗng cho dải {first} → nay")
        return 2
    src_from = src_all["time"].min().date()
    print(f"[rebase] kho từ {first} · nguồn phủ từ {src_from} "
          f"({len(src_all):,} bar)")

    wh_head = load_bars(prices_dir, tk, since_days=0)
    wh_head["time"] = pd.to_datetime(wh_head["time"]).dt.normalize()
    vol_factor = _measure_volume_factor(
        wh_head[wh_head["time"].dt.date < brk],
        src_all[src_all["time"].dt.date < brk])
    step = _volume_step(wh_head, brk)
    print(f"[rebase] khối lượng: nguồn/kho = {vol_factor:.4f}× · "
          f"bậc nhảy tại vách (sau/trước) = {step:.2f}×")
    # Nguồn KHÔNG điều chỉnh volume (≈1.0) MÀ khối lượng lại nhảy bậc đúng
    # bằng hệ số giá ⇒ chuỗi volume cũng đang gãy; chữa giá mà bỏ volume là
    # đổi một lỗi lấy một lỗi khác.
    scale_vol = 1.0
    _near = abs(step - factor) <= 0.35 * factor if step == step else False
    if volume_mode == "adjust" or (volume_mode == "auto" and
                                   abs(vol_factor - 1.0) < 0.05 and _near):
        scale_vol = factor
        print(f"[rebase] → NHÂN khối lượng lịch sử × {scale_vol:.4f} "
              f"(nguồn chỉ điều chỉnh giá; không nhân thì GTGD lịch sử còn "
              f"1/{factor:.2f} thực tế — screener lọc thanh khoản bằng số đó)")
    elif volume_mode == "source":
        print("[rebase] → GIỮ NGUYÊN khối lượng theo nguồn (--volume source)")
    else:
        print("[rebase] → giữ khối lượng theo nguồn: không thấy bằng chứng "
              "volume gãy tại vách")

    n_src, n_scaled, touched = 0, 0, 0
    plan = {}
    src_idx = src_all.set_index(src_all["time"].dt.normalize())
    for path, df in files.items():
        out = df.copy()
        t = pd.to_datetime(out["time"]).dt.normalize()
        mask_old = t.dt.date < brk
        if not mask_old.any():
            continue
        for i in out.index[mask_old]:
            day = t.loc[i]
            if day in src_idx.index:
                row = src_idx.loc[day]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                for c in OHLC:
                    if c in out.columns and c in row:
                        out.at[i, c] = float(row[c])
                if "volume" in out.columns and "volume" in row:
                    out.at[i, "volume"] = float(row["volume"]) * scale_vol
                n_src += 1
            else:
                for c in OHLC:
                    if c in out.columns:
                        out.at[i, c] = float(out.at[i, c]) / factor
                if "volume" in out.columns:
                    _vf = vol_factor if vol_factor != 1.0 else scale_vol
                    if _vf != 1.0:
                        out.at[i, "volume"] = float(out.at[i, "volume"]) * _vf
                n_scaled += 1
            touched += 1
        plan[path] = out

    print(f"[rebase] {touched:,} bar trước {brk} sẽ đổi: "
          f"{n_src:,} lấy thẳng từ nguồn · {n_scaled:,} nhân hệ số")
    if not apply:
        print(f"[rebase] 🔎 CHẠY THỬ — chưa ghi gì. Thêm --apply để ghi thật.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = wh_root / "_meta" / "backup_rebase" / f"{tk}_{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tdir, backup)
    print(f"[rebase] 💾 sao lưu: {backup}")

    for path, out in plan.items():
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        out.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    print(f"[rebase] ✍ đã ghi {len(plan)} file (nguyên tử)")

    left = [j for j in find_jumps(load_bars(prices_dir, tk, since_days=365))
            if j["suspect"]]
    if left:
        print(f"[rebase] ⚠️ VẪN CÒN {len(left)} vách sau khi chữa "
              f"(vách đầu: {left[0]['time']}) — có thể mã bị rebase NHIỀU LẦN, "
              f"chạy lại lệnh này để chữa tiếp lớp sau.")
        return 1
    print(f"[rebase] ✅ {tk}: chuỗi đã liền — không còn vách trong 365 ngày")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ticker", required=True, action="append")
    ap.add_argument("--warehouse", default="data_warehouse")
    ap.add_argument("--apply", action="store_true",
                    help="GHI THẬT vào kho (mặc định chỉ chạy thử)")
    ap.add_argument("--volume", choices=("auto", "adjust", "source"),
                    default="auto",
                    help="auto (mặc định): nhân khối lượng theo hệ số giá KHI "
                         "đo thấy nguồn không điều chỉnh volume mà chuỗi volume "
                         "lại gãy tại vách · adjust: luôn nhân · source: luôn "
                         "giữ nguyên theo nguồn")
    args = ap.parse_args(argv)

    wh_root = Path(args.warehouse)
    if not wh_root.is_absolute():
        wh_root = REPO_ROOT / wh_root
    worst = 0
    for tk in args.ticker:
        worst = max(worst, _rebase_one(tk.upper(), wh_root, args.apply,
                                       args.volume))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())

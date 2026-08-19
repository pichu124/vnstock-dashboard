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
import json
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
# Dưới hệ số này, bậc nhảy khối lượng KHÔNG phân biệt được với dao động thường
# ngày, nên nó không còn là bằng chứng gì. Chia tách/thưởng thật đổi giá ít
# nhất ~15%; cổ tức tiền mặt VN thường 2-8%. Ca VNM 19/08: hệ số 1.0327 mà
# heuristic cũ vẫn "thấy" bậc nhảy 1.03 rồi định nhân volume 5.089 bar.
VOL_SIGNAL_MIN_FACTOR = 1.15


def _corp_action_kind(tk: str, wh_root: Path, brk: date) -> "str | None":
    """Loại sự kiện quyền quanh ngày vách: cash / stock / split / bonus.

    Dùng lại kho sự kiện đã có (match_corp_action -> vnstock_adjust.load_events)
    theo nếp một-nơi-định-nghĩa. Không tra được thì trả None để chỗ gọi tự
    quyết, KHÔNG đoán bừa.
    """
    try:
        from check_unit_continuity import match_corp_action
        ev = match_corp_action(tk, wh_root, brk.isoformat())
        return str(ev.get("type")) if ev else None
    except Exception:
        return None


def _probe(tk: str, wh_root: Path, brk: date, win: int = 30) -> dict:
    from probe_price_basis import basis_report, fetch_source, load_wh
    d0, d1 = brk - timedelta(days=win), brk + timedelta(days=win)
    d1 = min(d1, date.today())     # xin giá tương lai là vô nghĩa (vết 19/08)
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


def _basis_break_of(tk: str, wh_root: Path, since_days: int = 365) -> "date | None":
    """Ngày ĐỔI BẬC tỉ lệ kho/nguồn — bộ dò dành cho lệch cỡ cổ tức.

    `_find_break` chỉ thấy vách giá ≥30% nên mù với lớp lỗi này (ca VNM
    1.0327×). Dùng chung `find_basis_step` với chế độ quét để hai bên không
    bao giờ bất đồng về "vách ở đâu".
    """
    from probe_price_basis import fetch_source, find_basis_step, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    wh = load_wh(wh_root / "prices", tk, d0, d1)
    if wh.empty:
        return None
    src = fetch_source(tk, d0, d1)
    if src.empty:
        return None
    step = find_basis_step(wh, src)
    return step["break"] if step else None


def _sweep_targets(wh_root: Path) -> list:
    """Danh sách mã từ vết quét gần nhất. Lỗi đọc thì trả rỗng, KHÔNG đoán."""
    p = wh_root / "_meta" / "basis_sweep_check.json"
    if not p.exists():
        print(f"[rebase] ✗ chưa có vết quét ({p}) — chạy trước: "
              f"python scripts/probe_price_basis.py --sweep")
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[rebase] ✗ vết quét hỏng ({type(e).__name__}: {e})")
        return []
    return list(data.get("suspect") or [])


def _rebase_one(tk: str, wh_root: Path, apply: bool,
                volume_mode: str = "auto",
                break_date: "date | None" = None) -> int:
    from check_unit_continuity import find_jumps, load_bars
    from probe_price_basis import _find_break, fetch_source

    prices_dir = wh_root / "prices"
    tdir = prices_dir / f"ticker={tk}"
    if not tdir.exists():
        print(f"\n[rebase] ⬜ {tk}: không có trong kho")
        return 1

    if break_date is not None:
        # Vách do NGƯỜI chỉ định: `_find_break` chỉ thấy vách ≥30%, nên lệch cơ
        # sở cỡ CỔ TỨC (2-5%) hoàn toàn vô hình với nó. Ca VNM 19/08:
        # kho/nguồn 1.0327× trước 2026-06-23 rồi 1.0000× từ đó — một mã VN30
        # lệch 3,27% suốt phần lịch sử, mà quét liên tục KHÔNG hề kêu.
        brk = break_date
        print(f"\n[rebase] {tk}: vách do người chỉ định = {brk}")
    else:
        try:
            brk = _find_break(prices_dir, tk)
        except Exception as e:
        # Phân biệt RÕ "sạch" với "không soi được" — gộp hai cái làm một là
        # cách chắc chắn nhất để người dùng tưởng đã chữa xong (vết 18/08).
            print(f"\n[rebase] ✗ {tk}: KHÔNG SOI ĐƯỢC ({type(e).__name__}: {e}) "
                  f"— chưa kết luận được gì, ĐỪNG coi là sạch")
            return 1
    if brk is None:
        # Không có vách GIÁ ≥30% ≠ không có lệch cơ sở: lớp lỗi cỡ cổ tức
        # (2-5%) chỉ hiện qua TỈ LỆ kho/nguồn (ca VNM 19/08, và 70/159 mã
        # universe thanh khoản). Hỏi nốt bộ dò kia trước khi tuyên bố sạch.
        brk = _basis_break_of(tk, wh_root)
        if brk is not None:
            print(f"\n[rebase] {tk}: không có vách giá, nhưng TỈ LỆ kho/nguồn "
                  f"đổi bậc tại {brk}")
    if brk is None:
        print(f"\n[rebase] ✅ {tk}: không còn vách nghi vấn trong 365 ngày "
              f"(soi {len(load_bars(prices_dir, tk, since_days=365)):,} bar)")
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
    # HỎI SỰ KIỆN QUYỀN TRƯỚC KHI SUY TỪ SỐ (vá 19/08, ca VNM).
    # Chỉ sự kiện ĐỔI SỐ CỔ PHIẾU (split/bonus) mới kéo theo khối lượng; cổ tức
    # TIỀN MẶT hạ giá mà KHÔNG tạo thêm cổ phiếu nào — nhân volume lên là bịa
    # ra cổ phiếu chưa từng khớp.
    # Vì sao heuristic cũ không đủ: nó chỉ hỏi "bậc nhảy volume có gần hệ số giá
    # không". Với hệ số 1.0327 (VNM), điều kiện đó thoả với MỌI bậc trong
    # khoảng 0.67-1.39 lần — tức toàn bộ dao động khối lượng thường ngày. Ở hệ
    # số nhỏ, bậc nhảy volume KHÔNG mang tín hiệu; 1.95 lần của VHM mới là
    # tín hiệu thật.
    _ev = _corp_action_kind(tk, wh_root, brk)
    _shares_changed = _ev in ("split", "bonus")
    _too_small_to_tell = factor < VOL_SIGNAL_MIN_FACTOR
    if _ev:
        print(f"[rebase] sự kiện quyền quanh vách: {_ev}"
              + (" -> CÓ đổi số cổ phiếu" if _shares_changed
                 else " -> KHÔNG đổi số cổ phiếu"))
    if volume_mode == "auto" and _ev == "cash":
        print("[rebase] -> GIỮ NGUYÊN khối lượng: cổ tức TIỀN MẶT không tạo "
              "thêm cổ phiếu nào (nhân lên là bịa ra khối lượng chưa từng khớp)")
    elif volume_mode == "auto" and not _ev and _too_small_to_tell:
        print(f"[rebase] -> GIỮ NGUYÊN khối lượng: hệ số {factor:.4f} lần quá "
              f"nhỏ để bậc nhảy volume mang tín hiệu (ngưỡng "
              f"{VOL_SIGNAL_MIN_FACTOR}) và không tra được sự kiện quyền — thà "
              f"không chữa còn hơn chữa sai. Chắc chắn là chia tách/thưởng thì "
              f"ép bằng --volume adjust")
    elif volume_mode == "adjust" or (volume_mode == "auto" and
                                     abs(vol_factor - 1.0) < 0.05 and _near
                                     and (_shares_changed or not _too_small_to_tell)):
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
    ap.add_argument("--ticker", action="append")
    ap.add_argument("--warehouse", default="data_warehouse")
    ap.add_argument("--apply", action="store_true",
                    help="GHI THẬT vào kho (mặc định chỉ chạy thử)")
    ap.add_argument("--break-date",
                    help="ngày vách (YYYY-MM-DD) khi tự tìm KHÔNG ra — lệch cơ "
                         "sở cỡ cổ tức (2-5%%) nằm dưới ngưỡng 30%% của bộ dò, "
                         "phải lấy ngày từ probe_price_basis")
    ap.add_argument("--from-sweep", action="store_true",
                    help="chữa HÀNG LOẠT mọi mã trong vết quét gần nhất "
                         "(_meta/basis_sweep_check.json). Mỗi mã vẫn qua đủ "
                         "cửa: probe phải phán warehouse_basis mới ghi, có sao "
                         "lưu + tự kiểm riêng. Mặc định vẫn CHẠY THỬ.")
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
    tickers = [t.upper() for t in (args.ticker or [])]
    if args.from_sweep:
        tickers = _sweep_targets(wh_root) or tickers
        if not tickers:
            return 2
        print(f"[rebase] chữa hàng loạt {len(tickers)} mã từ vết quét"
              + ("" if args.apply else " — CHẠY THỬ, chưa ghi gì"))
    if not tickers:
        ap.error("cần --ticker hoặc --from-sweep")

    worst, done, refused = 0, 0, []
    for tk in tickers:
        _bd = date.fromisoformat(args.break_date) if args.break_date else None
        rc = _rebase_one(tk, wh_root, args.apply, args.volume, _bd)
        worst = max(worst, rc)
        if rc == 0:
            done += 1
        else:
            refused.append(tk)
    if len(tickers) > 1:
        print(f"\n[rebase] TỔNG: {done}/{len(tickers)} mã xong"
              + (f" · {len(refused)} mã KHÔNG chữa được: "
                 + ", ".join(refused[:15]) + (" …" if len(refused) > 15 else "")
                 if refused else ""))
        if refused:
            # Không gộp "chưa chữa được" vào "xong" (vết 18/08): người đọc
            # thấy dòng TỔNG rồi tưởng cả rổ đã sạch.
            print("[rebase]   → mã ở trên CHƯA sạch, soi từng cái bằng "
                  "probe_price_basis trước khi kết luận")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())

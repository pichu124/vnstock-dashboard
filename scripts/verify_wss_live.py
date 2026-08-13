"""
Verify tay mục 1 checklist (docs/CLAUDE-NOTES.md): WSS volume tích luỹ.

Chạy TRONG GIỜ GIAO DỊCH (9:00-15:00 giờ VN, thứ 2-6):

    python scripts\\verify_wss_live.py                 # mặc định 300s (5 phút)
    python scripts\\verify_wss_live.py --duration 120  # thử nhanh hơn

Script tự làm trọn gói: mở WSS (VN30 + index + futures, 38 mã), gom bar
1 phút, rồi CHẤM 3 bất biến của đợt fix 07/08:

  [1] Mã cổ phiếu volume > 0     — feed gửi accumulatedvolume cho cổ phiếu
  [2] Index/futures volume == 0  — feed KHÔNG gửi accum cho VNINDEX/VN30F1M;
                                   trước fix, fallback volume TỪNG TICK bị
                                   cộng dồn thành số ảo (78x trên AAA)
  [3] suspect_count == 0         — sanity check không phải chặn tick nào

Exit code: 0 = đạt hết · 1 = CHƯA KẾT LUẬN ĐƯỢC (ngoài giờ / thiếu tick —
không đo được KHÁC với đo ra kết quả xấu) · 2 = có bất biến SAI.

Logic chấm nằm trong hàm thuần ``grade()`` — có lưới test ở
``tests/test_verify_wss_live.py`` (script chỉ chạy được trong phiên,
nhưng phần chấm điểm thì test được quanh năm).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

_OK, _UNSURE, _FAIL = 0, 1, 2


def _grade_stocks(vol: "pd.Series", non_stock: set[str]) -> tuple[str, int]:
    """Bất biến [1]: mã cổ phiếu phải có volume > 0."""
    stock_vol = vol[~vol.index.isin(non_stock)]
    if stock_vol.empty:
        return "⚠️ [1] Không gom được bar cổ phiếu nào — chưa chấm được.", _UNSURE
    traded = stock_vol[stock_vol > 0]
    zeros = sorted(stock_vol[stock_vol <= 0].index)
    if traded.empty:
        return ("❌ [1] TOÀN BỘ mã cổ phiếu volume = 0 — feed đổi schema "
                "hoặc lỗi accum→delta quay lại?", _FAIL)
    if len(traded) < 0.5 * len(stock_vol):
        return (f"⚠️ [1] Chỉ {len(traded)}/{len(stock_vol)} mã có volume > 0 "
                f"(mã volume 0: {', '.join(zeros[:8])}…) — chạy lại lâu hơn "
                f"hoặc giờ thanh khoản cao hơn.", _UNSURE)
    top = traded.sort_values(ascending=False).head(3)
    top_txt = ", ".join(f"{t} {v:,.0f}" for t, v in top.items())
    return (f"✅ [1] {len(traded)}/{len(stock_vol)} mã cổ phiếu volume > 0 "
            f"(top: {top_txt})", _OK)


def _grade_non_stock(vol: "pd.Series", non_stock: set[str]) -> tuple[str, int]:
    """Bất biến [2]: index/futures phải volume == 0."""
    ns_vol = vol[vol.index.isin(non_stock)]
    if ns_vol.empty:
        return ("⚠️ [2] Không thấy bar index/futures nào — chưa chấm được "
                "(VNINDEX thường tick liên tục trong phiên).", _UNSURE)
    leaks = ns_vol[ns_vol > 0]
    if not leaks.empty:
        leak_txt = ", ".join(f"{t} = {v:,.0f}" for t, v in leaks.items())
        return (f"❌ [2] Index/futures CÓ volume ({leak_txt}) — fallback "
                f"cộng dồn từng tick quay lại?", _FAIL)
    return (f"✅ [2] Index/futures volume == 0 đúng thiết kế "
            f"({', '.join(sorted(ns_vol.index))})", _OK)


def _grade_suspects(diag: dict) -> tuple[str, int]:
    """Bất biến [3]: sanity check không phải chặn tick nào."""
    count = diag.get("suspect_count")
    if count is None:
        return "⚠️ [3] diagnostics thiếu suspect_count — chưa chấm được.", _UNSURE
    if count > 0:
        samples = diag.get("suspect_samples", [])[:3]
        return (f"❌ [3] suspect_count = {count:,} (mẫu: {samples}) — có tick "
                f"volume bất thường bị chặn.", _FAIL)
    return "✅ [3] suspect_count = 0 — không tick nào bị nghi ngờ.", _OK


def grade(snap: "pd.DataFrame", diag: dict,
          index_syms: set[str], futures_syms: set[str]) -> tuple[list[str], int]:
    """
    Chấm 3 bất biến từ snapshot bars + diagnostics của BarAggregator.

    Trả (danh sách dòng in, exit code). Hàm thuần — không I/O, không đổi
    input — để test được mà không cần phiên giao dịch.
    """
    if snap.empty:
        return (["⚠️ Không gom được bar nào — ngoài giờ giao dịch, mạng đứt, "
                 "hoặc feed đổi? Chạy lại trong phiên (9:00-15:00 T2-T6)."],
                _UNSURE)
    vol = snap.groupby("ticker")["volume"].sum()
    non_stock = {s.upper() for s in index_syms} | {s.upper() for s in futures_syms}
    results = [
        _grade_stocks(vol, non_stock),
        _grade_non_stock(vol, non_stock),
        _grade_suspects(diag),
    ]
    return [line for line, _ in results], max(code for _, code in results)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify WSS volume tích luỹ (mục 1 checklist)")
    parser.add_argument("--duration", type=int, default=300,
                        help="Số giây gom tick, 60-900 (mặc định 300)")
    args = parser.parse_args()
    duration = max(60, min(900, args.duration))

    os.chdir(REPO_ROOT)         # LIVE_DIR trong vnstock_wss là đường dẫn tương đối
    sys.path.insert(0, str(REPO_ROOT))
    from datetime import datetime

    from vnstock_wss import (FUTURES_SYMBOLS, INDEX_SYMBOLS, LIVE_DIR,
                             get_wss_client)

    client = get_wss_client()
    if not client._is_market_open():
        print("⚠️ NGOÀI GIỜ GIAO DỊCH (9:00-15:00 giờ VN, thứ 2-6) — WSS sẽ")
        print("   đứng im, không có gì để chấm. Chạy lại script trong phiên.")
        return _UNSURE

    print(f"[verify] Mở WSS, gom tick {duration}s (VN30 + index + futures)…")
    client.start()
    client.subscribe_all()      # 38 mã — đủ cho 3 bất biến, nhẹ máy

    start = time.time()
    while time.time() - start < duration:
        time.sleep(15)
        status = client.get_status()
        diag = client.aggregator.diagnostics()
        err = (status.get("error") or "-")[:40]
        print(f"  [{int(time.time() - start):3d}s] status={status['status']} "
              f"bars={diag['active_bars']} suspect={diag['suspect_count']} "
              f"err={err}")

    print("[verify] Flush bars → parquet…")
    client._flush_bars()
    snap = client.aggregator.snapshot()
    diag = client.aggregator.diagnostics()
    client.stop()

    lines, code = grade(snap, diag, set(INDEX_SYMBOLS), set(FUTURES_SYMBOLS))
    print()
    print("=" * 62)
    print("KẾT QUẢ CHẤM 3 BẤT BIẾN (đợt fix WSS 07/08)")
    print("=" * 62)
    for line in lines:
        print(line)
    bars_file = LIVE_DIR / f"bars_{datetime.now():%Y-%m-%d}.parquet"
    if bars_file.exists():
        print(f"\nFile bar: {bars_file} ({bars_file.stat().st_size:,} bytes)")

    print("\nTiện cùng phiên (mục ↪ checklist): mở dashboard → tab Phân tích")
    print("→ sidebar 🔴 Live Mode bật 'Real-time WSS' → sang tab Thị trường")
    print("xem Live Market Heatmap VN30 có cập nhật ô màu theo tick không.")

    if code == _OK:
        print("\n✅ ĐẠT CẢ 3 — tick được mục 1 trong checklist.")
    elif code == _UNSURE:
        print("\n⚠️ CHƯA KẾT LUẬN ĐƯỢC — xem dòng ⚠️ ở trên rồi chạy lại.")
    else:
        print("\n❌ CÓ BẤT BIẾN SAI — dán NGUYÊN output này cho Claude.")
    return code


if __name__ == "__main__":
    sys.exit(main())

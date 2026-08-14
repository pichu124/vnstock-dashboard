"""In HÌNH DẠNG THÔ dữ liệu cổ tức/sự kiện của từng nguồn cho vài mã.

Đồ nghề chẩn đoán vùng mù 4d (14/08): VNM/SAB/VPB… 0 sự kiện trong 750
ngày dù trả cổ tức đều — câu hỏi phân xử: NGUỒN mù thật, hay EXTRACTOR
(`vnstock_adjust._extract_dividends`) chưa đọc được DẠNG dữ liệu (ví dụ
cổ tức ghi theo % mệnh giá thay vì VND, tên cột ngoài danh sách đang dò)?

    python scripts/dump_dividend_shape.py VNM SAB GVR

In cột + 5 dòng đầu của dividends()/events()/capital_history() theo từng
nguồn. DÁN NGUYÊN output cho Claude — nếu là dạng chưa đọc được, viết
thêm parser là 11 mã vùng mù sáng đèn; nếu rỗng thật thì chốt giới hạn.
(Là script riêng vì lệnh `python -c` nhiều nháy từng bị PowerShell nuốt —
bài học 11/08.)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def _dump(label: str, fetch) -> None:
    try:
        df = fetch()
    except Exception as e:
        print(f"    {label}: LỖI {type(e).__name__}: {str(e)[:120]}")
        return
    if df is None or getattr(df, "empty", True):
        print(f"    {label}: rỗng")
        return
    print(f"    {label}: {len(df)} dòng · cột = {list(df.columns)}")
    try:
        head = df.head(5).to_string()
        print("      " + head.replace("\n", "\n      "))
    except Exception:
        pass


def main() -> int:
    tickers = [t.upper() for t in sys.argv[1:]] or ["VNM"]
    from vnstock_adjust import _company_sources

    for ticker in tickers:
        print(f"\n{'=' * 20} {ticker} {'=' * 20}")
        for source_name, resolve in _company_sources():
            print(f"  [{source_name}]")
            try:
                company = resolve(ticker)
            except Exception as e:
                print(f"    resolve LỖI: {type(e).__name__}: {str(e)[:120]}")
                continue
            if company is None:
                print("    resolve trả None")
                continue
            for method in ("dividends", "events", "capital_history"):
                if hasattr(company, method):
                    _dump(method, getattr(company, method))
                else:
                    print(f"    {method}: (nguồn không có hàm này)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

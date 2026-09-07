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

Ca KHÔNG có vách (26/08) — nguồn back-adjust TRỌN lịch sử nên kho lệch cùng
một hệ số ở MỌI bar. Cả hai bộ dò bậc đều mù (đạo hàm bằng 0 ở mọi điểm) và
`_probe` luôn phán `aligned` vì trước = sau; chỉ cửa gác và bộ dò MỨC thấy:

    python scripts/rebase_ticker_history.py --ticker SDK --whole-series
    python scripts/rebase_ticker_history.py --ticker SDK --whole-series --apply

Chế độ đó coi TOÀN chuỗi là phần "trước vách", nên cửa vào KHÔNG phải `_probe`
mà là `uniform_offset_report` — chặt hơn: tỉ lệ phải vừa lệch vừa ỔN ĐỊNH.

Exit: 0 xong/sạch · 1 có mã không chữa được · 2 lỗi đọc kho/nguồn.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(Path(__file__).resolve().parent)
for _p in (str(REPO_ROOT), _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OHLC = ("open", "high", "low", "close")
# Kho nằm TRONG Dropbox (junction `C:\vnstock\data_warehouse`). Dropbox mở
# file để băm/tải lên NGAY SAU khi `shutil.copytree` sao lưu chạm vào chúng,
# nên `os.replace` gặp `WinError 5 Access is denied` đúng lúc tệ nhất — giữa
# một lượt ghi. Đo 07/09 trên desktop: chết ở file ĐẦU TIÊN của BRC, ngay sau
# dòng "💾 sao lưu". Retry ngắn là đủ cho khoá tạm; bit read-only thì retry
# bao nhiêu cũng vô ích nên thử gỡ ngay lần hỏng đầu.
REPLACE_RETRIES = 5
REPLACE_BACKOFF_S = 0.4
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


def _atomic_replace(tmp: Path, path: Path) -> None:
    """`os.replace` có retry — bắt buộc vì kho đi qua Dropbox.

    Giữ nguyên bất biến `_MUST_BE_ATOMIC`: vẫn là một `os.replace`, chỉ thử
    lại. KHÔNG bao giờ rơi về copy-đè, vì đó mới là thứ phá nguyên tử.
    """
    last = None
    for i in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            if i == 0:
                # Bit read-only KHÔNG tự hết theo thời gian — gỡ ngay, đừng
                # ngủ 5 lượt rồi mới báo hỏng.
                try:
                    os.chmod(path, stat.S_IWRITE)
                except Exception:
                    pass
            if i < REPLACE_RETRIES - 1:
                time.sleep(REPLACE_BACKOFF_S * (2 ** i))
    raise PermissionError(
        f"{path.name}: không thay được file sau {REPLACE_RETRIES} lượt "
        f"({last}). Kho nằm trong Dropbox — TẠM DỪNG ĐỒNG BỘ (Dropbox → "
        f"Pause syncing) hoặc tắt quét realtime của antivirus rồi chạy lại.")


def _sweep_tmp(tdir: Path) -> int:
    """Dọn file tạm CỦA CHÍNH LƯỢT NÀY. Rác `.tmp` trong `prices/` làm mọi bộ
    đếm file/năm sau đó đọc sai."""
    n = 0
    for t in tdir.glob(f"year=*/*.{os.getpid()}.tmp"):
        try:
            t.unlink()
            n += 1
        except Exception:
            pass
    return n


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


def _as_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Đưa cột time về `date` thuần để hai phía merge được dù ai chuẩn hoá kiểu gì."""
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"]).dt.date
    return out


def last_divergent_day(wh: pd.DataFrame, src: pd.DataFrame,
                       tol: float = 0.012,
                       today: "date | None" = None) -> "date | None":
    """Ngày CUỐI CÙNG giá kho còn lệch nguồn quá `tol` — mốc chữa thật sự.

    Hàm THUẦN (test được offline). Vì sao không dừng ở ngày vách: bộ dò chỉ
    trả về MỘT vách — cái nhảy mạnh nhất. Mã bị nguồn rebase NHIỀU LẦN (mỗi
    mùa quyền một lần) có nhiều bậc chồng nhau; chữa "mọi bar TRƯỚC vách" thì
    bậc Ở GIỮA sống sót, mà lần chạy sau bộ dò VẪN chỉ đúng cái vách cũ nên
    ghi lại y hệt phần đã đúng ⇒ chạy bao nhiêu lượt cũng không hội tụ.
    Đo được 19/08 sau lượt 70 mã: VTP (còn 0.8521×) và QNS (0.9785×) là hai
    mã duy nhất có bậc thứ hai, và chúng đứng yên qua mọi lượt chạy lại.

    Bỏ bar HÔM NAY: phiên chưa đóng thì bar kho (dựng từ rollup 1 phút) lệch
    bar nguồn là chuyện thường, không phải lệch cơ sở.
    """
    today = today or date.today()
    try:
        m = _as_dates(wh).merge(_as_dates(src), on="time",
                                suffixes=("_wh", "_src"))
        m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
        m = m[m["time"] < today]
        if m.empty:
            return None
        m = m.sort_values("time")
        bad = m[((m["close_wh"] / m["close_src"]) - 1.0).abs() > tol]
        return None if bad.empty else bad["time"].iloc[-1]
    except Exception:
        return None


def _residual_basis_step(prices_dir: Path, tk: str, src_all: pd.DataFrame,
                         since_days: int = 365) -> "dict | None":
    """Ghi xong rồi: tỉ lệ kho/nguồn CÒN đổi bậc không? Dùng lại nguồn đã fetch."""
    from probe_price_basis import find_basis_step, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(prices_dir, tk, d0, d1)
        if wh.empty:
            return None
        src = _as_dates(src_all[["time", "close"]])
        src = src[(src["time"] >= d0) & (src["time"] <= d1)]
        if src.empty:
            return None
        return find_basis_step(wh, src)
    except Exception:
        return None


def _residual_level(prices_dir: Path, tk: str, src_all: pd.DataFrame,
                    since_days: int = 365,
                    tol: float = 0.012) -> "date | None":
    """Ghi xong rồi: kho còn lệch MỨC so nguồn tới ngày nào? Chỉ ĐỌC.

    Cặp song sinh của `_residual_basis_step`, nhưng hỏi câu KHÁC. Hai bước tự
    kiểm cũ — `find_jumps` (vách giá ≥30%) và `_residual_basis_step` (đổi BẬC
    tỉ lệ) — đều đo ĐẠO HÀM, nên cùng mù với đúng lớp lỗi mà `--whole-series`
    sinh ra để chữa: lệch ĐỒNG ĐỀU có đạo hàm 0 ở mọi điểm. Chữa hụt hệ số
    (hoặc chữa nhầm chiều) sẽ để lại một chuỗi vẫn lệch ĐỀU, và cả hai bước
    cũ đều in xanh. Tự kiểm mà mù đúng lớp lỗi mình sinh ra để chữa thì không
    phải tự kiểm.

    Dùng lại `src_all` đã fetch — tự kiểm không được phép gọi mạng lần nữa
    (nguồn đổi giữa chừng thì đỏ/xanh không còn nói về việc mình vừa làm).
    """
    from probe_price_basis import load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(prices_dir, tk, d0, d1)
        if wh.empty:
            return None
        src = _as_dates(src_all[["time", "close"]])
        src = src[(src["time"] >= d0) & (src["time"] <= d1)]
        if src.empty:
            return None
        return last_divergent_day(wh, src, tol=tol)
    except Exception:
        return None


# Bao nhiêu bar ĐÃ SANG cơ sở mới thì đủ tin có một vách thật ở đó. Đây
# chính là chỗ `find_basis_step` bó tay (nó đòi `BASIS_MIN_SIDE` = 5 bar mỗi
# phía), nên đặt thấp hơn là CÓ CHỦ Ý — xem `level_break_report`.
LEVEL_BREAK_MIN_AFTER = 2
# Phần bar "sai phía" tối đa ở phía TRƯỚC vách. Vách sạch thì gần như mọi bar
# trước đều lệch; lẫn nhiều bar khớp nguồn nghĩa là không phải MỘT vách.
LEVEL_BREAK_MAX_DIRTY = 0.10


def level_break_report(wh, src, tol: float = 0.012) -> dict:
    """Vách suy từ MỨC: ngày ĐẦU TIÊN kho thôi lệch nguồn. Hàm THUẦN.

    ⚠️ Vì sao cần bộ dò vách THỨ BA. Đo trên máy user 26/08, lượt chạy thử 69
    mã: 13 mã bị `--whole-series` từ chối, và cả 13 có chung một chữ ký —
    tỉ lệ chạy từ **1.0000× tới f**. Tức chúng KHÔNG lệch đều: một phần chuỗi
    đã khớp nguồn rồi. Đó là một vách thật.

    Vậy sao `find_basis_step` không thấy? Vì nó đòi `BASIS_MIN_SIDE` = 5 bar
    **mỗi phía**::

        if i < BASIS_MIN_SIDE or len(r) - i < BASIS_MIN_SIDE:
            return None

    Mã bị gác chặn sau ngày GDKHQ 3 phiên thì chỉ có 2-3 bar ở phía cơ sở mới
    ⇒ dưới sàn ⇒ trả None. Và **phía đó không bao giờ mọc thêm**: gác chặn nên
    kho không nhận bar mới. Lại một vòng tự khoá, khác vòng ở U42 nhưng cùng
    hình dạng — bộ dò đòi bằng chứng mà chính cửa gác đang chặn không cho sinh.

    Bộ dò này không đếm bar mỗi phía mà hỏi **chỗ nào tỉ lệ thôi lệch**:
    ngày lệch cuối cùng + 1. Đổi lại nó đòi CHIA SẠCH — gần như mọi bar trước
    đều lệch (≤`LEVEL_BREAK_MAX_DIRTY` sai phía) và mọi bar sau đều khớp. Lệch
    xen kẽ thì không phải một vách, và trả None còn hơn đoán một cái mốc.

    Trả `{"break": ...}` khi có vách; `{"break": None, "why": ...}` mọi ca
    khác — kể cả ca lệch ở MỌI bar, vì đó là việc của `--whole-series`.
    """
    out = {"break": None, "n_before": 0, "n_after": 0,
           "ratio_before": None, "why": ""}
    try:
        m = _as_dates(wh).merge(_as_dates(src), on="time",
                                suffixes=("_wh", "_src"))
        m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)].sort_values("time")
        if m.empty:
            out["why"] = "không có bar nào chồng nhau"
            return out
        m = m.reset_index(drop=True)
        r = (m["close_wh"] / m["close_src"]).astype(float)
        div = (r - 1.0).abs() > tol
        if not div.any():
            out["why"] = f"không bar nào lệch quá {tol} — kho đã khớp nguồn"
            return out
        if div.all():
            out["why"] = ("lệch ở MỌI bar — không có phía 'cơ sở mới' nào để "
                          "làm mốc; đó là ca --whole-series, không phải vách")
            return out
        i = int(div[div].index[-1])                 # bar lệch CUỐI CÙNG
        before, after = m.iloc[:i + 1], m.iloc[i + 1:]
        out["n_before"], out["n_after"] = len(before), len(after)
        if len(after) < LEVEL_BREAK_MIN_AFTER:
            out["why"] = (f"chỉ {len(after)} bar đã sang cơ sở mới (cần ≥"
                          f"{LEVEL_BREAK_MIN_AFTER}) — chưa đủ để nói có vách")
            return out
        dirty = float((~div.iloc[:i + 1]).mean())
        if dirty > LEVEL_BREAK_MAX_DIRTY:
            out["why"] = (f"phía trước lẫn {dirty:.0%} bar ĐÃ khớp nguồn "
                          f"(trần {LEVEL_BREAK_MAX_DIRTY:.0%}) — lệch xen kẽ "
                          f"chứ không phải MỘT vách")
            return out
        out["ratio_before"] = float(r.iloc[:i + 1].median())
        out["break"] = m.at[i, "time"] + timedelta(days=1)
        out["why"] = (f"lệch tới hết {m.at[i, 'time']} rồi khớp nguồn ở "
                      f"{len(after)} bar cuối (trung vị trước "
                      f"{out['ratio_before']:.4f}×)")
        return out
    except Exception as e:                        # noqa: BLE001
        out["why"] = f"không đo được ({type(e).__name__}: {e})"
        return out


# Tỉ lệ kho/nguồn phải ỔN ĐỊNH tới mức nào mới cho ghi đè TRỌN lịch sử.
# max/min của tỉ lệ từng bar. Một lần đổi cơ sở SẠCH cho ra tỉ lệ gần như
# hằng số; lởm chởm nghĩa là còn chuyện khác trộn vào, và ghi đè trọn lịch sử
# là việc KHÔNG LÙI ĐƯỢC nên chỗ này thà chặt quá còn hơn lỏng.
UNIFORM_SPREAD_MAX = 1.01
UNIFORM_MIN_BARS = 20
# Cửa THƯA — mở cho mã gần như không giao dịch.
#
# Sàn 20 bar là cách ĐẾM để trả lời câu thật sự cần hỏi: *"chứng cứ có phủ đủ
# rộng để một lần đổi cơ sở trong cửa sổ này không lọt qua không?"* Với mã dày
# thì đếm bar là proxy tốt. Với mã thưa thì nó hỏi sai: GH3 (07/09) chỉ có 13
# bar chồng nhau trong 365 ngày, mà spread 1.0011 — chặt ngang mọi mã đã chữa
# sạch (1.0003-1.0014). Bảo "quá ít để nói đều" là bỏ qua chính con số đang
# nói rất rõ.
#
# Thứ đo trực tiếp hơn là **TẦM PHỦ THỜI GIAN**: bar rải trên nửa năm thì một
# lần đổi cơ sở trong nửa năm ấy chắc chắn nằm GIỮA hai bar nào đó ⇒ tỉ lệ
# phải gãy ⇒ spread phải nở. Spread không nở nghĩa là không có lần đổi nào.
# Vài bar chụm trong hai tuần thì không nói được gì như thế, dù đếm ra bao
# nhiêu. Nên cửa thưa đòi CẢ HAI, và vẫn qua đúng cửa spread như mọi mã khác.
UNIFORM_SPARSE_MIN_BARS = 8
UNIFORM_SPARSE_MIN_SPAN_DAYS = 180
# Trần hệ số. Sự kiện quyền lớn nhất thực tế ~1:4 (5×); tỉ lệ vượt xa mức này
# — nhất là cỡ 1.000× — là SAI ĐƠN VỊ (đồng ⇄ nghìn đồng), thuộc về
# `check_unit_continuity` / `run.py fix-units`, KHÔNG phải đổi cơ sở. Lệch
# đơn vị cũng đều tăm tắp nên nó qua được cửa "spread", tức không có rào này
# thì `--whole-series` sẽ ghi đè trọn lịch sử vì một lý do hoàn toàn khác.
UNIFORM_MAX_FACTOR = 10.0


def uniform_offset_report(wh, src, tol: float = 0.012) -> dict:
    """Kho có lệch nguồn ĐỒNG ĐỀU trên toàn dải không? — hàm THUẦN.

    Đây là cửa DUY NHẤT cho phép ghi đè trọn lịch sử, nên nó phải trả lời
    được hai câu tách bạch:

    * **có lệch không** — `|trung vị(kho/nguồn) − 1| > tol`;
    * **lệch có ĐỀU không** — `max(tỉ lệ) / min(tỉ lệ) ≤ UNIFORM_SPREAD_MAX`.

    Câu thứ hai mới là cửa thật. Lệch đều = nguồn đã back-adjust một lần,
    sạch, kho chỉ việc lấy lại. Lệch LỞM CHỞM = còn chuyện khác trộn vào
    (nhiều lần rebase chồng nhau, bar hỏng, sai đơn vị lẻ tẻ) — khi đó nhân
    cả chuỗi bằng MỘT hệ số là bôi cái sai ra khắp lịch sử.

    Trả `uniform=False` kèm `why` cho mọi ca không chắc. Không bao giờ đoán.
    """
    # `aligned` tách bạch với `uniform`: cả hai đều "không chữa được bằng chế
    # độ này", nhưng một cái nghĩa là ĐÃ SẠCH còn cái kia là KHÔNG ĐỦ BẰNG
    # CHỨNG — hai việc phải làm khác hẳn nhau. Dò chuỗi `why` để phân biệt là
    # buộc logic vào câu chữ tiếng Việt.
    out = {"n": 0, "ratio": None, "spread": None, "span_days": 0,
           "uniform": False, "aligned": False, "why": ""}
    try:
        m = _as_dates(wh).merge(_as_dates(src), on="time",
                                suffixes=("_wh", "_src"))
        m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
        if m.empty:
            out["why"] = "không có bar nào chồng nhau giữa kho và nguồn"
            return out
        ratios = (m["close_wh"] / m["close_src"]).astype(float)
        out["n"] = int(len(ratios))
        _t = pd.to_datetime(m["time"])
        out["span_days"] = int((_t.max() - _t.min()).days)
        out["ratio"] = float(ratios.median())
        lo, hi = float(ratios.min()), float(ratios.max())
        out["spread"] = (hi / lo) if lo > 0 else float("inf")
        _sparse_ok = (out["n"] >= UNIFORM_SPARSE_MIN_BARS
                      and out["span_days"] >= UNIFORM_SPARSE_MIN_SPAN_DAYS)
        if out["n"] < UNIFORM_MIN_BARS and not _sparse_ok:
            # In kèm SỐ ĐO — "quá ít bar" không nói được là mã ấy đáng xét
            # tiếp hay đáng bỏ, còn tỉ lệ + spread + tầm phủ thì nói được ngay.
            out["why"] = (f"chứng cứ quá mỏng: {out['n']} bar chồng nhau trải "
                          f"{out['span_days']} ngày — cần ≥{UNIFORM_MIN_BARS} "
                          f"bar, hoặc ≥{UNIFORM_SPARSE_MIN_BARS} bar trải "
                          f"≥{UNIFORM_SPARSE_MIN_SPAN_DAYS} ngày "
                          f"(đo được {out['ratio']:.4f}×, spread "
                          f"{out['spread']:.4f})")
            return out
        if abs(out["ratio"] - 1.0) <= tol:
            out["aligned"] = True
            out["why"] = (f"tỉ lệ {out['ratio']:.4f}× nằm trong ngưỡng {tol} "
                          f"— kho KHÔNG lệch, không có gì để chữa")
            return out
        if not (1.0 / UNIFORM_MAX_FACTOR <= out["ratio"] <= UNIFORM_MAX_FACTOR):
            out["why"] = (f"tỉ lệ {out['ratio']:.4f}× vượt trần "
                          f"{UNIFORM_MAX_FACTOR}× — cỡ này là SAI ĐƠN VỊ "
                          f"(đồng ⇄ nghìn đồng) chứ không phải đổi cơ sở; "
                          f"soi bằng check_unit_continuity, đừng chữa ở đây")
            return out
        if out["spread"] > UNIFORM_SPREAD_MAX:
            out["why"] = (f"tỉ lệ LỞM CHỞM: {lo:.4f}× → {hi:.4f}× "
                          f"(spread {out['spread']:.4f}, trần "
                          f"{UNIFORM_SPREAD_MAX}) — KHÔNG phải một lần đổi cơ "
                          f"sở sạch, nhân cả chuỗi bằng một hệ số là bôi cái "
                          f"sai ra khắp lịch sử")
            return out
        out["uniform"] = True
        out["why"] = (f"lệch ĐỀU {out['ratio']:.4f}× trên {out['n']} bar "
                      f"trải {out['span_days']} ngày "
                      f"(spread {out['spread']:.4f})"
                      + (" · qua CỬA THƯA: ít bar nhưng phủ đủ rộng để một "
                         "lần đổi cơ sở không lọt" if _sparse_ok
                         and out["n"] < UNIFORM_MIN_BARS else ""))
        return out
    except Exception as e:                        # noqa: BLE001
        out["why"] = f"không đo được ({type(e).__name__}: {e})"
        return out


# Trần nới cửa sổ đo khi 365 ngày cho ra quá ít bar. 12 năm phủ trọn mọi mã
# trong kho; xin xa hơn chỉ tốn một lượt fetch to mà không thêm bar nào.
WIDEN_MAX_DAYS = 4500


def _uniform_probe(tk: str, wh_root: Path, since_days: int = 365,
                   tol: float = 0.012) -> dict:
    """`uniform_offset_report` trên dữ liệu THẬT của một mã. Chỉ đọc.

    ⚠️ **Cửa sổ 365 ngày đo sai với mã kho ĐÃ ĐỨNG LÂU.** Vết GH3 (07/09):
    kho 1.033 bar trải 2021-08-04 → **2025-09-24**, tức đóng băng gần MỘT NĂM.
    Trong 365 ngày qua kho chỉ còn đúng 13 bar — cái đuôi của nó — nên phép đo
    kết luận *"chứng cứ quá mỏng"*. Nhưng mỏng ở đây là **thuộc tính của cửa
    sổ**, không phải của mã: nới ra tới đầu kho thì có ~1.000 bar chồng lấn.

    Nên khi cửa sổ mặc định cho ra dưới `UNIFORM_MIN_BARS` bar, nới tới tận
    bar ĐẦU của kho rồi đo lại. Bằng chứng khi ấy MẠNH HƠN hẳn — trần spread
    giữ nguyên, nên nhiều lần đổi cơ sở rải rác trong 4 năm sẽ làm spread nở
    và mã bị từ chối, đúng như phải thế.
    """
    from probe_price_basis import fetch_source, load_wh

    def _measure(d0: date, d1: date) -> dict:
        wh = load_wh(wh_root / "prices", tk, d0, d1)
        if wh.empty:
            return {"uniform": False, "why": "kho rỗng", "n": 0,
                    "ratio": None, "spread": None, "span_days": 0}
        src = fetch_source(tk, d0, d1)
        if src.empty:
            return {"uniform": False, "why": "nguồn trả rỗng", "n": 0,
                    "ratio": None, "spread": None, "span_days": 0}
        return uniform_offset_report(wh, src, tol=tol)

    d1 = date.today()
    try:
        out = _measure(d1 - timedelta(days=since_days), d1)
        if (out.get("n") or 0) >= UNIFORM_MIN_BARS or out.get("aligned"):
            return out
        first = _first_wh_bar(tk, wh_root)
        if first is None:
            return out
        wide = max(since_days + 1, min((d1 - first).days + 7, WIDEN_MAX_DAYS))
        if wide <= since_days:
            return out
        out2 = _measure(d1 - timedelta(days=wide), d1)
        if (out2.get("n") or 0) <= (out.get("n") or 0):
            return out                       # nới mà không thêm bar ⇒ giữ cũ
        out2["widened_days"] = wide
        out2["why"] = (f"{out2['why']} · đo trên cửa sổ NỚI {wide} ngày "
                       f"(365 ngày chỉ có {out.get('n') or 0} bar — kho đã "
                       f"đứng lâu, mỏng là do cửa sổ chứ không do mã)")
        return out2
    except Exception as e:                        # noqa: BLE001
        return {"uniform": False, "why": f"{type(e).__name__}: {e}", "n": 0,
                "ratio": None, "spread": None, "span_days": 0}


def _in_drift_ledger(tk: str, wh_root: Path) -> bool:
    """Mã này có đang nằm trong sổ cách ly của cửa gác không? Chỉ ĐỌC."""
    try:
        from vnstock_basis_guard import load_pending
        return tk.upper() in (load_pending(Path(wh_root)) or {})
    except Exception:
        return False


def _first_wh_bar(tk: str, wh_root: Path) -> "date | None":
    """Ngày bar ĐẦU của kho. Chỉ ĐỌC — dùng để nới cửa sổ đo cho mã kho đã
    đứng lâu (xem `_uniform_probe`)."""
    try:
        from check_unit_continuity import load_bars
        df = load_bars(wh_root / "prices", tk, since_days=0)
        if df is None or df.empty:
            return None
        return pd.to_datetime(df["time"]).min().date()
    except Exception:
        return None


def _last_wh_bar(tk: str, wh_root: Path) -> "date | None":
    """Ngày bar CUỐI của kho. Chỉ ĐỌC.

    Dùng làm MỐC ẢO cho `--whole-series`: lệch đồng đều thì không có vách nào
    thật, nên lấy "sau bar cuối" làm mốc để vòng ghi coi TOÀN chuỗi là phần
    'trước vách'. Không đọc được → None, và chỗ gọi từ chối chữa — đoán đại
    một mốc ở đây là ghi đè nhầm nửa lịch sử.
    """
    try:
        from check_unit_continuity import load_bars
        df = load_bars(wh_root / "prices", tk, since_days=0)
        if df is None or df.empty:
            return None
        return pd.to_datetime(df["time"]).max().date()
    except Exception:
        return None


def _level_divergence(tk: str, wh_root: Path, since_days: int = 365,
                      tol: float = 0.012) -> "date | None":
    """Kho còn lệch MỨC so nguồn tới ngày nào? — bộ dò MỨC, không dò bậc.

    ⚠️ Vì sao phải có: cả `_find_break` (vách GIÁ ≥30% trong kho) lẫn
    `_basis_break_of` → `find_basis_step` đều đo **ĐẠO HÀM** của tỉ lệ
    (`jumps = |r[1:]/r[:-1] − 1|`). Một chuỗi lệch **ĐỒNG ĐỀU** — nguồn đã
    back-adjust trọn lịch sử — có đạo hàm bằng 0 ở mọi điểm, nên **cả hai đều
    trả None**, và hàm gọi tuyên bố "✅ sạch" + exit 0.

    Trong khi `vnstock_basis_guard.check_basis` đo **MỨC** (`|r − 1| > TOL`)
    nên bắt gọn. Hai bên hỏi hai câu khác nhau: gác hỏi *"tỉ lệ có KHÁC 1
    không"*, bộ dò hỏi *"tỉ lệ có ĐỔI không"*. Mã bị gác chặn thì kho không
    bao giờ nhận bar cơ sở mới ⇒ không bao giờ sinh ra bậc ⇒ bộ dò đạo hàm mù
    vĩnh viễn. Đo 26/08 trên máy user: SDK 1.4857× mà `probe_price_basis` in
    "không tìm thấy vách nghi vấn trong 365 ngày".

    `last_divergent_day` (ngay trên) vốn ĐÃ đo đúng thứ này — nó chỉ nằm SAU
    hai cửa mù nên không bao giờ được chạm tới.
    """
    from probe_price_basis import fetch_source, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(wh_root / "prices", tk, d0, d1)
        if wh.empty:
            return None
        src = fetch_source(tk, d0, d1)
        if src.empty:
            return None
        return last_divergent_day(wh, src, tol=tol)
    except Exception:
        return None


def _level_break_of(tk: str, wh_root: Path, since_days: int = 365,
                    tol: float = 0.012) -> dict:
    """`level_break_report` trên dữ liệu THẬT của một mã. Chỉ đọc."""
    from probe_price_basis import fetch_source, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(wh_root / "prices", tk, d0, d1)
        if wh.empty:
            return {"break": None, "why": "kho rỗng"}
        src = fetch_source(tk, d0, d1)
        if src.empty:
            return {"break": None, "why": "nguồn trả rỗng"}
        return level_break_report(wh, src, tol=tol)
    except Exception as e:                        # noqa: BLE001
        return {"break": None, "why": f"{type(e).__name__}: {e}"}


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


def _drift_ledger_targets(wh_root: Path) -> list:
    """Danh sách mã từ SỔ CÁCH LY của cửa gác. Lỗi đọc thì trả rỗng, KHÔNG đoán.

    Vì sao phải có, bên cạnh `--from-sweep`: mã lệch ĐỒNG ĐỀU **không bao giờ**
    vào `basis_sweep_check.json:suspect` — vết quét cũng dùng `find_basis_step`,
    tức cùng một bộ dò đạo hàm đang mù (U42). Sổ cách ly thì do cửa gác ghi, mà
    gác đo MỨC ⇒ nó là nguồn DUY NHẤT liệt kê đúng lớp mã này.
    """
    try:
        from vnstock_basis_guard import load_pending
        return sorted((load_pending(Path(wh_root)) or {}).keys())
    except Exception as e:                        # noqa: BLE001
        print(f"[rebase] ✗ không đọc được sổ cách ly "
              f"({type(e).__name__}: {e})")
        return []


def _newest_backup(tk: str, wh_root: Path) -> "Path | None":
    """Bản sao lưu MỚI NHẤT của một mã. Tên thư mục `<MÃ>_<YYYYmmdd-HHMMSS>`
    nên sắp theo tên là sắp theo thời gian."""
    root = wh_root / "_meta" / "backup_rebase"
    if not root.exists():
        return None
    cands = sorted(d for d in root.glob(f"{tk.upper()}_*") if d.is_dir())
    return cands[-1] if cands else None


def _restore_one(tk: str, wh_root: Path, apply: bool) -> int:
    """Đưa một mã về đúng bản sao lưu gần nhất.

    Vì sao cần một đường CÓ TEST thay vì bảo user `Copy-Item` bằng tay: nó chỉ
    dùng đến khi vừa có sự cố ghi, tức đúng lúc dễ gõ nhầm nhất, và gõ nhầm ở
    đây là chép đè lên một mã KHÁC. Ca 07/09: Dropbox giữ file, `os.replace`
    ném `WinError 5` giữa lượt ghi.
    """
    tk = tk.upper()
    src = _newest_backup(tk, wh_root)
    if src is None:
        print(f"[rebase] ✗ {tk}: không có bản sao lưu nào trong "
              f"{wh_root / '_meta' / 'backup_rebase'}")
        return 1
    tdir = wh_root / "prices" / f"ticker={tk}"
    files = sorted(src.glob("year=*/*.parquet"))
    print(f"\n[rebase] ↩ {tk}: khôi phục từ {src.name} ({len(files)} file)")
    if not files:
        print(f"[rebase] ✗ bản sao lưu RỖNG — không khôi phục gì "
              f"(xoá sạch kho của mã là hỏng nặng hơn hẳn thứ đang chữa)")
        return 1
    if not apply:
        print(f"[rebase] 🔎 CHẠY THỬ — chưa ghi gì. Thêm --apply để ghi thật.")
        return 0
    try:
        for f in files:
            dst = tdir / f.parent.name / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(f".{os.getpid()}.tmp")
            shutil.copyfile(f, tmp)
            _atomic_replace(tmp, dst)
    except Exception as e:                        # noqa: BLE001
        _sweep_tmp(tdir)
        print(f"[rebase] ✗ {tk}: khôi phục HỎNG — {e}")
        print(f"[rebase]   bản sao lưu vẫn còn nguyên ở {src}")
        return 2
    print(f"[rebase] ✅ {tk}: đã trả về bản {src.name}")
    return 0


def _tail_ratios(tk: str, wh_root: Path, n: int = 12,
                 since_days: int = 400) -> "pd.DataFrame | None":
    """`n` bar CHỒNG LẤN cuối cùng, kèm tỉ lệ kho/nguồn từng bar. Chỉ đọc.

    Vì sao cần: mọi thứ khác trong `--explain` là số TỔNG HỢP — trung vị,
    spread, số bar mỗi phía. Chúng đủ để phân loại, nhưng không đủ để phân
    biệt hai cách đọc đối nghịch của cùng một bộ số. Ca DRG (07/09): 195 bar ở
    ~1.0204 rồi ĐÚNG MỘT bar ở 0.9964 — đọc cách này là **vách thật** (nguồn
    vừa back-adjust, kho mới nối được một bar mới), đọc cách kia là **lệch
    đồng đều kèm một bar hỏng**. Hai đường chữa khác nhau, mà không con số
    tổng hợp nào tách được. Nhìn thẳng vào đuôi chuỗi thì tách được ngay.
    """
    from probe_price_basis import fetch_source, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(wh_root / "prices", tk, d0, d1)
        if wh.empty:
            return None                      # khỏi gọi mạng cho mã không có kho
        src = fetch_source(tk, d0, d1)
        if src.empty:
            return None
        m = _as_dates(wh).merge(_as_dates(src), on="time",
                                suffixes=("_wh", "_src")).sort_values("time")
        m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
        if m.empty:
            return None
        m = m.tail(n).copy()
        m["ratio"] = m["close_wh"] / m["close_src"]
        return m
    except Exception:
        return None


def _explain_one(tk: str, wh_root: Path) -> int:
    """In MỌI số đo của một mã rồi dừng. **Chỉ đọc, không ghi, không chữa.**

    Vì sao cần: bảng triage vẫn dẫn người dùng tới
    `probe_price_basis --ticker <MÃ>`, mà lệnh đó chỉ chạy bộ dò **BẬC** —
    đúng lớp bộ dò đã chứng minh là mù với mã bị gác chặn (U42, U45). Đo
    07/09: cả GH3 lẫn DRG đều nhận *"không tìm thấy vách nghi vấn trong 365
    ngày — không có gì để phân định"*, trong khi có rất nhiều thứ để nói —
    tỉ lệ, spread, tầm phủ, độ dày kho. Dẫn người tới một công cụ mù rồi bảo
    "soi tay đi" là bỏ mặc, không phải giao việc.

    Không thay `probe_price_basis`: nó là tầng ĐO, còn đây là tầng đọc số đo
    bằng ống kính MỨC. Giữ một chiều phụ thuộc (rebase → probe).
    """
    tk = tk.upper()
    prices_dir = wh_root / "prices"
    print(f"\n{'=' * 62}\n[soi] {tk}\n{'=' * 62}")

    # ── kho có gì ────────────────────────────────────────────────────────
    try:
        from check_unit_continuity import load_bars
        allbars = load_bars(prices_dir, tk, since_days=0)
        yr = load_bars(prices_dir, tk, since_days=365)
        if allbars is None or allbars.empty:
            print("[soi] ⬜ kho RỖNG — không có gì để đo")
            return 0
        t = pd.to_datetime(allbars["time"])
        _frozen = (date.today() - t.max().date()).days
        print(f"[soi] KHO   : {len(allbars):,} bar · {t.min().date()} → "
              f"{t.max().date()} · trong 365 ngày: {len(yr):,} bar")
        print(f"[soi]         ĐỨNG {_frozen} ngày kể từ bar cuối"
              + (" ⚠️ (sổ cách ly đếm từ lần PHÁT HIỆN gần nhất nên báo ~0)"
                 if _frozen > 30 else ""))
    except Exception as e:                        # noqa: BLE001
        print(f"[soi] ✗ không đọc được kho ({type(e).__name__}: {e})")
        return 2

    # ── vùng chồng lấn với nguồn ────────────────────────────────────────
    uni = _uniform_probe(tk, wh_root)
    _n, _sp = uni.get("n") or 0, uni.get("span_days") or 0
    if _n:
        print(f"[soi] CHỒNG : {_n:,} bar trải {_sp} ngày · tỉ lệ kho/nguồn "
              f"{uni['ratio']:.4f}× · spread {uni['spread']:.4f}")
        # Vùng chồng lấn phủ được bao nhiêu phần lịch sử kho? Với mã MỚI
        # niêm yết, 16 ngày có thể là TRỌN đời của nó — khác hẳn 16 ngày của
        # một mã 20 năm tuổi, dù hai con số bằng nhau.
        _life = max(1, (t.max() - t.min()).days)
        print(f"[soi]         vùng chồng lấn phủ ~{100.0 * _sp / _life:.0f}% "
              f"bề dài lịch sử kho ({_life} ngày)")
    else:
        print(f"[soi] CHỒNG : — ({uni.get('why')})")

    # ── đuôi chuỗi: số TỔNG HỢP không tách được hai cách đọc, bar thì có ──
    tail = _tail_ratios(tk, wh_root)
    if tail is not None and not tail.empty:
        print(f"[soi] ĐUÔI  : {len(tail)} bar chồng lấn cuối "
              f"(✗ = lệch quá {0.012})")
        for _, r in tail.iterrows():
            _r = float(r["ratio"])
            print(f"[soi]         {r['time']}  kho {float(r['close_wh']):>12,.2f}"
                  f"  nguồn {float(r['close_src']):>12,.2f}  "
                  f"= {_r:.4f}×  {'✗' if abs(_r - 1.0) > 0.012 else '✓'}")

    # ── từng bộ dò nói gì ───────────────────────────────────────────────
    print("[soi] BỘ DÒ :")
    try:
        from probe_price_basis import _find_break
        _b1 = _find_break(prices_dir, tk)
    except Exception as e:                        # noqa: BLE001
        _b1 = f"lỗi: {type(e).__name__}"
    print(f"[soi]   vách giá ≥30% (ĐẠO HÀM)      : {_b1 or '—'}")
    try:
        _b2 = _basis_break_of(tk, wh_root)
    except Exception as e:                        # noqa: BLE001
        _b2 = f"lỗi: {type(e).__name__}"
    print(f"[soi]   bậc tỉ lệ (ĐẠO HÀM)          : {_b2 or '—'}")
    _lb = _level_break_of(tk, wh_root)
    print(f"[soi]   vách theo MỨC                : "
          f"{_lb.get('break') or '— ' + str(_lb.get('why', ''))}")
    _lvl = _level_divergence(tk, wh_root)
    print(f"[soi]   còn lệch MỨC tới ngày        : {_lvl or '— (sạch)'}")
    print(f"[soi]   sổ cách ly                   : "
          f"{'CÓ' if _in_drift_ledger(tk, wh_root) else 'không'}")

    # ── kết luận: làm gì tiếp ───────────────────────────────────────────
    print("[soi] ⇒ ", end="")
    if uni.get("aligned") and _in_drift_ledger(tk, wh_root):
        print(f"kho ĐÃ SẠCH, chỉ bản ghi trong sổ là cũ. Chữa:\n"
              f"      python scripts/rebase_ticker_history.py --ticker {tk} "
              f"--apply")
    elif _lb.get("break") is not None:
        print(f"có VÁCH THẬT tại {_lb['break']}. Chữa:\n"
              f"      python scripts/rebase_ticker_history.py --ticker {tk} "
              f"--apply")
    elif uni.get("uniform"):
        print(f"lệch ĐỒNG ĐỀU {uni['ratio']:.4f}×. Chữa:\n"
              f"      python scripts/rebase_ticker_history.py --ticker {tk} "
              f"--whole-series --apply")
    elif _lvl is None and not _in_drift_ledger(tk, wh_root):
        print("mã SẠCH, không có gì phải làm.")
    else:
        print(f"CẦN MẮT NGƯỜI — không cửa nào mở, và lý do là:\n"
              f"      {uni.get('why')}")
    return 0


def _rebase_one(tk: str, wh_root: Path, apply: bool,
                volume_mode: str = "auto",
                break_date: "date | None" = None,
                whole_series: bool = False) -> int:
    from check_unit_continuity import find_jumps, load_bars
    from probe_price_basis import _find_break, fetch_source

    prices_dir = wh_root / "prices"
    tdir = prices_dir / f"ticker={tk}"
    if not tdir.exists():
        print(f"\n[rebase] ⬜ {tk}: không có trong kho")
        return 1

    whole_factor = None
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
        # Bộ dò vách THỨ BA, đo MỨC. Hai bộ trên đòi đủ bar MỖI PHÍA
        # (`BASIS_MIN_SIDE` = 5); mã bị gác chặn sau GDKHQ 3 phiên chỉ có 2-3
        # bar ở phía cơ sở mới, và phía đó không bao giờ mọc thêm vì chính gác
        # đang chặn. Đo 26/08: đúng 13/69 mã rơi vào đây.
        _lb = _level_break_of(tk, wh_root)
        if _lb.get("break") is not None:
            brk = _lb["break"]
            print(f"\n[rebase] {tk}: không có vách giá lẫn bậc tỉ lệ, nhưng "
                  f"MỨC lệch DỪNG tại {brk} — {_lb['why']}")
            from probe_price_basis import BASIS_MIN_SIDE as _MIN_SIDE
            print(f"[rebase]   ({_lb['n_after']} bar sau vách, dưới sàn "
                  f"{_MIN_SIDE} bar/phía của bộ dò bậc nên nó im)")
    if brk is None:
        # ⚠️ ĐỪNG tuyên bố sạch chỉ vì hai bộ dò BẬC NHẢY im. Chúng mù với
        # lệch ĐỒNG ĐỀU (đạo hàm = 0 ở mọi điểm). Hỏi nốt bộ dò MỨC, và hỏi
        # cả sổ cách ly — cửa gác đo MỨC nên nó biết thứ bộ dò bậc không biết.
        _lvl = _level_divergence(tk, wh_root)
        _pend = _in_drift_ledger(tk, wh_root)
        # Đo MỘT LẦN rồi dùng cho cả hai nhánh — mỗi lượt `_uniform_probe` là
        # một lần gọi mạng, mà lô chạy 70 mã.
        _uni = (_uniform_probe(tk, wh_root)
                if (_lvl is not None or _pend) else None)
        if _pend and _uni is not None and _uni.get("aligned"):
            # BẢN GHI CŨ. Kho đã sạch, chỉ sổ là chưa xoá — và **không ai khác
            # xoá nó**: `clear_drift` chỉ có đúng một chỗ gọi, là chính công cụ
            # này. Trước 07/09 ca này rơi vào nhánh từ chối ⇒ mã sạch nằm lại
            # trong sổ VĨNH VIỄN, badge doctor warn mãi. Đo được trên ACE.
            print(f"\n[rebase] ↩ {tk}: kho ĐÃ SẠCH ({_uni['why']}) nhưng vẫn "
                  f"nằm trong sổ cách ly — bản ghi cũ, chỉ cần xoá sổ")
            if not apply:
                print(f"[rebase] 🔎 CHẠY THỬ — chưa ghi gì. "
                      f"Thêm --apply để xoá khỏi sổ.")
                return 0
            from vnstock_basis_guard import clear_drift
            if clear_drift(wh_root, tk):
                print(f"[rebase] ✅ {tk}: đã xoá khỏi sổ cách ly")
                return 0
            print(f"[rebase] ✗ {tk}: KHÔNG xoá được khỏi sổ cách ly "
                  f"(Dropbox/AV đang giữ `basis_drift_pending.json`?) — "
                  f"kho vẫn sạch, chạy lại lệnh này là xong")
            return 1
        if (_lvl is not None or _pend) and whole_series:
            # Đường CHỮA cho lớp lệch đồng đều. Cửa vào không phải `_probe`
            # (nó phán 'aligned' vì trước = sau) mà là `uniform_offset_report`
            # — chặt hơn: đòi tỉ lệ ỔN ĐỊNH, không chỉ đòi có lệch.
            if not _uni.get("uniform"):
                print(f"\n[rebase] ✗ {tk}: TỪ CHỐI --whole-series — "
                      f"{_uni.get('why')}")
                print(f"[rebase]   Ghi đè TRỌN lịch sử là việc không lùi được, "
                      f"nên cửa này cố tình chặt.")
                return 1
            _wh_last = _last_wh_bar(tk, wh_root)
            if _wh_last is None:
                print(f"\n[rebase] ✗ {tk}: không đọc được bar cuối của kho")
                return 1
            whole_factor = float(_uni["ratio"])
            brk = _wh_last + timedelta(days=1)
            print(f"\n[rebase] {tk} · LỆCH ĐỒNG ĐỀU — {_uni['why']}")
            print(f"[rebase]   không có vách để làm mốc ⇒ coi TOÀN chuỗi là "
                  f"'trước vách' (mốc ảo {brk}, sau bar cuối {_wh_last})")
            if _pend:
                print(f"[rebase]   {tk} đang nằm trong sổ cách ly — chữa xong "
                      f"sẽ tự xoá khỏi sổ")
        elif _lvl is not None or _pend:
            print(f"\n[rebase] ✗ {tk}: KHÔNG có bậc nhảy, NHƯNG vẫn lệch — "
                  f"hai bộ dò bậc mù với lớp lỗi này.")
            if _lvl is not None:
                print(f"[rebase]   kho còn lệch nguồn tới tận {_lvl} "
                      f"(đo theo MỨC |kho/nguồn − 1|, không theo bậc nhảy)")
            if _pend:
                print(f"[rebase]   và {tk} ĐANG nằm trong sổ cách ly của cửa gác")
            print(f"[rebase]   ⇒ lệch ĐỒNG ĐỀU toàn chuỗi: nguồn đã back-adjust "
                  f"trọn lịch sử, kho thì chưa.")
            print(f"[rebase]   Chữa kiểu 'nhân mọi bar TRƯỚC vách' KHÔNG áp "
                  f"dụng được ở đây — không có vách nào để làm mốc.")
            print(f"[rebase]   ⇒ CHỮA bằng: python scripts/rebase_ticker_history.py "
                  f"--ticker {tk} --whole-series      (chạy thử; thêm --apply "
                  f"để ghi)")
            print(f"[rebase]   Soi tay trước cũng được: "
                  f"python scripts/probe_price_basis.py --ticker {tk} "
                  f"--break-date {_lvl or '<ngày>'}")
            return 1
        if brk is None:
            # Nhánh --whole-series ở trên ĐẶT `brk` (mốc ảo) rồi đi tiếp; chỉ
            # khi vẫn chưa có mốc nào mới được tuyên bố sạch. Thiếu cửa này là
            # chế độ mới in "✅ sạch" ngay sau dòng "LỆCH ĐỒNG ĐỀU" và không
            # ghi gì — đúng cái bệnh báo-thành-công-sai nó sinh ra để chữa.
            print(f"\n[rebase] ✅ {tk}: không còn vách nghi vấn trong 365 ngày "
                  f"(soi {len(load_bars(prices_dir, tk, since_days=365)):,} bar)"
                  f" · bộ dò MỨC cũng sạch")
            return 0
    if whole_factor is None:
        print(f"\n[rebase] {tk} · vách {brk}")

    if whole_factor is not None:
        # Đường lệch ĐỒNG ĐỀU: `_probe` so trung vị HAI PHÍA mốc, mà ở đây
        # trước = sau nên nó luôn phán 'aligned' — hỏi nó là hỏi sai câu.
        # Cửa đã qua là `uniform_offset_report`, chặt hơn: đòi tỉ lệ ổn định.
        factor = whole_factor
        print(f"[rebase] hệ số cơ sở: {factor:.4f}× (đo trên TOÀN chuỗi — "
              f"không qua `_probe`, xem `uniform_offset_report`)")
    else:
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
    if whole_factor is None:
        print(f"[rebase] khối lượng: nguồn/kho = {vol_factor:.4f}× · "
              f"bậc nhảy tại vách (sau/trước) = {step:.2f}×")
    else:
        # Mốc là ẢO, nằm sau bar cuối ⇒ phía "sau vách" rỗng ⇒ `step` = nan.
        # In "bậc nhảy = nan×" rồi lấy chính nan đó làm lý do giữ khối lượng
        # là đúng số nhưng sai chuyện: ở đây không có vách nào để mà nhảy.
        print(f"[rebase] khối lượng: nguồn/kho = {vol_factor:.4f}× · "
              f"không có vách thật nên không có bậc nhảy để đo")
    # Mốc chữa KHÔNG dừng ở ngày vách — xem `last_divergent_day`.
    from probe_price_basis import SAME_BASIS_TOL
    _last_bad = last_divergent_day(wh_head[["time", "close"]],
                                   src_all[["time", "close"]],
                                   tol=SAME_BASIS_TOL)
    cut = brk
    if _last_bad is not None and _last_bad >= brk:
        cut = _last_bad + timedelta(days=1)
        print(f"[rebase] ⚠️ còn bậc SAU vách: bar lệch nguồn cuối cùng là "
              f"{_last_bad} (mã bị rebase nhiều lần) → chữa tới hết "
              f"{_last_bad}, không dừng ở {brk}")
    # Nguồn KHÔNG điều chỉnh volume (≈1.0) MÀ khối lượng lại nhảy bậc đúng
    # bằng hệ số giá ⇒ chuỗi volume cũng đang gãy; chữa giá mà bỏ volume là
    # đổi một lỗi lấy một lỗi khác.
    # So NHÂN chứ không so TRỪ: bậc nhảy phải cùng CỠ hệ số giá. Biên ±35%
    # kiểu trừ ở hệ số 1.3 chấp nhận cả bậc 0.85-1.75 — tức nhận cả volume ĐI
    # XUỐNG làm bằng chứng số cổ phiếu TĂNG (đo được ở HSG/SSI/VJC/VTP/TCX).
    _corroborates = (0.85 <= step / factor <= 1.25) if (step == step
                     and factor) else False
    _ev = _corp_action_kind(tk, wh_root, brk)
    _shares_changed = _ev in ("split", "bonus")
    _too_small_to_tell = factor < VOL_SIGNAL_MIN_FACTOR
    if _ev:
        print(f"[rebase] sự kiện quyền quanh vách: {_ev}"
              + (" -> CÓ đổi số cổ phiếu" if _shares_changed
                 else " -> KHÔNG đổi số cổ phiếu"))
    # Quyết định khối lượng — luật ĐÃ SIẾT 19/08 sau lượt chạy thử 70 mã.
    # Luật cũ chỉ đòi "bậc nhảy volume gần hệ số giá" với biên ±35% kiểu TRỪ,
    # và nó cho qua cả những ca NGƯỢC HẲN: HSG hệ số 1.3002 mà volume nhảy
    # XUỐNG 0.92 (bậc/hệ số = 0.71) vẫn được coi là bằng chứng chia tách.
    # Tương tự SSI 0.73 · VJC 0.70 · VTP 0.72 · TCX 0.82. Khối lượng ĐI XUỐNG
    # không thể là bằng chứng số cổ phiếu TĂNG.
    # Nay đòi bằng chứng DƯƠNG: bậc/hệ số phải nằm trong 0.85-1.25 (so NHÂN),
    # cộng thêm một trong hai — kho sự kiện xác nhận split/bonus, HOẶC hệ số
    # đủ lớn để không thể là cổ tức tiền mặt. `cash` thì không bao giờ nhân.
    scale_vol = 1.0
    _src_untouched = abs(vol_factor - 1.0) < 0.05
    _why_keep = None
    if volume_mode == "source":
        _why_keep = "--volume source"
    elif volume_mode != "adjust":
        if whole_factor is not None:
            _why_keep = ("back-adjust GIÁ trọn lịch sử không tạo thêm cổ phiếu "
                         "nào, và không có vách thì cũng không có bậc nhảy "
                         "khối lượng làm bằng chứng")
        elif _ev == "cash":
            _why_keep = ("cổ tức TIỀN MẶT không tạo thêm cổ phiếu nào (nhân "
                         "lên là bịa ra khối lượng chưa từng khớp)")
        elif not _src_untouched:
            _why_keep = f"nguồn ĐÃ điều chỉnh volume rồi ({vol_factor:.4f}×)"
        elif not _corroborates:
            _why_keep = (f"bậc nhảy volume {step:.2f}× KHÔNG cùng cỡ hệ số giá "
                         f"{factor:.4f}× (tỉ lệ {step / factor:.2f}, cần "
                         f"0.85-1.25) — không có bằng chứng số cổ phiếu đổi")
        elif not (_shares_changed or not _too_small_to_tell):
            _why_keep = (f"hệ số {factor:.4f}× quá nhỏ để loại trừ cổ tức tiền "
                         f"mặt (ngưỡng {VOL_SIGNAL_MIN_FACTOR}×) và kho sự kiện "
                         f"không xác nhận chia tách/thưởng")
    if _why_keep is None:
        scale_vol = factor
        print(f"[rebase] -> NHÂN khối lượng lịch sử × {scale_vol:.4f} "
              f"(nguồn chỉ điều chỉnh giá, bậc nhảy volume {step:.2f}× khớp "
              f"hệ số"
              + (f", kho sự kiện xác nhận '{_ev}'" if _shares_changed else "")
              + ")")
    else:
        print(f"[rebase] -> GIỮ NGUYÊN khối lượng: {_why_keep}"
              + ("" if volume_mode == "source"
                 else " · chắc chắn là chia tách/thưởng thì ép --volume adjust"))

    n_src, n_scaled, touched = 0, 0, 0
    plan = {}
    src_idx = src_all.set_index(src_all["time"].dt.normalize())
    for path, df in files.items():
        out = df.copy()
        t = pd.to_datetime(out["time"]).dt.normalize()
        mask_old = t.dt.date < cut
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
                    # Hệ số khối lượng chỉ đúng cho phần TRƯỚC sự kiện quyền;
                    # bar sau vách đã đếm trên số cổ phiếu mới rồi, nhân nữa
                    # là thổi GTGD lịch sử lên lần thứ hai.
                    _sv = scale_vol if day.date() < brk else 1.0
                    out.at[i, "volume"] = float(row["volume"]) * _sv
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

    print(f"[rebase] {touched:,} bar trước {cut} sẽ đổi: "
          f"{n_src:,} lấy thẳng từ nguồn · {n_scaled:,} nhân hệ số")
    if not apply:
        print(f"[rebase] 🔎 CHẠY THỬ — chưa ghi gì. Thêm --apply để ghi thật.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = wh_root / "_meta" / "backup_rebase" / f"{tk}_{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tdir, backup)
    print(f"[rebase] 💾 sao lưu: {backup}")

    done_files = []
    try:
        for path, out in plan.items():
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            out.to_parquet(tmp, index=False)
            _atomic_replace(tmp, path)
            done_files.append(path)
    except Exception as e:                        # noqa: BLE001
        _sweep_tmp(tdir)
        print(f"\n[rebase] ✗ {tk}: GHI HỎNG GIỮA CHỪNG — {e}")
        if done_files:
            # Trạng thái TỆ NHẤT: một phần file ở cơ sở mới, phần còn lại ở cơ
            # sở cũ. Tệ hơn cả hai đầu, và không bộ dò nào gọi tên được nó cho
            # gọn. Phải khôi phục, không được chạy lại đè lên.
            print(f"[rebase]   ⚠️ ĐÃ thay {len(done_files)}/{len(plan)} file "
                  f"⇒ {tk} đang LẪN HAI CƠ SỞ. ĐỪNG chạy lại đè lên.")
            print(f"[rebase]   KHÔI PHỤC TRƯỚC: python "
                  f"scripts/rebase_ticker_history.py --ticker {tk} --restore "
                  f"--apply")
        else:
            print(f"[rebase]   chưa file nào bị thay — {tk} còn NGUYÊN, "
                  f"chạy lại được sau khi tạm dừng Dropbox.")
        return 2
    print(f"[rebase] ✍ đã ghi {len(plan)} file (nguyên tử)")

    left = [j for j in find_jumps(load_bars(prices_dir, tk, since_days=365))
            if j["suspect"]]
    if left:
        print(f"[rebase] ⚠️ VẪN CÒN {len(left)} vách sau khi chữa "
              f"(vách đầu: {left[0]['time']}) — có thể mã bị rebase NHIỀU LẦN, "
              f"chạy lại lệnh này để chữa tiếp lớp sau.")
        return 1
    # `find_jumps` chỉ thấy vách GIÁ ≥30% nên nó báo XANH cả khi tỉ lệ
    # kho/nguồn còn đổi bậc — đúng chuyện xảy ra 19/08: VTP/QNS in "chuỗi đã
    # liền" xong lượt quét ngay sau đó vẫn gắn cờ cả hai. Tự kiểm mà mù đúng
    # lớp lỗi mình sinh ra để chữa thì không phải tự kiểm.
    _left = _residual_basis_step(prices_dir, tk, src_all)
    if _left is not None:
        print(f"[rebase] ⚠️ {tk}: giá đã liền nhưng TỈ LỆ kho/nguồn VẪN đổi "
              f"bậc {_left['shift']:.4f}× tại {_left['break']} — CHƯA chữa "
              f"xong. Soi tay: probe_price_basis --ticker {tk} "
              f"--break-date {_left['break']}")
        return 1
    # Bước tự kiểm THỨ BA, đo MỨC. Hai bước trên đo đạo hàm nên chuỗi vẫn
    # lệch ĐỀU sau khi chữa vẫn lọt — đúng lớp lỗi `--whole-series` sinh ra để
    # chữa, tức bước tự kiểm sẽ mù đúng vào lúc cần sáng nhất.
    _lvl_left = _residual_level(prices_dir, tk, src_all)
    if _lvl_left is not None:
        print(f"[rebase] ⚠️ {tk}: không còn vách nào, NHƯNG kho vẫn lệch MỨC "
              f"so nguồn tới tận {_lvl_left} — CHƯA chữa xong (hệ số hụt, "
              f"hoặc nguồn đổi cơ sở giữa chừng). Soi tay: "
              f"probe_price_basis --ticker {tk}")
        return 1
    # Chữa xong thì mã hết lý do nằm trong sổ cách ly của cửa gác V1 — để lại
    # là doctor kêu mãi và người mất niềm tin vào badge. Xoá ở ĐÂY chứ không ở
    # updater: sync chạy 8 worker, đọc-sửa-ghi sổ 1.700 lần mỗi đêm là tự chuốc
    # lost-update vào đúng thứ sinh ra để giữ.
    _cleared = True
    try:
        from vnstock_basis_guard import clear_drift
        _cleared = bool(clear_drift(wh_root, tk))
    except Exception as e:                        # noqa: BLE001
        _cleared, _err = False, e
    if not _cleared:
        # Nuốt lỗi ở đây là để một mã ĐÃ CHỮA nằm lại trong sổ vĩnh viễn:
        # badge doctor warn mãi cho một mã sạch, và người dùng học cách bỏ qua
        # badge. Vết ACE 07/09 — chữa lúc 21:07, in ✅, 21:20 vẫn trong sổ.
        print(f"[rebase] ⚠️ {tk}: GIÁ đã chữa xong và tự kiểm sạch, NHƯNG "
              f"không xoá được khỏi sổ cách ly (Dropbox/AV đang giữ "
              f"`basis_drift_pending.json`?)")
        print(f"[rebase]   ⇒ cửa gác vẫn chặn mã này. Chạy lại chính lệnh này "
              f"là xong — lượt sau sẽ thấy kho đã sạch và chỉ xoá sổ.")
        return 1
    print(f"[rebase] ✅ {tk}: chuỗi đã liền — không còn vách trong 365 ngày"
          f" · bộ dò MỨC cũng sạch")
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
    ap.add_argument("--whole-series", action="store_true",
                    help="chế độ LỆCH ĐỒNG ĐỀU: kho lệch nguồn cùng một hệ số "
                         "ở MỌI bar (nguồn đã back-adjust trọn lịch sử) nên "
                         "không có vách nào để làm mốc — hai bộ dò bậc đều mù, "
                         "chỉ bộ dò MỨC và cửa gác thấy. Coi TOÀN chuỗi là "
                         "phần 'trước vách'. Cửa vào KHÔNG phải probe mà là "
                         "`uniform_offset_report`, chặt hơn: tỉ lệ phải ổn "
                         "định (spread ≤ %s) trên ≥%s bar. Vẫn CHẠY THỬ nếu "
                         "không có --apply." % (UNIFORM_SPREAD_MAX,
                                                UNIFORM_MIN_BARS))
    ap.add_argument("--from-drift-ledger", action="store_true",
                    help="chữa HÀNG LOẠT mọi mã trong SỔ CÁCH LY của cửa gác "
                         "(_meta/basis_drift_pending.json). Khác --from-sweep: "
                         "vết quét dùng bộ dò BẬC nên không bao giờ thấy lớp "
                         "lệch ĐỒNG ĐỀU, còn sổ cách ly do cửa gác ghi mà gác "
                         "đo MỨC. Mỗi mã vẫn qua đủ cửa riêng. Mặc định CHẠY THỬ.")
    ap.add_argument("--explain", action="store_true",
                    help="CHỈ ĐỌC: in mọi số đo của mã (độ dày kho, vùng chồng "
                         "lấn, tỉ lệ/spread/tầm phủ, từng bộ dò nói gì) rồi "
                         "dừng. Dùng thay `probe_price_basis --ticker <MÃ>` "
                         "cho mã bị gác chặn — lệnh đó chỉ chạy bộ dò BẬC, "
                         "vốn mù với đúng lớp mã này.")
    ap.add_argument("--restore", action="store_true",
                    help="KHÔI PHỤC mã về bản sao lưu gần nhất trong "
                         "_meta/backup_rebase/ thay vì chữa. Dùng khi một lượt "
                         "ghi chết giữa chừng (Dropbox/AV giữ file) và mã đang "
                         "LẪN HAI CƠ SỞ. Mặc định vẫn CHẠY THỬ.")
    ap.add_argument("--volume", choices=("auto", "adjust", "source"),
                    default="auto",
                    help="auto (mặc định): nhân khối lượng theo hệ số giá KHI "
                         "đo thấy nguồn không điều chỉnh volume mà chuỗi volume "
                         "lại gãy tại vách · adjust: luôn nhân · source: luôn "
                         "giữ nguyên theo nguồn")
    args = ap.parse_args(argv)
    if args.whole_series and args.break_date:
        # Có vách thì dùng đường vách; ghi đè TRỌN lịch sử là việc mạnh tay
        # hơn hẳn. Nhận cả hai rồi âm thầm bỏ một cái là cách chắc chắn để
        # người dùng tưởng mình đã chạy chế độ kia.
        ap.error("--whole-series và --break-date loại trừ nhau: có vách thì "
                 "chữa theo vách, --whole-series chỉ dành cho ca KHÔNG có vách")

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
    if args.from_drift_ledger:
        _led = _drift_ledger_targets(wh_root)
        if not _led:
            print("[rebase] ✅ sổ cách ly RỖNG — không mã nào đang bị chặn.")
            return 0
        tickers = _led
        print(f"[rebase] chữa hàng loạt {len(tickers)} mã từ SỔ CÁCH LY"
              + ("" if args.apply else " — CHẠY THỬ, chưa ghi gì"))
    if not tickers:
        ap.error("cần --ticker, --from-sweep hoặc --from-drift-ledger")

    if args.explain:
        worst = 0
        for tk in tickers:
            worst = max(worst, _explain_one(tk, wh_root))
        return worst

    if args.restore:
        worst = 0
        for tk in tickers:
            worst = max(worst, _restore_one(tk, wh_root, args.apply))
        return worst

    worst, done, refused = 0, 0, []
    # Hỏng GHI liên tiếp = Dropbox/AV đang giữ cả thư mục, không phải chuyện
    # của riêng mã nào. Cày tiếp 70 mã nữa chỉ để hỏng 70 lần là phí một tiếng
    # và đẻ ra 70 thư mục sao lưu vô ích.
    _io_streak, _IO_STREAK_MAX = 0, 3
    for tk in tickers:
        _bd = date.fromisoformat(args.break_date) if args.break_date else None
        try:
            rc = _rebase_one(tk, wh_root, args.apply, args.volume, _bd,
                             whole_series=args.whole_series)
        except Exception as e:                    # noqa: BLE001
            # Một mã ném ra ngoài KHÔNG được giết cả lô. Ca 07/09: BRC ném
            # PermissionError ⇒ 68/73 mã còn lại không bao giờ được sờ tới.
            print(f"\n[rebase] ✗ {tk}: LỖI KHÔNG LƯỜNG "
                  f"({type(e).__name__}: {e}) — bỏ qua mã này, chạy tiếp")
            rc = 2
        worst = max(worst, rc)
        if rc == 0:
            done += 1
        else:
            refused.append(tk)
        _io_streak = _io_streak + 1 if rc == 2 else 0
        if _io_streak >= _IO_STREAK_MAX:
            print(f"\n[rebase] ⛔ DỪNG SỚM: {_io_streak} mã liên tiếp hỏng ở "
                  f"bước GHI. Đây là chuyện của cả thư mục, không phải của "
                  f"từng mã — tạm dừng đồng bộ Dropbox (Pause syncing) hoặc "
                  f"tắt quét realtime của antivirus, rồi chạy lại.")
            break
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

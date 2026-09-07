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


# Tỉ lệ kho/nguồn phải ỔN ĐỊNH tới mức nào mới cho ghi đè TRỌN lịch sử.
# max/min của tỉ lệ từng bar. Một lần đổi cơ sở SẠCH cho ra tỉ lệ gần như
# hằng số; lởm chởm nghĩa là còn chuyện khác trộn vào, và ghi đè trọn lịch sử
# là việc KHÔNG LÙI ĐƯỢC nên chỗ này thà chặt quá còn hơn lỏng.
UNIFORM_SPREAD_MAX = 1.01
UNIFORM_MIN_BARS = 20
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
    out = {"n": 0, "ratio": None, "spread": None, "uniform": False, "why": ""}
    try:
        m = _as_dates(wh).merge(_as_dates(src), on="time",
                                suffixes=("_wh", "_src"))
        m = m[(m["close_wh"] > 0) & (m["close_src"] > 0)]
        if m.empty:
            out["why"] = "không có bar nào chồng nhau giữa kho và nguồn"
            return out
        ratios = (m["close_wh"] / m["close_src"]).astype(float)
        out["n"] = int(len(ratios))
        out["ratio"] = float(ratios.median())
        lo, hi = float(ratios.min()), float(ratios.max())
        out["spread"] = (hi / lo) if lo > 0 else float("inf")
        if out["n"] < UNIFORM_MIN_BARS:
            out["why"] = (f"chỉ {out['n']} bar chồng nhau (cần ≥"
                          f"{UNIFORM_MIN_BARS}) — quá ít để nói 'đều'")
            return out
        if abs(out["ratio"] - 1.0) <= tol:
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
                      f"(spread {out['spread']:.4f})")
        return out
    except Exception as e:                        # noqa: BLE001
        out["why"] = f"không đo được ({type(e).__name__}: {e})"
        return out


def _uniform_probe(tk: str, wh_root: Path, since_days: int = 365,
                   tol: float = 0.012) -> dict:
    """`uniform_offset_report` trên dữ liệu THẬT của một mã. Chỉ đọc."""
    from probe_price_basis import fetch_source, load_wh
    d1 = date.today()
    d0 = d1 - timedelta(days=since_days)
    try:
        wh = load_wh(wh_root / "prices", tk, d0, d1)
        if wh.empty:
            return {"uniform": False, "why": "kho rỗng", "n": 0,
                    "ratio": None, "spread": None}
        src = fetch_source(tk, d0, d1)
        if src.empty:
            return {"uniform": False, "why": "nguồn trả rỗng", "n": 0,
                    "ratio": None, "spread": None}
        return uniform_offset_report(wh, src, tol=tol)
    except Exception as e:                        # noqa: BLE001
        return {"uniform": False, "why": f"{type(e).__name__}: {e}", "n": 0,
                "ratio": None, "spread": None}


def _in_drift_ledger(tk: str, wh_root: Path) -> bool:
    """Mã này có đang nằm trong sổ cách ly của cửa gác không? Chỉ ĐỌC."""
    try:
        from vnstock_basis_guard import load_pending
        return tk.upper() in (load_pending(Path(wh_root)) or {})
    except Exception:
        return False


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
        # ⚠️ ĐỪNG tuyên bố sạch chỉ vì hai bộ dò BẬC NHẢY im. Chúng mù với
        # lệch ĐỒNG ĐỀU (đạo hàm = 0 ở mọi điểm). Hỏi nốt bộ dò MỨC, và hỏi
        # cả sổ cách ly — cửa gác đo MỨC nên nó biết thứ bộ dò bậc không biết.
        _lvl = _level_divergence(tk, wh_root)
        _pend = _in_drift_ledger(tk, wh_root)
        if (_lvl is not None or _pend) and whole_series:
            # Đường CHỮA cho lớp lệch đồng đều. Cửa vào không phải `_probe`
            # (nó phán 'aligned' vì trước = sau) mà là `uniform_offset_report`
            # — chặt hơn: đòi tỉ lệ ỔN ĐỊNH, không chỉ đòi có lệch.
            _uni = _uniform_probe(tk, wh_root)
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
    try:
        from vnstock_basis_guard import clear_drift
        clear_drift(wh_root, tk)
    except Exception:
        pass
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

    worst, done, refused = 0, 0, []
    for tk in tickers:
        _bd = date.fromisoformat(args.break_date) if args.break_date else None
        rc = _rebase_one(tk, wh_root, args.apply, args.volume, _bd,
                         whole_series=args.whole_series)
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

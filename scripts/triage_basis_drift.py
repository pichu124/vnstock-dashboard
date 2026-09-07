#!/usr/bin/env python3
"""SOI sổ cách ly lệch cơ sở — phân loại 47 mã TRƯỚC khi chữa.

    python scripts/triage_basis_drift.py            # bảng đầy đủ
    python scripts/triage_basis_drift.py --plan     # thêm kế hoạch chữa theo lô

🔒 **CHỈ ĐỌC.** Script này không ghi gì vào kho — chạy lúc nào cũng được, kể
cả sát giờ phát 18:00. Việc CHỮA (`rebase_ticker_history --apply`) mới ghi
kho, và kho dùng chung qua Dropbox nên **đừng chữa trong lúc phát chạy**.

Vì sao cần soi trước: `run.py doctor` in ra "47 mã ĐANG KHÔNG cập nhật giá"
kèm sáu cái tên đầu. Con số đó không nói được điều quan trọng nhất — **mỗi mã
lệch VÌ SAO**:

* **Có sự kiện quyền khớp ngày vách** ⇒ lệch là ĐÚNG DỰ KIẾN, kho chỉ chưa
  nối lại thang giá. Chữa máy móc được, hàng loạt.
* **Không sự kiện nào** ⇒ chưa biết vì sao lệch. Chữa mù ở đây là **nhân bản
  một con số sai lên toàn bộ lịch sử của mã** — đúng thứ cửa gác sinh ra để
  chặn. Phải soi tay từng mã.

Hai nhóm đó cần hai cách xử lý khác hẳn nhau, nên gộp chúng vào một lệnh
`--from-sweep` là bỏ qua đúng chỗ cần người quyết.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

def _guard_tol_pct() -> float:
    """Ngưỡng kích hoạt của chính cửa gác, tính bằng %. MỘT nguồn sự thật.

    Mọi mã trong sổ đều đã vượt ngưỡng này — đó là lý do nó có mặt. Đặt một
    con số riêng ở đây là đẻ ra ngưỡng thứ hai phải giữ đồng bộ bằng tay,
    đúng thứ `CLAUDE.md` cấm.
    """
    try:
        from vnstock_basis_guard import TOL
        return float(TOL) * 100.0
    except Exception:
        return 1.2


# "Sát ngưỡng" = trong vòng 25% phía trên mốc kích hoạt. Ở quanh đó, làm tròn
# giá là nguồn báo động giả đáng kể (ghi ngay trong `vnstock_basis_guard`).
NOISE_PCT = _guard_tol_pct() * 1.25

# Tỉ lệ "tròn" hay gặp ở chia tách / thưởng / cổ tức cổ phiếu VN.
ROUND_RATIOS = (1.05, 1.10, 1.15, 1.20, 1.25, 1.50, 2.00, 3.00)
# ⚠️ Dung sai phải CHẶT. Các mốc cách nhau 0,05 nên nới tới 0,015 là bắt nhầm
# gần một phần ba dải — AAM 1.0424 "khớp" 1.05 và tụt khỏi nhóm ĐỎ, đúng cái
# nhóm cần người nhìn. Gợi ý bắt bừa thì tệ hơn không gợi ý.
ROUND_TOL = 0.005


# ─────────────────────────────────────────────────────────────────────────
# Hàm THUẦN — test được không cần kho
# ─────────────────────────────────────────────────────────────────────────
def days_stale(detected_at: str, today: "date | None" = None) -> "int | None":
    """Mã này đứng giá bao nhiêu ngày rồi? Không đọc được ngày ⇒ None."""
    try:
        d = date.fromisoformat(str(detected_at)[:10])
    except Exception:
        return None
    return max(0, ((today or date.today()) - d).days)


def near_round_ratio(ratio: float) -> "float | None":
    """Tỉ lệ này có sát một tỉ lệ quyền TRÒN không? — gợi ý, KHÔNG phải kết luận.

    Sát `1.10` thì RẤT có thể là thưởng 10%, nhưng "rất có thể" không phải
    bằng chứng. Nó chỉ dùng để xếp thứ tự soi tay, không để tự chữa.
    """
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return None
    for cand in ROUND_RATIOS:
        if abs(r - cand) <= ROUND_TOL:
            return cand
    return None


def classify(rec: dict) -> str:
    """`co_su_kien` · `tron_chua_ro` · `chua_ro` · `nhieu`.

    Chỉ nhìn thứ CÓ TRONG SỔ. Không suy ra nguyên nhân — đó là việc của người
    đọc, và của `probe_price_basis` khi soi tay.
    """
    if rec.get("event"):
        return "co_su_kien"
    try:
        pct = abs(float(rec.get("pct", 0.0)))
    except (TypeError, ValueError):
        pct = 0.0
    if pct < NOISE_PCT:
        return "nhieu"
    return "tron_chua_ro" if near_round_ratio(rec.get("ratio")) else "chua_ro"


NHOM = {
    "co_su_kien": ("✅ CÓ sự kiện quyền khớp", "chữa máy móc được, hàng loạt"),
    "tron_chua_ro": ("🟡 tỉ lệ TRÒN, chưa khớp sự kiện",
                     "nhiều khả năng là quyền chưa vào sổ — soi tay trước"),
    "chua_ro": ("🔴 KHÔNG sự kiện, tỉ lệ lẻ",
                "chưa biết vì sao — CHỮA MÙ Ở ĐÂY LÀ NHÂN BẢN SỐ SAI"),
    "nhieu": (f"⚪ SÁT ngưỡng ({_guard_tol_pct():.1f}%–{NOISE_PCT:.1f}%)",
              "quanh mốc kích hoạt, làm tròn giá có thể đủ gây ra"),
}
NHOM_ORDER = ("chua_ro", "tron_chua_ro", "co_su_kien", "nhieu")


def summarize(pending: dict, today: "date | None" = None,
              resolve=None) -> dict:
    """{nhóm: [bản ghi]} + vài con số tổng. Hàm thuần — `resolve` bơm từ ngoài.

    `resolve(ticker, rec) -> kind | None` tra LẠI kho sự kiện. Bơm từ ngoài
    để hàm này vẫn test được offline, và để chỗ gọi quyết định có tra lại hay
    không.
    """
    groups: dict = {k: [] for k in NHOM_ORDER}
    n_live = 0
    for tk in sorted(pending):
        rec = dict(pending[tk] or {})
        rec["ticker"] = tk.upper()
        rec["stale"] = days_stale(rec.get("detected_at", ""), today)
        rec["round_hint"] = near_round_ratio(rec.get("ratio"))
        if resolve is not None and not rec.get("event"):
            live = resolve(rec["ticker"], rec)
            if live:
                rec["event"] = live
                rec["event_source"] = "tra lại"
                n_live += 1
        groups[classify(rec)].append(rec)
    stales = [r["stale"] for g in groups.values() for r in g
              if r["stale"] is not None]
    return {
        "groups": groups,
        "total": sum(len(g) for g in groups.values()),
        "max_stale": max(stales) if stales else None,
        "bars_lost": sum(stales),        # xấp xỉ: mỗi ngày đứng ≈ 1 bar thiếu
        "n_live": n_live,                # tra LẠI mới ra, sổ cũ không có
    }


def registry_event_kind(ticker: str, warehouse, start, end):
    """Tra SỔ ĐĂNG KÝ `corp_actions_registry.parquet` — kho THỨ HAI.

    ⚠️ Đo 26/08: app có **HAI kho sự kiện quyền song song, không nói chuyện
    với nhau**:

    | kho | file | ai NẠP | ai ĐỌC |
    |---|---|---|---|
    | cache theo mã | `_meta/corp_actions/<MÃ>.parquet` | `vnstock_adjust.refresh_events` (API vnstock) | `load_events` → `_corp_event_kind` → **cửa gác** |
    | sổ đăng ký | `_meta/corp_actions_registry.parquet` | `run.py vietstock --register`, `registry` | `vnstock_corp_registry`, `load_recent_exdiv` |

    Nên `vietstock --bulk --register` (26/08: nạp 1.520 mã) đổ đầy kho THỨ
    HAI, còn cửa gác tra kho THỨ NHẤT ⇒ vẫn 0/70. Bộ soi vì thế phải hỏi CẢ
    HAI, nếu không nó báo "không có sự kiện" trong khi sự kiện nằm ngay đó.

    Khoảng tìm do `event_window` quyết định, và nó tìm **về phía TRƯỚC** từ
    mép cửa sổ so sánh — ex_date nằm SAU khoảng đối chiếu, không nằm trong.
    Xem chứng minh ở docstring của `event_window`.
    """
    try:
        import pandas as pd

        path = Path(warehouse) / "_meta" / "corp_actions_registry.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if df is None or df.empty or "ex_date" not in df.columns:
            return None
        hit = df[df["ticker"].astype(str).str.upper() == ticker.upper()]
        if hit.empty:
            return None
        ex = pd.to_datetime(hit["ex_date"]).dt.date
        near = hit[(ex >= start) & (ex <= end)]
        if near.empty:
            return None
        return str(near.iloc[0].get("type") or "") or None
    except Exception:
        return None


def event_window(rec: dict, pad_days: int = 5, today: "date | None" = None):
    """(đầu, cuối) khoảng tìm sự kiện — **VỀ PHÍA TRƯỚC** từ mép cửa sổ so sánh.

    ⚠️ Bản đầu của hàm này viết *"vách gãy nằm TRONG cửa sổ ấy"* và tìm trong
    `[first, last]`. **SAI**, và sai theo kiểu đảm bảo trượt 100%. Chứng minh
    từ chính cơ chế lỗi (`vnstock_basis_guard` đầu module):

        nguồn back-adjust MỌI bar TRƯỚC ex_date; bar từ ex_date trở đi giữ nguyên
        ⇒ ρ(d) = kho/nguồn = f ≠ 1 với d < ex_date,  ρ(d) = 1.0 với d ≥ ex_date

    `check_basis` báo `basis_changed` khi TRUNG VỊ ρ trên `[first, last]` lệch
    khỏi 1. Muốn trung vị lệch thì **mọi bar trong khoảng phải cùng một phía
    của ex_date**, tức `ex_date > last`. Chiều ngược lại cũng chặn: nếu ex_date
    nằm TRƯỚC khoảng thì kho đã ở cơ sở mới, ρ = 1, verdict `aligned`, guard
    câm hẳn — đúng như docstring của guard nói (*"bắt đúng khoảnh khắc lệch
    sinh ra, không bắt di chứng cũ"*).

    ⇒ Tìm trong `(last, detected_at + pad]`: ex_date nằm đúng trong khe mà kho
    chưa cập nhật, từ bar cuối tới lúc cửa gác nổ.

    Và cửa sổ so sánh **hẹp** (~7 phiên: `WANT_BARS = MIN_BARS + 3`), nên
    `[first, last]` lại càng không thể chứa ex_date.
    """
    from datetime import timedelta

    def _d(v):
        try:
            return date.fromisoformat(str(v)[:10])
        except Exception:
            return None

    win = rec.get("window") or []
    last = _d(win[-1]) if win else None
    seen = _d(rec.get("detected_at"))
    if last is None and seen is None:
        return None
    hi_base = seen or last
    lo = last or (seen - timedelta(days=pad_days))
    hi = hi_base + timedelta(days=pad_days)
    cap = today or date.today()
    if hi > cap:
        hi = cap
    return (lo, hi) if lo <= hi else (lo, lo)


def live_event_kind(ticker: str, warehouse, around, window_days: int = 10):
    """Tra CACHE THEO MÃ **NGAY BÂY GIỜ**. Không tra được ⇒ None.

    ⚠️ Vì sao phải tra lại: trường `event` trong sổ cách ly là **ảnh chụp lúc
    PHÁT HIỆN** — `vnstock_updater` ghi nó vào đúng lúc mã bị chặn. Nạp lại
    kho sự kiện **không viết ngược lại sổ**. Bộ soi chỉ đọc ảnh chụp thì nạp
    kho xong chạy lại vẫn ra y nguyên số cũ, và người đọc kết luận việc nạp
    kho vô ích — trong khi thật ra đang đọc số cũ.

    Chỉ ĐỌC: `load_events` đọc parquet trong `_meta/corp_actions/`.
    """
    try:
        from vnstock_updater import _corp_event_kind
        return _corp_event_kind(Path(warehouse), ticker, around, window_days)
    except Exception:
        return None


def event_around(rec: dict) -> "date | None":
    """Ngày để tra CACHE THEO MÃ: mép cuối cửa sổ so sánh (`last`).

    `_corp_event_kind` tự nới ±`window_days` quanh mốc này, và vì ex_date nằm
    **SAU** `last` (xem `event_window`), phần nới VỀ PHÍA TRƯỚC mới là phần
    có tác dụng.
    """
    win = rec.get("window") or []
    for cand in (win[-1] if win else None, rec.get("detected_at")):
        try:
            return date.fromisoformat(str(cand)[:10])
        except Exception:
            continue
    return None


def match_rate(groups: dict) -> "float | None":
    """Bao nhiêu phần trăm mã tra ra được loại sự kiện. Sổ rỗng ⇒ None."""
    total = sum(len(g) for g in groups.values())
    if not total:
        return None
    return len(groups.get("co_su_kien", [])) / total


# Dưới sàn này thì con số nói về KHO SỰ KIỆN chứ không nói về các mã.
BLIND_RATE = 0.10
BLIND_MIN_N = 10


def event_store_is_blind(groups: dict) -> bool:
    """Kho sự kiện có đang MÙ không — tra gần như không ra gì?

    ⚠️ Đây là chỗ dễ đọc sai nhất của cả bộ soi. `event: None` nghĩa là **kho
    sự kiện không biết**, KHÔNG phải "mã này không có sự kiện quyền". Chính
    `vnstock_updater._corp_event_kind` đã ghi: *"Kho sự kiện đang MỎNG (19/08:
    70 mã lệch chỉ 3 mã tra ra loại)"*.

    Khi tra ra gần bằng 0 trên một sổ đủ lớn, xếp cả đống vào "🔴 chưa biết vì
    sao" là **đổ lỗi cho các mã trong khi lỗi nằm ở kho tra cứu** — và nó đẩy
    người đọc đi soi tay hàng chục mã thay vì nạp lại kho một lần.
    """
    total = sum(len(g) for g in groups.values())
    rate = match_rate(groups)
    return bool(total >= BLIND_MIN_N and rate is not None and rate < BLIND_RATE)


def vn30_hits(pending: dict, basket) -> list:
    """Mã VN30 nào đang bị cách ly — một mã VN30 đứng giá nặng hơn hẳn.

    Nó vào rổ chỉ số, vào brief, vào heatmap tầng nóng. Lẫn trong danh sách
    47 cái tên thì không ai nhận ra.
    """
    want = {str(t).upper() for t in (basket or [])}
    return sorted(t.upper() for t in pending if t.upper() in want)


def registry_size(warehouse) -> dict:
    """Sổ đăng ký sự kiện có bao nhiêu mã / dòng? Chỉ ĐỌC.

    Dùng để phân biệt hai chuyện mà bản đầu gộp làm một: **sổ TRỐNG** (nạp là
    cứu) với **sổ ĐẦY mà vẫn không khớp** (nạp lại KHÔNG cứu). Bản đầu thấy
    "tra không ra" là bảo nạp lại, nên sau khi user đã nạp 1.520 mã sáng 26/08
    mà tỉ lệ khớp vẫn 3%, nó vẫn in đúng câu ấy — đẩy user vào một lượt chạy
    1.723 mã lần thứ hai cho cùng một kết quả.
    """
    out = {"exists": False, "rows": 0, "tickers": 0}
    try:
        import pandas as pd

        path = Path(warehouse) / "_meta" / "corp_actions_registry.parquet"
        if not path.exists():
            return out
        out["exists"] = True
        df = pd.read_parquet(path)
        if df is None or df.empty:
            return out
        out["rows"] = int(len(df))
        if "ticker" in df.columns:
            out["tickers"] = int(df["ticker"].astype(str).str.upper().nunique())
        return out
    except Exception:
        return out


def batch_plan(groups: dict, warehouse=None) -> list:
    """Các dòng lệnh đề xuất, THEO NHÓM. Chạy thử trước, không gộp nhóm đỏ.

    ⚠️ Bản đầu dừng hẳn ở "nạp lại kho sự kiện" khi kho mù. Sai hai lần:

    1. **Nạp lại không phải lúc nào cũng cứu.** Sổ đăng ký đầy mà tỉ lệ khớp
       vẫn 3% thì lượt nạp thứ hai cho đúng kết quả ấy — xem `registry_size`.
    2. **Loại sự kiện KHÔNG phải cửa của bước chữa.** Nó chỉ trả lời *vì sao*.
       `--whole-series` mang bằng chứng riêng về *cái gì*: tỉ lệ kho/nguồn có
       ĐỀU trên toàn dải không (`uniform_offset_report`). Bắt bước chữa chờ
       một kho tra cứu mà nó không cần là giam 69 mã vô thời hạn.

    Giữ nguyên bất biến gốc: **không gộp mã chưa rõ vào một lệnh chữa mù**.
    Lệnh theo sổ cách ly không liệt kê mã nào — mỗi mã tự qua cửa đo riêng và
    bị từ chối riêng, nên nó không phải một lượt chữa hàng loạt mù.
    """
    lines = []
    _ws = "python scripts/rebase_ticker_history.py --from-drift-ledger --whole-series"
    if event_store_is_blind(groups):
        reg = registry_size(warehouse) if warehouse is not None else {}
        if not reg.get("tickers"):
            lines.append((
                "① kho sự kiện TRỐNG — nạp một lần. Đây chỉ để ĐỌC ĐƯỢC VÌ "
                "SAO, KHÔNG phải cửa của bước chữa bên dưới",
                "python run.py vietstock --bulk --register"))
            lines.append((
                "② rồi chạy lại bộ soi", 
                "python scripts/triage_basis_drift.py --plan"))
        else:
            lines.append((
                f"① sổ đăng ký ĐÃ có {reg['tickers']:,} mã / {reg['rows']:,} "
                f"dòng mà vẫn không khớp ⇒ NẠP LẠI KHÔNG CỨU, đừng chạy "
                f"`vietstock --bulk` lần nữa. Loại sự kiện chỉ trả lời VÌ SAO; "
                f"bước chữa không hỏi nó — nó tự đo tỉ lệ có ĐỀU không",
                _ws))
            lines.append(("② …thấy ổn thì ghi thật", f"{_ws} --apply"))
            lines.append(("③ soi lại — sổ cách ly phải vơi",
                          "python scripts/triage_basis_drift.py --plan"))
            return lines
        lines.append((
            "③ chữa theo SỔ CÁCH LY — mỗi mã tự qua cửa `uniform_offset_report`, "
            "mã không lệch đều thì bị từ chối RIÊNG nó (không có chữa mù)",
            _ws))
        lines.append(("④ …thấy ổn thì ghi thật", f"{_ws} --apply"))
        return lines

    safe = [r["ticker"] for r in groups.get("co_su_kien", [])]
    if safe:
        args = " ".join(f"--ticker {t}" for t in safe)
        # `--whole-series` CHO PHÉP chứ không ép: có vách thì vẫn đi đường
        # vách. Thiếu cờ này thì mã lệch đồng đều bị từ chối rồi user phải gõ
        # lại đúng lệnh đó kèm cờ — một vòng thừa.
        lines.append(("Nhóm CÓ sự kiện — chạy thử trước",
                      f"python scripts/rebase_ticker_history.py {args} --whole-series"))
        lines.append(("…thấy ổn thì ghi thật",
                      f"python scripts/rebase_ticker_history.py {args} "
                      f"--whole-series --apply"))
    for key in ("tron_chua_ro", "chua_ro"):
        for r in groups.get(key, []):
            lines.append((f"soi tay {r['ticker']} ({NHOM[key][0]})",
                          f"python scripts/probe_price_basis.py "
                          f"--ticker {r['ticker']}"))
    return lines


# ─────────────────────────────────────────────────────────────────────────
# Đường có KHO — chỉ đọc
# ─────────────────────────────────────────────────────────────────────────
def load_pending(warehouse: Path) -> dict:
    from vnstock_basis_guard import load_pending as _lp
    return _lp(Path(warehouse))


def _basket() -> list:
    try:
        from vnstock_brief_canon import VN30_TICKERS
        return list(VN30_TICKERS)
    except Exception:
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warehouse", default="data_warehouse")
    ap.add_argument("--plan", action="store_true",
                    help="In thêm kế hoạch chữa theo lô")
    ap.add_argument("--no-relookup", action="store_true",
                    help="Chỉ đọc trường `event` trong sổ, KHÔNG tra lại kho "
                         "sự kiện (nhanh hơn, nhưng thấy số cũ)")
    args = ap.parse_args(argv)

    pending = load_pending(Path(args.warehouse))
    if not pending:
        print("[triage] ✅ sổ cách ly RỖNG — không mã nào đang bị chặn cập nhật.")
        return 0

    wh = Path(args.warehouse)

    def _resolve(ticker, rec):
        # Hỏi CẢ HAI kho — chúng được nạp bằng hai lệnh khác nhau và không
        # đồng bộ với nhau (xem `registry_event_kind`).
        around = event_around(rec)
        kind = live_event_kind(ticker, wh, around) if around else None
        if kind:
            return kind
        span = event_window(rec)
        return registry_event_kind(ticker, wh, *span) if span else None

    st = summarize(pending, resolve=None if args.no_relookup else _resolve)
    if st["n_live"]:
        print(f"[triage] 🔄 tra LẠI kho sự kiện: {st['n_live']} mã nay ra được "
              f"loại sự kiện mà sổ cũ không có "
              f"(sổ ghi `event` lúc PHÁT HIỆN, nạp kho không viết ngược lại)")
    print(f"[triage] {st['total']} mã đang bị chặn cập nhật giá")
    if st["max_stale"] is not None:
        print(f"[triage] đứng lâu nhất {st['max_stale']} ngày · "
              f"tổng ~{st['bars_lost']} bar giá đang thiếu")

    blind = event_store_is_blind(st["groups"])
    if blind:
        rate = match_rate(st["groups"]) or 0.0
        print("\n" + "!" * 70)
        print(f"⚠️  CHỈ {rate:.0%} SỐ MÃ TRA RA ĐƯỢC LOẠI SỰ KIỆN "
              f"({len(st['groups']['co_su_kien'])}/{st['total']}).")
        print("    Đây là phát biểu về KHO SỰ KIỆN, KHÔNG phải về các mã này.")
        print("    `event: None` = kho tra cứu không biết, không phải 'mã này")
        print("    không có sự kiện quyền'. Nhóm 🔴 bên dưới vì thế đọc là")
        print("    'CHƯA TRA ĐƯỢC', đừng đọc thành 'đáng ngờ'.")
        print("    ⇒ Việc đầu tiên KHÔNG phải soi tay từng mã. Và loại sự")
        print("    kiện KHÔNG phải cửa của bước chữa — xem KẾ HOẠCH bên dưới.")
        print("!" * 70)

    vn30 = vn30_hits(pending, _basket())
    if vn30:
        print(f"[triage] ⚠️ trong đó có {len(vn30)} mã VN30: {', '.join(vn30)}"
              f" — vào chỉ số, vào brief, vào heatmap tầng nóng")

    for key in NHOM_ORDER:
        rows = st["groups"][key]
        if not rows:
            continue
        title, why = NHOM[key]
        if blind and key in ("chua_ro", "tron_chua_ro"):
            why = "CHƯA TRA ĐƯỢC (kho sự kiện đang mù) — không phải đáng ngờ"
        print(f"\n── {title} · {len(rows)} mã — {why}")
        print(f"   {'MÃ':<6} {'TỈ LỆ':>8} {'LỆCH %':>8} {'ĐỨNG':>6}  SỰ KIỆN / GỢI Ý")
        for r in rows:
            ratio = r.get("ratio")
            pct = r.get("pct")
            stale = r.get("stale")
            hint = r.get("event") or (
                f"~{r['round_hint']:.2f}?" if r.get("round_hint") else "—")
            s_ratio = f"{ratio:.4f}" if isinstance(ratio, (int, float)) else "—"
            s_pct = f"{pct:.2f}" if isinstance(pct, (int, float)) else "—"
            s_stale = f"{stale}d" if stale is not None else "—"
            print(f"   {r['ticker']:<6} {s_ratio:>8} {s_pct:>8} {s_stale:>6}"
                  f"  {hint}")

    if args.plan:
        print("\n" + "=" * 70)
        print("KẾ HOẠCH — ⚠️ mọi lệnh dưới đây GHI KHO. Kho dùng chung qua")
        print("Dropbox, nên KHÔNG chạy trong lúc phát 18:00-19:xx.")
        print("=" * 70)
        for label, cmd in batch_plan(st["groups"], wh):
            print(f"\n# {label}\n{cmd}")
        if st["groups"]["chua_ro"] and not blind:
            print(f"\n🔴 {len(st['groups']['chua_ro'])} mã KHÔNG có sự kiện và "
                  f"tỉ lệ lẻ — ĐỪNG gộp vào lệnh chữa hàng loạt.")
            print("   Chữa mù ở đó là nhân bản một con số sai lên toàn bộ lịch "
                  "sử của mã,\n   mà đó đúng là thứ cửa gác sinh ra để chặn.")
    else:
        print("\n(thêm --plan để in kế hoạch chữa theo lô)")
    return 1 if st["groups"]["chua_ro"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

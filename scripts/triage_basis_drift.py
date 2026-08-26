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

# Lệch dưới ngưỡng này thì gần như chắc là làm tròn/nhiễu, không phải sự kiện
# quyền. Trên nó mà KHÔNG có sự kiện mới thật sự đáng ngờ.
NOISE_PCT = 1.5

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
    "nhieu": (f"⚪ lệch < {NOISE_PCT}%", "gần ngưỡng, có thể chỉ là làm tròn"),
}
NHOM_ORDER = ("chua_ro", "tron_chua_ro", "co_su_kien", "nhieu")


def summarize(pending: dict, today: "date | None" = None) -> dict:
    """{nhóm: [bản ghi]} + vài con số tổng. Hàm thuần."""
    groups: dict = {k: [] for k in NHOM_ORDER}
    for tk in sorted(pending):
        rec = dict(pending[tk] or {})
        rec["ticker"] = tk.upper()
        rec["stale"] = days_stale(rec.get("detected_at", ""), today)
        rec["round_hint"] = near_round_ratio(rec.get("ratio"))
        groups[classify(rec)].append(rec)
    stales = [r["stale"] for g in groups.values() for r in g
              if r["stale"] is not None]
    return {
        "groups": groups,
        "total": sum(len(g) for g in groups.values()),
        "max_stale": max(stales) if stales else None,
        "bars_lost": sum(stales),        # xấp xỉ: mỗi ngày đứng ≈ 1 bar thiếu
    }


def vn30_hits(pending: dict, basket) -> list:
    """Mã VN30 nào đang bị cách ly — một mã VN30 đứng giá nặng hơn hẳn.

    Nó vào rổ chỉ số, vào brief, vào heatmap tầng nóng. Lẫn trong danh sách
    47 cái tên thì không ai nhận ra.
    """
    want = {str(t).upper() for t in (basket or [])}
    return sorted(t.upper() for t in pending if t.upper() in want)


def batch_plan(groups: dict) -> list:
    """Các dòng lệnh đề xuất, THEO NHÓM. Chạy thử trước, không gộp nhóm đỏ."""
    lines = []
    safe = [r["ticker"] for r in groups.get("co_su_kien", [])]
    if safe:
        args = " ".join(f"--ticker {t}" for t in safe)
        lines.append(("Nhóm CÓ sự kiện — chạy thử trước",
                      f"python scripts/rebase_ticker_history.py {args}"))
        lines.append(("…thấy ổn thì ghi thật",
                      f"python scripts/rebase_ticker_history.py {args} --apply"))
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
    args = ap.parse_args(argv)

    pending = load_pending(Path(args.warehouse))
    if not pending:
        print("[triage] ✅ sổ cách ly RỖNG — không mã nào đang bị chặn cập nhật.")
        return 0

    st = summarize(pending)
    print(f"[triage] {st['total']} mã đang bị chặn cập nhật giá")
    if st["max_stale"] is not None:
        print(f"[triage] đứng lâu nhất {st['max_stale']} ngày · "
              f"tổng ~{st['bars_lost']} bar giá đang thiếu")

    vn30 = vn30_hits(pending, _basket())
    if vn30:
        print(f"[triage] ⚠️ trong đó có {len(vn30)} mã VN30: {', '.join(vn30)}"
              f" — vào chỉ số, vào brief, vào heatmap tầng nóng")

    for key in NHOM_ORDER:
        rows = st["groups"][key]
        if not rows:
            continue
        title, why = NHOM[key]
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
        for label, cmd in batch_plan(st["groups"]):
            print(f"\n# {label}\n{cmd}")
        if st["groups"]["chua_ro"]:
            print(f"\n🔴 {len(st['groups']['chua_ro'])} mã KHÔNG có sự kiện và "
                  f"tỉ lệ lẻ — ĐỪNG gộp vào lệnh chữa hàng loạt.")
            print("   Chữa mù ở đó là nhân bản một con số sai lên toàn bộ lịch "
                  "sử của mã,\n   mà đó đúng là thứ cửa gác sinh ra để chặn.")
    else:
        print("\n(thêm --plan để in kế hoạch chữa theo lô)")
    return 1 if st["groups"]["chua_ro"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

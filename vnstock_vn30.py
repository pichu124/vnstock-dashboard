"""vnstock_vn30.py — rổ VN30 hiện hành, một nguồn sự thật duy nhất.

HOSE xét lại rổ VN30 **hai lần mỗi năm** (hiệu lực đầu tháng 2 và đầu tháng
8). Trước module này, danh sách 30 mã được CHÉP CỨNG ở ba chỗ độc lập —
``vnstock_brief_canon.VN30_TICKERS``, ``vnstock_wss.VN30_SYMBOLS`` và
``vnstock_news._VN30_FALLBACK`` — nên mỗi kỳ đổi rổ là dashboard, brief và
heatmap live cùng nói sai, mà KHÔNG có gì báo. Vết 20/08/2026: user nhìn
heatmap VN30 trong phiên và thấy rổ cũ.

Thứ tự lấy: **API sống → cache đĩa → hằng số chép cứng**. Hằng số vẫn giữ
nguyên vai trò lưới cuối (mất mạng vẫn vẽ được), nhưng nó KHÔNG còn là nguồn
sự thật, và ``diff_vs_fallback()`` cho ``run.py doctor`` réo khi hai bên lệch.

Cache nằm trong ``data_warehouse/_meta/`` ⇒ đi qua Dropbox ⇒ fetch một lần ở
máy nào cũng phục vụ cả hai máy.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent
CACHE_PATH = _REPO / "data_warehouse" / "_meta" / "vn30_members.json"

# Rổ đúng 30 mã. Nhận dưới ngưỡng này = API trả dở dang ⇒ TỪ CHỐI, giữ nguồn
# cũ. Rổ teo còn 12 mã âm thầm còn tệ hơn rổ cũ: heatmap mất mã mà không ai
# biết vì sao.
MIN_MEMBERS = 25
MAX_MEMBERS = 35
CACHE_MAX_AGE_DAYS = 7.0

_ENV_FLAG = "VNSTOCK_VN30_DYNAMIC"


def enabled() -> bool:
    """Kill-switch: đặt VNSTOCK_VN30_DYNAMIC=0 để chỉ dùng hằng số chép cứng."""
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "false", "no")


def fallback_members() -> list[str]:
    """Rổ chép cứng — lưới cuối, KHÔNG phải nguồn sự thật."""
    from vnstock_brief_canon import VN30_TICKERS
    return sorted(VN30_TICKERS)


# ─────────────────────────────────────────────────────────────────────────
# Hàm thuần — test được không cần mạng, không cần đĩa
# ─────────────────────────────────────────────────────────────────────────
def validate(members) -> list[str] | None:
    """Chuẩn hoá + kiểm tỉnh táo. Trả None nếu danh sách không dùng được."""
    if not members:
        return None
    clean = sorted({str(m).strip().upper() for m in members if str(m).strip()})
    if not MIN_MEMBERS <= len(clean) <= MAX_MEMBERS:
        return None
    if not all(t.isalnum() and 3 <= len(t) <= 4 for t in clean):
        return None
    return clean


def diff_vs_fallback(members, fallback=None) -> tuple[list[str], list[str]]:
    """(mã MỚI vào rổ, mã ĐÃ rời rổ) so với hằng số chép cứng."""
    fb = set(fallback if fallback is not None else fallback_members())
    cur = set(members or ())
    return sorted(cur - fb), sorted(fb - cur)


def cache_age_days(updated_at: str | None, now: datetime | None = None) -> float | None:
    """Tuổi cache theo ngày; None nếu dấu thời gian không đọc được."""
    if not updated_at:
        return None
    try:
        then = datetime.fromisoformat(str(updated_at))
    except (TypeError, ValueError):
        return None
    now = now or datetime.now()
    return (now - then).total_seconds() / 86400.0


def resolve(fetch=None, cache=None, fallback=None,
            now: datetime | None = None) -> dict:
    """
    Chọn rổ VN30 theo thứ tự API sống → cache → hằng số. HÀM THUẦN: mọi I/O
    được tiêm vào qua ``fetch`` (callable) và ``cache`` (dict đã đọc sẵn).

    Trả ``{"members": [...], "source": "live"|"cache"|"fallback",
    "stale": bool, "age_days": float|None}``.
    """
    fb = list(fallback if fallback is not None else fallback_members())

    if fetch is not None:
        try:
            live = validate(fetch())
        except Exception:
            live = None
        if live:
            return {"members": live, "source": "live", "stale": False,
                    "age_days": 0.0}

    if cache:
        cached = validate(cache.get("members"))
        if cached:
            age = cache_age_days(cache.get("updated_at"), now)
            return {"members": cached, "source": "cache",
                    "stale": age is None or age > CACHE_MAX_AGE_DAYS,
                    "age_days": age}

    return {"members": sorted(fb), "source": "fallback", "stale": True,
            "age_days": None}


# ─────────────────────────────────────────────────────────────────────────
# Đường có I/O — mỏng, gói quanh `resolve`
# ─────────────────────────────────────────────────────────────────────────
def extract_symbols(obj) -> list[str] | None:
    """
    Bóc danh sách mã ra khỏi thứ mà API trả về. HÀM THUẦN.

    ⚠️ `Listing.symbols_by_group("VN30")` của VCI trả **pd.Series** (`return
    df["symbol"]`), KHÔNG phải DataFrame. Bản đầu ở đây — và
    `vnstock_brief.get_vn30_live()` từ trước tới nay — đều dò `obj.columns`
    nên ném AttributeError ngay và im lặng rơi về hằng số: đường "lấy rổ
    động" trông như đang sống mà thực ra CHƯA BAO GIỜ chạy (doctor --net
    20/08 mới lòi ra). Nhận mọi dạng hợp lý, đừng đoán dạng nào.
    """
    if obj is None:
        return None
    # pandas Series — dạng THẬT của VCI
    if hasattr(obj, "tolist") and not hasattr(obj, "columns"):
        vals = list(obj.tolist())
    # pandas DataFrame
    elif hasattr(obj, "columns"):
        cols = [str(c) for c in obj.columns]
        col = next((c for c in cols
                    if str(c).lower() in ("ticker", "symbol", "code")), None)
        if col is None:
            if len(cols) != 1:
                return None
            col = cols[0]           # 1 cột tên lạ vẫn dùng được
        vals = list(obj[col])
    elif isinstance(obj, dict):
        vals = list(obj.values())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        vals = list(obj)
    else:
        return None
    out = [str(v).strip() for v in vals if v is not None and str(v).strip()]
    return out or None


def _fetch_live() -> list[str] | None:
    """Hỏi API danh sách thành phần VN30. Lỗi gì cũng trả None."""
    from vnstock_auth import get_vnstock
    return extract_symbols(
        get_vnstock("VCB", "VCI").listing.symbols_by_group("VN30"))


def load_cache() -> dict | None:
    import json
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_cache(members: list[str]) -> None:
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(
        {"members": list(members), "updated_at": datetime.now().isoformat(timespec="seconds")},
        CACHE_PATH,
    )


# Cache trong tiến trình: dashboard rerun liên tục, không được gọi API mỗi lượt.
_MEM: dict | None = None


def get_members(force_refresh: bool = False) -> list[str]:
    """Rổ VN30 dùng được ngay. Không bao giờ ném — xấu nhất trả hằng số."""
    return status(force_refresh=force_refresh)["members"]


def status(force_refresh: bool = False, allow_fetch: bool = True) -> dict:
    """
    Như ``get_members`` nhưng kèm nguồn/tuổi — cho doctor và badge.

    ``allow_fetch=False`` cấm tuyệt đối gọi mạng: đường doctor OFFLINE phải
    chạy dưới 1s và không được đụng internet, kể cả khi cache đã cũ.
    """
    global _MEM
    if _MEM is not None and not force_refresh:
        return dict(_MEM)

    cache = load_cache()
    age = cache_age_days((cache or {}).get("updated_at"))
    # Cache còn tươi thì KHÔNG gọi API — rổ đổi 2 lần/năm, không đáng
    # một request mỗi lần mở dashboard.
    want_live = (allow_fetch and enabled()
                 and (force_refresh or age is None or age > CACHE_MAX_AGE_DAYS))
    out = resolve(fetch=_fetch_live if want_live else None, cache=cache)

    if out["source"] == "live":
        try:
            save_cache(out["members"])
        except Exception:
            pass
        _MEM = dict(out)
    elif allow_fetch:
        # Không nhớ kết quả của lượt CẤM MẠNG: lượt sau (dashboard, brief)
        # vẫn phải được thử lấy rổ sống.
        _MEM = dict(out)
    return dict(out)


# ─────────────────────────────────────────────────────────────────────────
# Chẩn đoán — `python vnstock_vn30.py --diag`
# ─────────────────────────────────────────────────────────────────────────
def _diag() -> int:
    """In THẬT nguồn trả về cái gì. Không có nó thì 'API không trả rổ dùng
    được' là một câu bí hiểm — 20/08 thủ phạm hoá ra là Series-vs-DataFrame."""
    print(f"[vn30] kill-switch {_ENV_FLAG}={os.environ.get(_ENV_FLAG, '(mặc định 1)')}"
          f" → enabled={enabled()}")
    print(f"[vn30] cache: {CACHE_PATH}")
    cache = load_cache()
    if cache:
        print(f"[vn30]   {len(cache.get('members') or [])} mã · "
              f"updated_at={cache.get('updated_at')} · "
              f"tuổi={cache_age_days(cache.get('updated_at'))}")
    else:
        print("[vn30]   (chưa có cache)")

    print("[vn30] gọi listing.symbols_by_group('VN30')…")
    try:
        from vnstock_auth import get_vnstock
        raw = get_vnstock("VCB", "VCI").listing.symbols_by_group("VN30")
    except Exception as e:
        print(f"[vn30] ❌ gọi API ném {type(e).__name__}: {e}")
        return 2
    print(f"[vn30]   type={type(raw).__name__} "
          f"columns={getattr(raw, 'columns', '(không có)')} "
          f"len={len(raw) if hasattr(raw, '__len__') else '?'}")
    syms = extract_symbols(raw)
    print(f"[vn30]   bóc ra: {len(syms) if syms else 0} mã → {(syms or [])[:8]}…")
    ok = validate(syms)
    if not ok:
        print(f"[vn30] ❌ không qua validate (cần {MIN_MEMBERS}-{MAX_MEMBERS} mã, "
              f"mã 3-4 ký tự chữ+số)")
        return 2
    # Diag ĐÃ trả giá cho lượt fetch — không ghi cache thì lượt sau lại gọi
    # mạng, và máy kia không được hưởng gì qua Dropbox. (Vết 20/08: diag ra
    # ✅ cả ba dòng mà vẫn in "chưa có cache".)
    try:
        save_cache(ok)
        print(f"[vn30] 💾 đã ghi cache → {CACHE_PATH}")
    except Exception as e:
        print(f"[vn30] ⚠️ không ghi được cache ({type(e).__name__}: {e})")

    added, removed = diff_vs_fallback(ok)
    print(f"[vn30] ✅ rổ sống {len(ok)} mã")
    if added or removed:
        print(f"[vn30] ⚠️ LỆCH hằng số — VÀO rổ: {added or '-'} · RỜI rổ: {removed or '-'}")
    else:
        print("[vn30] ✅ khớp hằng số chép cứng")

    # Rổ đúng chưa đủ: mã MỚI vào rổ mà kho chưa có giá thì heatmap vẫn ô
    # trống và screener vẫn bỏ sót — hỏng ở chỗ khác hẳn, phải nói ra.
    prices = _REPO / "data_warehouse" / "prices"
    if prices.is_dir():
        missing = [t for t in ok if not (prices / f"ticker={t}").is_dir()]
        if missing:
            print(f"[vn30] ⚠️ {len(missing)} mã trong rổ CHƯA có giá trong kho: "
                  f"{', '.join(missing)}")
            print("[vn30]    chữa: python run.py sync   (updater sẽ kéo lịch sử)")
        else:
            print(f"[vn30] ✅ cả {len(ok)} mã đều có thư mục giá trong kho")
    else:
        print(f"[vn30] ⬜ không thấy {prices} — bỏ qua phần đối chiếu kho")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_diag() if "--diag" in sys.argv else _diag())

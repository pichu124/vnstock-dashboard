#!/usr/bin/env python3
"""vnstock_doctor.py — khám sức khỏe TOÀN BỘ nguồn dữ liệu nuôi brief/dashboard.

Trước đây mỗi nguồn có ``--diag`` riêng rải rác (news_feeds / macro / vbma / nso /
foreign_flow / events / fundamentals) — phải nhớ chạy từng cái. Module này gom về
MỘT lệnh theo mô hình "doctor" của Agent-Reach: mỗi nguồn tự check (kiểm tra
THẬT chứ không chỉ "file tồn tại") và trả về trạng thái + ĐƠN THUỐC sửa cụ thể.

    python run.py doctor            # nhanh, OFFLINE — tuổi cache + key cấu hình
    python run.py doctor --net      # thêm probe MẠNG (RSS/FX/VBMA/NSO/API/Jina)
    python vnstock_doctor.py [...]  # chạy trực tiếp, thêm --json / --no-save

Hai tầng check:
  • OFFLINE (mặc định, <1s): đọc cache/_meta — tuổi data so với NGÀY GIAO DỊCH
    trước đó (không báo động giả sáng thứ 2 / trước pipeline 18:00), key .env.
    Trạng thái: ok ✅ · warn ⚠️ (cũ/thiếu một phần) · off ⬜ (chưa cấu hình/chưa
    chạy) · error ❌ (hỏng, cần sửa).
  • NET (--net): fetch thử từng nguồn ngoài — đúng việc các ``--diag`` lẻ làm,
    chạy trên MÁY CÓ MẠNG (sandbox/web session bị allowlist chặn → toàn ❌ là
    bình thường, không phải bug).

Kết quả ghi ``data_warehouse/_meta/doctor_status.json`` → sidebar dashboard hiện
badge 🩺 (mirror badge test_status). Mọi check đều best-effort: một nguồn nổ
không được kéo sập cả báo cáo (exception → status "error" của riêng nguồn đó).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time as _time_t, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_STATUS_NAME = "doctor_status.json"

_ICONS = {"ok": "✅", "warn": "⚠️", "off": "⬜", "error": "❌"}
# Thứ tự xấu dần — dùng chọn "trạng thái tệ nhất" cho badge/exit code
_SEVERITY = {"ok": 0, "off": 1, "warn": 2, "error": 3}

# Tuổi tối đa (ngày lịch) cho as_of từng chỉ số vĩ mô trước khi coi là cũ —
# theo cadence nguồn: FX auto hằng ngày, VBMA tuần, NSO tháng, GDP quý.
# sbv_policy_rate nhập tay khi SBV ra quyết định → không bao giờ tính cũ.
_MACRO_MAX_AGE_DAYS = {
    "usdvnd": 5,
    "interbank_on": 12,
    "interbank_1w": 12,
    "govt_bond_yield_2y": 12,
    "govt_bond_yield_10y": 12,
    "us10y": 7,                # FRED daily (DGS10 nghỉ cuối tuần/lễ)
    "fed_funds": 7,
    "cpi_yoy": 45,
    "iip_yoy": 45,
    "pmi": 40,
    "gdp_yoy": 120,
    "trade_balance": 45,
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _result(key: str, name: str, status: str, message: str, fix: str = "") -> dict:
    return {"key": key, "name": name, "status": status,
            "message": message, "fix": fix}


def _prev_trading_day(d: "date | None" = None) -> date:
    """Ngày giao dịch (T2-T6) TRƯỚC ``d`` — chuẩn so tuổi data EOD: sáng nay
    chưa chạy pipeline thì data hôm qua vẫn là tươi; T2 nhìn về T6 tuần trước."""
    d = d or date.today()
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _age_days(iso: str) -> "int | None":
    """Tuổi (ngày lịch) của một mốc ISO 'YYYY-MM-DD[THH:MM:SS]' — None nếu rác."""
    try:
        return (date.today() - date.fromisoformat(str(iso)[:10])).days
    except (TypeError, ValueError):
        return None


def _mtime_age_days(path: Path) -> "int | None":
    try:
        return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    except OSError:
        return None


def _fmt_age(n: "int | None") -> str:
    if n is None:
        return "?"
    return "hôm nay" if n <= 0 else f"{n} ngày trước"


# ── OFFLINE checks — tuổi cache + cấu hình ───────────────────────────────────


_UNIT_WARN_DAYS = 7     # vết cũ hơn coi như đã xem — warn vĩnh viễn = alarm fatigue


def check_unit_normalizations() -> dict:
    """Guard đơn vị giá penny (rollup 07/08) có VỪA kích hoạt không.

    `_normalize_units` tự quy đổi khi giá bar lệch ≥100× lịch sử của chính mã
    đó, và ghi vết vào `_meta/unit_normalizations.json` (11/08). Tự sửa xong
    vẫn cần NGƯỜI liếc chart mã đó — ca quy đổi OAN lý thuyết là chia tách tỉ
    lệ cực lớn. Trước đây việc này là "nhớ quét run_daily.log"; nay badge tự
    báo, đúng doctrine: mọi lớp best-effort tự-sửa cần một doctor check.
    """
    name = "Quy đổi đơn vị giá (rollup)"
    path = _META / "unit_normalizations.json"
    if not path.exists():
        return _result("unit_norm", name, "ok", "guard chưa từng kích hoạt", "")
    try:
        events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except Exception as e:
        return _result("unit_norm", name, "error",
                       f"không đọc được vết quy đổi: {type(e).__name__}",
                       f"xem tay file {path}")
    cutoff = datetime.now() - timedelta(days=_UNIT_WARN_DAYS)
    fresh = []
    for ev in events:
        try:
            if datetime.fromisoformat(str(ev.get("at", ""))) >= cutoff:
                fresh.append(ev)
        except ValueError:
            fresh.append(ev)        # timestamp hỏng → coi là MỚI, thà soi thừa
    if not fresh:
        last = events[-1] if events else None
        note = (f"lần cuối {str(last.get('at', '?'))[:10]} "
                f"({last.get('ticker', '?')})" if last
                else "guard chưa từng kích hoạt")
        return _result("unit_norm", name, "ok", note, "")
    # Ba chỗ badge từng NÓI SAI, sửa 18/08 sau khi user đi soi 5 chart oan:
    # 1. In `ratio` kèm mã khiến người đọc tưởng "1000× = đúng, 764× = sai".
    #    Thực ra ratio = giá bar mới / TRUNG VỊ YTD của chính mã (rollup:291)
    #    nên nó đo mã đang ở đâu so với trung vị năm, KHÔNG đo độ tin cậy của
    #    phép quy đổi. Bỏ khỏi badge; ai cần thì đọc thẳng file vết.
    # 2. `fresh[-5:]` là 5 vết CUỐI, mà rollup duyệt `groupby("ticker")` =
    #    alphabet → luôn ra đuôi bảng chữ cái (WSS/WTC/XPH/YBM/YEG), không
    #    phải 5 ca đáng ngờ nhất. Nay nói rõ "5 mã cuối theo vần" + tổng số mã.
    # 3. Log giữ tối đa `_UNIT_LOG_MAX` vết (rollup:242) nên khi đầy, con số
    #    đếm được là SÀN chứ không phải số thật — phải ghi "≥".
    # Đã có người đối chiếu SAU sự kiện mới nhất và ra sạch chưa? Nếu rồi thì
    # đây là "guard tự sửa, đã kiểm, xong" chứ không phải việc còn treo.
    verdict = _continuity_verdict(fresh)
    if verdict is not None:
        return verdict
    n_tickers = len({str(e.get("ticker", "?")) for e in fresh})
    shown = [str(e.get("ticker", "?")) for e in fresh[-5:]]
    saturated = len(events) >= _rollup_log_cap()
    count = f"≥{len(fresh)}" if saturated else str(len(fresh))
    tail = f"{', '.join(shown)}{' …' if n_tickers > len(shown) else ''}"
    return _result(
        "unit_norm", name, "warn",
        f"{count} lần quy đổi / {n_tickers} mã trong {_UNIT_WARN_DAYS} ngày"
        f"{' (log đầy — số thật có thể hơn)' if saturated else ''}: {tail}"
        f"{' (5 mã cuối theo vần, không phải nặng nhất)' if n_tickers > len(shown) else ''}"
        f" — guard ĐÃ tự sửa, việc còn lại là soi giá có liên tục không",
        "python scripts/check_unit_continuity.py "
        "(vách ~1000× = vết sót · ~2× = nghi chia tách · lệch giá live = kho lỡ phiên)")


def _continuity_verdict(fresh: list) -> "dict | None":
    """Đọc vết đối chiếu của `scripts/check_unit_continuity.py`.

    Trả `ok` khi lượt soi diễn ra SAU sự kiện quy đổi mới nhất VÀ không mã nào
    cần soi tay. Soi trước sự kiện mới nhất thì không tính — nó chưa nhìn thấy
    thứ vừa xảy ra. Trả None để badge giữ nguyên đường cũ (cảnh báo).
    """
    path = _META / "unit_continuity_check.json"
    if not path.exists() or not fresh:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(str(data.get("checked_at")))
    except Exception:
        return None
    if data.get("scope") not in ("trace", "all") or data.get("suspect"):
        return None
    newest = None
    for ev in fresh:
        try:
            at = datetime.fromisoformat(str(ev.get("at", "")))
        except Exception:
            continue
        newest = at if newest is None or at > newest else newest
    if newest is None or checked < newest:
        return None
    return _result(
        "unit_norm", "Quy đổi đơn vị giá (rollup)", "ok",
        f"guard tự sửa {len(fresh)} lần trong {_UNIT_WARN_DAYS} ngày — ĐÃ đối "
        f"chiếu {data.get('scanned', '?')} mã lúc "
        f"{checked.strftime('%d/%m %H:%M')}: không mã nào cần soi tay", "")


def _rollup_log_cap() -> int:
    """Trần lưu vết của rollup — đọc từ nguồn, không nuôi bản sao hằng số."""
    try:
        from vnstock_rollup import _UNIT_LOG_MAX
        return int(_UNIT_LOG_MAX)
    except Exception:
        return 50


# ── Phát tối đã tới KHO NÀY chưa (việc #11, 16/09) ────────────────────────
#
# Câu hỏi badge phải trả lời: kết quả của phát pipeline gần nhất đã nằm trong
# bản kho mà máy này đang đọc chưa. Không trả lời được bằng tuổi data
# (`check_warehouse` cố ý dung sai 2 phiên vì VNINDEX EOD về trễ) — vụ 07/09:
# desktop TẮT sync Dropbox, laptop sáng 08/09 vẫn VNINDEX ✅, chỉ hai badge
# ⚠️ market_overview/NN ròng nói bóng gió. Hai marker nằm TRONG kho nói thẳng:
#   `pipeline_status.json["updater"]` — ghi CUỐI bước updater (success/partial),
#       có `covered_session` = phiên PHỦ (giờ chạy so 15:05; T7/CN = thứ 6)
#   `brief_push.json` — "close" khi brief chiều đã đẩy (bước 14/14), "skipped"
#       khi máy chạy pipeline cố ý tắt brief bằng cờ (.env không đồng bộ)
# Marker không có trường máy ngoài `last_machine` ⇒ "chưa tới kho này" có
# HAI cách xảy ra và badge phải nói cả hai: pipeline không chạy HOẶC Dropbox
# tắt sync.
# Hạn phát tối: task 18:00 + trần 180′ ⇒ 21:00 với phát KHỞI ĐỘNG ĐÚNG GIỜ;
# nhưng máy bật muộn thì StartWhenAvailable chạy bù (đo 08–14/09: khởi động
# 20:15–20:40, xong 21:00–23:15) ⇒ hạn 23:00, đủ rộng để đêm bật muộn không
# réo giả; sáng hôm sau verdict không đổi (phiên đã qua ngày là tới hạn).
# `now` = giờ máy (== VN trên cả hai máy user); marker ngày theo get_today_vn —
# máy ngoài VN chỉ lệch về phía lạc quan, không réo giả.
_DAILY_DUE_HOUR = 23
# Marker updater ghi CUỐI bước updater, TRƯỚC rollup/fix-units/auto-heal
# (5–38′ đo 19–25/08) và 11 bước sau (~45–55′): đo marker→doctor bước 13 =
# 61′/69′/88′; trần task 180′. Trong cửa sổ này brief chưa có là ĐANG chạy.
# Cùng đêm KHÔNG BAO GIỜ kết luận "brief chưa": doctor bước 13 luôn chạy
# trước brief bước 14, kết luận đó ghi vào doctor_status.json là sai suốt
# 24 giờ ở cả hai máy. Brief chỉ xét từ ngày hôm sau.
_POST_SYNC_GRACE_MIN = 150


def _session_for(d: date) -> date:
    """Phiên mà phát tối tại ngày `d` nói về: T2–T6 là chính ngày đó, T7/CN là
    thứ 6 vừa rồi (mirror `run.py._close_session_date` — có test parity; ngày
    lễ giữa tuần chưa phân biệt được ở cả hai nơi)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    return d


def _iso_date(v) -> "date | None":
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _iso_dt(v) -> "datetime | None":
    """ISO → datetime NAIVE giờ VN (marker có thể mang +07:00/Z sau này —
    trừ naive với aware là TypeError, chỗ duy nhất check này có thể nổ)."""
    try:
        dt = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return _to_naive_vn(dt)


def _to_naive_vn(dt: datetime) -> datetime:
    """Aware → naive theo Asia/Ho_Chi_Minh (mọi mốc trong kho là giờ VN)."""
    if dt.tzinfo is None:
        return dt
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)
    except Exception:
        return dt.astimezone().replace(tzinfo=None)


def _int0(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _covered_session(upd: dict, ran_at: "datetime | None",
                     sync_date: date) -> date:
    """Phiên mà lượt sync trong marker PHỦ: trường `covered_session` (ghi từ
    16/09) > suy từ giờ chạy (marker cũ) > ngày lịch của marker (không có giờ)."""
    cs = _iso_date(upd.get("covered_session"))
    if cs:
        return cs
    if ran_at is not None:
        try:
            from vnstock_rollup import session_covered_at
            return session_covered_at(ran_at)
        except Exception:
            pass
    return sync_date


_FIX_NOT_REACHED = (
    "⇄ CẢ HAI: kiểm icon Dropbox ở khay TRƯỚC (hệ quả #5 CLAUDE.md) · 🖥️ DESKTOP: "
    "Get-ScheduledTaskInfo -TaskName 'VnStock Daily Pipeline' ; Select-String "
    "-Path run_daily.log -Pattern '⏱ TỔNG' | Select-Object -Last 1")
_FIX_BRIEF_MISSING = (
    "🖥️ DESKTOP: Select-String -Path run_daily.log -Pattern '⏱ TỔNG|\\[brief\\]' "
    "| Select-Object -Last 3")
# `telegram close` gắn brief vào phiên của LÚC GỬI (`_close_session_date`): ngày
# làm việc thì brief phiên cũ không gửi lại được (gửi là dán nhãn phiên hôm nay
# và chặn brief tối nay); chỉ T7/CN mới còn là phiên thứ 6.
_FIX_BRIEF_RESEND = " · ○ gửi tay MỘT LẦN (marker đi qua Dropbox): python run.py telegram close"
_FIX_BRIEF_PAST = " · brief phiên cũ không gửi lại được — kiểm brief tối nay"


def pipeline_reach_verdict(updater: "dict | None", brief: "dict | None",
                           now: datetime, *, brief_enabled: bool = True,
                           host: "str | None" = None) -> dict:
    """Hàm thuần — verdict cho badge từ hai marker + giờ hiện tại (test cắm `now`).

    `updater`: khối `pipeline_status.json["updater"]`. `brief`: nội dung
    `brief_push.json` ({"close": "YYYY-MM-DD", "skipped": {...}}) hoặc None.
    `brief_enabled`: False khi `VNSTOCK_PIPELINE_BRIEF` tắt ở máy đang khám
    (`host` — ghi tên máy vì verdict đi qua Dropbox sang máy kia; máy kia tắt
    thì đọc qua "skipped" trong marker dùng chung).
    """
    name = "Phát tối — đã tới kho này chưa"
    key = "pipeline_reach"
    now = _to_naive_vn(now)
    upd = updater if isinstance(updater, dict) else {}
    sync_dates = [d for d in (_iso_date(upd.get("last_success_date")),
                              _iso_date(upd.get("last_partial_date"))) if d]
    if not sync_dates:
        return _result(key, name, "off",
                       "chưa có marker sync trong pipeline_status.json — pipeline "
                       "chưa từng chạy (--skip-if-done) hoặc kho chưa sync về máy này",
                       "○ MỘT LẦN: python run.py all (máy nào cũng được, kho đi qua "
                       "Dropbox) · ⇄ CẢ HAI: kiểm icon Dropbox ở khay")
    sync_date = max(sync_dates)
    if upd.get("last_result") in ("success", "partial"):
        partial = upd.get("last_result") == "partial"
    else:
        partial = (sync_date == _iso_date(upd.get("last_partial_date"))
                   and sync_date != _iso_date(upd.get("last_success_date")))
    machine = str(upd.get("last_machine") or "?")
    ran_at = _iso_dt(upd.get("last_run_at"))
    ran_txt = ran_at.strftime("%d/%m %H:%M") if ran_at else "?"
    covered = _covered_session(upd, ran_at, sync_date)
    if ran_at is not None and covered > ran_at.date():
        covered = ran_at.date()            # phiên phủ không thể SAU ngày chạy
    n_err = _int0(upd.get("errors"))
    how = (("sync partial" + (f" {n_err} lỗi" if n_err else "")) if partial else "sync OK") \
        + f" lúc {ran_txt} bởi {machine}"
    if ran_at is not None and covered != ran_at.date():
        how += f" (phủ tới phiên {covered.isoformat()})"

    session = _session_for(now.date())
    due = now.date() > session or now.hour >= _DAILY_DUE_HOUR
    brief_dict = brief if isinstance(brief, dict) else {}
    brief_date = _iso_date(brief_dict.get("close"))
    skipped = brief_dict.get("skipped") if isinstance(brief_dict.get("skipped"), dict) else {}
    skipped_date = _iso_date(skipped.get("session"))
    fresh = ran_at is not None and \
        (now - ran_at) <= timedelta(minutes=_POST_SYNC_GRACE_MIN)

    def _brief_state(target: date) -> "tuple[bool, str]":
        """(brief phiên `target` coi như xong?, chữ cho message)."""
        if not brief_enabled:
            return True, (f"brief chiều đang TẮT bằng VNSTOCK_PIPELINE_BRIEF trên "
                          f"{host or '?'} (.env máy khám)")
        if brief_date and brief_date >= target:
            return True, "brief chiều đã đẩy"
        if skipped_date and skipped_date >= target:
            return True, (f"brief chiều TẮT bằng {skipped.get('reason') or 'cờ'} "
                          f"trên {skipped.get('machine') or '?'} (ghi ở brief_push.json)")
        return False, ""

    def _brief_missing(target: date) -> dict:
        brief_txt = brief_date.isoformat() if brief_date else "chưa có marker"
        resend_ok = now.weekday() >= 5 and target == session     # T7/CN vẫn là phiên T6
        return _result(key, name, "warn",
                       f"sync {target.isoformat()} đã tới kho này ({how}) nhưng brief "
                       f"chiều {target.isoformat()} CHƯA (brief_push: {brief_txt}) — pipeline "
                       "đứt sau bước sync, brief bị bỏ qua, hoặc brief đẩy từ máy khác "
                       "chưa sync về",
                       _FIX_BRIEF_MISSING + (_FIX_BRIEF_RESEND if resend_ok else _FIX_BRIEF_PAST))

    def _is_catchup(target: date) -> bool:
        """Lượt sync chạy bù SÁNG hôm sau (ngày làm việc, trước 15:05, sau
        phiên `target`): brief phiên đó KHÔNG gửi là theo thiết kế
        (`_should_push_close` chặn trước 15:00) — không phải pipeline đứt."""
        return (ran_at is not None and ran_at.weekday() < 5
                and ran_at.time() < _time_t(15, 5) and ran_at.date() > target)

    if covered >= session:
        ok_brief, brief_txt = _brief_state(session)
        if ok_brief:
            return _result(key, name, "ok",
                           f"phát tối {session.isoformat()} đã tới kho này — {how} · "
                           f"{brief_txt}", "")
        if now.date() == session or fresh:
            why = ("phát còn đang chạy — bước 13 luôn trước bước 14; xét lại từ "
                   "sáng mai" if now.date() == session
                   else "các bước sau sync còn đang chạy")
            return _result(key, name, "ok",
                           f"phát tối {session.isoformat()} đang tới kho này — {how} · "
                           f"brief chiều chưa ({why})", "")
        return _brief_missing(session)

    target = session if due else _prev_trading_day(session)
    if covered >= target:
        ok_brief, brief_txt = _brief_state(target)
        if not ok_brief and _is_catchup(target):
            brief_txt = (f"brief chiều {target.isoformat()} không gửi — chạy bù sáng "
                         f"{ran_txt} không gửi brief cũ (theo thiết kế)")
        elif not ok_brief and fresh:
            brief_txt = "brief chiều chưa (các bước sau sync còn đang chạy)"
        elif not ok_brief:
            return _brief_missing(target)
        return _result(key, name, "ok",
                       f"phát tối {target.isoformat()} đã tới kho này — {how} · "
                       f"{brief_txt} · phát {session.isoformat()} chưa tới hạn "
                       f"{_DAILY_DUE_HOUR:02d}:00", "")
    extra = ""
    if brief_date and brief_date >= target:
        weekend_gap = target.weekday() == 4 and (now.date() - target).days <= 3
        if weekend_gap:
            extra = (f" — brief {target.isoformat()} đã đẩy mà sync chưa: chạy bù T7/CN "
                     "bằng code cũ thì updater bỏ qua cuối tuần (nay run.py sync tự "
                     "thêm --force)")
        else:
            extra = (f" — brief {target.isoformat()} đã đẩy mà sync chưa: updater lỗi "
                     "trước khi ghi marker, hoặc brief gửi tay từ máy khác")
    return _result(key, name, "warn",
                   f"phát tối {target.isoformat()} CHƯA tới kho này — sync gần nhất phủ "
                   f"phiên {covered.isoformat()} ({how}) — pipeline không chạy HOẶC "
                   "Dropbox tắt sync (hoặc máy bật muộn đang chạy dở, hoặc hôm đó nghỉ "
                   f"lễ không có phiên){extra} — các badge tuổi data bên dưới cũ theo "
                   "là HỆ QUẢ, không phải lỗi riêng",
                   _FIX_NOT_REACHED)


def check_pipeline_reach() -> dict:
    """Đọc hai marker trong kho rồi giao cho `pipeline_reach_verdict`."""
    def _load(p: Path):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    status = _load(_META / "pipeline_status.json")
    updater = status.get("updater") if isinstance(status, dict) else None
    brief = _load(_META / "brief_push.json")
    flag = (os.environ.get("VNSTOCK_PIPELINE_BRIEF") or "1").strip().lower()
    try:
        from vnstock_rollup import get_hostname
        host = get_hostname()
    except Exception:
        host = os.environ.get("COMPUTERNAME") or "?"
    return pipeline_reach_verdict(updater, brief, datetime.now(),
                                  brief_enabled=flag not in _OFF_VALUES, host=host)


# ── Engine brief (Claude Code CLI thuê bao) — 30/09, U62 ────────────────────
_ENGINE_ENVS = ("VNSTOCK_BRIEF_ENGINE", "VNSTOCK_LLM_ENGINE")


def _engine_setting() -> str:
    """Engine brief theo cấu hình MÁY NÀY: os.environ rồi `.env` (cùng cách
    đọc với `check_kill_switches` — .env là nơi cờ sống dai). "" = chưa đặt."""
    for k in _ENGINE_ENVS:
        v = os.environ.get(k)
        if v is not None and v.strip():
            return v.strip().lower()
    env_file = _REPO / ".env"
    found: dict = {}
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k in _ENGINE_ENVS:
                    found.setdefault(k, v.strip().strip('"\''))
        except OSError:
            pass
    for k in _ENGINE_ENVS:
        if found.get(k):
            return found[k].lower()
    return ""


def brief_engine_verdict(marker, configured: str, ledger_days: list,
                         today=None) -> dict:
    """Hàm thuần. `marker` = brief_push.json (dict/None); `configured` =
    "claude"/"ladder"/""; `ledger_days` = [{"ok": n, "fail": m}, …] các dòng
    ClaudeCode của 3 ngày gần nhất (mới → cũ), thiếu ngày thì bỏ.
    Không bao giờ đỏ vì brief không đi — brief vẫn đi bằng ladder; đỏ khi
    Claude hỏng LIÊN TIẾP ≥3 ngày mà cấu hình vẫn claude (user đi vắng)."""
    name = "Engine brief (Claude Code)"
    key = "brief_engine"
    if configured != "claude":
        return _result(key, name, "ok",
                       "ladder agent free (VNSTOCK_BRIEF_ENGINE/LLM_ENGINE chưa "
                       "đặt claude) — đường A chưa bật", "")
    mk = marker if isinstance(marker, dict) else {}
    engine = str(mk.get("engine") or "")
    agent = mk.get("agent") or "?"
    close = mk.get("close") or "?"
    dead_days = [d for d in ledger_days if isinstance(d, dict)
                 and int(d.get("fail", 0)) > 0 and int(d.get("ok", 0)) == 0]
    fix = ("python vnstock_brief_pack.py --check (🖥️ DESKTOP, dưới tài khoản chạy "
           "task) — exe/đăng nhập/probe; sửa VNSTOCK_CLAUDE_CLI_EXE hoặc `claude` → /login")
    if engine in ("claude", "claude-file"):
        return _result(key, name, "ok",
                       f"brief phiên {close} do {agent} ({engine})", "")
    if engine == "ladder":
        why = mk.get("claude_error") or "không rõ lý do (marker cũ, chưa có claude_error)"
        if len(dead_days) >= 3:
            return _result(key, name, "error",
                           f"Claude hỏng {len(dead_days)} ngày liền, brief phiên {close} "
                           f"rơi về ladder ({agent}): {why}", fix)
        return _result(key, name, "warn",
                       f"brief phiên {close} rơi về ladder ({agent}): {why}", fix)
    return _result(key, name, "ok",
                   "cấu hình claude, chưa có brief nào đi qua engine mới "
                   "(marker chưa có `engine`) — xem lại sau phát tối", "")


def check_brief_engine() -> dict:
    """Đọc marker + cấu hình + sổ ClaudeCode 3 ngày rồi giao cho verdict."""
    try:
        marker = json.loads((_META / "brief_push.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marker = None
    days: list = []
    try:
        from datetime import timedelta as _td
        from vnstock_llm_ledger import summary
        for back in range(3):
            d = (date.today() - _td(days=back)).isoformat()
            s = summary(d)
            if not s or s.get("day") != d:
                continue
            agg = {"ok": 0, "fail": 0}
            for k, row in (s.get("providers") or {}).items():
                if str(k).startswith("ClaudeCode:"):
                    agg["ok"] += int(row.get("ok", 0))
                    agg["fail"] += int(row.get("fail", 0))
            if agg["ok"] or agg["fail"]:
                days.append(agg)
    except Exception:
        days = []
    return brief_engine_verdict(marker, _engine_setting(), days)


def check_warehouse() -> dict:
    """Kho giá EOD: bar VNINDEX cuối cùng, dung sai 2 PHIÊN.

    VNINDEX daily qua API EOD về trễ ~1 phiên so với cổ phiếu (lý do tồn tại
    của `_augment_with_live_vnindex` trong brief), và pipeline sync chạy 18:00
    — chạy doctor ban ngày thì bar index mới nhất hợp lệ là 2 phiên trước.
    Chỉ warn khi TRỄ HƠN thế (sync thật sự bị bỏ); ngày chính xác luôn in ra.
    """
    name = "Kho giá EOD (VNINDEX)"
    vn_dir = _META.parent / "prices" / "ticker=VNINDEX"
    files = sorted(vn_dir.glob("year=*/*.parquet")) if vn_dir.exists() else []
    if not files:
        return _result("warehouse", name, "off",
                       "chưa có dữ liệu VNINDEX trong kho",
                       "python run.py sync")
    import pandas as pd
    df = pd.read_parquet(files[-1], columns=["time"])
    last = pd.to_datetime(df["time"]).max().date()
    threshold = _prev_trading_day(_prev_trading_day())     # 2 phiên trước
    status = "ok" if last >= threshold else "warn"
    return _result("warehouse", name, status,
                   f"bar cuối {last.isoformat()} ({_fmt_age((date.today() - last).days)})",
                   "" if status == "ok" else "python run.py sync")


def check_dir_shapes() -> dict:
    """Thư mục kho có ĐÚNG là thư mục không — bắt kiểu hỏng ÂM THẦM nhất.

    Máy user 06/08: `data_warehouse/_live` là một FILE RỖNG 0 byte (không
    phải thư mục), tạo lúc 07/07 03:13 — trùng sự cố Dropbox 2 máy đã ghi
    trong journal. Suốt MỘT THÁNG sau đó WSS không ghi nổi quote/bar nào, mà
    không có tín hiệu nào báo: mọi đường ghi đều nằm trong `try/except` để
    khỏi kéo sập vòng poll. Triệu chứng duy nhất lộ ra là `missing_in_rolled`
    cao bất thường trong reconciler — nhìn qua rất giống "WSS không chạy".

    Check này rẻ (vài lần `stat`) và bắt đúng lớp lỗi đó.
    """
    name = "Hình dạng thư mục kho"
    root = _META.parent
    expected = [root, root / "prices", root / "_live", _META]
    bad = []
    for p in expected:
        try:
            if p.exists() and not p.is_dir():
                bad.append(p.name)
        except OSError:
            bad.append(f"{p.name}(stat lỗi)")
    if not bad:
        return _result("dir_shapes", name, "ok",
                       f"{len(expected)} thư mục đều đúng dạng", "")
    joined = ", ".join(bad)
    return _result(
        "dir_shapes", name, "error",
        f"KHÔNG phải thư mục: {joined} — mọi thao tác ghi vào đó đều hỏng "
        f"âm thầm (WSS/rollup)",
        f"kiểm tra rồi xoá vật cản: python -c \"import pathlib;"
        f"p=pathlib.Path('data_warehouse/_live');print(p.stat())\" — nếu là "
        f"file rỗng thì xoá đi, thư mục sẽ được tạo lại tự động")


def check_market_overview() -> dict:
    """market_overview.json (độ rộng/movers/dòng tiền ngành/regime) — so data_date."""
    name = "Market overview (screener)"
    p = _META / "market_overview.json"
    if not p.exists():
        return _result("market_overview", name, "off",
                       "chưa có market_overview.json", "python run.py screener")
    data = json.loads(p.read_text(encoding="utf-8"))
    dd = str(data.get("data_date") or "").strip()
    if not dd:                       # file cũ trước khi có field data_date
        gen = str(data.get("generated_at", ""))
        dd = gen[:10] if gen else ""
    age = _age_days(dd)
    stale = bool(dd) and date.fromisoformat(dd) < _prev_trading_day()
    status = "warn" if (stale or age is None) else "ok"
    return _result("market_overview", name, status,
                   f"data_date {dd or '?'} ({_fmt_age(age)})",
                   "python run.py screener" if status != "ok" else "")


def check_fundamentals() -> dict:
    """fundamentals.parquet — cadence 1×/tuần (thêm trong mùa BCTC)."""
    name = "Cơ bản VN30 (fundamentals)"
    p = _META / "fundamentals.parquet"
    age = _mtime_age_days(p)
    if age is None:
        return _result("fundamentals", name, "off",
                       "chưa có fundamentals.parquet",
                       "python vnstock_fundamental_updater.py")
    status = "ok" if age <= 10 else "warn"
    return _result("fundamentals", name, status, f"cập nhật {_fmt_age(age)}",
                   "python vnstock_fundamental_updater.py" if status != "ok" else "")


def check_macro() -> dict:
    """Vĩ mô: từng chỉ số so cadence nguồn của nó + nhắc PMI quên set."""
    name = "Vĩ mô (lãi suất/tỷ giá/CPI…)"
    from vnstock_macro import load_macro, pmi_reminder
    macro = load_macro()
    if not macro:
        return _result("macro", name, "off", "cache vĩ mô rỗng",
                       "python run.py macro")
    stale = []
    for ind in macro:
        max_age = _MACRO_MAX_AGE_DAYS.get(ind.get("key") or "")
        age = _age_days(ind.get("as_of") or "")
        if max_age is not None and age is not None and age > max_age:
            stale.append(f"{ind.get('label')} (as_of {ind.get('as_of')})")
    remind = pmi_reminder(macro)
    parts = [f"{len(macro)} chỉ số có reading"]
    if stale:
        parts.append("cũ: " + "; ".join(stale))
    if remind:
        parts.append(remind.strip())
    status = "warn" if (stale or remind) else "ok"
    return _result("macro", name, status, " · ".join(parts),
                   "python run.py macro (auto) hoặc python vnstock_macro.py "
                   "--set <key> <value>" if status != "ok" else "")


def check_market_news() -> dict:
    """Tin kinh tế/chính trị RSS — tuổi lần fetch cuối + độ phủ phân tích LLM."""
    name = "Tin vĩ mô RSS (market news)"
    p = _META / "market_news_cache.json"
    if not p.exists():
        return _result("market_news", name, "off",
                       "chưa có market_news_cache.json", "python run.py news")
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    fetched = str(data.get("fetched_at", "")) if isinstance(data, dict) else ""
    age = _age_days(fetched)
    cutoff = (date.today() - timedelta(days=3)).isoformat()
    recent = [it for it in items if (it.get("_date_sort") or "") >= cutoff]
    analyzed = sum(1 for it in recent if it.get("_impact"))
    status = "ok" if age is not None and age <= 3 else "warn"
    return _result("market_news", name, status,
                   f"fetch {_fmt_age(age)} · {len(recent)} tin ≤3 ngày "
                   f"({analyzed} có tác động LLM)",
                   "python run.py news" if status != "ok" else "")


def check_ticker_news() -> dict:
    """Tin theo mã (vnstock company.news) — tuổi cache."""
    name = "Tin theo mã (news cache)"
    p = _META / "news_cache.json"
    age = _mtime_age_days(p)
    if age is None:
        return _result("ticker_news", name, "off", "chưa có news_cache.json",
                       "python run.py news")
    status = "ok" if age <= 3 else "warn"
    return _result("ticker_news", name, status, f"cập nhật {_fmt_age(age)}",
                   "python run.py news" if status != "ok" else "")


def check_foreign_flow() -> dict:
    """NN ròng 1D full-market — phiên mới nhất trong cache theo ngày."""
    name = "NN ròng 1D (foreign flow)"
    p = _META / "foreign_net_daily.json"
    if not p.exists():
        return _result("foreign_flow", name, "off",
                       "chưa có foreign_net_daily.json",
                       "python run.py foreign-flow --days 5")
    cache = json.loads(p.read_text(encoding="utf-8"))
    if not cache:
        return _result("foreign_flow", name, "off", "cache rỗng",
                       "python run.py foreign-flow --days 5")
    last = max(cache)
    rec = cache.get(last) or {}
    stale = date.fromisoformat(last) < _prev_trading_day()
    n_sym = rec.get("n_symbols")
    parts = [f"phiên {last}: net {rec.get('net', '?')} tỷ ({n_sym} mã)"]
    # CLAUDE.md: chỉ ~100 mã ⇒ API đang cap limit → tổng net méo (top-100 bug cũ)
    capped = isinstance(n_sym, int) and n_sym <= 120
    if capped:
        parts.append("⚠️ số mã ≤120 — API có thể đang cap limit, net thiếu đuôi small-cap")
    status = "warn" if (stale or capped) else "ok"
    return _result("foreign_flow", name, status, " · ".join(parts),
                   "python run.py foreign-flow --days 5" if status != "ok" else "")


def check_events() -> dict:
    """Sự kiện GDKHQ sắp tới — brief tự refresh 1×/ngày nên cache phải mới."""
    name = "Sự kiện DN (GDKHQ)"
    p = _META / "upcoming_events.parquet"
    age = _mtime_age_days(p)
    if age is None:
        return _result("events", name, "off", "chưa có upcoming_events.parquet",
                       "python vnstock_events.py")
    status = "ok" if age <= 3 else "warn"
    return _result("events", name, status, f"refresh {_fmt_age(age)}",
                   "python vnstock_events.py" if status != "ok" else "")


def _has_pypdf() -> bool:
    # BaseException chứ không chỉ Exception: pypdf kéo cryptography (native) —
    # bản cài hỏng có thể nổ pyo3 PanicException (kế thừa BaseException, thấy
    # thật trong sandbox 10/07). Import hỏng kiểu gì cũng = "không dùng được".
    try:
        import pypdf  # noqa: F401
        return True
    except BaseException:  # noqa: BLE001
        return False


def check_pdf_tooling() -> dict:
    """Khả năng PDF→text cho nguồn VBMA (pdftotext trên PATH hoặc pypdf).

    Máy MỚI hay dính bẫy này (desktop user 10/07: venv thiếu pypdf → VBMA chết
    IM LẶNG vì best-effort giữ cache cũ, LNH/2Y/10Y không bao giờ cập nhật) —
    check offline rẻ, khỏi đợi --net mới lộ."""
    name = "PDF→text (nguồn VBMA)"
    if os.environ.get("VNSTOCK_MACRO_VBMA", "1") == "0":
        return _result("pdf_tooling", name, "off", "đã tắt (VNSTOCK_MACRO_VBMA=0)")
    import shutil
    if shutil.which("pdftotext"):
        return _result("pdf_tooling", name, "ok", "pdftotext (poppler) trên PATH")
    if _has_pypdf():
        return _result("pdf_tooling", name, "ok", "pypdf khả dụng")
    return _result("pdf_tooling", name, "error",
                   "thiếu cả pdftotext lẫn pypdf — lãi suất LNH / lợi suất TPCP "
                   "sẽ KHÔNG BAO GIỜ cập nhật (fetch fail im lặng, giữ cache cũ)",
                   "pip install pypdf (đã cài mà vẫn lỗi → "
                   "pip install --force-reinstall pypdf cryptography)")


def check_llm_ledger() -> dict:
    """Sổ call LLM per provider (món 3 deep-dive DojoAgents 15/07) — cảnh
    báo khi hôm nay có call bị RATE-LIMIT (= lý do ladder rơi bậc âm thầm)
    hoặc quá nửa call lỗi. off khi sổ chưa tồn tại (tự tích lũy)."""
    name = "LLM call ledger"
    p = _META / "llm_ledger.json"
    if not p.exists():
        return _result("llm_ledger", name, "off",
                       "chưa có llm_ledger.json (sổ tự tích lũy khi có call LLM)")
    data = json.loads(p.read_text(encoding="utf-8"))
    days = data.get("days") or {}
    today = date.today().isoformat()
    day = days.get(today) or {}
    if not day:
        last = sorted(days)[-1] if days else "?"
        return _result("llm_ledger", name, "ok",
                       f"hôm nay chưa có call nào (ngày gần nhất có sổ: {last})")
    calls = sum(int(r.get("calls", 0)) for r in day.values())
    fails = sum(int(r.get("fail", 0)) for r in day.values())
    limited = sum(int(r.get("rate_limited", 0)) for r in day.values())
    oks = sum(int(r.get("ok", 0)) for r in day.values())
    hot = [k for k, r in day.items() if int(r.get("rate_limited", 0)) > 0]
    msg = f"hôm nay {calls} call · {fails} lỗi · {limited} rate-limit"
    if calls >= 3 and oks == 0:
        # all-free 22/07: KHÔNG call nào thành công = ladder down toàn phần
        return _result("llm_ledger", name, "error",
                       msg + " — TOÀN BỘ call lỗi (ladder down)",
                       "python scripts/probe_models.py soi slug/key; "
                       "python vnstock_llm_ledger.py --show soi provider")
    if limited > 0:
        return _result("llm_ledger", name, "warn",
                       msg + f" — chạm trần: {', '.join(sorted(hot))}",
                       "đợi trần reset / giảm số call (--max) / để ladder rơi bậc")
    if calls >= 4 and fails * 2 > calls:
        return _result("llm_ledger", name, "warn",
                       msg + " — quá nửa call lỗi (không phải rate-limit)",
                       "python vnstock_llm_ledger.py --show rồi soi provider lỗi")
    return _result("llm_ledger", name, "ok", msg)


def check_llm_keys() -> dict:
    """Key LLM trong .env: provider chấm sentiment + key agent viết brief."""
    name = "LLM keys (.env)"
    from vnstock_sentiment import available_provider
    provider = available_provider()
    brief_keys = [k for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                              "OPENAI_API_KEY", "GROQ_API_KEY",
                              "MISTRAL_API_KEY", "DEEPSEEK_API_KEY")
                  if (os.environ.get(k) or "").strip()]
    if not provider and not brief_keys:
        return _result("llm_keys", name, "off", "chưa có key nào trong .env",
                       "thêm GROQ_API_KEY / ANTHROPIC_API_KEY… vào .env")
    parts = [f"sentiment: {provider or '❌ không có (GEMINI/GROQ/CEREBRAS/OPENROUTER)'}"]
    parts.append(f"brief agent: {len(brief_keys)} key" if brief_keys
                 else "brief agent: ❌ không có key")
    status = "ok" if (provider and brief_keys) else "warn"
    return _result("llm_keys", name, status, " · ".join(parts),
                   "bổ sung key thiếu vào .env" if status != "ok" else "")


def check_telegram() -> dict:
    name = "Telegram push"
    tok = bool((os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip())
    chat = bool((os.environ.get("TELEGRAM_CHAT_ID") or "").strip())
    if tok and chat:
        return _result("telegram", name, "ok", "BOT_TOKEN + CHAT_ID có trong env")
    if tok or chat:
        missing = "TELEGRAM_CHAT_ID" if tok else "TELEGRAM_BOT_TOKEN"
        return _result("telegram", name, "warn", f"thiếu {missing}",
                       f"thêm {missing} vào .env")
    return _result("telegram", name, "off", "chưa cấu hình",
                   "thêm TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID vào .env")


def check_reports() -> dict:
    """Thư viện báo cáo vĩ mô (P2/P3) — metadata thiếu / digest chưa chạy /
    claim lệch registry. off khi chưa dùng tính năng (không tính exit code)."""
    name = "Báo cáo vĩ mô (reports)"
    p = _META / "reports_index.json"
    if not p.exists():
        return _result("reports", name, "off", "chưa có báo cáo nào trong thư viện",
                       "thêm qua sub-tab 📚 Báo cáo hoặc vnstock_reports.py --add")
    reports = list((json.loads(p.read_text(encoding="utf-8"))
                    .get("reports") or {}).values())
    from vnstock_reports import in_analysis
    ready = [r for r in reports if in_analysis(r)]
    no_meta = sum(1 for r in reports if not in_analysis(r))
    no_digest = sum(1 for r in ready if not r.get("digest"))
    mismatch = sum(1 for r in ready
                   if (r.get("digest") or {}).get("has_mismatch"))
    parts = [f"{len(reports)} báo cáo, {len(ready)} đủ điều kiện phân tích"]
    if no_meta:
        parts.append(f"{no_meta} thiếu metadata/scan")
    if no_digest:
        parts.append(f"{no_digest} chưa digest")
    if mismatch:
        parts.append(f"{mismatch} digest có claim lệch registry")
    status = "warn" if (no_digest or mismatch) else "ok"
    fix = ("python vnstock_report_digest.py --refresh" if no_digest else
           "python vnstock_report_digest.py --show <id> — soi claim lệch"
           if mismatch else "")
    return _result("reports", name, status, " · ".join(parts), fix)


def _allocation_brief_reminder(today: "date | None" = None) -> "str | None":
    """Nhắc tạo brief phân bổ KỲ THÁNG (mirror pmi_reminder): từ mùng 3 mà
    tháng này chưa có brief_type='allocation' trong memory → 1 dòng nhắc.
    Best-effort — memory lỗi/thiếu coi như không nhắc (không báo động giả)."""
    t = today or date.today()
    if t.day < 3:
        return None
    try:
        from vnstock_memory import recent_briefs
        rows = recent_briefs("allocation", limit=5)
        month = t.strftime("%Y-%m")
        if any((r.get("created_at") or "").startswith(month) for r in rows):
            return None
        return (f"⏰ chưa có brief phân bổ tháng {t.month}/{t.year} — tạo ở "
                "tab Tin tức → sub-tab 🧭 Phân bổ (cadence tháng)")
    except Exception:
        return None


def check_allocation() -> dict:
    """Band phân bổ (P1) — tuổi state so phiên trước (run.py all refresh hằng
    ngày) + nhắc brief kỳ tháng. off khi chưa chạy lần nào."""
    name = "Phân bổ tài sản (allocation)"
    p = _META / "allocation_state.json"
    if not p.exists():
        return _result("allocation", name, "off", "chưa có allocation_state.json",
                       "python run.py allocation")
    st = json.loads(p.read_text(encoding="utf-8"))
    as_of = str(st.get("as_of") or "")
    stale = bool(as_of) and date.fromisoformat(as_of) < _prev_trading_day()
    parts = [f"band {st.get('band', '?')} ({st.get('band_label', '?')}) · "
             f"phiên {as_of or '?'} · {st.get('n_inputs', 0)} tín hiệu · "
             f"history {len(st.get('history') or [])} phiên"]
    if (st.get("report_tilt") or {}).get("tilt"):
        parts.append(f"tilt {st['report_tilt']['tilt']:+d} từ báo cáo")
    remind = _allocation_brief_reminder()
    if remind:
        parts.append(remind)
    status = "warn" if (stale or remind) else "ok"
    fix = "python run.py allocation" if stale else \
        ("dashboard → tab Tin tức → sub-tab 🧭 Phân bổ → nút 📝 Tạo brief"
         if remind else "")
    return _result("allocation", name, status, " · ".join(parts), fix)


def check_tests() -> dict:
    """Badge test gần nhất — fail thì đừng deploy/merge (kỷ luật trong CLAUDE.md)."""
    name = "Tests (pytest)"
    p = _META / "test_status.json"
    if not p.exists():
        return _result("tests", name, "off", "chưa chạy",
                       "python run.py test --fast")
    st = json.loads(p.read_text(encoding="utf-8"))
    bad = int(st.get("failed", 0)) + int(st.get("errors", 0))
    age = _age_days(str(st.get("ran_at", "")))
    msg = (f"{st.get('passed', 0)} passed"
           + (f", {bad} FAIL" if bad else "")
           + f" · chạy {_fmt_age(age)} ({st.get('mode', '?')})")
    if bad:
        return _result("tests", name, "error", msg,
                       "python run.py test --fast — xem test nào fail trước khi merge")
    # Badge XANH mà CODE đã đổi sau lần chạy đó là lời trấn an sai — đúng loại
    # hỏng vừa vá ở badge quy đổi đơn vị. Ca thật 19/08: user merge code mới rồi
    # chạy `pytest` thẳng (không qua `run.py test` nên badge không được ghi) —
    # badge vẫn khoe "2148 passed" của hôm trước trong khi thực tế đã 2196.
    stale_vs = _code_changed_after(str(st.get("ran_at", "")))
    if stale_vs:
        return _result("tests", name, "warn",
                       f"{msg} — nhưng CODE đã đổi sau đó ({stale_vs})",
                       "python run.py test  (chạy qua run.py mới cập nhật badge; "
                       "`pytest` thẳng thì badge không biết)")
    return _result("tests", name, "ok" if (age is not None and age <= 7) else "warn",
                   msg, "" if (age is not None and age <= 7) else "python run.py test --fast")


def _code_changed_after(ran_at: str) -> "str | None":
    """File .py nào mới hơn lần chạy test gần nhất? Trả tên file mới nhất.

    Câu hỏi badge cần trả lời không phải "test chạy lâu chưa" mà "có ai chạy
    test SAU lần code đổi gần nhất không". Dùng mtime: `git merge` chạm file
    nào thì file đó có mtime mới — đúng ngữ nghĩa cần.
    """
    try:
        ran = datetime.fromisoformat(ran_at)
    except Exception:
        return None
    newest, newest_at = None, ran
    for pat in ("*.py", "dashboard/*.py", "scripts/*.py", "tests/*.py"):
        for f in _REPO.glob(pat):
            try:
                at = datetime.fromtimestamp(f.stat().st_mtime)
            except Exception:
                continue
            if at > newest_at:
                newest, newest_at = f.name, at
    if newest is None:
        return None
    return f"{newest} lúc {newest_at.strftime('%d/%m %H:%M')}"


# ── NET checks (--net) — probe thật từng nguồn ngoài ─────────────────────────


def net_rss_feeds() -> dict:
    """Fetch thử TỪNG feed RSS (song song) — đúng việc news_feeds --diag làm."""
    name = "RSS feeds (mạng)"
    from concurrent.futures import ThreadPoolExecutor
    import vnstock_news_feeds as nf
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda f: (f["name"], len(nf.fetch_feed(f))), nf._FEEDS))
    ok = [n for n, c in counts if c]
    dead = [n for n, c in counts if not c]
    msg = f"{len(ok)}/{len(counts)} feed trả dữ liệu"
    if dead:
        msg += " · ❌ " + ", ".join(dead)
    status = "ok" if not dead else ("warn" if ok else "error")
    return _result("net_rss", name, status, msg,
                   "feed ❌ → URL sai/bị chặn: sửa/xoá trong vnstock_news_feeds._FEEDS"
                   if dead else "")


def net_fx() -> dict:
    """API tỷ giá free (er-api → exchangerate.host)."""
    name = "FX USD/VND (mạng)"
    from vnstock_macro import fetch_usdvnd
    v = fetch_usdvnd()
    if v:
        return _result("net_fx", name, "ok", f"fetch OK: {v:,.0f} VND")
    return _result("net_fx", name, "error", "không fetch được tỷ giá",
                   "kiểm tra mạng/allowlist (open.er-api.com, exchangerate.host); "
                   "cache cũ vẫn được giữ")


def net_vbma() -> dict:
    """Báo cáo tuần VBMA (PDF) → lãi suất LNH + lợi suất TPCP."""
    name = "VBMA weekly (mạng)"
    if os.environ.get("VNSTOCK_MACRO_VBMA", "1") == "0":
        return _result("net_vbma", name, "off", "đã tắt (VNSTOCK_MACRO_VBMA=0)")
    from vnstock_vbma import fetch_weekly
    got = fetch_weekly()
    if got:
        keys = ", ".join(sorted(k for k in got if k not in ("as_of", "source_url")))
        return _result("net_vbma", name, "ok",
                       f"parse OK (as_of {got.get('as_of', '?')}): {keys}")
    return _result("net_vbma", name, "error", "không tải/parse được PDF tuần",
                   "python vnstock_vbma.py --diag --dump — gửi output để chỉnh regex; "
                   "tạm thời: python vnstock_macro.py --set interbank_on <số>")


def net_nso() -> dict:
    """Báo cáo tháng NSO → CPI/IIP/GDP/cán cân thương mại."""
    name = "NSO monthly (mạng)"
    if os.environ.get("VNSTOCK_MACRO_NSO", "1") == "0":
        return _result("net_nso", name, "off", "đã tắt (VNSTOCK_MACRO_NSO=0)")
    from vnstock_nso import fetch_monthly
    got = fetch_monthly()
    if got:
        keys = ", ".join(sorted(k for k in got if k not in ("as_of", "source_url")))
        return _result("net_nso", name, "ok",
                       f"parse OK (as_of {got.get('as_of', '?')}): {keys}")
    return _result("net_nso", name, "error", "không tải/parse được bài NSO",
                   "python vnstock_nso.py --diag --dump. TOÀN lỗi kết nối "
                   "(ConnectTimeout/ConnectionReset) = mạng máy này chặn, "
                   "thử máy/mạng khác TRƯỚC khi sửa code; tải được mà parse "
                   "hỏng mới là chuyện regex")


def net_foreign_flow_api() -> dict:
    """API TopStock foreign buy/sell cho phiên giao dịch trước."""
    name = "Foreign-flow API (mạng)"
    from vnstock_foreign_flow import fetch_market_net
    d = _prev_trading_day().isoformat()
    rec = fetch_market_net(d)
    if not rec:
        return _result("net_foreign_flow", name, "error",
                       f"API không trả dữ liệu cho {d}",
                       "kiểm tra vnstock_data/sponsor API + mạng; "
                       "python vnstock_foreign_flow.py --diag " + d)
    n = rec.get("n_symbols", 0)
    msg = f"{d}: net {rec.get('net')} tỷ, {n} mã"
    if n <= 120:
        return _result("net_foreign_flow", name, "warn",
                       msg + " · số mã ≤120 — API có thể cap limit",
                       "tăng --limit hoặc đổi nguồn (xem TODO #0/#1 trong CLAUDE.md)")
    return _result("net_foreign_flow", name, "ok", msg)


def net_fred() -> dict:
    """FRED (US10Y + Fed funds) — cần FRED_API_KEY free trong .env."""
    name = "FRED US10Y/Fed (mạng)"
    if os.environ.get("VNSTOCK_MACRO_FRED", "1") == "0":
        return _result("net_fred", name, "off", "đã tắt (VNSTOCK_MACRO_FRED=0)")
    from vnstock_fred import _api_key, fetch_daily
    if not _api_key():
        return _result("net_fred", name, "off",
                       "chưa có FRED_API_KEY trong .env — us10y/fed_funds sẽ "
                       "không tự cập nhật",
                       "đăng ký key free (~2 phút): "
                       "https://fred.stlouisfed.org/docs/api/api_key.html "
                       "→ thêm FRED_API_KEY=<key> vào .env")
    got = fetch_daily()
    if got:
        parts = ", ".join(f"{k}={v} ({d})" for k, (v, d) in sorted(got.items()))
        return _result("net_fred", name, "ok", f"fetch OK: {parts}")
    return _result("net_fred", name, "error",
                   "có key nhưng không fetch được",
                   "kiểm tra mạng/allowlist api.stlouisfed.org + key còn hiệu lực; "
                   "python vnstock_fred.py --diag")


def net_hnx() -> dict:
    """HNX yield curve (POST API) → lợi suất TPCP 8 kỳ hạn theo ngày."""
    name = "HNX yield curve (mạng)"
    if os.environ.get("VNSTOCK_HNX", "1") == "0":
        return _result("net_hnx", name, "off", "đã tắt (VNSTOCK_HNX=0)")
    from vnstock_hnx import fetch_latest
    got = fetch_latest(verbose=False)
    if got:
        d, ys = got
        return _result("net_hnx", name, "ok",
                       f"fetch OK ({d}): " + ", ".join(f"{k}={v}" for k, v in ys.items()))
    return _result("net_hnx", name, "error",
                   "không tải/parse được đường cong HNX",
                   "python vnstock_hnx.py --diag — kiểm endpoint/selector còn đúng; "
                   "tạm thời VBMA PDF vẫn nuôi 2Y/10Y")


def net_sbv() -> dict:
    """Bản tin tuần SBV (PDF) → LNH + OMO ròng + tỷ giá trung tâm."""
    name = "SBV weekly (mạng)"
    if os.environ.get("VNSTOCK_SBV", "1") == "0":
        return _result("net_sbv", name, "off", "đã tắt (VNSTOCK_SBV=0)")
    from vnstock_sbv import fetch_weekly
    got = fetch_weekly()
    if got:
        fields = ", ".join(k for k, v in got.__dict__.items() if v is not None)
        return _result("net_sbv", name, "ok", f"parse OK: {fields or '(rỗng)'}")
    return _result("net_sbv", name, "warn",
                   "không tải/parse được bản tin SBV (LNH vẫn có từ VBMA/HNX)",
                   "python vnstock_sbv.py --diag — kiểm slug bài/URL PDF; "
                   "OMO tạm nhập tay: python vnstock_sbv.py --set-omo <số>")


def net_sbv_daily() -> dict:
    """LNH bình quân THEO NGÀY (headless-delivery API portal SBV)."""
    name = "SBV daily LNH (mạng)"
    if os.environ.get("VNSTOCK_SBV_DAILY", "1") == "0":
        return _result("net_sbv_daily", name, "off", "đã tắt (VNSTOCK_SBV_DAILY=0)")
    from vnstock_sbv_rates import fetch_daily
    entries = fetch_daily()
    if entries:
        e = entries[0]
        return _result("net_sbv_daily", name, "ok",
                       f"fetch OK ({e['date']}): "
                       + ", ".join(f"{k}={v}" for k, v in sorted(e["rates"].items())))
    return _result("net_sbv_daily", name, "warn",
                   "không fetch/parse được LNH ngày (registry vẫn có nguồn tuần)",
                   "python vnstock_sbv_rates.py --diag — kiểm endpoint "
                   "headless-delivery / schema contentFields còn đúng")


def net_jina() -> dict:
    """Jina Reader (r.jina.ai) — full text cho tin chấm LLM."""
    name = "Jina Reader (mạng)"
    from vnstock_news_feeds import _fulltext_enabled, fetch_fulltext
    if not _fulltext_enabled():
        return _result("net_jina", name, "off", "đã tắt (VNSTOCK_NEWS_FULLTEXT=0)")
    body = fetch_fulltext("https://example.com/")
    if body:
        return _result("net_jina", name, "ok",
                       f"đọc thử OK ({len(body)} ký tự)")
    return _result("net_jina", name, "warn",
                   "không truy cập được r.jina.ai — tin chấm LLM sẽ chỉ dùng "
                   "title+summary (vẫn chạy được)",
                   "kiểm tra mạng/allowlist r.jina.ai; tắt hẳn: VNSTOCK_NEWS_FULLTEXT=0")


# Kill-switch NGUY HIỂM: tắt hẳn một bước, im lặng, và KHÔNG để lại dấu nào
# ngoài một dòng log dễ trôi. Vết 19/08: cả buổi truy "vì sao brief không gửi"
# mà `VNSTOCK_PIPELINE_BRIEF=0` là một trong bốn nghi phạm — doctor lẽ ra phải
# nói ngay. Doctor cũ chỉ soi 6 cờ tắt của nguồn vĩ mô, không soi nhóm này.
#
# Bẫy đường lây: một dòng trong `.env` cũng đủ, vì các bước chạy IN-PROCESS
# (`cmd_news` bước 4, `cmd_doctor` bước 13) đều `load_dotenv` vào os.environ
# trước khi tới bước 14.
_DANGEROUS_SWITCHES = {
    "VNSTOCK_PIPELINE_BRIEF": "tắt HẲN bước brief — pipeline chạy xong mà "
                              "Telegram không nhận gì",
    "VNSTOCK_BRIEF_AUTO_REFRESH": "brief thôi tự làm mới độ rộng thị trường "
                                  "→ có thể báo số giữa phiên",
    "VNSTOCK_BRIEF_AUTO_RECONCILE": "thôi tự đóng lệnh quá hạn → sổ lệnh đầy "
                                    "lệnh zombie",
    "VNSTOCK_NEWS_FULLTEXT": "tin chỉ chấm bằng title+summary",
    "VNSTOCK_STRATEGY_ISOLATION": "nới cách ly sandbox chiến lược",
    "VNSTOCK_BASIS_GUARD": "tắt cửa gác lệch cơ sở — nguồn rebase là kho lại "
                           "sinh bậc giả âm thầm như trước 19/08",
    "VNSTOCK_OHLC_REPAIR": "thôi nới bar tự mâu thuẫn — chúng quay lại hàng "
                           "đợi cách ly và đốt 36 phút refetch mỗi đêm",
}
_OFF_VALUES = {"0", "false", "off", "no"}


def check_kill_switches() -> dict:
    """Có cờ môi trường nào đang TẮT một phần pipeline không.

    Chỉ báo khi cờ được đặt về giá trị TẮT — đặt "1"/"true" là mặc định, không
    phải chuyện đáng nói. Đọc `.env` nữa chứ không chỉ os.environ, vì đó mới là
    nơi cờ sống dai và là đường lây đã vấp.
    """
    name = "Kill-switch pipeline"
    found: "list[str]" = []
    seen: "dict[str, str]" = {}
    for k in _DANGEROUS_SWITCHES:
        v = os.environ.get(k)
        if v is not None:
            seen[k] = v.strip()
    env_file = _REPO / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k in _DANGEROUS_SWITCHES:
                    seen.setdefault(k, v.strip().strip('"\''))
        except Exception:
            pass
    for k, v in seen.items():
        if str(v).strip().lower() in _OFF_VALUES:
            found.append(f"{k}={v} ({_DANGEROUS_SWITCHES[k]})")
    if not found:
        return _result("kill_switches", name, "ok",
                       "không cờ nào đang tắt phần nào của pipeline", "")
    return _result(
        "kill_switches", name, "warn",
        "ĐANG TẮT: " + " · ".join(found),
        "bỏ dòng đó khỏi .env (hoặc biến môi trường User/Machine) rồi chạy lại; "
        "cố ý tắt thì bỏ qua cảnh báo này")


def check_basis_drift() -> dict:
    """Có mã nào bị cửa gác lệch cơ sở CÁCH LY mà chưa chữa không?

    Guard ở `vnstock_updater` từ chối nối bar mới khi phát hiện nguồn vừa
    rebase toàn chuỗi (V1, sau ca 70/159 mã ngày 19/08) và ghi mã vào
    `_meta/basis_drift_pending.json`. Mã nằm trong sổ = ĐANG KHÔNG được cập
    nhật giá — im lặng là mất data, nên đây là warn chứ không phải info.
    """
    name = "Lệch cơ sở — mã bị cách ly"
    try:
        from vnstock_basis_guard import load_pending
        pending = load_pending(_META.parent)   # tests monkeypatch _META
    except Exception as e:
        return _result("basis_drift", name, "error",
                       f"không đọc được sổ cách ly ({type(e).__name__}: {e})", "")
    if not pending:
        return _result("basis_drift", name, "ok",
                       "không mã nào bị cách ly vì lệch cơ sở", "")
    items = sorted(pending.items())
    head = " · ".join(f"{tk} {v.get('ratio', 0):.4f}× ({v.get('detected_at')})"
                      for tk, v in items[:6])
    more = f" … +{len(items) - 6} mã" if len(items) > 6 else ""
    return _result(
        "basis_drift", name, "warn",
        f"{len(items)} mã ĐANG KHÔNG cập nhật giá: {head}{more}",
        "chữa: python scripts/rebase_ticker_history.py --ticker <MÃ> --apply "
        "(chữa xong tool tự xoá khỏi sổ). Cố ý bỏ qua thì "
        "VNSTOCK_BASIS_GUARD=0 — nhưng khi đó lệch quay lại âm thầm")


def check_ohlc_repairs() -> dict:
    """Bar tự mâu thuẫn đã được NỚI low/high — người vẫn phải liếc qua.

    `vnstock_ohlc_repair` sửa `low > min(open, close)` / `high < max(...)` ở
    đường ghi (V-OHLC, 19/08) để bar khỏi rơi vào hàng đợi cách ly rồi bị
    refetch vô ích 36 phút mỗi đêm. Giá trị mới là chính open/close nên không
    bịa số — nhưng đây vẫn là lớp TỰ SỬA, và doctrine của repo là mọi lớp tự
    sửa best-effort đều cần một badge để không âm thầm.
    """
    name = "Nới OHLC (bar tự mâu thuẫn)"
    try:
        from vnstock_ohlc_repair import MAX_WIDEN_PCT, load_repairs
        data = load_repairs(_META.parent)   # tests monkeypatch _META
    except Exception as e:
        return _result("ohlc_repair", name, "error",
                       f"không đọc được vết nới OHLC ({type(e).__name__}: {e})", "")
    events = list(data.get("events") or [])
    if not events:
        return _result("ohlc_repair", name, "ok", "chưa nới bar nào", "")
    total = int(data.get("total") or len(events))
    cutoff = (date.today() - timedelta(days=_UNIT_WARN_DAYS)).isoformat()
    fresh = [e for e in events if str(e.get("at", ""))[:10] >= cutoff]
    if not fresh:
        return _result("ohlc_repair", name, "ok",
                       f"tổng {total:,} lần, gần nhất "
                       f"{str(events[-1].get('at', '?'))[:10]}", "")
    widest = max((float(e.get("widen_pct") or 0) for e in fresh), default=0.0)
    tickers = sorted({str(e.get("ticker", "?")) for e in fresh})
    head = ", ".join(tickers[:5]) + (" …" if len(tickers) > 5 else "")
    return _result(
        "ohlc_repair", name, "warn",
        f"{len(fresh):,} bar nới trong {_UNIT_WARN_DAYS} ngày / {len(tickers)} mã "
        f"({head}) · nới rộng nhất {widest:.2f}% (trần {MAX_WIDEN_PCT:.0%})",
        "xem _meta/ohlc_repairs.json — giá mới là open/close ĐÃ khớp nên không "
        "bịa số; nới sát trần thì soi lại bar đó. Tắt: VNSTOCK_OHLC_REPAIR=0")


def check_vn30_basket() -> dict:
    """Rổ VN30 chép cứng có còn khớp rổ thật không?

    HOSE xét lại VN30 **hai lần mỗi năm** (hiệu lực đầu tháng 2 và đầu tháng
    8). Danh sách 30 mã từng được chép cứng ở ba module độc lập, không chỗ
    nào tự làm mới ⇒ mỗi kỳ đổi rổ là brief, screener và heatmap live cùng
    nói sai mà KHÔNG có gì báo. Vết 20/08/2026: user nhìn heatmap trong phiên
    mới phát hiện.

    Ở đây `warn` là trạng thái ĐÚNG khi vừa qua kỳ đổi rổ — nó nhắc sửa hằng
    số, không phải báo hỏng.
    """
    name = "Rổ VN30 (HOSE đổi 2 lần/năm)"
    try:
        import vnstock_vn30 as _v30
        # OFFLINE: đọc cache thôi, cấm gọi mạng ở đây (net_vn30_basket lo
        # phần làm mới).
        st = _v30.status(allow_fetch=False)
        added, removed = _v30.diff_vs_fallback(st["members"])
    except Exception as e:
        return _result("vn30_basket", name, "error",
                       f"không phân giải được rổ VN30 ({type(e).__name__}: {e})", "")

    src = st.get("source")
    if src == "fallback":
        return _result(
            "vn30_basket", name, "warn",
            "chưa từng lấy được rổ sống — đang chạy bằng hằng số chép cứng",
            "chạy `python run.py doctor --net` trên máy có mạng để nạp cache "
            "_meta/vn30_members.json. Cố ý dùng hằng số thì VNSTOCK_VN30_DYNAMIC=0")

    if not added and not removed:
        age = st.get("age_days")
        age_txt = f", cache {age:.1f} ngày" if isinstance(age, (int, float)) else ""
        return _result("vn30_basket", name, "ok",
                       f"{len(st['members'])} mã, khớp hằng số (nguồn {src}{age_txt})", "")

    parts = []
    if added:
        parts.append("VÀO rổ: " + ", ".join(added))
    if removed:
        parts.append("RỜI rổ: " + ", ".join(removed))
    return _result(
        "vn30_basket", name, "warn",
        f"rổ thật đã đổi so với hằng số — {' · '.join(parts)}",
        "sửa VN30_TICKERS (vnstock_brief_canon.py), VN30_SYMBOLS "
        "(vnstock_wss.py) và _VN30_FALLBACK (vnstock_news.py) cho khớp. "
        "Đường sống + heatmap đã tự dùng rổ mới; hằng số chỉ là lưới cuối")


def check_brief_watch() -> dict:
    """Sổ theo dõi nghi ngờ của brief — ĐẾM TRƯỚC, QUYẾT SAU.

    Hai mục từ đợt soi close 21/08 (U22) chưa đủ căn cứ để viết guard: Op.CF
    quá lớn so với quy mô (KBC −17.344 tỷ ≈ 0,8× vốn hoá — ngưỡng nào là
    "sai" thì chưa biết, BĐS âm nặng là chuyện thật) và câu viện dẫn dòng
    tiền ngoại không có trong ctx (ca SSI).

    DƯỚI sàn mẫu thì badge **ok kèm n=…**, tuyệt đối không warn: trình bày
    "chưa đo được" thành "đo ra kết quả xấu" đúng là lỗi repo đã dính (n=2 vẽ
    thành "0%", 13/08).
    """
    name = "Sổ theo dõi nghi ngờ brief"
    try:
        import vnstock_brief_watch as _w
        st = _w.summarize(_META.parent)
    except Exception as e:
        return _result("brief_watch", name, "error",
                       f"không đọc được sổ ({type(e).__name__}: {e})", "")
    if not st["n_ocf"] and not st["n_flow"]:
        return _result("brief_watch", name, "ok",
                       f"chưa nhặt được nghi ngờ nào (đã soi {st['n_days']} phiên)", "")
    parts = []
    if st["n_ocf"]:
        w = st["worst_ocf"] or {}
        parts.append(f"Op.CF/vốn hoá lớn bất thường ×{st['n_ocf']} "
                     f"({', '.join(st['ocf_tickers'][:5])}"
                     + (" …" if len(st["ocf_tickers"]) > 5 else "") +
                     f"; đậm nhất {w.get('ticker','?')} {w.get('ratio','?')}×)")
    if st["n_flow"]:
        parts.append(f"câu dòng tiền ngoại NGƯỢC data ×{st['n_flow']} "
                     f"({', '.join(st['flow_sectors'][:3])})")
    msg = f"{st['n_days']} phiên đã soi — " + " · ".join(parts)
    if not st["enough"]:
        return _result("brief_watch", name, "ok",
                       f"{msg} — CHƯA đủ mẫu để kết luận "
                       f"(cần ≥{_w.MIN_SAMPLES} phiên)", "")
    return _result(
        "brief_watch", name, "warn",
        f"{msg} — ĐỦ mẫu, đáng quyết",
        "đọc _meta/brief_watch.json rồi chốt: Op.CF lệch đơn vị hay số thật của "
        "BĐS? câu dòng tiền ngoại có đáng viết guard chặn không? Xong thì xoá "
        "file để đếm lại. Tắt sổ: VNSTOCK_BRIEF_WATCH=0")


def check_exdiv_source() -> dict:
    """Bộ chặn cờ "phân phối" GIẢ có data để chặn không, hay đang chạy chay?

    `market_commentary` gọi `load_recent_exdiv(days_back=7)` để **bỏ qua** cờ
    phân phối khi giá rơi chỉ vì cổ tức. Không có data thì hàm trả `{}`, cờ
    giả đi thẳng ra dashboard — **im lặng**, vì `{}` là giá trị hợp lệ.

    Vết 26/08 (U36): đường nạp duy nhất khi đó là `_meta/cash_dividends/*.json`,
    mà kho đó chỉ do `run.py cash-dividends` ghi — lệnh cào CafeF **404 từ
    19/08** và **KHÔNG nằm trong `cmd_all`**. Cửa sổ 7 ngày ⇒ hàm luôn rỗng.
    Nay đọc thẳng sổ đăng ký; badge này canh để nó không lặng lẽ chết lần nữa.

    ⚠️ 7 ngày mà KHÔNG mã nào chia cổ tức là chuyện **BÌNH THƯỜNG**, nên
    "rỗng" một mình KHÔNG đủ để warn — báo động giả dạy người ta bỏ qua badge,
    hỏng nặng hơn cái nó cảnh báo. Chỉ warn khi **sổ rỗng ở MỌI kỳ**, tức
    không phải "tuần này không có" mà là "không có nguồn".
    """
    name = "Nguồn chặn cờ cổ tức"
    try:
        from vnstock_market_analyzer import exdiv_source_status
        st = exdiv_source_status()
    except Exception as e:
        return _result("exdiv_source", name, "error",
                       f"không đọc được ({type(e).__name__}: {e})", "")

    if st["recent"]:
        return _result("exdiv_source", name, "ok",
                       f"sổ đăng ký trả {st['recent']} mã trong "
                       f"{st['days_back']} ngày (sổ có {st['total_cash']} sự "
                       f"kiện cổ tức tất cả các kỳ)", "")
    if st["total_cash"]:
        return _result("exdiv_source", name, "ok",
                       f"{st['days_back']} ngày qua không mã nào chia cổ tức "
                       f"(sổ có {st['total_cash']} sự kiện ở các kỳ khác)", "")
    return _result(
        "exdiv_source", name, "warn",
        "sổ đăng ký KHÔNG có sự kiện cổ tức tiền mặt nào — bộ chặn cờ "
        "\"phân phối\" giả đang chạy CHAY",
        "nạp sổ: `python run.py vietstock --bulk --register` (GHI KHO — đừng "
        "chạy trong lúc phát 18:00). Đường CafeF `run.py cash-dividends` đã bỏ "
        "26/08 vì 404 từ 19/08, đừng tìm lại")


def check_autoheal_yield() -> dict:
    """auto-heal có chữa được gì không, hay chỉ đang xay không tải?

    Đo trên máy thật 24-25/08: **0 mã lành / 3.076 lượt refetch** qua hai
    đêm, mỗi đêm tiêu trọn ~620s ngân sách. Con số này lẽ ra phải TỰ nổi
    lên chứ không phải chờ user dán log về — badge này là chỗ đó.

    Dưới sàn mẫu ⇒ ok kèm n=…, không warn.
    """
    name = "Hiệu suất auto-heal"
    try:
        from vnstock_quarantine import HEAL_MIN_ATTEMPTS, heal_stats
        st = heal_stats(_META.parent)
    except Exception as e:
        return _result("autoheal_yield", name, "error",
                       f"không đọc được sổ ({type(e).__name__}: {e})", "")
    if not st["runs"]:
        return _result("autoheal_yield", name, "ok", "chưa có lượt nào được ghi", "")
    head = (f"{st['healed']:,}/{st['attempts']:,} bar lành qua {st['runs']} lượt"
            + (f" ({st['rate']:.1%})" if st["rate"] is not None else ""))
    if not st["enough"]:
        return _result("autoheal_yield", name, "ok",
                       f"{head} — chưa đủ mẫu (cần ≥{HEAL_MIN_ATTEMPTS:,} lượt)", "")
    if st["healed"]:
        return _result("autoheal_yield", name, "ok", head, "")
    return _result(
        "autoheal_yield", name, "warn",
        f"{head} — refetch KHÔNG chữa được gì",
        "đối chiếu CHI PHÍ trước khi tắt: xem `auto-heal <n>s` trong dòng "
        "`⏱ CHẶNG` của run_daily.log. Tốn giờ thì hạ trần "
        "VNSTOCK_AUTOHEAL_BUDGET_S=120, hoặc =0 để TẮT HẲN (khi ấy hàng đợi "
        "cách ly không được thử lại lẫn dọn — chạy tay: python run.py heal). "
        "Tốn ~0s thì cứ để, nó không hại gì; xem _meta/autoheal_runs.json")


def check_gtgd_coverage() -> dict:
    """#18: mã LỚN thiếu bar ở phiên screener vừa quét (cách ly cơ sở / sync
    lỗi / cửa KBS từ chối) ⇒ GTGD cả ngày trong brief ước tính THẤP. Runner ghi
    `gtgd_missing_heavy` vào market_overview.json; bản cũ không có key → off."""
    name = "GTGD cả ngày — mã lớn thiếu bar"
    p = _META / "market_overview.json"
    if not p.exists():
        return _result("gtgd_coverage", name, "off", "chưa có market_overview.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return _result("gtgd_coverage", name, "error",
                       f"không đọc được market_overview.json ({type(e).__name__})")
    if "gtgd_missing_heavy" not in data:
        return _result("gtgd_coverage", name, "off",
                       "screener bản cũ chưa ghi gtgd_missing_heavy — phát kế sẽ có")
    mh = data.get("gtgd_missing_heavy") or []
    dd = data.get("data_date") or "?"
    floor = data.get("gtgd_heavy_min") or 50
    if not mh:
        return _result("gtgd_coverage", name, "ok",
                       f"phiên {dd}: mọi mã lớn (TB ≥ {float(floor):.0f} tỷ/phiên) đều có bar")
    try:
        est = float(data.get("gtgd_missing_est") or 0) or float(
            sum(float(m.get("avg_gtgd") or 0) for m in mh))
    except (TypeError, ValueError):
        est = 0.0
    top = ", ".join(f"{m.get('ticker')} (≈{float(m.get('avg_gtgd') or 0):,.0f} tỷ, bar cuối "
                    f"{m.get('last_date')})" for m in mh[:5])
    more = f" +{len(mh) - 5} mã" if len(mh) > 5 else ""
    return _result(
        "gtgd_coverage", name, "warn",
        f"phiên {dd} thiếu bar {len(mh)} mã lớn ≈ {est:,.0f} tỷ/phiên: {top}{more} — "
        "GTGD cả ngày trong brief ước tính THẤP (% so baseline đã loại các mã này)",
        "mã trong sổ cách ly → chữa rebase (badge Lệch cơ sở); mã đứng im mà KHÔNG "
        "trong sổ = cửa KBS từ chối (#15) → python scripts\\rebase_ticker_history.py "
        "--ticker <MÃ> --explain")


OFFLINE_CHECKS = [
    check_dir_shapes, check_unit_normalizations, check_kill_switches,
    check_basis_drift, check_ohlc_repairs, check_vn30_basket,
    check_autoheal_yield,
    check_brief_watch,
    check_exdiv_source,
    check_pipeline_reach, check_brief_engine,
    check_warehouse, check_market_overview, check_gtgd_coverage,
    check_fundamentals, check_macro,
    check_pdf_tooling, check_market_news, check_ticker_news,
    check_foreign_flow, check_events, check_reports, check_allocation,
    check_llm_keys, check_llm_ledger, check_telegram, check_tests,
]
def net_vn30_basket() -> dict:
    """Làm mới rổ VN30 từ API rồi so với hằng số chép cứng.

    Bản offline chỉ đọc cache; bản này mới được gọi mạng — và nó GHI lại
    cache trong `_meta/` nên chạy một lần ở máy nào cũng phục vụ cả hai máy
    (kho đi qua Dropbox).
    """
    name = "Rổ VN30 — làm mới từ nguồn"
    try:
        import vnstock_vn30 as _v30
        st = _v30.status(force_refresh=True)
        added, removed = _v30.diff_vs_fallback(st["members"])
    except Exception as e:
        return _result("vn30_basket_net", name, "error",
                       f"không lấy được rổ VN30 ({type(e).__name__}: {e})",
                       "kiểm tra VNSTOCK_API_KEY trong .env và đường mạng")
    if st.get("source") != "live":
        return _result("vn30_basket_net", name, "warn",
                       f"API không trả rổ dùng được (đang dùng {st.get('source')})",
                       "chạy `python vnstock_vn30.py --diag` — nó in THẬT nguồn "
                       "trả về type/columns/mấy mã, đừng đoán")
    if not added and not removed:
        return _result("vn30_basket_net", name, "ok",
                       f"{len(st['members'])} mã, khớp hằng số chép cứng", "")
    parts = []
    if added:
        parts.append("VÀO rổ: " + ", ".join(added))
    if removed:
        parts.append("RỜI rổ: " + ", ".join(removed))
    return _result("vn30_basket_net", name, "warn",
                   f"rổ thật đã đổi — {' · '.join(parts)}",
                   "sửa hằng số ở vnstock_brief_canon.py, vnstock_wss.py, "
                   "vnstock_news.py cho khớp")


NET_CHECKS = [
    net_rss_feeds, net_fx, net_vbma, net_hnx, net_sbv, net_sbv_daily,
    net_nso, net_fred, net_foreign_flow_api, net_jina, net_vn30_basket,
]


def run_checks(net: bool = False) -> list[dict]:
    """Chạy toàn bộ check (offline; + net khi ``net=True``). Một check nổ →
    status "error" của riêng nó, KHÔNG kéo sập báo cáo (mirror doctor Agent-Reach)."""
    results: list[dict] = []
    for fn in OFFLINE_CHECKS + (NET_CHECKS if net else []):
        try:
            results.append(fn())
        except KeyboardInterrupt:      # Ctrl+C của user thì phải thoát thật
            raise
        except BaseException as e:  # noqa: BLE001 — doctor phải sống sót mọi nguồn,
            # KỂ CẢ BaseException ngoài Exception (pyo3 PanicException từ native
            # package hỏng — thấy thật khi import pypdf trên bản cryptography lỗi)
            key = fn.__name__.removeprefix("check_").removeprefix("net_")
            results.append(_result(key, fn.__name__, "error",
                                   f"check lỗi: {type(e).__name__}: {e}"))
    return results


# ── report / persist ─────────────────────────────────────────────────────────


def worst_status(results: list[dict]) -> str:
    return max((r["status"] for r in results),
               key=lambda s: _SEVERITY.get(s, 3), default="ok")


def format_report(results: list[dict], net: bool = False) -> str:
    lines = ["🩺 vnstock doctor — sức khỏe nguồn dữ liệu",
             "=" * 46,
             "✅ ok · ⚠️ cũ/thiếu một phần · ⬜ chưa cấu hình/chưa chạy · ❌ hỏng",
             ""]
    for r in results:
        lines.append(f"  {_ICONS.get(r['status'], '?')} {r['name']} — {r['message']}")
        if r.get("fix"):
            lines.append(f"       ↳ sửa: {r['fix']}")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in _ICONS}
    lines.append("")
    lines.append("Tổng: " + " · ".join(
        f"{counts[s]} {_ICONS[s]}" for s in ("ok", "warn", "off", "error") if counts[s]))
    if not net:
        lines.append("(offline — thêm --net trên máy có mạng để probe "
                     "RSS/FX/VBMA/NSO/API/Jina)")
    return "\n".join(lines)


def write_status(results: list[dict], mode: str) -> "Path | None":
    """Ghi doctor_status.json cho badge sidebar. Best-effort."""
    try:
        from vnstock_rollup import get_hostname
        machine = get_hostname()
    except Exception:
        machine = os.environ.get("COMPUTERNAME") or "?"
    payload = {
        "ran_at": datetime.now().isoformat(),
        "machine": machine,          # badge đi qua Dropbox — máy nào khám (hệ quả #2)
        "mode": mode,
        "counts": {s: sum(1 for r in results if r["status"] == s) for s in _ICONS},
        "worst": worst_status(results),
        "checks": results,
    }
    try:
        out = _META / _STATUS_NAME
        from vnstock_parquet_io import write_json_atomic
        write_json_atomic(payload, out)
        return out
    except OSError:
        return None


def main(argv: "list[str] | None" = None) -> int:
    # .env trước khi check key (mirror generate_brief._ensure_env_loaded)
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Khám sức khỏe nguồn dữ liệu (doctor).")
    ap.add_argument("--net", action="store_true",
                    help="Thêm probe mạng (RSS/FX/VBMA/NSO/foreign-flow/Jina) — chậm hơn")
    ap.add_argument("--json", action="store_true", help="In JSON thay vì text")
    ap.add_argument("--no-save", action="store_true",
                    help="Không ghi doctor_status.json (badge sidebar)")
    a = ap.parse_args(argv)

    results = run_checks(net=a.net)
    mode = "net" if a.net else "offline"
    if not a.no_save:
        write_status(results, mode)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_report(results, net=a.net))
    return 1 if worst_status(results) in ("warn", "error") else 0


if __name__ == "__main__":
    sys.exit(main())

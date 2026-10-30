"""Thanh trạng thái trên MỌI trang (thiết kế lại giao diện P2, `docs/THIET-KE-GIAO-DIEN.md` §5b).

Phần thuần (phiên giao dịch, gộp mức trạng thái, đọc 3 file badge) tách khỏi phần vẽ để
test được không cần Streamlit. Vẽ ở `render_status_strip()` — Streamlit import LƯỜI.

Gộp 3 badge cũ của sidebar (tests · doctor · ladder model) thành MỘT chấm: đỏ nếu có một
cái đỏ — giữ quy tắc "badge tests đỏ = KHÔNG merge/deploy" (CLAUDE.md).
"""
from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path

META = Path("data_warehouse/_meta")
_ORDER = {"error": 3, "warn": 2, "ok": 1, "off": 0}

# Giờ giao dịch HOSE. Không biết lịch nghỉ lễ ⇒ ngày lễ vẫn ghi theo giờ (nhãn là
# GỢI Ý trạng thái phiên, không phải nguồn sự thật — dữ liệu phiên nào thì xem ô "Dữ liệu").
_PHASES = (
    (time(9, 0), "pre", "Chưa mở cửa"),
    (time(11, 30), "open", "Đang khớp lệnh"),
    (time(13, 0), "lunch", "Nghỉ trưa"),
    (time(14, 30), "open", "Đang khớp lệnh"),
    (time(14, 45), "atc", "ATC"),
    (time(15, 0), "pt", "Thoả thuận"),
)


def session_phase(now: datetime) -> tuple[str, str]:
    """(khoá, nhãn) của phiên tại `now` theo giờ HOSE."""
    if now.weekday() >= 5:
        return "weekend", "Nghỉ cuối tuần"
    t = now.time()
    for end, key, label in _PHASES:
        if t < end:
            return key, label
    return "closed", "Đã đóng cửa"


def worst_level(levels) -> str:
    """Mức nặng nhất trong ok/warn/error/off (lạ ⇒ off)."""
    norm = [lv if lv in _ORDER else "off" for lv in levels]
    return max(norm, key=_ORDER.__getitem__) if norm else "off"


def _read(path: Path) -> dict | None:
    """None = chưa có file; ném lỗi = file hỏng (chỗ gọi báo 'không đọc được')."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _age(ran_at: str, now: datetime) -> str:
    try:
        d = (now - datetime.fromisoformat(ran_at)).days
    except (TypeError, ValueError):
        return "?"
    return f"{d}d trước" if d > 0 else "hôm nay"


def system_items(meta: Path = META, now: datetime | None = None) -> list[dict]:
    """3 dòng trạng thái {name, level, text, sub}. File hỏng ⇒ level warn + nói rõ."""
    now = now or datetime.now()
    items = []

    def add(name, fname, build):
        # Hỏng ở BẤT KỲ khâu nào (đọc, JSON lạ như `[]`, trường sai kiểu) ⇒ dòng "warn" nói rõ.
        # Thanh trạng thái vẽ trên MỌI trang: ném ra ở đây là sập cả trang Hệ thống — nơi
        # cần vào để bấm 📥 (review P2, 31/10).
        try:
            data = _read(meta / fname)
            if data is not None and not isinstance(data, dict):
                raise ValueError(f"không phải object JSON ({type(data).__name__})")
            items.append(build(data))
        except Exception as e:  # noqa: BLE001 — badge phải sống dù file lạ cỡ nào
            items.append({"name": name, "level": "warn",
                          "text": f"không đọc được {fname}", "sub": type(e).__name__})

    def tests(d):
        if d is None:
            return {"name": "Tests", "level": "off", "text": "chưa chạy",
                    "sub": "python run.py test --fast"}
        bad = int(d.get("failed", 0) or 0) + int(d.get("errors", 0) or 0)
        # pytest thoát ≠ 0 mà không parse ra số fail ("no tests ran", lỗi nội bộ) vẫn là ĐỎ —
        # chấm gộp là chỗ duy nhất còn lại cho quy tắc "đỏ = KHÔNG merge" (review P2).
        crashed = int(d.get("exit_code", 0) or 0) not in (0,) and not bad
        text = f"{d.get('mode', '?')}: {d.get('passed', 0)} passed" + (f", {bad} fail" if bad else "")
        if crashed:
            text += f" · pytest thoát mã {d.get('exit_code')}"
        return {"name": "Tests", "level": "error" if (bad or crashed) else "ok", "text": text,
                "sub": f"Chạy {_age(d.get('ran_at', ''), now)} · {d.get('elapsed_s', '?')}s"}

    def doctor(d):
        if d is None:
            return {"name": "Nguồn dữ liệu", "level": "off", "text": "chưa khám",
                    "sub": "python run.py doctor"}
        c = d.get("counts", {}) or {}
        parts = [f"{c[k]} {lbl}" for k, lbl in (("ok", "ổn"), ("warn", "cảnh báo"),
                                                ("off", "tắt"), ("error", "lỗi")) if c.get(k)]
        return {"name": "Nguồn dữ liệu", "level": worst_level([d.get("worst", "ok")]),
                "text": " · ".join(parts) or "?",
                "sub": f"Khám {_age(d.get('ran_at', ''), now)} · {d.get('machine', '?')} · {d.get('mode', '?')}"}

    def models(d):
        if d is None:
            return {"name": "Ladder model", "level": "off", "text": "chưa soi",
                    "sub": "python run.py models"}
        lvl = {"green": "ok", "warn": "warn", "red": "error"}.get(d.get("level"), "off")
        probe = d.get("probe") or {}
        gone = len((d.get("catalog") or {}).get("gone_in_use", []))
        ripe = sum(1 for p in (d.get("proposals") or []) if p.get("ripe"))
        slow = len((d.get("latency") or {}).get("slow", []))
        bits = [f"{probe.get('ok', 0)} ổn"]
        bits += [f"{probe['fail']} lỗi"] if probe.get("fail") else []
        bits += [f"{gone} đang dùng bị gỡ"] if gone else []
        bits += [f"{slow} chậm bất thường"] if slow else []
        bits += [f"{ripe} đề xuất"] if ripe else []
        return {"name": "Ladder model", "level": lvl, "text": " · ".join(bits),
                "sub": f"Soi {_age(d.get('ran_at', ''), now)}"}

    add("Tests", "test_status.json", tests)
    add("Nguồn dữ liệu", "doctor_status.json", doctor)
    add("Ladder model", "model_status.json", models)
    return items


def index_change(closes) -> tuple[float, float, float] | None:
    """(đóng cửa, đổi điểm, đổi %) từ chuỗi đóng cửa tăng dần; thiếu 2 phiên ⇒ None."""
    vals = [float(v) for v in (closes or []) if v is not None and v == v]
    if len(vals) < 2 or vals[-2] == 0:
        return None
    last, prev = vals[-1], vals[-2]
    return last, last - prev, (last / prev - 1) * 100


def fmt_signed(v: float, digits: int = 2) -> str:
    """'+1.23' / '-1.23' — số kiểu EN như quy ước."""
    return f"{v:+,.{digits}f}"

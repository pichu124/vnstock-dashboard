"""Chụp ảnh từng trang dashboard để so trước/sau mỗi pha thiết kế lại giao diện.

Dùng (○ máy nào cũng được — kho Dropbox nào cũng như nhau, nhưng CHỤP Ở MỘT MÁY):
    python scripts/ui_snapshots.py --label before      # tự bật dashboard ở cổng 8599
    python scripts/ui_snapshots.py --label after
    python scripts/ui_snapshots.py --url http://localhost:8501 --label now   # dashboard đang chạy

Ảnh ra `ui_snapshots/<label>/NN-<trang>.png` ở gốc repo (gitignore — KHÔNG để trong
`data_warehouse`, khỏi đi Dropbox). Cần Playwright:
    pip install playwright
    python -m playwright install chromium

Chỉ ĐỌC: không bấm nút nào ngoài thanh điều hướng, không bật Live Mode.
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "vnstock_dashboard.py"
# Lưới cuối nếu không đọc được danh sách tab từ code.
_FALLBACK_TABS = ["📊 Screener", "🔬 Phân tích", "🌏 Thị trường", "🗞️ Tin tức", "💰 Dòng Tiền",
                  "📑 Phái sinh NN", "💱 Hàng hoá & Tiền tệ", "💼 Portfolio", "⚕️ Sức khỏe"]


def nav_labels(source: str) -> list[str]:
    """Đọc `_TAB_OPTIONS = [...]` trong vnstock_dashboard.py — không import (import là dựng UI)."""
    m = re.search(r"_TAB_OPTIONS\s*=\s*\[(.*?)\]", source, re.S)
    if not m:
        return list(_FALLBACK_TABS)
    labels = re.findall(r'"([^"]+)"', m.group(1))
    return labels or list(_FALLBACK_TABS)


def slug(label: str) -> str:
    """'💱 Hàng hoá & Tiền tệ' → 'hang-hoa-tien-te' (bỏ emoji + dấu, tên file an toàn)."""
    s = unicodedata.normalize("NFD", label.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn" and ord(c) < 128)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "trang"


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch(port: int) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "streamlit", "run", str(DASHBOARD), "--server.headless", "true",
           "--server.port", str(port), "--browser.gatherUsageStats", "false"]
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    deadline = time.time() + 60
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return proc
        if proc.poll() is not None:
            raise SystemExit(f"Dashboard thoát sớm (mã {proc.returncode}) — chạy tay "
                             f"`python run.py dashboard` xem lỗi.")
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("Dashboard không mở cổng sau 60s.")


def nav_text(label: str) -> str:
    """Phần CHỮ của nhãn: nút pills vẽ emoji và chữ thành hai khối ("📊\n\nScreener")."""
    head, _, rest = label.partition(" ")
    return rest if rest and not any(c.isalnum() for c in head) else label


def nav_button(page, label: str):
    """Nút điều hướng hiện tại (`st.pills`); P2 chuyển `st.navigation` thì thêm nhánh ở đây."""
    return page.locator('button[data-testid^="stBaseButton-pills"]').filter(has_text=nav_text(label))


def _wait_idle(page, settle_s: float) -> None:
    """Đợi Streamlit chạy xong lượt (hết biểu tượng "Running…") rồi đợi thêm cho chart vẽ."""
    page.wait_for_selector('[data-testid="stApp"]', timeout=60_000)
    deadline = time.time() + 90
    while time.time() < deadline:
        if not page.locator('[data-testid="stStatusWidget"]').is_visible():
            break
        time.sleep(0.5)
    time.sleep(settle_s)


def _shoot_full(page, path: Path, width: int, height: int, settle_s: float) -> None:
    """Chụp HẾT trang. Streamlit cuộn bên trong `stMain`, không cuộn `body` ⇒
    `full_page=True` chỉ ra đúng một màn hình (reviewer đo 31/10: scrollHeight 6.555 vs
    ảnh 900). Nới viewport bằng chiều cao nội dung rồi chụp, xong trả lại."""
    h = page.evaluate("(() => { const m = document.querySelector('[data-testid=\"stMain\"]');"
                      " return m ? m.scrollHeight : document.body.scrollHeight; })()")
    full = max(height, min(int(h or height), 16_000))
    if full > height:
        page.set_viewport_size({"width": width, "height": full})
        time.sleep(min(settle_s, 3.0))
    page.screenshot(path=str(path))
    if full > height:
        page.set_viewport_size({"width": width, "height": height})


def snapshot(url: str, out: Path, settle_s: float, width: int, height: int,
             scheme: str = "dark") -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Thiếu Playwright: pip install playwright && python -m playwright install chromium")
    labels = nav_labels(DASHBOARD.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Chế độ sáng/tối của HỆ ĐIỀU HÀNH quyết định theme Streamlit khi config chưa ghim.
        page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
        page.goto(url)
        _wait_idle(page, settle_s)
        for i, label in enumerate(labels, 1):
            btn = nav_button(page, label)
            if btn.count() == 0:
                print(f"  ⚠ không thấy nút điều hướng {label!r} — bỏ qua")
                continue
            btn.first.click()
            _wait_idle(page, settle_s)
            path = out / f"{i:02d}-{slug(label)}.png"
            _shoot_full(page, path, width, height, settle_s)
            saved.append(path)
            print(f"  ✓ {path.relative_to(REPO)}")
        browser.close()
    return saved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default="now", help="tên thư mục ảnh: before / after / now…")
    ap.add_argument("--url", help="dashboard đang chạy (bỏ trống = tự bật ở cổng 8599)")
    ap.add_argument("--settle", type=float, default=6.0, help="giây đợi thêm mỗi trang (chart vẽ)")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--scheme", choices=("dark", "light"), default="dark",
                    help="giả lập hệ điều hành đang ở chế độ tối/sáng")
    a = ap.parse_args(argv)

    out = REPO / "ui_snapshots" / slug(a.label)
    proc = None
    url = a.url
    if not url:
        port = _free_port(8599)
        proc = _launch(port)
        url = f"http://localhost:{port}"
    try:
        print(f"Chụp {url} → {out.relative_to(REPO)}")
        saved = snapshot(url, out, a.settle, a.width, a.height, a.scheme)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=15)
    print(f"Xong: {len(saved)} ảnh.")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())

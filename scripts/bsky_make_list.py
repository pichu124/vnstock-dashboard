"""Tạo (hoặc bổ sung) Bluesky List từ `docs/bluesky-macro-list.md` — khỏi thêm tay (02/10/2026, #31).

Dùng trên máy có mạng (🖥️ desktop — `--write-env` ghi `.env` của máy đang chạy):

    python scripts/bsky_make_list.py --check              # KHÔNG đăng nhập: handle nào tồn tại, tên, bài cuối
    python scripts/bsky_make_list.py --write-env          # đăng nhập → tạo List → thêm nhóm ⭐ → ghi .env
    python scripts/bsky_make_list.py --all --write-env    # thêm cả bảng (trừ độ tin cậy "thấp" và ⛔)
    python scripts/bsky_make_list.py --browse             # List RIÊNG cả bảng để đọc thử, KHÔNG đụng .env

Đăng nhập bằng **App Password** (Bluesky → Settings → Privacy and security → App
passwords), KHÔNG dùng mật khẩu chính. Mật khẩu nhập qua `getpass`, không lưu đâu
cả; muốn chạy không hỏi thì đặt `BSKY_HANDLE` + `BSKY_APP_PASSWORD` trong môi
trường của phiên shell (đừng ghi vào `.env`). Xong có thể thu hồi App Password.

Chạy lại an toàn: List cùng tên đã có thì dùng lại, chỉ thêm người CHƯA có. Handle
không tồn tại / không resolve được thì bỏ qua và in tên để sửa bảng. Tên hiển thị
lệch hẳn với tên trong bảng ⇒ in ⚠️ (có thể là tài khoản giả trùng handle).

Chỉ dùng API công khai của giao thức AT: `app.bsky.actor.getProfiles` /
`getAuthorFeed` / `graph.getLists` / `graph.getList` (không auth) và
`com.atproto.server.createSession` + `com.atproto.repo.createRecord` (bản ghi
`app.bsky.graph.list` / `app.bsky.graph.listitem`) trên PDS của user.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MD = REPO / "docs" / "bluesky-macro-list.md"
PUBLIC_API = "https://public.api.bsky.app/xrpc/"
DEFAULT_PDS = "https://bsky.social"
DEFAULT_NAME = "Vĩ mô VN — cảnh báo tin"
DEFAULT_DESC = ("Chuyên gia, phóng viên, định chế ảnh hưởng thị trường chứng khoán Việt Nam: "
                "Fed/vĩ mô Mỹ, thị trường, châu Á/thương mại, năng lượng, địa chính trị.")
BROWSE_NAME = "Vĩ mô — đọc thử (đầy đủ)"
BROWSE_DESC = ("Danh sách đầy đủ để đọc thử trước khi chọn người theo dõi — KHÔNG dùng cho "
               "cảnh báo tin (list đó chỉ giữ nhóm ⭐).")
ENV_KEY = "VNSTOCK_NEWS_ALERT_BSKY_LIST"
ENV_HANDLES_KEY = "VNSTOCK_NEWS_ALERT_BSKY_HANDLES"
TIMEOUT_S = 20
PROFILES_BATCH = 25            # getProfiles nhận tối đa 25 actor/lần
UA = "vnstock-dashboard/bsky_make_list (+private use)"


# ── Đọc bảng ─────────────────────────────────────────────────────────────────

_HANDLE_CELL_RE = re.compile(r"`([^`]+)`")


def parse_md(path: Path, starred_only: bool = True, include_low: bool = False) -> list:
    """Hàng bảng markdown `| ⭐ | Tên | [`handle`](url) | … | Hoạt động | Tin cậy |`
    → [{name, handle, starred, confidence}]. Không trùng handle, giữ thứ tự file.
    Cột đầu `⛔` = KHÔNG BAO GIỜ đưa vào List, kể cả `--all` (tài khoản hãng tin
    đăng hàng chục bài/giờ — chiếm hết suất bài Bluesky mỗi lượt, đã có qua RSS)."""
    out, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| | Tên") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        m = _HANDLE_CELL_RE.search(cells[2])
        if not m:
            continue
        handle = m.group(1).strip().lstrip("@").lower()
        starred = cells[0] == "⭐"
        conf = cells[-1]
        if cells[0] == "⛔":
            continue
        if handle in seen or (starred_only and not starred):
            continue
        if not starred and conf == "thấp" and not include_low:
            continue
        seen.add(handle)
        out.append({"name": cells[1], "handle": handle, "starred": starred, "confidence": conf})
    return out


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _req(method: str, url: str, *, params=None, json_body=None, token: Optional[str] = None):
    import requests
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(2):
        resp = requests.request(method, url, params=params, json=json_body, headers=headers,
                                timeout=TIMEOUT_S)
        if resp.status_code == 429 and attempt == 0:
            wait = int(resp.headers.get("Retry-After") or 5)
            time.sleep(min(max(wait, 1), 60))
            continue
        break
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("message") or resp.json().get("error") or resp.text[:200]
        except ValueError:
            detail = resp.text[:200]
        raise RuntimeError(f"HTTP {resp.status_code} {url.rsplit('/', 1)[-1]}: {detail}")
    return resp.json() if resp.content else {}


def _get(method_name: str, params: dict, base: str = PUBLIC_API, token: Optional[str] = None) -> dict:
    return _req("GET", base + method_name, params=params, token=token)


def _post(method_name: str, body: dict, base: str, token: Optional[str] = None) -> dict:
    return _req("POST", base + method_name, json_body=body, token=token)


# ── Xác minh (không cần đăng nhập) ───────────────────────────────────────────


def get_profiles(handles: list) -> dict:
    """{handle_thường: profile} cho handle resolve được; handle sai/đổi tên vắng mặt."""
    out: dict = {}
    for i in range(0, len(handles), PROFILES_BATCH):
        batch = handles[i:i + PROFILES_BATCH]
        data = _get("app.bsky.actor.getProfiles", {"actors": batch})
        for p in data.get("profiles") or []:
            h = str(p.get("handle") or "").lower()
            if h:
                out[h] = p
    return out


def last_post_at(actor: str) -> str:
    try:
        data = _get("app.bsky.feed.getAuthorFeed",
                    {"actor": actor, "limit": 1, "filter": "posts_no_replies"})
    except Exception:
        return ""
    feed = data.get("feed") or []
    if not feed:
        return ""
    rec = ((feed[0].get("post") or {}).get("record") or {})
    return str(rec.get("createdAt") or "")[:10]


def _tokens(s: str) -> set:
    t = unicodedata.normalize("NFKD", str(s or "")).lower()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return {w for w in re.split(r"[^a-z0-9]+", t) if len(w) >= 3}


def name_mismatch(expected: str, profile: dict) -> bool:
    """Tên trong bảng và tên hiển thị/handle không chung từ nào (≥3 ký tự) ⇒ nghi."""
    exp = _tokens(re.sub(r"\(.*?\)", " ", expected)) - {"the", "and", "news", "official"}
    if not exp:
        return False
    got = _tokens(profile.get("displayName")) | _tokens(profile.get("handle"))
    return not (exp & got)


def check(rows: list, with_activity: bool = True) -> "tuple[list, list]":
    """(tìm thấy [(row, profile, last_post)], không thấy [row])."""
    profiles = get_profiles([r["handle"] for r in rows])
    found = [(r, profiles[r["handle"]]) for r in rows if r["handle"] in profiles]
    missing = [r for r in rows if r["handle"] not in profiles]
    lasts: dict = {}
    if with_activity and found:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for (r, p), last in zip(found, pool.map(lambda rp: last_post_at(rp[1].get("did")), found)):
                lasts[r["handle"]] = last
    return [(r, p, lasts.get(r["handle"], "")) for r, p in found], missing


def print_check(found: list, missing: list) -> None:
    print(f"{'handle':38s} {'tên hiển thị':30s} {'follower':>9s} {'bài':>7s}  bài cuối")
    for r, p, last in found:
        warn = "  ⚠️ tên lệch bảng" if name_mismatch(r["name"], p) else ""
        print(f"{r['handle']:38s} {str(p.get('displayName') or '')[:30]:30s} "
              f"{int(p.get('followersCount') or 0):>9,d} {int(p.get('postsCount') or 0):>7,d}  "
              f"{last or '—'}{warn}")
    for r in missing:
        print(f"{r['handle']:38s} ❌ không tồn tại / đã đổi handle — sửa bảng ({r['name']})")
    print(f"\n{len(found)}/{len(found) + len(missing)} handle tồn tại.")


# ── Ghi List (cần đăng nhập) ─────────────────────────────────────────────────


def normalize_identifier(raw: str) -> str:
    """Handle người dùng gõ → dạng `createSession` nhận: bỏ `@` đầu, chữ thường;
    tên trần (không dấu chấm) ⇒ thêm `.bsky.social`; email giữ nguyên."""
    s = (raw or "").strip()
    if "@" in s.lstrip("@"):
        return s                                         # email cũng đăng nhập được
    s = s.lstrip("@").lower()
    return s + ".bsky.social" if s and "." not in s else s


def check_identifier(ident: str) -> None:
    """Handle phải resolve được (API công khai) TRƯỚC khi hỏi mật khẩu — 04/10 user
    gõ `pichu124.bsky.socia` ba lần, 401 chung chung khiến tưởng sai App Password.
    Chỉ chặn khi API nói rõ không resolve được (HTTP 400); lỗi khác ⇒ để login quyết."""
    if not ident:
        raise RuntimeError("chưa nhập handle")
    if "@" in ident:
        return
    try:
        _get("com.atproto.identity.resolveHandle", {"handle": ident})
    except RuntimeError as e:
        if "HTTP 400" not in str(e):
            return
        hint = ""
        if "bsky" in ident and not ident.endswith(".bsky.social"):
            hint = f" — ý bạn là {ident.split('.bsky')[0]}.bsky.social?"
        raise RuntimeError(f"handle '{ident}' không tồn tại trên Bluesky{hint} "
                           "(handle đầy đủ ở trang cá nhân trong app, dưới tên hiển thị)")


def ask_identifier(tries: int = 3) -> str:
    """Handle từ env `BSKY_HANDLE` (kiểm một lần) hoặc hỏi lại tới `tries` lần."""
    env = normalize_identifier(os.environ.get("BSKY_HANDLE") or "")
    if env:
        check_identifier(env)
        return env
    for attempt in range(tries):
        ident = normalize_identifier(input("Handle Bluesky của bạn (vd ten.bsky.social): "))
        try:
            check_identifier(ident)
            return ident
        except RuntimeError as e:
            if attempt == tries - 1:
                raise
            print(f"  ❌ {e}")
    raise RuntimeError("chưa nhập handle")


APP_PW_RE = re.compile(r"^[a-z0-9]{4}(-[a-z0-9]{4}){3}$")
READ_HOST_HINT = ("$s = Read-Host 'App Password' -AsSecureString; $env:BSKY_APP_PASSWORD = "
                  "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                  "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))")


def normalize_app_password(pw: str) -> str:
    """Gõ tay hay bỏ/thay dấu `-` (04/10: user gõ 16 ký tự liền). Chỉ đụng khi bỏ
    `-`/khoảng trắng ra đúng 16 ký tự a-z0-9 — mật khẩu khác giữ nguyên."""
    bare = re.sub(r"[\s-]", "", pw or "")
    if re.fullmatch(r"[a-z0-9]{16}", bare):
        return "-".join(bare[i:i + 4] for i in range(0, 16, 4))
    return (pw or "").strip()


def password_shape(pw: str) -> str:
    """Mô tả mật khẩu NHẬN ĐƯỢC mà không lộ nó: độ dài + có đúng dạng App Password
    `xxxx-xxxx-xxxx-xxxx` không. 04/10: ô getpass ẩn trên Windows, user dán ba lần
    vẫn 401 mà không biết đã dán được gì."""
    if APP_PW_RE.match(pw or ""):
        return f"{len(pw)} ký tự, ĐÚNG dạng App Password xxxx-xxxx-xxxx-xxxx"
    ctrl = sum(1 for c in (pw or "") if ord(c) < 32)
    extra = f", có {ctrl} ký tự điều khiển (Ctrl+V không dán vào ô ẩn mà gõ ra ^V)" if ctrl else ""
    return f"{len(pw or '')} ký tự, KHÔNG đúng dạng App Password xxxx-xxxx-xxxx-xxxx{extra}"


def login(pds: str, identifier: str, password: str) -> dict:
    try:
        sess = _post("com.atproto.server.createSession",
                     {"identifier": identifier, "password": password}, base=pds.rstrip("/") + "/xrpc/")
    except RuntimeError as e:
        if "401" in str(e) or "AuthenticationRequired" in str(e):
            if APP_PW_RE.match(password or ""):
                why = ("mật khẩu đúng dạng App Password mà vẫn bị từ chối ⇒ nó đã bị xoá/thu hồi, "
                       "hoặc tạo ở TÀI KHOẢN KHÁC — tạo cái mới khi đang đăng nhập đúng "
                       f"{identifier} (Settings → Privacy and security → App passwords)")
            else:
                why = ("dán hỏng — nhập lại qua ô CÓ dấu *: " + READ_HOST_HINT +
                       " (đếm đủ 19 dấu *), rồi chạy lại script")
            raise RuntimeError(f"đăng nhập thất bại cho {identifier} — mật khẩu nhận được "
                               f"{password_shape(password)}; {why}")
        raise
    return {"did": sess["did"], "handle": sess.get("handle") or identifier,
            "token": sess["accessJwt"], "xrpc": pds.rstrip("/") + "/xrpc/"}


def find_list(owner_did: str, name: str) -> Optional[str]:
    cursor = None
    for _ in range(20):
        params = {"actor": owner_did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("app.bsky.graph.getLists", params)
        for lst in data.get("lists") or []:
            if str(lst.get("name") or "").strip() == name.strip():
                return lst.get("uri")
        cursor = data.get("cursor")
        if not cursor:
            return None
    return None


def list_members(list_uri: str) -> dict:
    """{did: {"uri": URI bản ghi listitem, "handle": handle}} — URI cần để GỠ (`--prune`)."""
    out, cursor = {}, None
    for _ in range(50):
        params = {"list": list_uri, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("app.bsky.graph.getList", params)
        for it in data.get("items") or []:
            subj = (it or {}).get("subject") or {}
            if subj.get("did"):
                out[subj["did"]] = {"uri": str((it or {}).get("uri") or ""),
                                    "handle": str(subj.get("handle") or subj["did"])}
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


def list_member_dids(list_uri: str) -> set:
    return set(list_members(list_uri))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def create_list(sess: dict, name: str, description: str) -> str:
    rec = {"$type": "app.bsky.graph.list", "purpose": "app.bsky.graph.defs#curatelist",
           "name": name[:64], "description": description[:300], "createdAt": _now_iso()}
    res = _post("com.atproto.repo.createRecord",
                {"repo": sess["did"], "collection": "app.bsky.graph.list", "record": rec},
                base=sess["xrpc"], token=sess["token"])
    return res["uri"]


def remove_member(sess: dict, listitem_uri: str) -> None:
    """Xoá MỘT bản ghi listitem của chính user (URI phải thuộc repo của phiên đăng nhập)."""
    prefix = f"at://{sess['did']}/app.bsky.graph.listitem/"
    if not listitem_uri.startswith(prefix):
        raise RuntimeError(f"không gỡ bản ghi ngoài repo của bạn: {listitem_uri}")
    _post("com.atproto.repo.deleteRecord",
          {"repo": sess["did"], "collection": "app.bsky.graph.listitem",
           "rkey": listitem_uri[len(prefix):]},
          base=sess["xrpc"], token=sess["token"])


def add_member(sess: dict, list_uri: str, did: str) -> None:
    rec = {"$type": "app.bsky.graph.listitem", "subject": did, "list": list_uri,
           "createdAt": _now_iso()}
    _post("com.atproto.repo.createRecord",
          {"repo": sess["did"], "collection": "app.bsky.graph.listitem", "record": rec},
          base=sess["xrpc"], token=sess["token"])


def list_url(owner_handle: str, list_uri: str) -> str:
    return f"https://bsky.app/profile/{owner_handle}/lists/{list_uri.rsplit('/', 1)[-1]}"


def update_env(env_path: Path, key: str, value: str) -> str:
    """Đặt `key=value` trong .env (thay dòng cũ nếu có, không thì thêm cuối).
    Trả 'added' | 'updated' | 'same'. Giữ nguyên mọi dòng khác."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    new_line = f"{key}={value}"
    for i, ln in enumerate(lines):
        if ln.strip().startswith("#"):
            continue
        k, sep, _ = ln.partition("=")
        if sep and k.strip() == key:
            if ln.strip() == new_line:
                return "same"
            lines[i] = new_line
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "updated"
    lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "added"


def _env_has(env_path: Path, key: str) -> bool:
    if not env_path.exists():
        return False
    for ln in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = ln.partition("=")
        if sep and not ln.strip().startswith("#") and k.strip() == key and v.strip():
            return True
    return False


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Tạo Bluesky List từ docs/bluesky-macro-list.md")
    ap.add_argument("--check", action="store_true", help="chỉ xác minh handle (không đăng nhập, không ghi)")
    ap.add_argument("--all", action="store_true", help="cả bảng thay vì chỉ nhóm ⭐")
    ap.add_argument("--include-low", action="store_true", help="kèm handle độ tin cậy 'thấp' (với --all)")
    ap.add_argument("--handles", default="", help="danh sách handle phẩy, thay cho file")
    ap.add_argument("--md", default=str(DEFAULT_MD))
    ap.add_argument("--name", default=DEFAULT_NAME, help="tên List (trùng tên ⇒ dùng lại)")
    ap.add_argument("--pds", default=DEFAULT_PDS)
    ap.add_argument("--write-env", action="store_true", help=f"ghi {ENV_KEY} vào .env của repo")
    ap.add_argument("--yes", action="store_true", help="không hỏi xác nhận trước khi ghi")
    ap.add_argument("--prune", action="store_true",
                    help="GỠ khỏi List những người không còn trong tập đích (vd hạ ⭐) — hỏi trước khi gỡ")
    ap.add_argument("--browse", action="store_true",
                    help=f"List RIÊNG '{BROWSE_NAME}' gồm cả bảng (như --all) để đọc thử trong app; "
                         "không bao giờ ghi .env — List cảnh báo tin giữ nguyên nhóm ⭐")
    a = ap.parse_args(argv)
    if a.browse:
        # Gộp cả bảng vào List cảnh báo thì suất 6 bài Bluesky/lượt rơi vào người đăng
        # nhiều nhất, nhóm ⭐ bị đẩy ra (04/10) ⇒ đọc thử ở List riêng.
        if a.write_env:
            print("--browse không ghi .env (List đọc thử không dùng cho cảnh báo tin) — bỏ --write-env.")
            return 2
        a.all = True
        if a.name == DEFAULT_NAME:
            a.name = BROWSE_NAME

    if a.handles:
        rows = [{"name": h, "handle": h.strip().lstrip("@").lower(), "starred": True, "confidence": "?"}
                for h in a.handles.split(",") if h.strip()]
    else:
        rows = parse_md(Path(a.md), starred_only=not a.all, include_low=a.include_low)
    if not rows:
        print("Không có handle nào để xử lý (kiểm --md / --handles).")
        return 1
    print(f"{len(rows)} handle từ {'--handles' if a.handles else Path(a.md).name}"
          f"{'' if a.all or a.handles else ' (nhóm ⭐)'} — đang xác minh qua API công khai…")

    found, missing = check(rows, with_activity=a.check)
    if a.check:
        print_check(found, missing)
        return 1 if missing else 0

    for r in missing:
        print(f"  ❌ bỏ qua {r['handle']} — không tồn tại / đã đổi handle")
    for r, p, _ in found:
        if name_mismatch(r["name"], p):
            print(f"  ⚠️ {r['handle']}: tên hiển thị '{p.get('displayName')}' lệch bảng '{r['name']}' "
                  f"— vẫn thêm; xoá trong app nếu là tài khoản giả")

    ident = ask_identifier()
    pw = normalize_app_password(os.environ.get("BSKY_APP_PASSWORD")
                                or getpass.getpass("App Password (không hiện khi gõ/dán): "))
    sess = login(a.pds, ident, pw)
    print(f"Đã đăng nhập: @{sess['handle']}")

    list_uri = find_list(sess["did"], a.name)
    members = list_members(list_uri) if list_uri else {}
    existing = set(members)
    todo = [(r, p) for r, p, _ in found if p.get("did") not in existing]
    wanted = {p.get("did") for _, p, _ in found}
    drop = {d: m for d, m in members.items() if d not in wanted} if a.prune else {}
    if a.prune and not found:
        print("--prune nhưng không resolve được ai trong tập đích — dừng để khỏi gỡ sạch List.")
        return 2
    print(f"List '{a.name}': {'đã có, ' + str(len(existing)) + ' thành viên' if list_uri else 'chưa có — sẽ tạo'}; "
          f"sẽ thêm {len(todo)} người" + (f", GỠ {len(drop)} người" if a.prune else "") + ".")
    for m in drop.values():
        print(f"  − sẽ gỡ {m['handle']}")
    if (todo or drop) and not a.yes:
        if input("Tiếp tục? [y/N] ").strip().lower() not in ("y", "yes", "c", "co", "có"):
            print("Huỷ — không ghi gì.")
            return 1

    if not list_uri:
        list_uri = create_list(sess, a.name, BROWSE_DESC if a.browse else DEFAULT_DESC)
        print(f"  ✅ tạo List {list_uri}")
    added, failed = 0, []
    for r, p in todo:
        try:
            add_member(sess, list_uri, p["did"])
            added += 1
            print(f"  + {r['handle']}")
        except Exception as e:                       # noqa: BLE001 — một người lỗi không dừng cả lượt
            failed.append(f"{r['handle']}: {e}")
        time.sleep(0.2)                              # lịch sự với PDS (giới hạn ~1.600 bản ghi/giờ)
    removed = 0
    for d, m in drop.items():
        try:
            remove_member(sess, m["uri"])
            removed += 1
            print(f"  − {m['handle']}")
        except Exception as e:                       # noqa: BLE001
            failed.append(f"gỡ {m['handle']}: {e}")
        time.sleep(0.2)
    url = list_url(sess["handle"], list_uri)
    print(f"\nXong: thêm {added}" + (f", gỡ {removed}" if a.prune else "") +
          f", lỗi {len(failed)}, bỏ qua {len(missing)} handle sai.")
    for f in failed:
        print(f"  ❌ {f}")
    print(f"URL List: {url}")
    if a.browse:
        print("List ĐỌC THỬ — KHÔNG dán vào .env (cảnh báo tin vẫn dùng List nhóm ⭐). Mở link trên "
              "trong app Bluesky → ⋯ → Pin to home để có tab riêng. Chọn ⭐ bằng số liệu: "
              "python scripts/bsky_eval.py → Claude sửa bảng → --write-env --prune.")
        return 1 if failed else 0

    env_path = REPO / ".env"
    if a.write_env:
        how = update_env(env_path, ENV_KEY, url)
        print(f".env: {ENV_KEY} {dict(added='đã thêm', updated='đã cập nhật', same='không đổi')[how]}")
    else:
        print(f"Dán vào .env (🖥️ desktop): {ENV_KEY}={url}  — hoặc chạy lại với --write-env")
    if _env_has(env_path, ENV_HANDLES_KEY):
        print(f"⚠️ .env còn {ENV_HANDLES_KEY} — List đã chứa họ, nên xoá dòng đó để khỏi gọi trùng.")
    print("Kiểm: python run.py news-alert --diag  (dòng bsky:analysts phải > 0 tin)")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"❌ {e}")
        raise SystemExit(2)
    except OSError as e:                         # requests.ConnectionError/ProxyError/Timeout đều là OSError
        print(f"❌ không gọi được Bluesky ({type(e).__name__}) — kiểm mạng/tường lửa, chạy lại trên máy có mạng")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nHuỷ.")
        raise SystemExit(130)

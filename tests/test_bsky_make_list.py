"""scripts/bsky_make_list.py — tạo Bluesky List từ docs/bluesky-macro-list.md (02/10).

Hermetic: `_req` giả theo tên method XRPC, `REPO` về tmp (không đụng .env thật),
mật khẩu qua env giả (không bao giờ hỏi getpass trong test)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bsky_make_list", _REPO / "scripts" / "bsky_make_list.py")
bml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bml)

MD = """# x

| | Tên | Handle | Vai trò | Vì sao | Hoạt động | Tin cậy |
|---|---|---|---|---|---|---|
| ⭐ | Nick Timiraos | [`nicktimiraos.bsky.social`](https://bsky.app/profile/nicktimiraos.bsky.social) | WSJ | Fed | 2026 | cao |
| | Greg Ip | [`gregip.bsky.social`](https://x) | WSJ | thuế | unknown | vừa |
| | Tom Orlik (?) | [`orlik69.bsky.social`](https://x) | ? | ? | unknown | thấp |
| ⭐ | Reuters | [`reuters.com`](https://x) | wire | tin | 2026 | cao |
| ⭐ | Nick again | [`NickTimiraos.bsky.social`](https://x) | dup | dup | 2026 | cao |
"""


@pytest.fixture
def md(tmp_path):
    p = tmp_path / "list.md"
    p.write_text(MD, encoding="utf-8")
    return p


# ── đọc bảng ─────────────────────────────────────────────────────────────────


def test_parse_md_starred_all_and_low(md):
    assert [r["handle"] for r in bml.parse_md(md)] == ["nicktimiraos.bsky.social", "reuters.com"]
    assert [r["handle"] for r in bml.parse_md(md, starred_only=False)] == \
        ["nicktimiraos.bsky.social", "gregip.bsky.social", "reuters.com"]            # bỏ "thấp"
    assert "orlik69.bsky.social" in [r["handle"] for r in bml.parse_md(md, False, include_low=True)]
    assert bml.parse_md(md)[0]["name"] == "Nick Timiraos"


def test_parse_real_doc_starter_set_is_the_24_starred():
    # --check desktop 04/10: 6 tài khoản ngừng đăng từ 2025 bỏ ⭐; 3 hãng tin thành ⛔.
    rows = bml.parse_md(bml.DEFAULT_MD)
    handles = {r["handle"] for r in rows}
    assert len(rows) == 24 and all(r["starred"] for r in rows)
    assert {"nicktimiraos.bsky.social", "claudia-sahm.bsky.social", "michaelpettis.bsky.social",
            "roryjohnston.bsky.social", "federalreserve.gov"} <= handles
    assert not handles & {"tracyalloway.bsky.social", "javierblas.bsky.social", "anaswanson.bsky.social"}
    every = bml.parse_md(bml.DEFAULT_MD, starred_only=False)
    assert len(every) > len(rows) and all(r["confidence"] != "thấp" for r in every if not r["starred"])
    wires = {"reuters.com", "bloomberg.com", "asia.nikkei.com"}
    assert not wires & {r["handle"] for r in every}                     # ⛔ không vào cả --all
    assert not wires & {r["handle"] for r in bml.parse_md(bml.DEFAULT_MD, False, include_low=True)}


def test_parse_md_blocked_rows_never_included(tmp_path):
    p = tmp_path / "l.md"
    p.write_text(MD + "| ⛔ | Wire | [`wire.com`](https://x) | wire | ồn | 2026 | cao |\n", encoding="utf-8")
    assert "wire.com" not in [r["handle"] for r in bml.parse_md(p, starred_only=False, include_low=True)]


@pytest.mark.parametrize("expected,profile,bad", [
    ("Nick Timiraos", {"displayName": "Nick Timiraos", "handle": "nicktimiraos.bsky.social"}, False),
    ("Federal Reserve Board", {"displayName": "Federal Reserve", "handle": "federalreserve.gov"}, False),
    ("Lisa Abramowicz", {"displayName": "Brian K", "handle": "briankillmeadew.bsky.social"}, True),
    ("Joseph Politano (Apricitas)", {"displayName": "Joey Politano", "handle": "josephpolitano.bsky.social"}, False),
    ("Reuters", {"displayName": "", "handle": "reuters.com"}, False),
])
def test_name_mismatch_flags_impostor_like_profiles(expected, profile, bad):
    assert bml.name_mismatch(expected, profile) is bad


# ── API giả ──────────────────────────────────────────────────────────────────


class FakeAPI:
    def __init__(self, known, lists=None, members=None, login_ok=True):
        self.known = known                       # handle → did
        self.lists = lists or []                 # [{"name", "uri"}]
        self.members = set(members or [])
        self.login_ok = login_ok
        self.calls: list = []
        self.created: list = []

    def __call__(self, method, url, *, params=None, json_body=None, token=None):
        name = url.rsplit("/", 1)[-1]
        self.calls.append((name, params, json_body, token))
        if name == "app.bsky.actor.getProfiles":
            return {"profiles": [{"handle": h, "did": self.known[h], "displayName": h.split(".")[0],
                                  "followersCount": 10, "postsCount": 5}
                                 for h in params["actors"] if h in self.known]}
        if name == "app.bsky.feed.getAuthorFeed":
            return {"feed": [{"post": {"record": {"createdAt": "2026-10-01T09:00:00Z"}}}]}
        if name == "com.atproto.identity.resolveHandle":
            h = params["handle"]
            if h in self.known or h in ("me.bsky.social", "pichu124.bsky.social"):
                return {"did": self.known.get(h, "did:plc:me")}
            raise RuntimeError("HTTP 400 com.atproto.identity.resolveHandle: Unable to resolve handle")
        if name == "com.atproto.server.createSession":
            if not self.login_ok:
                raise RuntimeError("HTTP 401 createSession: Invalid identifier or password")
            return {"did": "did:plc:me", "handle": "me.bsky.social", "accessJwt": "jwt"}
        if name == "app.bsky.graph.getLists":
            return {"lists": self.lists}
        if name == "app.bsky.graph.getList":
            return {"items": [{"subject": {"did": d}} for d in sorted(self.members)]}
        if name == "com.atproto.repo.createRecord":
            assert token == "jwt" and json_body["repo"] == "did:plc:me"
            self.created.append(json_body)
            rkey = f"r{len(self.created)}"
            return {"uri": f"at://did:plc:me/{json_body['collection']}/{rkey}", "cid": "c"}
        raise AssertionError(f"method lạ {name}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(bml, "REPO", tmp_path)
    monkeypatch.setattr(bml.time, "sleep", lambda s: None)
    monkeypatch.setenv("BSKY_HANDLE", "me.bsky.social")
    monkeypatch.setenv("BSKY_APP_PASSWORD", "app-pw")
    return tmp_path


def test_get_profiles_batches_by_25(monkeypatch):
    known = {f"u{i}.bsky.social": f"did:plc:{i}" for i in range(30)}
    api = FakeAPI(known)
    monkeypatch.setattr(bml, "_req", api)
    got = bml.get_profiles(list(known))
    assert len(got) == 30
    sizes = [len(p["actors"]) for n, p, _, _ in api.calls if n == "app.bsky.actor.getProfiles"]
    assert sizes == [25, 5]


def test_check_mode_needs_no_login_and_reports_missing(md, env, monkeypatch, capsys):
    api = FakeAPI({"nicktimiraos.bsky.social": "did:plc:n"})
    monkeypatch.setattr(bml, "_req", api)
    rc = bml.main(["--check", "--md", str(md)])
    out = capsys.readouterr().out
    assert rc == 1 and "reuters.com" in out and "❌ không tồn tại" in out and "2026-10-01" in out
    assert not any(n == "com.atproto.server.createSession" for n, *_ in api.calls)


def test_create_flow_makes_list_adds_members_and_writes_env(md, env, monkeypatch, capsys):
    api = FakeAPI({"nicktimiraos.bsky.social": "did:plc:n", "reuters.com": "did:plc:r"})
    monkeypatch.setattr(bml, "_req", api)
    (env / ".env").write_text("# keys\nTELEGRAM_CHAT_ID=1\n", encoding="utf-8")
    rc = bml.main(["--md", str(md), "--yes", "--write-env"])
    assert rc == 0
    lists = [c for c in api.created if c["collection"] == "app.bsky.graph.list"]
    items = [c for c in api.created if c["collection"] == "app.bsky.graph.listitem"]
    assert len(lists) == 1 and lists[0]["record"]["purpose"] == "app.bsky.graph.defs#curatelist"
    assert {i["record"]["subject"] for i in items} == {"did:plc:n", "did:plc:r"}
    assert all(i["record"]["list"] == "at://did:plc:me/app.bsky.graph.list/r1" for i in items)
    env_txt = (env / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_CHAT_ID=1" in env_txt and "# keys" in env_txt
    assert f"{bml.ENV_KEY}=https://bsky.app/profile/me.bsky.social/lists/r1" in env_txt
    assert "app-pw" not in capsys.readouterr().out                         # mật khẩu không bao giờ in


def test_rerun_reuses_list_and_adds_only_missing_members(md, env, monkeypatch):
    uri = "at://did:plc:me/app.bsky.graph.list/old"
    api = FakeAPI({"nicktimiraos.bsky.social": "did:plc:n", "reuters.com": "did:plc:r"},
                  lists=[{"name": bml.DEFAULT_NAME, "uri": uri}], members={"did:plc:n"})
    monkeypatch.setattr(bml, "_req", api)
    assert bml.main(["--md", str(md), "--yes"]) == 0
    assert [c["record"]["subject"] for c in api.created] == ["did:plc:r"]
    assert api.created[0]["record"]["list"] == uri


def test_declining_confirmation_writes_nothing(md, env, monkeypatch):
    api = FakeAPI({"nicktimiraos.bsky.social": "did:plc:n"})
    monkeypatch.setattr(bml, "_req", api)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert bml.main(["--md", str(md)]) == 1 and api.created == []


def test_bad_login_gives_app_password_hint(md, env, monkeypatch):
    monkeypatch.setattr(bml, "_req", FakeAPI({"reuters.com": "did:plc:r"}, login_ok=False))
    with pytest.raises(RuntimeError, match="App Password"):
        bml.main(["--md", str(md), "--yes"])


def test_update_env_add_update_same_and_ignores_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\n# VNSTOCK_NEWS_ALERT_BSKY_LIST=old-comment\n", encoding="utf-8")
    assert bml.update_env(p, "VNSTOCK_NEWS_ALERT_BSKY_LIST", "u1") == "added"
    assert bml.update_env(p, "VNSTOCK_NEWS_ALERT_BSKY_LIST", "u1") == "same"
    assert bml.update_env(p, "VNSTOCK_NEWS_ALERT_BSKY_LIST", "u2") == "updated"
    txt = p.read_text(encoding="utf-8").splitlines()
    assert txt == ["A=1", "# VNSTOCK_NEWS_ALERT_BSKY_LIST=old-comment", "VNSTOCK_NEWS_ALERT_BSKY_LIST=u2"]
    assert bml.update_env(tmp_path / "new.env", "K", "v") == "added"


def test_list_url_from_at_uri():
    assert bml.list_url("me.bsky.social", "at://did:plc:me/app.bsky.graph.list/3kxyz") == \
        "https://bsky.app/profile/me.bsky.social/lists/3kxyz"


@pytest.mark.parametrize("raw,want", [
    ("pichu124.bsky.social", "pichu124.bsky.social"), ("@Pichu124", "pichu124.bsky.social"),
    ("  chadpbown.com ", "chadpbown.com"), ("me@mail.com", "me@mail.com"), ("", "")])
def test_normalize_identifier(raw, want):
    assert bml.normalize_identifier(raw) == want


def test_typo_handle_stops_before_password_with_suggestion(md, env, monkeypatch):
    # Vết thật 04/10: `pichu124.bsky.socia` ×3 ⇒ 401 "sai handle hoặc App Password".
    api = FakeAPI({"reuters.com": "did:plc:r"})
    monkeypatch.setattr(bml, "_req", api)
    monkeypatch.setenv("BSKY_HANDLE", "pichu124.bsky.socia")
    monkeypatch.delenv("BSKY_APP_PASSWORD")
    monkeypatch.setattr(bml.getpass, "getpass", lambda *a, **k: pytest.fail("không được hỏi mật khẩu"))
    with pytest.raises(RuntimeError, match=r"ý bạn là pichu124\.bsky\.social\?"):
        bml.main(["--md", str(md), "--yes"])
    assert not any(n == "com.atproto.server.createSession" for n, *_ in api.calls)


def test_interactive_handle_reprompts_then_logs_in(md, env, monkeypatch, capsys):
    api = FakeAPI({"reuters.com": "did:plc:r"})
    monkeypatch.setattr(bml, "_req", api)
    monkeypatch.delenv("BSKY_HANDLE")
    answers = iter(["pichu124.bsky.socia", "pichu124"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert bml.main(["--md", str(md), "--yes"]) == 0
    assert "ý bạn là pichu124.bsky.social" in capsys.readouterr().out
    sess = [b for n, _, b, _ in api.calls if n == "com.atproto.server.createSession"]
    assert sess == [{"identifier": "pichu124.bsky.social", "password": "app-pw"}]


def test_resolve_endpoint_other_error_does_not_block(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("HTTP 501 com.atproto.identity.resolveHandle: not implemented")
    monkeypatch.setattr(bml, "_get", _boom)
    assert bml.check_identifier("someone.example.com") is None

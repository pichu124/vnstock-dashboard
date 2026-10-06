"""scripts/bsky_eval.py — chấm tài khoản Bluesky bằng số liệu 7 ngày (04/10).

Hermetic: `bml._get` giả theo actor (getAuthorFeed), `na.score_items_cli` giả theo
tiêu đề — không mạng, không Claude."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bsky_eval", _REPO / "scripts" / "bsky_eval.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)
bml, na = ev.bml, ev.na

NOW = datetime.now()


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).astimezone().isoformat()


def _entry(handle, rkey, text, hours_ago, reason=None):
    e = {"post": {"uri": f"at://did:plc:{handle}/app.bsky.feed.post/{rkey}",
                  "author": {"handle": handle},
                  "record": {"text": text, "createdAt": _ts(hours_ago)}}}
    if reason:
        e["reason"] = reason
    return e


LONG = " — and this is long enough to pass the sixty character minimum filter."


class FakeFeed:
    def __init__(self, pages):
        self.pages = pages               # {handle: [page1_entries, page2_entries]}
        self.calls = []

    def __call__(self, method, params, base=None, token=None):
        assert method == "app.bsky.feed.getAuthorFeed" and params["filter"] == "posts_no_replies"
        h = params["actor"]
        self.calls.append((h, params.get("cursor")))
        if h == "broken.bsky.social":
            raise RuntimeError("HTTP 400 getAuthorFeed: Profile not found")
        pages = self.pages.get(h, [[]])
        i = int(params.get("cursor") or 0)
        nxt = str(i + 1) if i + 1 < len(pages) else None
        return {"feed": pages[i], **({"cursor": nxt} if nxt else {})}


def test_author_posts_skips_reposts_pins_and_stops_at_window(monkeypatch):
    h = "sahm.bsky.social"
    old_pin = _entry(h, "pin", "Pinned old thread" + LONG, 24 * 60,
                     reason={"$type": "app.bsky.feed.defs#reasonPin"})
    rt = _entry("other.bsky.social", "rt", "Someone else's chart" + LONG, 5,
                reason={"$type": "app.bsky.feed.defs#reasonRepost", "indexedAt": _ts(2)})
    page1 = [old_pin, rt, _entry(h, "a", "Payrolls beat" + LONG, 3), _entry(h, "b", "short", 10)]
    page2 = [_entry(h, "c", "Older but in window" + LONG, 24 * 5),
             _entry(h, "d", "Too old" + LONG, 24 * 9)]
    feed = FakeFeed({h: [page1, page2, [_entry(h, "e", "never fetched" + LONG, 1)]]})
    monkeypatch.setattr(bml, "_get", feed)
    since = (NOW - timedelta(days=7)).isoformat(timespec="seconds")
    got = ev.author_posts(h, since)
    assert [p["link"].rsplit("/", 1)[-1] for p in got["posts"]] == ["a", "b", "c"]
    assert got["reposts"] == 1
    assert [c[1] for c in feed.calls] == [None, "1"]                # dừng khi chạm bài cũ


def test_fetch_all_isolates_errors(monkeypatch):
    monkeypatch.setattr(bml, "_get", FakeFeed({"ok.bsky.social": [[_entry("ok.bsky.social", "a", "x" + LONG, 1)]]}))
    since = (NOW - timedelta(days=7)).isoformat(timespec="seconds")
    res = ev.fetch_all(["ok.bsky.social", "broken.bsky.social"], since)
    assert len(res["ok.bsky.social"]["posts"]) == 1 and "HTTP 400" in res["broken.bsky.social"]["error"]


def _st(**kw):
    base = {"posts": 10, "scored": 10, "hi": 0, "top": 0, "off": 0, "per_day": 1.0,
            "mean": 2.0, "rate": 0.0, "off_rate": 0.0, "error": ""}
    base.update(kw)
    return base


@pytest.mark.parametrize("st,starred,want", [
    (_st(hi=3, rate=0.3), False, "⭐ THÊM"),
    (_st(hi=3, rate=0.3), True, "⭐ giữ"),
    (_st(hi=2, rate=0.1), False, "đọc thêm"),                        # đủ số bài nhưng tỉ lệ thấp
    (_st(hi=1, rate=0.05, per_day=25), False, "ồn"),
    (_st(hi=1, rate=0.05, per_day=25), True, "hạ ⭐ (ồn)"),
    (_st(hi=0, scored=8), False, "bỏ"),
    (_st(hi=0, scored=8), True, "hạ ⭐"),
    (_st(hi=1, scored=4, off_rate=0.75), False, "bỏ"),                # lạc đề
    (_st(hi=0, scored=3), True, "giữ ⭐"),                             # quá ít bài để kết luận
    (_st(posts=0, scored=0), True, "im"),
    (_st(error="HTTP 400"), False, "lỗi"),
])
def test_verdict_rules(st, starred, want):
    assert ev.verdict(st, starred) == want


def test_verdict_dry_run_only_judges_silence():
    assert ev.verdict(_st(posts=0, scored=0), True, scored_run=False) == "im"
    assert ev.verdict(_st(hi=5, rate=1.0), False, scored_run=False) == "—"


MD = """| | Tên | Handle | Vai trò | Vì sao | Hoạt động | Tin cậy |
|---|---|---|---|---|---|---|
| ⭐ | Claudia Sahm | [`sahm.bsky.social`](https://x) | econ | Fed | 2026 | cao |
| | Pundit | [`pundit.bsky.social`](https://x) | opinion | politics | 2026 | cao |
| | Quiet | [`quiet.bsky.social`](https://x) | econ | rare | 2026 | cao |
| ⛔ | Wire | [`wire.com`](https://x) | wire | noisy | 2026 | cao |
"""


def test_main_scores_ranks_and_summarises(tmp_path, monkeypatch, capsys):
    md = tmp_path / "l.md"
    md.write_text(MD, encoding="utf-8")
    pages = {
        "sahm.bsky.social": [[_entry("sahm.bsky.social", f"s{i}", f"Fed insight {i}" + LONG, i + 1) for i in range(4)]],
        "pundit.bsky.social": [[_entry("pundit.bsky.social", f"p{i}", f"Election gossip {i}" + LONG, i + 1)
                                for i in range(6)]],
        "quiet.bsky.social": [[]],
    }
    feed = FakeFeed(pages)
    monkeypatch.setattr(bml, "_get", feed)
    monkeypatch.setattr(na, "_load_env", lambda: None)
    batches = []

    def fake_score(todo, sent_titles=()):
        batches.append(len(todo))
        out = {}
        for i, it in enumerate(todo):
            m = 80 if "Fed insight" in it["title"] else 10
            out[i] = {"muc_do": m, "nhan": "neutral", "tac_dong": "Lãi suất Mỹ → tỷ giá"}
        return out, None
    monkeypatch.setattr(na, "score_items_cli", fake_score)
    assert ev.main(["--md", str(md), "--yes", "--batch", "4"]) == 0
    out = capsys.readouterr().out
    assert "wire.com" not in out and not any(c[0] == "wire.com" for c in feed.calls)   # ⛔ không đụng
    assert batches == [4, 4, 2]                                                         # 10 bài / lô 4
    assert "THÊM ⭐ (0)" in out                       # sahm đã ⭐ ⇒ "⭐ giữ", không phải THÊM
    assert "BỎ khỏi List đọc thử (1): pundit.bsky.social" in out
    assert "IM 7 ngày qua (1): quiet.bsky.social" in out
    assert "@sahm.bsky.social 80/100" in out


def test_dry_run_never_calls_claude(tmp_path, monkeypatch, capsys):
    md = tmp_path / "l.md"
    md.write_text(MD, encoding="utf-8")
    monkeypatch.setattr(bml, "_get", FakeFeed({"sahm.bsky.social": [[_entry("sahm.bsky.social", "a", "x" + LONG, 1)]]}))
    monkeypatch.setattr(na, "_load_env", lambda: None)
    monkeypatch.setattr(na, "score_items_cli", lambda *a, **k: pytest.fail("dry-run không được gọi Claude"))
    assert ev.main(["--md", str(md), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1 bài gốc" in out and "ĐỀ XUẤT" not in out


def test_all_batches_failing_exits_2(tmp_path, monkeypatch, capsys):
    md = tmp_path / "l.md"
    md.write_text(MD, encoding="utf-8")
    monkeypatch.setattr(bml, "_get", FakeFeed({"sahm.bsky.social": [[_entry("sahm.bsky.social", "a", "x" + LONG, 1)]]}))
    monkeypatch.setattr(na, "_load_env", lambda: None)
    monkeypatch.setattr(na, "score_items_cli", lambda todo, sent_titles=(): ({}, "CLI treo"))
    assert ev.main(["--md", str(md), "--yes"]) == 2
    assert "không chấm được bài nào" in capsys.readouterr().out

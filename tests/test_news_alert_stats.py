"""`scripts/news_alert_stats.daily_stats` — gom sổ tin mỗi giờ theo ngày."""
from __future__ import annotations

from scripts.news_alert_stats import daily_stats


def test_daily_stats_counts_hours_scores_and_sends_by_day():
    seen = {"items": {
        "a": {"first_seen": "2026-11-07T09:05:00", "score": 80, "source_key": "fed",
              "sent": True, "sent_at": "2026-11-07T09:06:00"},
        "b": {"first_seen": "2026-11-07T10:05:00", "score": 40, "source_key": "cnbc", "sent": False},
        "c": {"first_seen": "2026-11-07T10:20:00", "score": None, "source_key": "cnbc"},
        "d": {"first_seen": "2026-11-07T23:55:00", "score": 66, "source_key": "ft",
              "sent": True, "sent_at": "2026-11-08T00:05:00", "topup": True},
        "x": "rác",
    }}
    d7, d8 = daily_stats(seen, min_score=65)
    assert d7 == {"day": "2026-11-07", "hours": 3, "seen": 4, "scored": 3, "max": 80, "pass": 2,
                  "sent": 1, "topup": 0, "sources": 3}
    assert (d8["day"], d8["seen"], d8["sent"], d8["topup"]) == ("2026-11-08", 0, 1, 1)


def test_daily_stats_empty():
    assert daily_stats({}) == []

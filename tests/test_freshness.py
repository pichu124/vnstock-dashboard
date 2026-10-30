"""Tests for vnstock_freshness — data staleness badge helper."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dashboard.theme import TOKENS as T
from vnstock_freshness import (
    _format_age, file_age_seconds, freshness_color, freshness_html,
)


# ─── _format_age ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds,expected_substr", [
    (5,      "5s"),
    (45,     "45s"),
    (60,     "1 phút"),
    (3500,   "phút"),
    (3600,   "1.0 giờ"),
    (7200,   "2.0 giờ"),
    (86400,  "1.0 ngày"),
    (200000, "2.3 ngày"),
])
def test_format_age_buckets(seconds, expected_substr):
    assert expected_substr in _format_age(seconds)


# ─── file_age_seconds ─────────────────────────────────────────────────────────

def test_file_age_seconds_returns_none_for_missing(tmp_path):
    assert file_age_seconds(tmp_path / "nope.json") is None


def test_file_age_seconds_returns_positive_for_existing(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    age = file_age_seconds(p)
    assert age is not None
    assert 0 <= age < 10  # just created


def test_file_age_seconds_grows_after_backdating(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    # Set mtime 1 hour ago
    one_hr_ago = time.time() - 3600
    os.utime(p, (one_hr_ago, one_hr_ago))
    age = file_age_seconds(p)
    assert age is not None
    assert 3590 < age < 3610


# ─── freshness_color ──────────────────────────────────────────────────────────

def test_freshness_color_green_when_fresh():
    assert freshness_color(60, 3600) == T["up"]


def test_freshness_color_amber_at_70pct_of_stale():
    assert freshness_color(2520, 3600) == T["warn"]


def test_freshness_color_red_when_stale():
    assert freshness_color(7200, 3600) == T["down"]


def test_freshness_color_red_when_exactly_at_threshold():
    assert freshness_color(3600, 3600) == T["down"]


# ─── freshness_html ───────────────────────────────────────────────────────────

def test_freshness_html_shows_no_data_for_missing(tmp_path):
    html = freshness_html("Test", tmp_path / "missing.json", 3600)
    assert "chưa có dữ liệu" in html
    assert "Test" in html


def test_freshness_html_includes_age_for_existing(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    html = freshness_html("Test", p, 3600)
    assert "Test" in html
    assert "trước" in html


def test_freshness_html_uses_red_for_stale(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    # Make it 2 hours old, stale threshold 1 hour
    two_hr_ago = time.time() - 7200
    os.utime(p, (two_hr_ago, two_hr_ago))
    html = freshness_html("Test", p, 3600)
    assert T["down"] in html


def test_freshness_html_uses_green_for_fresh(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    html = freshness_html("Test", p, 3600)
    assert T["up"] in html

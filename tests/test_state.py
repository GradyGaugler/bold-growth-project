"""Unit tests for state persistence and history accounting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import config, state as state_mod


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    state_file = tmp_path / "cta_state.json"
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "STATE_FILE", state_file)
    yield


def test_load_empty_when_no_file_exists():
    s = state_mod.load_state()
    assert s == {"blogs": {}, "last_run_at": None}


def test_save_then_load_round_trips():
    s = {"blogs": {"https://x": {"v": 1}}, "last_run_at": "2026-05-16"}
    state_mod.save_state(s)
    assert state_mod.load_state() == s


def test_record_deploy_replaces_current_cta_and_appends_history():
    s = state_mod._empty_state()
    state_mod.record_deploy(
        s, blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "https://bold.org/scholarships/x", "headline": "h", "body": "b"},
        content_hash="sha256:abc",
        action="add",
        perf_snapshot=None,
    )
    assert s["blogs"]["https://bold.org/blog/a"]["current_cta"]["target_url"] == "https://bold.org/scholarships/x"
    assert s["blogs"]["https://bold.org/blog/a"]["history"] == []

    state_mod.record_deploy(
        s, blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "https://bold.org/scholarships/y", "headline": "h2", "body": "b2"},
        content_hash="sha256:def",
        action="rewrite",
        perf_snapshot={"cta_clicks": 0},
    )
    assert s["blogs"]["https://bold.org/blog/a"]["current_cta"]["target_url"] == "https://bold.org/scholarships/y"
    assert len(s["blogs"]["https://bold.org/blog/a"]["history"]) == 1
    assert s["blogs"]["https://bold.org/blog/a"]["rewrite_count_without_lift"] == 1


def test_record_retire_clears_current_cta_and_pushes_history():
    s = state_mod._empty_state()
    state_mod.record_deploy(
        s, blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "u", "headline": "h", "body": "b"},
        content_hash="sha256:abc",
        action="add",
        perf_snapshot=None,
    )
    state_mod.record_retire(s, blog_url="https://bold.org/blog/a", perf_snapshot={"cta_clicks": 0})
    blog = s["blogs"]["https://bold.org/blog/a"]
    assert blog["current_cta"] is None
    assert blog["content_hash_at_deploy"] is None
    assert blog["rewrite_count_without_lift"] == 0
    assert any(h.get("action_when_replaced") == "retire" for h in blog["history"])


def test_atomic_write_creates_file_at_expected_path():
    s = {"blogs": {}, "last_run_at": "2026-05-16T00:00:00+00:00"}
    state_mod.save_state(s)
    assert config.STATE_FILE.exists()
    data = json.loads(config.STATE_FILE.read_text())
    assert data == s


def test_reset_rewrite_counter_zeros_the_field():
    # Regression: a blog that earned strong CTR should not carry prior
    # rewrite debt into the next weak week.
    s = state_mod._empty_state()
    state_mod.record_deploy(
        s, blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "u", "headline": "h", "body": "b"},
        content_hash="sha256:abc", action="add", perf_snapshot=None,
    )
    state_mod.record_deploy(
        s, blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "u2", "headline": "h2", "body": "b2"},
        content_hash="sha256:def", action="rewrite", perf_snapshot=None,
    )
    assert s["blogs"]["https://bold.org/blog/a"]["rewrite_count_without_lift"] == 1
    state_mod.reset_rewrite_counter(s, "https://bold.org/blog/a")
    assert s["blogs"]["https://bold.org/blog/a"]["rewrite_count_without_lift"] == 0

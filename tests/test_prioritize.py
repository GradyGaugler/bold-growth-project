"""Unit tests for prioritization + decision rules."""

from __future__ import annotations

import hashlib

from agent.prioritize import build_queue, compute_ctr, decide_action
from agent.scrape import BlogPage


def _blog(url: str, text: str = "content") -> BlogPage:
    return BlogPage(
        url=url,
        title="t",
        h1="h",
        full_text_excerpt=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )


_DEPLOYED_CTA = {"target_url": "u", "headline": "h", "body": "b"}


def test_no_cta_yields_add_action():
    action, reason = decide_action(
        blog=_blog("https://bold.org/blog/a"),
        blog_state={"current_cta": None, "rewrite_count_without_lift": 0},
        perf=None,
        baseline_sessions=300,
    )
    assert action == "add"


def test_strong_ctr_yields_keep():
    action, _ = decide_action(
        blog=_blog("https://bold.org/blog/a"),
        blog_state={
            "current_cta": _DEPLOYED_CTA,
            "content_hash_at_deploy": "sha256:" + hashlib.sha256(b"content").hexdigest(),
            "rewrite_count_without_lift": 0,
        },
        perf={"cta_clicks": 9},
        baseline_sessions=300,  # ctr = 3%
    )
    assert action == "keep"


def test_weak_ctr_yields_rewrite():
    action, reason = decide_action(
        blog=_blog("https://bold.org/blog/a"),
        blog_state={
            "current_cta": _DEPLOYED_CTA,
            "content_hash_at_deploy": "sha256:" + hashlib.sha256(b"content").hexdigest(),
            "rewrite_count_without_lift": 0,
        },
        perf={"cta_clicks": 1},
        baseline_sessions=500,  # ctr = 0.2%, below 0.5% floor
    )
    assert action == "rewrite"
    assert "below" in reason


def test_content_hash_change_forces_rewrite_even_with_strong_ctr():
    action, reason = decide_action(
        blog=_blog("https://bold.org/blog/a", text="fresh content"),
        blog_state={
            "current_cta": _DEPLOYED_CTA,
            "content_hash_at_deploy": "sha256:" + hashlib.sha256(b"old content").hexdigest(),
            "rewrite_count_without_lift": 0,
        },
        perf={"cta_clicks": 50},
        baseline_sessions=500,  # ctr = 10%, would otherwise be keep
    )
    assert action == "rewrite"
    assert "content changed" in reason


def test_retire_after_three_rewrites_without_lift():
    action, reason = decide_action(
        blog=_blog("https://bold.org/blog/a"),
        blog_state={
            "current_cta": _DEPLOYED_CTA,
            "content_hash_at_deploy": "sha256:" + hashlib.sha256(b"content").hexdigest(),
            "rewrite_count_without_lift": 3,
        },
        perf={"cta_clicks": 1},
        baseline_sessions=500,
    )
    assert action == "retire"


def test_compute_ctr_handles_missing_perf_and_sessions():
    assert compute_ctr(None, 100) is None
    assert compute_ctr({"cta_clicks": 5}, 0) is None
    assert compute_ctr({"cta_clicks": 5}, 100) == 0.05


def test_build_queue_caps_at_top_n_and_appends_keepers():
    blogs = [_blog(f"https://bold.org/blog/{i}", text=f"c{i}") for i in range(7)]
    state = {"blogs": {}}
    baseline = {"blogs": {b.url: {"sessions_organic_google": 300 + i * 10} for i, b in enumerate(blogs)}}
    queue = build_queue(
        blogs=blogs,
        state=state,
        baseline=baseline,
        perf_measurements={},
        top_n=3,
    )
    actionable = [q for q in queue if q.action != "keep"]
    assert len(actionable) == 3

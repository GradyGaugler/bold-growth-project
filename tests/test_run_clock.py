"""Unit tests for deterministic weekly run timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

from agent.run import _run_at_for_week_label
from agent.state import record_deploy


def test_run_at_for_week_label_uses_embedded_date():
    assert _run_at_for_week_label("1-2026-05-16") == datetime(2026, 5, 16, tzinfo=timezone.utc)
    assert _run_at_for_week_label("2026-05-23") == datetime(2026, 5, 23, tzinfo=timezone.utc)


def test_record_deploy_uses_run_at_timestamp():
    run_at = datetime(2026, 5, 23, tzinfo=timezone.utc)
    state: dict = {"blogs": {}, "last_run_at": None}

    record_deploy(
        state,
        blog_url="https://bold.org/blog/a",
        new_cta={"target_url": "u", "headline": "h", "body": "b"},
        content_hash="sha256:abc",
        action="add",
        perf_snapshot=None,
        run_at=run_at,
    )

    cta = state["blogs"]["https://bold.org/blog/a"]["current_cta"]
    assert cta["deployed_at"] == "2026-05-23T00:00:00+00:00"

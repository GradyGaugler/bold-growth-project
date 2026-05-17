"""Unit tests for the structural and run-level guardrails.

These tests avoid the live URL check (`verify_url_live=False`) so they don't
touch the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent import config
from agent import guardrails as guardrails_mod
from agent.guardrails import (
    check_proposal_structure,
    circuit_breaker_tripped,
    enforce_run_caps,
    reset_url_cache,
    should_skip_blog,
)

CATALOG = {
    "https://bold.org/scholarships/by-major/nursing-scholarships/",
    "https://bold.org/scholarships/by-major/art-scholarships/",
}


def _valid_proposal(**overrides):
    base = {
        "target_url": "https://bold.org/scholarships/by-major/nursing-scholarships/",
        "target_rationale": "matches the persona reading the blog",
        "headline": "Find nursing scholarships built for you",
        "body": "Filter by program, level, and state, then apply in minutes through Bold.",
        "alternative_targets": [],
    }
    base.update(overrides)
    return base


def test_valid_proposal_passes_all_structural_checks():
    result = check_proposal_structure(
        proposal=_valid_proposal(),
        catalog_urls=CATALOG,
        frozen_sgps=set(),
        current_cta=None,
        verify_url_live=False,
    )
    assert result.ok, result.failures


def test_off_catalog_target_is_rejected():
    result = check_proposal_structure(
        proposal=_valid_proposal(target_url="https://bold.org/scholarships/not-in-catalog/"),
        catalog_urls=CATALOG,
        frozen_sgps=set(),
        current_cta=None,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "off_catalog" in codes


def test_off_domain_is_rejected():
    result = check_proposal_structure(
        proposal=_valid_proposal(target_url="https://example.com/foo/"),
        catalog_urls=CATALOG | {"https://example.com/foo/"},
        frozen_sgps=set(),
        current_cta=None,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "off_domain" in codes


def test_banned_phrase_is_rejected_even_when_otherwise_valid():
    result = check_proposal_structure(
        proposal=_valid_proposal(headline="100% free money for nursing students"),
        catalog_urls=CATALOG,
        frozen_sgps=set(),
        current_cta=None,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "banned_phrase" in codes


def test_oversized_headline_is_rejected():
    too_long = "x" * (config.HEADLINE_MAX_CHARS + 5)
    result = check_proposal_structure(
        proposal=_valid_proposal(headline=too_long),
        catalog_urls=CATALOG,
        frozen_sgps=set(),
        current_cta=None,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "headline_too_long" in codes


def test_no_op_change_is_rejected_against_current_cta():
    current = {
        "headline": "Find nursing scholarships built for you",
        "body": "Filter by program, level, and state, then apply in minutes through Bold.",
        "target_url": "https://bold.org/scholarships/by-major/nursing-scholarships/",
    }
    result = check_proposal_structure(
        proposal=_valid_proposal(),  # identical to current
        catalog_urls=CATALOG,
        frozen_sgps=set(),
        current_cta=current,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "no_op_change" in codes


def test_frozen_sgp_blocks_target():
    result = check_proposal_structure(
        proposal=_valid_proposal(),
        catalog_urls=CATALOG,
        frozen_sgps={"https://bold.org/scholarships/by-major/nursing-scholarships/"},
        current_cta=None,
        verify_url_live=False,
    )
    codes = {f.code for f in result.failures}
    assert "frozen_sgp" in codes


def test_min_age_blocks_recent_cta():
    today = datetime(2026, 5, 16, tzinfo=timezone.utc)
    recent = (today - timedelta(days=2)).isoformat()
    failure = should_skip_blog(
        blog_url="https://bold.org/blog/x",
        current_cta={"deployed_at": recent},
        frozen_blogs=set(),
        today=today,
    )
    assert failure and failure.code == "min_age"


def test_frozen_blog_skipped():
    today = datetime(2026, 5, 16, tzinfo=timezone.utc)
    failure = should_skip_blog(
        blog_url="https://bold.org/blog/x",
        current_cta=None,
        frozen_blogs={"https://bold.org/blog/x"},
        today=today,
    )
    assert failure and failure.code == "frozen_blog"


def test_diversity_cap_defers_extra_routes_to_same_sgp():
    same_target = "https://bold.org/scholarships/by-major/nursing-scholarships/"
    items = [
        {"blog_url": f"https://bold.org/blog/b{i}", "proposal": {"target_url": same_target}}
        for i in range(config.MAX_PER_SGP + 2)
    ]
    kept, deferred = enforce_run_caps(items)
    assert len(kept) == config.MAX_PER_SGP
    assert len(deferred) == 2
    assert all(d["deferred_reason"] == "diversity_cap" for d in deferred)


def test_weekly_change_cap_defers_overflow():
    items = []
    for i in range(config.MAX_WEEKLY_CHANGES + 3):
        items.append({
            "blog_url": f"https://bold.org/blog/b{i}",
            "proposal": {"target_url": f"https://bold.org/scholarships/x{i}/"},  # unique each
        })
    kept, deferred = enforce_run_caps(items)
    assert len(kept) == config.MAX_WEEKLY_CHANGES
    assert len(deferred) == 3
    assert all(d["deferred_reason"] == "weekly_change_cap" for d in deferred)


@pytest.mark.parametrize(
    "rejected,total,expected",
    [
        (0, 0, False),
        (1, 2, False),  # too few proposals to draw a conclusion
        (4, 10, False),
        (5, 10, True),
        (3, 5, True),
    ],
)
def test_circuit_breaker(rejected, total, expected):
    assert circuit_breaker_tripped(rejected=rejected, total_proposed=total) is expected


def test_url_resolve_cache_avoids_repeat_requests(monkeypatch):
    """Catalog URLs are fixed within a run; we should only HEAD each one once."""
    reset_url_cache()
    calls = {"count": 0}

    class _StubResponse:
        status_code = 200

    def _fake_head(url, **kwargs):
        calls["count"] += 1
        return _StubResponse()

    monkeypatch.setattr(guardrails_mod.requests, "head", _fake_head)
    url = "https://bold.org/scholarships/example/"
    assert guardrails_mod._url_resolves(url) is True
    assert guardrails_mod._url_resolves(url) is True
    assert guardrails_mod._url_resolves(url) is True
    assert calls["count"] == 1
    reset_url_cache()

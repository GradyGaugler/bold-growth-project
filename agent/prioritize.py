"""Decision rules + queue selection.

Pure functions over (state, mocks, freshly-scraped blogs). No I/O, no LLM
calls - everything here should be unit-testable on fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent import config
from agent.scrape import BlogPage

Action = Literal["add", "rewrite", "keep", "retire"]


@dataclass
class QueueItem:
    blog: BlogPage
    action: Action
    reason: str
    score: float
    current_cta: dict[str, Any] | None
    perf: dict[str, Any] | None
    measured_ctr: float | None  # None if perf is missing or baseline_sessions == 0


def compute_ctr(perf: dict[str, Any] | None, baseline_sessions: int) -> float | None:
    """CTR = cta_clicks / sessions_organic_google. None if we have no measurement."""
    if not perf:
        return None
    if baseline_sessions <= 0:
        return None
    return perf.get("cta_clicks", 0) / baseline_sessions


def _staleness_factor(blog_state: dict[str, Any]) -> float:
    """Older CTAs get a small bump in the priority score so they don't go stale."""
    cta = blog_state.get("current_cta")
    if not cta:
        return 1.5  # never had one - bump it up
    rewrite_count = blog_state.get("rewrite_count_without_lift", 0)
    return 1.0 + 0.1 * rewrite_count


def decide_action(
    *,
    blog: BlogPage,
    blog_state: dict[str, Any],
    perf: dict[str, Any] | None,
    baseline_sessions: int,
) -> tuple[Action, str]:
    """Return (action, human-readable reason)."""
    cta = blog_state.get("current_cta")
    if cta is None:
        return "add", "no CTA deployed yet"

    # Retire trigger comes first - if we've already burned 3 rewrites without
    # lift, the next signal shouldn't matter.
    if blog_state.get("rewrite_count_without_lift", 0) >= config.MAX_REWRITES_WITHOUT_LIFT:
        return "retire", f"{config.MAX_REWRITES_WITHOUT_LIFT} rewrites without lift"

    # Content-hash change since deploy: blog itself was rewritten, our CTA may
    # no longer match. Force a rewrite regardless of perf.
    deployed_hash = blog_state.get("content_hash_at_deploy")
    if deployed_hash and deployed_hash != blog.content_hash:
        return "rewrite", "blog content changed since CTA was deployed"

    ctr = compute_ctr(perf, baseline_sessions)
    if ctr is None:
        # CTA exists, no perf yet - keep it; don't churn before we measure.
        return "keep", "CTA deployed; no measured performance yet"
    if ctr >= config.CTR_STRONG:
        return "keep", f"CTR {ctr:.2%} >= strong threshold {config.CTR_STRONG:.0%}"
    if ctr < config.CTR_FLOOR:
        return "rewrite", f"CTR {ctr:.2%} below floor {config.CTR_FLOOR:.0%}"
    return "keep", f"CTR {ctr:.2%} between floor and strong - hold"


def score_blog(
    *,
    blog_state: dict[str, Any],
    perf: dict[str, Any] | None,
    baseline_sessions: int,
) -> float:
    """Priority score for the weekly queue."""
    ctr = compute_ctr(perf, baseline_sessions)
    # `(1 - ctr_normalized)` weights underperformers higher; clamp ctr to [0, 0.1].
    ctr_norm = min((ctr or 0.0) / 0.10, 1.0)
    staleness = _staleness_factor(blog_state)
    return baseline_sessions * (1 - ctr_norm) * staleness


def build_queue(
    *,
    blogs: list[BlogPage],
    state: dict[str, Any],
    baseline: dict[str, Any],
    perf_measurements: dict[str, Any],
    top_n: int = config.PRIORITY_TOP_N,
) -> list[QueueItem]:
    items: list[QueueItem] = []
    for blog in blogs:
        blog_state = state["blogs"].get(blog.url, {
            "current_cta": None,
            "content_hash_at_deploy": None,
            "rewrite_count_without_lift": 0,
        })
        blog_baseline = baseline["blogs"].get(blog.url, {})
        baseline_sessions = int(blog_baseline.get("sessions_organic_google", 0))
        perf = perf_measurements.get(blog.url)
        action, reason = decide_action(
            blog=blog,
            blog_state=blog_state,
            perf=perf,
            baseline_sessions=baseline_sessions,
        )
        score = score_blog(
            blog_state=blog_state, perf=perf, baseline_sessions=baseline_sessions
        )
        items.append(QueueItem(
            blog=blog,
            action=action,
            reason=reason,
            score=score,
            current_cta=blog_state.get("current_cta"),
            perf=perf,
            measured_ctr=compute_ctr(perf, baseline_sessions),
        ))

    # `keep` actions don't need the LLM - they're skipped from the LLM-call queue
    # but still emitted in the artifact so the PM sees them.
    actionable = [it for it in items if it.action != "keep"]
    actionable.sort(key=lambda it: it.score, reverse=True)
    keepers = [it for it in items if it.action == "keep"]
    return actionable[:top_n] + keepers

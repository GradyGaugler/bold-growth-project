"""CLI entrypoint and weekly-loop orchestrator.

    python3 -m agent.run                  # one weekly run (real LLM calls)
    python3 -m agent.run --dry-run        # smoke the pipeline, no LLM, no writes
    python3 -m agent.run --week 2026-05-23  # custom artifacts label
    python3 -m agent.run --simulate-perf  # advance mocked perf for the loop demo
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent import config
from agent.artifacts import AuditLog, write_artifacts
from agent.generator import CtaProposal, propose_cta
from agent.guardrails import (
    StructureCheck,
    check_proposal_structure,
    should_skip_blog,
)
from agent.llm import CostCapExceeded, CostMeter
from agent.prioritize import QueueItem, build_queue
from agent.reviewer import ReviewerVerdict, passes_approval_floor, review
from agent.scrape import BlogPage, SgpEntry, build_catalog, fetch_all_blogs
from agent.state import (
    load_state,
    record_deploy,
    record_retire,
    reset_rewrite_counter,
    save_state,
)

logger = logging.getLogger("agent.run")


def _load_mocks() -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = json.loads(config.SITE_BASELINE_FILE.read_text(encoding="utf-8"))
    perf = json.loads(config.CTA_PERFORMANCE_FILE.read_text(encoding="utf-8"))
    return (
        baseline,
        perf.get("measurements", {}),
    )


def _catalog_lookup(catalog: list[SgpEntry]) -> dict[str, SgpEntry]:
    return {entry.url: entry for entry in catalog}


def _run_generator_then_review(
    *,
    blog: BlogPage,
    catalog: list[SgpEntry],
    catalog_by_url: dict[str, SgpEntry],
    current_cta: dict[str, Any] | None,
    meter: CostMeter,
    audit: AuditLog,
) -> tuple[CtaProposal | None, ReviewerVerdict | None, StructureCheck | None, str | None]:
    """One full generator + reviewer cycle with at most one revise retry.

    Returns (proposal, verdict, structure_check, failure_reason).
    `failure_reason` is None on approval; otherwise a human-readable code.
    """
    reviewer_feedback: list[str] | None = None
    last_structure: StructureCheck | None = None
    last_proposal: CtaProposal | None = None
    last_verdict: ReviewerVerdict | None = None

    for attempt in range(2):  # 1 initial + 1 retry on `revise`
        proposal = propose_cta(
            blog=blog,
            catalog=catalog,
            current_cta=current_cta,
            reviewer_feedback=reviewer_feedback,
            meter=meter,
        )
        audit.log(
            "generator_proposal",
            blog_url=blog.url,
            attempt=attempt + 1,
            proposal=asdict(proposal),
        )
        last_proposal = proposal

        structure = check_proposal_structure(
            proposal=asdict(proposal),
            catalog_urls=set(catalog_by_url.keys()),
            current_cta=current_cta,
        )
        last_structure = structure
        if not structure.ok:
            audit.log(
                "structure_check_failed",
                blog_url=blog.url,
                failures=[asdict(f) for f in structure.failures],
            )
            return proposal, None, structure, "structure_check_failed"

        target = catalog_by_url[proposal.target_url]
        verdict = review(
            blog=blog,
            proposal=proposal,
            target=target,
            catalog=catalog,
            current_cta=current_cta,
            meter=meter,
        )
        audit.log("reviewer_verdict", blog_url=blog.url, attempt=attempt + 1, verdict=asdict(verdict))
        last_verdict = verdict

        if passes_approval_floor(verdict):
            return proposal, verdict, structure, None

        if verdict.verdict == "revise" and attempt == 0:
            reviewer_feedback = verdict.issues or [verdict.reasoning]
            audit.log("retrying_with_feedback", blog_url=blog.url, feedback=reviewer_feedback)
            continue

        # Unresolved revise on attempt 2, or reject, or approve-but-low-score.
        return proposal, verdict, structure, (
            "reviewer_rejected" if verdict.verdict == "reject"
            else "reviewer_low_score" if verdict.verdict == "approve"
            else "revise_unresolved"
        )

    return last_proposal, last_verdict, last_structure, "exhausted_attempts"


def run_once(*, week_label: str, dry_run: bool) -> Path | None:
    audit = AuditLog()
    audit.log("run_start", week=week_label, dry_run=dry_run, generator=config.GENERATOR_MODEL, reviewer=config.REVIEWER_MODEL)

    state = load_state()
    baseline, perf_measurements = _load_mocks()

    blogs = fetch_all_blogs()
    catalog = build_catalog()
    catalog_by_url = _catalog_lookup(catalog)
    audit.log("inputs_loaded", n_blogs=len(blogs), n_catalog=len(catalog), n_perf=len(perf_measurements))

    queue = build_queue(
        blogs=blogs,
        state=state,
        baseline=baseline,
        perf_measurements=perf_measurements,
    )
    audit.log("queue_built", items=[{"blog": it.blog.url, "action": it.action, "reason": it.reason, "score": it.score} for it in queue])

    today = datetime.now(timezone.utc)
    approved: list[dict[str, Any]] = []
    human_review: list[dict[str, Any]] = []
    retired: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    proposals_made = 0
    llm_budget_exhausted = False

    meter = CostMeter()

    for item in queue:
        if item.action == "keep":
            kept.append({"blog_url": item.blog.url, "reason": item.reason})
            audit.log("kept", blog_url=item.blog.url, reason=item.reason)
            # Strong CTR means the current CTA earned its keep - clear any
            # prior "rewrite without lift" debt so future weak weeks restart
            # the retire countdown from zero.
            if (
                not dry_run
                and item.measured_ctr is not None
                and item.measured_ctr >= config.CTR_STRONG
            ):
                reset_rewrite_counter(state, item.blog.url)
            continue

        if item.action == "retire":
            retired.append({"blog_url": item.blog.url, "reason": item.reason})
            audit.log("retire_decided", blog_url=item.blog.url, reason=item.reason)
            if not dry_run:
                record_retire(state, blog_url=item.blog.url, perf_snapshot=item.perf)
            continue

        # add | rewrite
        skip = should_skip_blog(
            current_cta=item.current_cta,
            today=today,
        )
        if skip:
            # Pre-generator skips don't need a human - the CTA just stays as-is
            # until next week. Push to `kept` so the human-review queue only
            # shows items that actually need a person.
            kept.append({"blog_url": item.blog.url, "reason": skip.detail})
            audit.log("pre_generator_skip", blog_url=item.blog.url, failure=asdict(skip))
            continue

        if dry_run:
            audit.log("dry_run_skip_llm", blog_url=item.blog.url, action=item.action)
            kept.append({"blog_url": item.blog.url, "reason": f"dry-run: would {item.action}"})
            continue

        if llm_budget_exhausted:
            human_review.append({
                "blog_url": item.blog.url,
                "reason": "not_processed_cost_cap",
                "guardrail_failures": [
                    {
                        "code": "cost_cap",
                        "detail": "LLM budget was exhausted earlier in the run",
                    }
                ],
            })
            audit.log("llm_skip_cost_cap", blog_url=item.blog.url, action=item.action)
            continue

        try:
            proposals_made += 1
            proposal, verdict, structure, failure_reason = _run_generator_then_review(
                blog=item.blog,
                catalog=catalog,
                catalog_by_url=catalog_by_url,
                current_cta=item.current_cta,
                meter=meter,
                audit=audit,
            )
        except CostCapExceeded as exc:
            audit.log("cost_cap_hit", blog_url=item.blog.url, detail=str(exc))
            human_review.append({
                "blog_url": item.blog.url,
                "reason": "cost_cap",
                "guardrail_failures": [{"code": "cost_cap", "detail": str(exc)}],
            })
            llm_budget_exhausted = True
            continue

        if failure_reason is None:
            approved.append({
                "blog_url": item.blog.url,
                "action": item.action,
                "proposal": asdict(proposal),
                "verdict": asdict(verdict),
                "previous_cta": item.current_cta,
                "content_hash": item.blog.content_hash,
                "perf": item.perf,
            })
            audit.log("approved", blog_url=item.blog.url, action=item.action)
            continue

        # Failed - to human queue.
        human_review.append({
            "blog_url": item.blog.url,
            "reason": failure_reason,
            "proposal": asdict(proposal) if proposal else None,
            "verdict": asdict(verdict) if verdict else None,
            "guardrail_failures": [asdict(f) for f in (structure.failures if structure else [])] or None,
        })

    if not dry_run:
        for item in approved:
            record_deploy(
                state,
                blog_url=item["blog_url"],
                new_cta={
                    "target_url": item["proposal"]["target_url"],
                    "headline": item["proposal"]["headline"],
                    "body": item["proposal"]["body"],
                },
                content_hash=item["content_hash"],
                action=item["action"],
                perf_snapshot=item.get("perf"),
            )
        state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_state(state)

    plan_context = {
        "week": week_label,
        "run_completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator_model": config.GENERATOR_MODEL,
        "reviewer_model": config.REVIEWER_MODEL,
        "n_blogs": len(blogs),
        "total_proposed": proposals_made,
        "n_approved": len(approved),
        "n_human_review": len(human_review),
        "n_kept": len(kept),
        "n_retired": len(retired),
        "prompt_tokens": meter.total_prompt_tokens,
        "completion_tokens": meter.total_completion_tokens,
        "cost_usd": meter.total_cost_usd,
        "cost_cap": meter.cap_usd,
        "approved": approved,
        "kept": kept,
        "retired": retired,
        "human_review": human_review,
    }

    audit.log("run_end", spent_usd=meter.total_cost_usd, n_approved=len(approved))

    if dry_run:
        logger.info("dry run complete; no artifacts written")
        for entry in audit.entries:
            print(json.dumps(entry))
        return None

    out = write_artifacts(
        week_label=week_label,
        plan_context=plan_context,
    )
    logger.info("wrote artifacts -> %s", out)
    return out


def simulate_perf(*, seed: int = 7) -> None:
    """Generate plausible mocked perf for everything in state.

    Used between weekly runs so the demo can show the loop behaving differently
    on week 2 (some CTAs measured below floor -> rewrite, some above -> keep).
    Deterministic given a seed so reviewers see the same numbers.
    """
    rng = random.Random(seed)
    state = load_state()
    baseline = json.loads(config.SITE_BASELINE_FILE.read_text(encoding="utf-8"))

    measurements: dict[str, Any] = {}
    for blog_url, blog_state in state["blogs"].items():
        cta = blog_state.get("current_cta")
        if not cta:
            continue
        sessions = int(baseline["blogs"].get(blog_url, {}).get("sessions_organic_google", 0))
        if sessions == 0:
            continue
        # Bias the distribution so we get a healthy mix of below-floor,
        # in-band, and strong CTRs for the demo. Keep numbers integer-y.
        bucket = rng.choices(
            ["weak", "okay", "strong"],
            weights=[0.4, 0.4, 0.2],
        )[0]
        if bucket == "weak":
            ctr = rng.uniform(0.001, 0.004)  # below floor (0.5%)
        elif bucket == "okay":
            ctr = rng.uniform(0.008, 0.018)
        else:
            ctr = rng.uniform(0.022, 0.035)  # at or above strong
        clicks = max(1, round(sessions * ctr))
        blog_to_sgp_sessions = max(0, round(clicks * rng.uniform(0.6, 0.9)))
        downstream_submits = max(0, round(blog_to_sgp_sessions * rng.uniform(0.05, 0.15)))
        measurements[blog_url] = {
            "cta_clicks": clicks,
            "blog_to_sgp_sessions": blog_to_sgp_sessions,
            "downstream_submits": downstream_submits,
            "measured_through": datetime.now(timezone.utc).date().isoformat(),
        }

    payload = {
        "_comment": "Mock perf written by `python3 -m agent.run --simulate-perf`. Deterministic given the same seed.",
        "measurements": measurements,
    }
    config.CTA_PERFORMANCE_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("wrote simulated perf for %d blogs", len(measurements))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blog -> SGP routing agent (weekly loop)")
    parser.add_argument(
        "--week",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Label for the artifacts directory (defaults to today's UTC date).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline with no LLM calls and no writes - print audit log only.",
    )
    parser.add_argument(
        "--simulate-perf",
        action="store_true",
        help="Don't run the agent; instead write deterministic mocked perf to mocks/cta_performance.json based on whatever is currently in state. Use between weekly runs.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    load_dotenv()

    if args.simulate_perf:
        simulate_perf()
        return 0

    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Copy .env.example to .env or use --dry-run.")
        return 2

    run_once(week_label=args.week, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Reviewer agent: scores + verdicts proposals in a fresh LLM context.

Separate from the generator on purpose. No `confidence` field is carried over,
and no "we just wrote this" framing in the prompt - the reviewer judges the
proposal cold so we don't get LLM self-flattery.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from agent import config
from agent._prompts import current_cta_block, load_prompt
from agent.generator import CtaProposal
from agent.llm import CostMeter, call_json
from agent.scrape import BlogPage, SgpEntry

_PROMPT_FILE = config.PROMPTS_DIR / "reviewer.md"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "relevance_score",
        "copy_quality_score",
        "brand_safety_pass",
        "issues",
        "verdict",
        "reasoning",
    ],
    "properties": {
        "relevance_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "copy_quality_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "brand_safety_pass": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {"type": "string", "maxLength": 240},
            "maxItems": 6,
        },
        "verdict": {"type": "string", "enum": ["approve", "revise", "reject"]},
        "reasoning": {"type": "string", "minLength": 5, "maxLength": 400},
    },
}


@dataclass
class ReviewerVerdict:
    relevance_score: float
    copy_quality_score: float
    brand_safety_pass: bool
    issues: list[str]
    verdict: str
    reasoning: str


def _catalog_block(catalog: list[SgpEntry]) -> str:
    """Compact catalog listing - URL + title only.

    The reviewer needs this to validate alternative_targets and reason about
    whether a better page exists. Keep it terse - we're paying per token.
    """
    return "\n".join(f"- {entry.url}: {entry.title}" for entry in catalog)


def review(
    *,
    blog: BlogPage,
    proposal: CtaProposal,
    target: SgpEntry,
    catalog: list[SgpEntry],
    current_cta: dict[str, Any] | None,
    meter: CostMeter,
) -> ReviewerVerdict:
    system_prompt, user_template = load_prompt(_PROMPT_FILE)
    user_prompt = user_template.format(
        blog_url=blog.url,
        blog_title=blog.title,
        blog_excerpt=blog.full_text_excerpt[:1500],
        proposal_json=json.dumps(asdict(proposal), indent=2),
        target_url=target.url,
        target_title=target.title,
        target_summary=target.one_line_summary,
        current_cta_block=current_cta_block(current_cta),
        catalog_block=_catalog_block(catalog),
    )
    raw = call_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=_SCHEMA,
        schema_name="reviewer_verdict",
        model=config.REVIEWER_MODEL,
        meter=meter,
        purpose="reviewer",
        reasoning_effort=config.REVIEWER_EFFORT,
    )
    return ReviewerVerdict(**raw)


def passes_approval_floor(verdict: ReviewerVerdict) -> bool:
    return (
        verdict.verdict == "approve"
        and verdict.brand_safety_pass
        and verdict.relevance_score >= config.REVIEWER_APPROVAL_FLOOR
        and verdict.copy_quality_score >= config.REVIEWER_APPROVAL_FLOOR
    )

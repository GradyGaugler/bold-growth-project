"""Generator agent: picks a target SGP and writes the CTA copy.

One LLM call per blog. Output is constrained by a JSON schema whose
`target_url` is an enum of the actual catalog URLs - the model literally
cannot emit a hallucinated path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent import config
from agent._prompts import current_cta_block, load_prompt
from agent.llm import CostMeter, call_json
from agent.scrape import BlogPage, SgpEntry

_PROMPT_FILE = config.PROMPTS_DIR / "generator.md"


@dataclass
class CtaProposal:
    target_url: str
    target_rationale: str
    headline: str
    body: str


def _catalog_block(catalog: list[SgpEntry]) -> str:
    lines = []
    for entry in catalog:
        lines.append(f"- {entry.url}\n  title: {entry.title}\n  about: {entry.one_line_summary}")
    return "\n".join(lines)


def _build_schema(catalog: list[SgpEntry]) -> dict[str, Any]:
    """Enum-constrained schema. Hallucinated target_urls are unrepresentable."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target_url",
            "target_rationale",
            "headline",
            "body",
        ],
        "properties": {
            "target_url": {
                "type": "string",
                "enum": [entry.url for entry in catalog],
            },
            "target_rationale": {
                "type": "string",
                "minLength": 10,
                "maxLength": 400,
            },
            "headline": {
                "type": "string",
                "minLength": 5,
                "maxLength": config.HEADLINE_MAX_CHARS,
            },
            "body": {
                "type": "string",
                "minLength": 10,
                "maxLength": config.BODY_MAX_CHARS,
            },
        },
    }


def propose_cta(
    *,
    blog: BlogPage,
    catalog: list[SgpEntry],
    current_cta: dict[str, Any] | None,
    reviewer_feedback: list[str] | None,
    meter: CostMeter,
) -> CtaProposal:
    system_prompt, user_template = load_prompt(_PROMPT_FILE)
    system_prompt = system_prompt.format(
        banned_phrases=", ".join(f'"{p}"' for p in config.BANNED_PHRASES)
    )
    user_prompt = user_template.format(
        blog_url=blog.url,
        blog_title=blog.title,
        blog_h1=blog.h1,
        blog_excerpt=blog.full_text_excerpt[:1800],
        current_cta_block=current_cta_block(current_cta),
        reviewer_feedback_block=(
            "- " + "\n- ".join(reviewer_feedback) if reviewer_feedback else "(none)"
        ),
        catalog_block=_catalog_block(catalog),
    )
    schema = _build_schema(catalog)
    result = call_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=schema,
        schema_name="cta_proposal",
        model=config.GENERATOR_MODEL,
        meter=meter,
        purpose="generator",
        reasoning_effort=config.GENERATOR_EFFORT,
    )
    return CtaProposal(**result)

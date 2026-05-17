"""Emit human-reviewable artifacts at the end of each run.

- `plan.md`: the PR-style markdown a PM approves
- `diff.json`: machine-readable changeset (what a real CMS push would consume)
- `run.log`: structured audit trail (one JSON line per step), rewritten each run
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader

from agent import config

logger = logging.getLogger(__name__)


_PLAN_TEMPLATE = """# Weekly CTA Plan, {{ week }}

Run completed: {{ run_completed_at }}
Generator model: `{{ generator_model }}` • Reviewer model: `{{ reviewer_model }}`

{% if drift_flag -%}
> **Drift suspected.** Reviewer rejected {{ rejected }}/{{ total_proposed }} proposals (>= 50%). Run halted, everything is in the human-review queue below. Check the prompts, the catalog, or the model before next week.
{%- endif %}

## Run stats

- Blogs reviewed: {{ n_blogs }}
- LLM proposals generated: {{ total_proposed }}
- Approved (queued for deploy): {{ n_approved }}
- Sent to human review: {{ n_human_review }}
- Deferred to next week: {{ n_deferred }}
- LLM tokens: {{ prompt_tokens }} in / {{ completion_tokens }} out
- LLM spend: ${{ '%.4f'|format(cost_usd) }} of ${{ '%.2f'|format(cost_cap) }} cap

## Approved changes ({{ n_approved }})

{% if approved -%}
{% for item in approved %}
### {{ loop.index }}. `{{ item.blog_url }}` -> {{ item.action }}

- **Target**: [{{ item.proposal.target_url }}]({{ item.proposal.target_url }})
- **Rationale**: {{ item.proposal.target_rationale }}
- **Headline**: {{ item.proposal.headline }}
- **Body**: {{ item.proposal.body }}
- **Reviewer**: verdict `{{ item.verdict.verdict }}`, relevance `{{ '%.2f'|format(item.verdict.relevance_score) }}`, copy `{{ '%.2f'|format(item.verdict.copy_quality_score) }}`
- **Reviewer reasoning**: {{ item.verdict.reasoning }}
{% if item.previous_cta %}
- **Replaces**:
  - headline: {{ item.previous_cta.headline }}
  - body: {{ item.previous_cta.body }}
  - target: {{ item.previous_cta.target_url }}
{% endif %}
{% endfor %}
{% else -%}
_None this week._
{% endif %}

## Kept as-is ({{ n_kept }})

{% for item in kept %}
- `{{ item.blog_url }}` — {{ item.reason }}
{% else %}
_None._
{% endfor %}

## Retired ({{ n_retired }})

{% for item in retired %}
- `{{ item.blog_url }}` — {{ item.reason }}; CTA reverted to generic `/scholarships`. Flagged for human follow-up.
{% else %}
_None._
{% endfor %}

## Needs human review ({{ n_human_review }})

{% for item in human_review %}
### `{{ item.blog_url }}` — {{ item.reason }}

{% if item.proposal -%}
- Proposed target: {{ item.proposal.target_url }}
- Headline: {{ item.proposal.headline }}
- Body: {{ item.proposal.body }}
{% endif -%}
{% if item.verdict -%}
- Reviewer verdict: `{{ item.verdict.verdict }}` ({{ item.verdict.reasoning }})
- Issues: {{ item.verdict.issues | join('; ') }}
{% endif -%}
{% if item.guardrail_failures -%}
- Guardrail failures: {% for f in item.guardrail_failures %}`{{ f.code }}` ({{ f.detail }}){% if not loop.last %}; {% endif %}{% endfor %}
{% endif %}
{% else %}
_None._
{% endfor %}

## Deferred to next week ({{ n_deferred }})

{% for item in deferred %}
- `{{ item.blog_url }}` — {{ item.deferred_reason }}
{% else %}
_None._
{% endfor %}
"""


def render_plan_md(context: dict[str, Any]) -> str:
    env = Environment(loader=BaseLoader(), trim_blocks=False, lstrip_blocks=False)
    template = env.from_string(_PLAN_TEMPLATE)
    return template.render(**context)


def week_dir(week_label: str) -> Path:
    out = config.ARTIFACTS_DIR / f"week-{week_label}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_artifacts(
    *,
    week_label: str,
    plan_context: dict[str, Any],
    diff: dict[str, Any],
    audit_log: list[dict[str, Any]],
) -> Path:
    out = week_dir(week_label)
    (out / "plan.md").write_text(render_plan_md(plan_context), encoding="utf-8")
    (out / "diff.json").write_text(json.dumps(diff, indent=2, sort_keys=True), encoding="utf-8")
    with (out / "run.log").open("w", encoding="utf-8") as fh:
        for entry in audit_log:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return out


class AuditLog:
    """Tiny helper that timestamps every decision and keeps it in memory.

    Flushed once at the end of the run so a crashed run still leaves partial
    artifacts behind for debugging.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def log(self, event: str, **payload: Any) -> None:
        self.entries.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            **payload,
        })

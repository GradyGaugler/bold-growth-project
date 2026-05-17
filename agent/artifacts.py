"""Emit human-reviewable artifacts at the end of each run.

`plan.md` is the PR-style markdown a PM approves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import config


def _money(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def _append_approved(lines: list[str], approved: list[dict[str, Any]]) -> None:
    if not approved:
        lines.append("_None this week._")
        return

    for index, item in enumerate(approved, start=1):
        proposal = item["proposal"]
        verdict = item["verdict"]
        lines.extend(
            [
                f"### {index}. `{item['blog_url']}` -> {item['action']}",
                "",
                f"- **Target**: [{proposal['target_url']}]({proposal['target_url']})",
                f"- **Rationale**: {proposal['target_rationale']}",
                f"- **Headline**: {proposal['headline']}",
                f"- **Body**: {proposal['body']}",
                (
                    f"- **Reviewer**: verdict `{verdict['verdict']}`, "
                    f"relevance `{verdict['relevance_score']:.2f}`, "
                    f"copy `{verdict['copy_quality_score']:.2f}`"
                ),
                f"- **Reviewer reasoning**: {verdict['reasoning']}",
            ]
        )
        previous = item.get("previous_cta")
        if previous:
            lines.extend(
                [
                    "- **Replaces**:",
                    f"  - headline: {previous['headline']}",
                    f"  - body: {previous['body']}",
                    f"  - target: {previous['target_url']}",
                ]
            )
        lines.append("")


def _append_simple_list(lines: list[str], items: list[dict[str, Any]], *, retired: bool = False) -> None:
    if not items:
        lines.append("_None._")
        return
    for item in items:
        suffix = "; CTA reverted to generic `/scholarships`. Flagged for human follow-up." if retired else ""
        lines.append(f"- `{item['blog_url']}` - {item['reason']}{suffix}")


def _append_human_review(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append("_None._")
        return

    for item in items:
        lines.extend([f"### `{item['blog_url']}` - {item['reason']}", ""])
        proposal = item.get("proposal")
        if proposal:
            lines.extend(
                [
                    f"- Proposed target: {proposal['target_url']}",
                    f"- Headline: {proposal['headline']}",
                    f"- Body: {proposal['body']}",
                ]
            )
        verdict = item.get("verdict")
        if verdict:
            issues = "; ".join(verdict.get("issues", []))
            lines.extend(
                [
                    f"- Reviewer verdict: `{verdict['verdict']}` ({verdict['reasoning']})",
                    f"- Issues: {issues}",
                ]
            )
        failures = item.get("guardrail_failures")
        if failures:
            rendered = "; ".join(f"`{f['code']}` ({f['detail']})" for f in failures)
            lines.append(f"- Guardrail failures: {rendered}")
        lines.append("")


def render_plan_md(context: dict[str, Any]) -> str:
    lines = [
        f"# Weekly CTA Plan, {context['week']}",
        "",
        f"Run completed: {context['run_completed_at']}",
        f"Generator model: `{context['generator_model']}` - Reviewer model: `{context['reviewer_model']}`",
        "",
        "## Run stats",
        "",
        f"- Blogs reviewed: {context['n_blogs']}",
        f"- LLM proposals generated: {context['total_proposed']}",
        f"- Approved (queued for deploy): {context['n_approved']}",
        f"- Sent to human review: {context['n_human_review']}",
        f"- LLM tokens: {context['prompt_tokens']} in / {context['completion_tokens']} out",
        f"- LLM spend: ${_money(context['cost_usd'], 4)} of ${_money(context['cost_cap'], 2)} cap",
        "",
        f"## Approved changes ({context['n_approved']})",
        "",
    ]
    _append_approved(lines, context["approved"])
    lines.extend(["", f"## Kept as-is ({context['n_kept']})", ""])
    _append_simple_list(lines, context["kept"])
    lines.extend(["", f"## Retired ({context['n_retired']})", ""])
    _append_simple_list(lines, context["retired"], retired=True)
    lines.extend(["", f"## Needs human review ({context['n_human_review']})", ""])
    _append_human_review(lines, context["human_review"])
    return "\n".join(lines).rstrip() + "\n"


def week_dir(week_label: str) -> Path:
    out = config.ARTIFACTS_DIR / f"week-{week_label}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_artifacts(
    *,
    week_label: str,
    plan_context: dict[str, Any],
) -> Path:
    out = week_dir(week_label)
    (out / "plan.md").write_text(render_plan_md(plan_context), encoding="utf-8")
    return out


class AuditLog:
    """Tiny helper that timestamps decisions for dry-run output."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def log(self, event: str, **payload: Any) -> None:
        self.entries.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            **payload,
        })

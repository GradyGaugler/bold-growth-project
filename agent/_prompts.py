"""Shared prompt helpers for generator + reviewer.

Both agents load a `## System` / `## User template` markdown file and both
need a tiny "current CTA as JSON or null" block in the user prompt. Keep the
catalog formatting in each agent because the two callers want different
fields (generator wants summaries; reviewer wants a terse URL: title list).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SYS_MARKER = "## System"
_USER_MARKER = "## User template"


def _heading_start(text: str, marker: str) -> int:
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip() == marker:
            return offset
        offset += len(line)
    raise ValueError(f"Prompt file is missing heading: {marker}")


def load_prompt(path: Path) -> tuple[str, str]:
    """Return (system_prompt, user_template) parsed from a prompt markdown file."""
    text = path.read_text(encoding="utf-8")
    sys_start = _heading_start(text, _SYS_MARKER) + len(_SYS_MARKER)
    user_start = _heading_start(text, _USER_MARKER)
    system = text[sys_start:user_start].strip()
    user = text[user_start + len(_USER_MARKER):].strip()
    return system, user


def current_cta_block(current_cta: dict[str, Any] | None) -> str:
    """Compact JSON view of a deployed CTA, or a 'null' sentinel string."""
    if not current_cta:
        return "null (this blog has no CTA yet)"
    return json.dumps(
        {k: current_cta.get(k) for k in ("target_url", "headline", "body")},
        indent=2,
    )

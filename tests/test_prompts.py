"""Unit tests for prompt loading."""

from __future__ import annotations

from agent import config
from agent._prompts import load_prompt


def test_load_prompt_ignores_heading_names_in_comments():
    system_prompt, user_template = load_prompt(config.PROMPTS_DIR / "generator.md")

    assert "{banned_phrases}" in system_prompt
    assert "{blog_url}" in user_template
    assert "{placeholders}" not in system_prompt
    assert "{placeholders}" not in user_template

"""Persistent state for deployed CTAs and their history.

Single JSON file, atomic write (temp + rename) so a crashed run can't corrupt
it. Keyed by blog URL so re-runs see what the last run shipped.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import config

logger = logging.getLogger(__name__)


def _empty_state() -> dict[str, Any]:
    return {"blogs": {}, "last_run_at": None}


def load_state() -> dict[str, Any]:
    if not config.STATE_FILE.exists():
        return _empty_state()
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.error("corrupt state at %s, starting fresh", config.STATE_FILE)
        return _empty_state()


def save_state(state: dict[str, Any]) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="cta_state_", suffix=".json", dir=config.STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, config.STATE_FILE)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def get_blog_state(state: dict[str, Any], blog_url: str) -> dict[str, Any]:
    return state["blogs"].get(blog_url, {
        "current_cta": None,
        "content_hash_at_deploy": None,
        "history": [],
        "rewrite_count_without_lift": 0,
    })


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record_deploy(
    state: dict[str, Any],
    *,
    blog_url: str,
    new_cta: dict[str, Any],
    content_hash: str,
    action: str,
    perf_snapshot: dict[str, Any] | None,
) -> None:
    """Mutate `state` in place to record a deploy. Caller is responsible for save_state."""
    blog = get_blog_state(state, blog_url)
    prior = blog.get("current_cta")
    if prior:
        history_entry = {
            **prior,
            "retired_at": now_iso(),
            "action_when_replaced": action,
            "perf_snapshot": perf_snapshot,
        }
        blog["history"] = (blog.get("history") or []) + [history_entry]

    if action == "rewrite":
        blog["rewrite_count_without_lift"] = blog.get("rewrite_count_without_lift", 0) + 1
    if action == "add":
        blog["rewrite_count_without_lift"] = 0

    blog["current_cta"] = {
        **new_cta,
        "deployed_at": now_iso(),
    }
    blog["content_hash_at_deploy"] = content_hash

    state["blogs"][blog_url] = blog


def record_retire(state: dict[str, Any], *, blog_url: str, perf_snapshot: dict[str, Any] | None) -> None:
    blog = get_blog_state(state, blog_url)
    prior = blog.get("current_cta")
    if prior:
        blog["history"] = (blog.get("history") or []) + [
            {
                **prior,
                "retired_at": now_iso(),
                "action_when_replaced": "retire",
                "perf_snapshot": perf_snapshot,
            }
        ]
    blog["current_cta"] = None
    blog["content_hash_at_deploy"] = None
    blog["rewrite_count_without_lift"] = 0
    state["blogs"][blog_url] = blog


def reset_rewrite_counter(state: dict[str, Any], blog_url: str) -> None:
    blog = get_blog_state(state, blog_url)
    blog["rewrite_count_without_lift"] = 0
    state["blogs"][blog_url] = blog

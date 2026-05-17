"""Hard rules. The LLM cannot waive these.

Organized by where in the pipeline they fire:

- `should_skip_blog` : pre-generator (filter the queue)
- `check_proposal_structure` : post-generator, pre-reviewer (cheap structural checks)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import logging
from typing import Any
from urllib.parse import urlparse

import requests

from agent import config

logger = logging.getLogger(__name__)


@dataclass
class GuardrailFailure:
    code: str
    detail: str


@dataclass
class StructureCheck:
    """Result of post-generator structural checks. `failures` empty == pass."""

    failures: list[GuardrailFailure]

    @property
    def ok(self) -> bool:
        return not self.failures


def should_skip_blog(
    *,
    current_cta: dict[str, Any] | None,
    today: datetime,
) -> GuardrailFailure | None:
    """Pre-generator: filter blogs we won't touch this run. None => proceed."""
    if current_cta and current_cta.get("deployed_at"):
        deployed = _parse_iso(current_cta["deployed_at"])
        age_days = (today - deployed).days
        if age_days < config.MIN_CTA_AGE_DAYS:
            return GuardrailFailure(
                "min_age",
                f"CTA deployed {age_days}d ago, below MIN_CTA_AGE_DAYS={config.MIN_CTA_AGE_DAYS}",
            )
    return None


def _parse_iso(s: str) -> datetime:
    # Tolerate trailing Z (which fromisoformat doesn't accept on some Pythons).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Process-wide cache so we don't HEAD the same catalog URL once per proposal.
# Cleared by `reset_url_cache()` between test runs.
_url_resolve_cache: dict[str, bool] = {}


def reset_url_cache() -> None:
    _url_resolve_cache.clear()


def _url_resolves(url: str) -> bool:
    """HEAD request; treat 2xx/3xx as ok. Network errors fail closed.

    Result is memoized for the lifetime of the process - the catalog is
    fixed within a run, so 5-15 proposals shouldn't issue 5-15 HEADs.
    """
    if url in _url_resolve_cache:
        return _url_resolve_cache[url]
    try:
        resp = requests.head(
            url,
            allow_redirects=True,
            timeout=config.SCRAPE_TIMEOUT_SECONDS,
            headers={"User-Agent": config.SCRAPE_USER_AGENT},
        )
        if resp.status_code < 400:
            _url_resolve_cache[url] = True
            return True
        # Some hosts 405 HEAD; fall back to GET.
        if resp.status_code == 405:
            resp = requests.get(
                url,
                timeout=config.SCRAPE_TIMEOUT_SECONDS,
                headers={"User-Agent": config.SCRAPE_USER_AGENT},
            )
            ok = resp.status_code < 400
            _url_resolve_cache[url] = ok
            return ok
        _url_resolve_cache[url] = False
        return False
    except requests.RequestException as exc:
        logger.warning("HEAD %s failed: %s", url, exc)
        # Don't cache transient failures - retry next time.
        return False


def check_proposal_structure(
    *,
    proposal: dict[str, Any],
    catalog_urls: set[str],
    current_cta: dict[str, Any] | None,
    verify_url_live: bool = True,
) -> StructureCheck:
    """Run all post-generator structural checks. Cheap, no LLM calls."""
    failures: list[GuardrailFailure] = []

    target = proposal.get("target_url", "")
    headline = proposal.get("headline", "")
    body = proposal.get("body", "")

    # Catalog membership (defense in depth - schema enum should make this impossible).
    if target not in catalog_urls:
        failures.append(
            GuardrailFailure("off_catalog", f"target_url {target!r} not in catalog")
        )

    # On-domain.
    host = urlparse(target).netloc.lower()
    if host and host != "bold.org" and not host.endswith(".bold.org"):
        failures.append(
            GuardrailFailure("off_domain", f"target_url host {host!r} is not bold.org")
        )

    # Length caps (also schema-enforced; belt and suspenders).
    if len(headline) > config.HEADLINE_MAX_CHARS:
        failures.append(GuardrailFailure("headline_too_long", f"{len(headline)} > {config.HEADLINE_MAX_CHARS}"))
    if len(body) > config.BODY_MAX_CHARS:
        failures.append(GuardrailFailure("body_too_long", f"{len(body)} > {config.BODY_MAX_CHARS}"))

    # Similarity vs current CTA (don't churn for cosmetic changes).
    if current_cta and current_cta.get("headline") is not None:
        cur_blob = (current_cta.get("headline", "") + " | " + current_cta.get("body", "")).strip()
        new_blob = (headline + " | " + body).strip()
        similarity = SequenceMatcher(None, cur_blob, new_blob).ratio()
        if cur_blob and similarity >= config.SIMILARITY_REJECT_THRESHOLD:
            failures.append(
                GuardrailFailure(
                    "no_op_change",
                    f"proposed copy >= {config.SIMILARITY_REJECT_THRESHOLD} similar to current",
                )
            )

    # Live URL check last - it's the slowest. Skip if anything already failed.
    if verify_url_live and not failures and not _url_resolves(target):
        failures.append(GuardrailFailure("dead_link", f"HEAD {target} did not return 2xx/3xx"))

    return StructureCheck(failures=failures)

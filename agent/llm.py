"""Thin OpenAI client wrapper.

Exposes one function, `call_json`, that returns a validated dict via
structured outputs (JSON schema). Tracks tokens + spend per run and raises
`CostCapExceeded` before issuing the next call if the running total would
cross `config.MAX_RUN_COST_USD`. This is the run-level kill switch.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from openai import APIError, APIConnectionError, RateLimitError

from agent import config

logger = logging.getLogger(__name__)


class CostCapExceeded(Exception):
    """Raised when the cost meter would cross `MAX_RUN_COST_USD`."""


@dataclass
class CallRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    purpose: str


@dataclass
class CostMeter:
    """Per-run tally. One meter is constructed in run.py and threaded through."""

    cap_usd: float = config.MAX_RUN_COST_USD
    total_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    calls: list[CallRecord] = field(default_factory=list)

    def estimate(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        prices = config.TOKEN_PRICES_PER_MTOK.get(model)
        if not prices:
            return 0.0
        return (
            prompt_tokens * prices["input"] / 1_000_000
            + completion_tokens * prices["output"] / 1_000_000
        )

    def charge(self, record: CallRecord) -> None:
        self.total_cost_usd += record.cost_usd
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.calls.append(record)

    def check_headroom(self, estimated_next_cost_usd: float) -> None:
        if self.total_cost_usd + estimated_next_cost_usd > self.cap_usd:
            raise CostCapExceeded(
                f"would exceed ${self.cap_usd:.2f} cap "
                f"(spent ${self.total_cost_usd:.4f}, next call ~${estimated_next_cost_usd:.4f})"
            )


_client: OpenAI | None = None


def _client_singleton() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI(api_key=key)
    return _client


def call_json(
    *,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    schema_name: str,
    model: str,
    meter: CostMeter,
    purpose: str,
    reasoning_effort: str | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """One LLM call returning a dict that conforms to `schema`.

    `purpose` is a free-form string ("generator", "reviewer", ...) used only
    for cost-attribution logging in the run audit log. `reasoning_effort` is
    passed through to OpenAI's `reasoning_effort` param when set; valid values
    are "minimal" | "low" | "medium" | "high" | "xhigh".
    """
    # Pre-check: bail early if we have basically no headroom left.
    meter.check_headroom(estimated_next_cost_usd=0.001)

    client = _client_singleton()
    attempt = 0
    last_err: Exception | None = None
    extra_kwargs: dict[str, Any] = {}
    if reasoning_effort is not None:
        extra_kwargs["reasoning_effort"] = reasoning_effort
    while attempt <= max_retries:
        start = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
                **extra_kwargs,
            )
        except (RateLimitError, APIConnectionError) as exc:
            last_err = exc
            wait = 2 ** attempt
            logger.warning("transient LLM error %s, retrying in %ss", exc, wait)
            time.sleep(wait)
            attempt += 1
            continue
        except APIError as exc:
            last_err = exc
            logger.error("LLM API error: %s", exc)
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = meter.estimate(model, prompt_tokens, completion_tokens)

        record = CallRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            purpose=purpose,
        )
        meter.charge(record)
        # After-charge cap check: if THIS call put us over, future calls bail.
        if meter.total_cost_usd > meter.cap_usd:
            logger.warning(
                "cost cap exceeded after %s call: $%.4f > $%.2f",
                purpose, meter.total_cost_usd, meter.cap_usd,
            )

        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            # Schema-strict should make this impossible, but defend anyway.
            last_err = exc
            logger.warning("invalid JSON from LLM despite strict schema: %s", exc)
            attempt += 1
            continue

    raise RuntimeError(f"LLM call exhausted retries: {last_err}")

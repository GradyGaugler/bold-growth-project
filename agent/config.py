"""Central configuration: paths, thresholds, model names, hard limits.

Everything tunable lives here so reviewers can see policy in one place
rather than hunting through modules.
"""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT_DIR / "agent"
PROMPTS_DIR = AGENT_DIR / "prompts"
MOCKS_DIR = ROOT_DIR / "mocks"
STATE_DIR = ROOT_DIR / "state"
CACHE_DIR = STATE_DIR / "cache"
ARTIFACTS_DIR = ROOT_DIR / "human" / "artifacts"

STATE_FILE = STATE_DIR / "cta_state.json"

SEED_BLOGS_FILE = MOCKS_DIR / "seed_blogs.json"
SEED_CATALOG_FILE = MOCKS_DIR / "seed_catalog.json"
CTA_PERFORMANCE_FILE = MOCKS_DIR / "cta_performance.json"
SITE_BASELINE_FILE = MOCKS_DIR / "site_baseline.json"

# Model selection. Generator can be cheaper; reviewer should be at least as strong.
# Effort knobs are passed straight through as OpenAI's `reasoning_effort` param
# ("minimal" | "low" | "medium" | "high" | "xhigh"). We pair a cheap model with
# high effort on the generator (small per-call ceiling, room to think) and a
# stronger model with medium effort on the reviewer (already capable; don't
# over-pay for deliberation on a yes/no judgment).
GENERATOR_MODEL = "gpt-5.4-mini"
GENERATOR_EFFORT = "high"
REVIEWER_MODEL = "gpt-5.4"
REVIEWER_EFFORT = "medium"

# Run-level guardrails.
MAX_REWRITES_WITHOUT_LIFT = 3
MAX_RUN_COST_USD = 1.00

# Copy + quality limits.
HEADLINE_MAX_CHARS = 70
BODY_MAX_CHARS = 200
SIMILARITY_REJECT_THRESHOLD = 0.85  # difflib ratio vs current CTA
REVIEWER_APPROVAL_FLOOR = 0.7  # both relevance + copy quality must clear this

# Prioritization tuning.
PRIORITY_TOP_N = 5  # blogs to act on per week
CTR_FLOOR = 0.005  # below this -> action `rewrite`
CTR_STRONG = 0.02  # at or above -> action `keep` (no LLM call)

# Network hygiene for scraping bold.org.
SCRAPE_USER_AGENT = "bold-growth-agent/0.1 (take-home; respectful crawler)"
SCRAPE_RATE_LIMIT_SECONDS = 1.0
SCRAPE_TIMEOUT_SECONDS = 15

# Brand-voice hints inlined into the generator prompt. The reviewer agent
# enforces brand safety; there is no separate post-check.
BANNED_PHRASES = [
    "guaranteed",
    "free money",
    "no strings attached",
    "easy cash",
    "win big",
    "click here",
    "notorious",
    "100% free",
]

# Token pricing (USD per 1M tokens). Approximate; only used to enforce the cost cap.
# Update if real prices drift; the cap is the real safety net regardless.
TOKEN_PRICES_PER_MTOK = {
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    # Kept for compatibility with older local runs.
    "gpt-5": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
}

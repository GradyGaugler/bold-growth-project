# Part 3 - Avoiding fake wins

The three agents (Part 1, 2a, 2b) all measure their own success - which makes it easy to declare wins that aren't real. Four failure modes to defend against, plus the hard-coded seatbelts.

## Instrumentation bugs

`EVENT_SANITY` already has tells:

- `account_created > session_start` - impossible.
- `donor_registration ≈ donor_registration2` - duplicate event.
- GA4↔ClickHouse ratios pinned near `0.5` - one side double-counts.
- `click` count suspiciously small - under-fires or deprecated.

I'd run an event-triggered watchdog one hour after every deploy, flag flip, or CMS publish (gives traffic time to accumulate) that checks:

- **Hard invariants** - child-event count ≤ parent-event count.
- **Pair-relation bands** - registered event pairs stay within tolerance (e.g. `donor_registration / donor_registration2` in `[0.85, 1.15]`).
- **GA4↔ClickHouse parity** - per-event ratio stays in `[0.4, 0.6]` (band tuned to `EVENT_SANITY` baseline)

When a failure is identified, the agent:

1. Pings team in Slack
2. Generates a Linear issue with an RCA
3. Generates a PR with a potential fix requiring human review

## Traffic-mix shifts

A CTA's CTR can "improve" purely because the mix changed - more mobile, less branded search, fewer returning users.

- **Matched-cohort comparison** - Compare new CTA performance against the same blog's prior 4 weeks, segmented by device + traffic source + new/returning. Not the blended number.
- **Mix-drift alert** - If device split, branded/non-branded GSC, or paid/organic moves >10% week-over-week, decisions off blended numbers are suspect → human review.
- **Held-out control** - Keep ~20% of comparable blogs untouched. Lift only counts if treated beats held-out by more than mix drift alone explains.

## Downstream quality regressions

CTR is the easiest metric to game. The real goal is verified applications and Day-7 activation.

- **Always measure end-to-end** - Every CTA tracks click → SGP submit → verified application → D7. PostHog charts with alerts on each step.
- **Regression rule** - If CTA clicks rise but submit / verify / D7 fall below baseline, auto-retire or route to human review. Encoded in Part 1's analytics guardrails; applies to 2a too.

## Hard-coded guardrails

Per system, seatbelts that don't depend on the LLM behaving:

- **Cost cap per run** - raises `CostCapExceeded` before the next call ($1 for Part 1, $2 for 2a).
- **Run cap** - max items acted on per run (5 blogs, 3 new SGPs), at least for early stages.
- **Brand-safety blocklist** - banned phrases enforced in code, not just in the prompt.
- **Similarity threshold** - reject minimal, cosmetic rewrites.
- **Reviewer approval floor** - relevance + copy scores both ≥ `REVIEWER_APPROVAL_FLOOR` (0.7 in Part 1) before anything ships.
- **Namespace allow-list** - new pages only in approved URL paths (2a); 2b PRs only touch `llms.txt`, canonicals, and redirects (no body copy).
- **Kill switch** - any downstream regression check fires → all recurring agents pause until a human clears.


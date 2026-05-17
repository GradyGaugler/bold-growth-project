# Sample output

Two real weekly runs against bold.org with the real OpenAI API (`gpt-5-mini` generator, `gpt-5` reviewer). Committed so reviewers can see the human-reviewable `plan.md` output without running the agent themselves.

## Files

- `week-1-2026-05-16/plan.md` - first run on an empty state. Five blogs, five approved `add` actions. ~$0.19 of LLM spend.
- `cta_performance_after_week1_simulation.json` - deterministic mocked perf produced by `python3 -m agent.run --simulate-perf` between the two runs. This is the stand-in for what GA4 / ClickHouse would return one week later.
- `week-2-2026-05-23/plan.md` - second run. The loop behaves differently because the state and perf inputs changed:
  - **3 blogs kept** (in-band CTR, no LLM call - cost discipline)
  - **1 blog rewritten** (CTR below floor, reviewer approved the new copy)
  - **1 blog routed to human review** (reviewer wanted tighter copy than
    the generator could produce in one revise loop)
- `cta_state_after_week2.json` - the persisted state file after both runs.

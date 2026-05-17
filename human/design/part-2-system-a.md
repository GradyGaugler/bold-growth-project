# Part 2a - Persona SGP Generator

**Shape:** recurring loop. **One-liner:** weekly job that finds underserved student personas with real search demand and drafts a new persona-targeted SGP for each, queued as a human-approvable artifact.

## Problem and why this one

`TOP_PUBLIC_LANDING_PAGES` shows persona-targeted SGPs convert dramatically better than generic ones: nursing ~46%, Black-students ~71%, vs ~8% on
`merit-based` and `easy-scholarships`. One of the biggest lifts Bold can achieve is **more persona SGPs aimed at real demand**. This system is the supply-side complement to Part 1: routing into the catalog only compounds if the catalog keeps getting better destinations.

## Why a loop (not one-shot or event-triggered)

Identifying personas and nailing the persona fit takes a lot of iteration. You can't do it in one go.

## Trigger

Cron, weekly.

## Data and tools

- **GSC** - per-query impressions, position, CTR; used to size persona demand.
- **GA4 + ClickHouse** - conversion by existing SGP, by referrer persona.
- **Existing SGP catalog** - to avoid cannibalization (schema-enum, same pattern as Part 1).
- **Blog post titles + tags** - surface emerging personas Bold already audiences (e.g. low-GPA, older students, single parents).
- **LLM** - generator (drafts page: title, hero, intro, FAQ, slug, target keyword), reviewer (separate context: relevance + copy quality + legal sensitivity).

## State between runs

The loop keeps a simple history of everything it has tried, so each weekly run can build on prior judgment instead of starting over:

- **Live pages** - which persona SGPs are currently published, where they live, when they launched, and how they are performing.
- **Iterations** - what the agent already rewrote or adjusted, so it can tell whether changes helped instead of repeatedly making the same move.
- **Retired pages** - which personas were removed after sustained underperformance, so the agent does not keep reviving failed ideas.
- **Rejected ideas** - personas that were blocked for being too weak, duplicative, or sensitive, so bad candidates do not reappear every week.

## Decision rules

Per candidate persona each week, pick one of:

- `propose` - demand ≥ `MIN_GSC_IMPRESSIONS_30D = 2000`, no live SGP within `KEYWORD_OVERLAP = 0.7` of the target keyword, not on the `sensitive_personas` block-list.
- `rewrite` - live SGP, `submit_rate < 0.08` after `MIN_LIVE_DAYS = 28` (i.e. worse than the weakest existing generic SGP - the persona angle isn't earning its keep).
- `retire` - live SGP, `consecutive_weeks_no_lift >= 6`.
- `keep` - anything else.

## Guardrails

Similar to part 1

### Script / output guardrails

Before a draft reaches a PM:

- **Legal safety** - block sensitive personas or anything that could imply discriminatory eligibility.
- **Approved paths** - keep new pages inside approved URL paths (`/by-life-situation/`, `/by-major/`, `/by-background/`).
- **No duplicates** - check that the page is not a duplicate of an existing SGP and does not reuse the same angle with slightly different wording.
- **Reviewer check** - have a separate reviewer agent score persona fit, brand safety, legal sensitivity, and cannibalization risk.
- **Run cap** - cap the loop at 3 new SGPs and $2 of LLM spend per week.

### Analytics / business guardrails

The agent should also prove new persona pages are helping the funnel, not just creating more pages:

- **Search performance check** - make sure new pages get indexed and are not causing meaningful GSC impression or ranking drops on existing SGPs.
- **Conversion checks** - monitor submit rate, verified application rate, and D7 activation for each new or rewritten persona SGP.
- **Regression rule** - if a new page gets search traffic but submit / verify / activation rates are meaningfully worse than baseline, or if it cannibalizes a stronger existing SGP, route it back to human review instead of expanding the pattern.

## How you'd know it's working

- **Leading:** new SGPs clear the ~8% baseline within 30 days; trending toward persona-SGP territory (40–70%).
- **Lagging:** persona-SGP submits as a share of site submits trends up week-over-week without cannibalizing other high-performing SGPs.
- **Quality:** reviewer approval rate stays in a 50–80% band. Too low means the generator drifts; too high means the reviewer rubber-stamps.
- **Negative signal:** GSC impressions drop on existing SGPs after a new one launches → cannibalization, retire the new page.

## How you'd graduate it toward acting without you

1. **Today:** human approves every proposed page in `plan.md` before any CMS write. `retire` is also human-gated. Limited to 3 per week
2. **Next:** When 80% is approved, switch to auto rewrite and retire; humans still gate net-new pages. LLM won't publish anything below confidence threshold.
3. **Later:** When 80% do not require changes, expand to auto publish. Humans review only the weekly summary. LLM won't publish anything below confidence threshold.


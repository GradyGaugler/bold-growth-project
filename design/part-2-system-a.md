# Part 2a - Persona SGP Generator

**Shape:** recurring loop. **One-liner:** weekly job that finds underserved student personas with real search demand and drafts a new persona-targeted SGP for each, queued as a human-approvable artifact.

## Problem and why this one

`TOP_PUBLIC_LANDING_PAGES` shows persona-targeted SGPs convert dramatically better than generic ones: nursing ~46%, Black-students ~71%, vs ~8% on
`merit-based` and `easy-scholarships`. One of the biggest lifts  
Bold can achieve is **more persona SGPs aimed at real demand**. This system is the supply-side complement to Part 1: routing into the catalog only compounds if the catalog keeps getting better destinations.

## Why a loop (not one-shot or event-triggered)

Identifying personas and nailing the persona fit takes a lot of iteration. You can't do it in one go.

## Trigger

Cron, weekly (same cadence as Part 1, offset by a day so artifacts don't pile up).

## Data and tools

- **GSC** — per-query impressions, position, CTR; used to size persona demand.
- **GA4 + ClickHouse** — conversion by existing SGP, by referrer persona.
- **Existing SGP catalog** — to avoid cannibalization (schema-enum, same pattern as Part 1).
- **Blog post titles + tags** — surface emerging personas Bold already audiences (e.g. low-GPA, older students, single parents).
- **LLM** — generator (drafts page: title, hero, intro, FAQ, slug, target keyword), reviewer (separate context: relevance + copy quality + legal sensitivity).

## State between runs

`state/persona_state.json`:

```jsonc
{
  "personas": {
    "single-parents": {
      "status": "live",           // proposed | live | retired
      "sgp_url": "/scholarships/by-life-situation/single-parents",
      "launched_at": "2026-05-09",
      "gsc_impressions_30d": 4200,
      "submits_30d": 38,
      "consecutive_weeks_no_lift": 0
    }
  },
  "tried_and_rejected": ["lottery-winners-scholarships"]  // dedup
}
```

## Decision rules

Per candidate persona each week, pick one of:

- `propose` — demand ≥ `MIN_GSC_IMPRESSIONS_30D = 2000`, no live SGP within `KEYWORD_OVERLAP = 0.7` of the target keyword, not on the `sensitive_personas` block-list.
- `rewrite` — live SGP, `submit_rate < 0.08` after `MIN_LIVE_DAYS = 28` (i.e. worse than the weakest existing generic SGP — the persona angle isn't earning its keep).
- `retire` — live SGP, `consecutive_weeks_no_lift >= 6`.
- `keep` — anything else.

## Guardrails (four layers, mirroring Part 1)

- **Before the agent runs.** Skip personas on a legal block-list (where an *eligibility* requirement could discriminate against a protected class).
- **Inside the prompt.** Reuse Part 1's banned phrases. Constrain the slug to a pre-approved URL prefix (`/by-life-situation/`*, `/by-major/*`, `/by-background/*`) so the agent can't invent a new namespace.
- **After the agent writes the page.** Reject on cannibalization (title or headline too similar to an existing SGP), slug collision, or length caps.
- **At the run level.** Max 2 new SGPs per week. $2 hard cap on LLM spend per run.

## How you'd know it's working

- **Leading:** new SGPs clear the ~8% baseline within 30 days; trending toward persona-SGP territory (40–70%) within 90.
- **Lagging:** persona-SGP submits as a share of site submits trends up week-over-week without cannibalizing other high-performing SGPs.
- **Quality:** reviewer approval rate stays in a 50–80% band. Too low means the generator drifts; too high means the reviewer rubber-stamps.
- **Negative signal:** GSC impressions drop on existing SGPs after a new one launches → cannibalization, retire the new page.

## How you'd graduate it toward acting without you

1. **Today:** human approves every proposed page in `plan.md` before any CMS write. `retire` is also human-gated.
2. **Next:** auto-publish `rewrite` of live SGPs that have a high confidence level and auto retire pages that are not performing; humans still gate net-new pages.
3. **Later:** auto-publish net-new SGPs in a small ringfenced URL namespace (e.g. `/scholarships/by-life-situation/`*). Humans review only the weekly summary.


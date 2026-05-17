# Part 3 - Instrumentation Watchdog

**Shape:** event-triggered.  
**One-liner:** anomaly-driven agent that watches event-count health, files a plain-English incident the moment something violates a known invariant, and proposes the root-cause hypothesis a data engineer would write themselves.

## Problem and why this one

`EVENT_SANITY` has indications of a number of issues:

- `account_created > session_start` - impossible by definition.
- `donor_registration` ≈ `donor_registration2` - near-identical counts, likely duplicate event.
- GA4↔ClickHouse ratios pinned near `0.5` across the board - one side double-counts.
- `click` event count is suspiciously small. It under-fires or is deprecated.

You can't trust the system if the data is wrong.

## Why event-triggered (not loop or one-shot)

Instrumentation regressions can be caused by a deploy, flag flip, or CMS  
publish - so the change itself is the trigger. A weekly loop would let a  
broken event fire wrong for days.

## Trigger

One hour after any of:

- a **code deploy** lands (production push webhook),
- a **feature flag** flips (LaunchDarkly / Statsig webhook), or
- a **CMS publish** (Bold's content stack).

The 1-hour delay gives traffic time to accumulate enough volume for the checks to be meaningful. On fire, the agent runs its detectors against the trailing window:

- a **hard invariant** is violated (`account_created > session_start`, `submit > session_start`, child-event > parent-event),
- a **pair-relation** drifts outside its registered band (e.g. `donor_registration` / `donor_registration2` ratio leaves `[0.85, 1.15]`),
- a **GA4↔ClickHouse parity** for any event leaves `[0.4, 0.6]` (using the baseline already visible in the data), or

Any check failing → file an incident.

## Output

Identified issues will result in a team Slack message, Linear issues created with an RCA, and initial PR generated human need to review.
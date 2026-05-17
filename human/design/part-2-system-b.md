# Part 2b - AI-Discoverability PR Generator

**Shape:** one-shot generator.  
**One-liner:** one PR ships an `llms.txt` for the site and patches the canonicals flagged in `TECH_INDEX_SIGNALS`; an `AGENTS.md` rule + a PR check keep future changes compliant.

## Problem and why this one

`llms.txt` 404s. Result: Bold gets crawled but not *cited* by Google rich results or AI assistants. This is a quick, low effort improvement that has potential for medium impact.

## Why one-shot (not loop or event-triggered)

Structural fix. Run once to backfill, including:

- `AGENTS.md` rule - new page types must ship with an `llms.txt` entry.
- **PR check** - CI agent comments when template/sitemap diffs miss the entry.

## Trigger

Manual, one-time. Re-run only when the catalog shape changes if needed (new page type or URL namespace), however the new LLM rule and PR check should help avoid that.

## Data and tools

- **Sitemap + crawler** - enumerate every indexable URL by page type.
- `TECH_INDEX_SIGNALS` - per-URL canonical, redirect, and robots state.
- **LLM** - generator (drafts `llms.txt` sections grouped by surface + topic), reviewer (validates factual accuracy of each section against the live pages).

## What it outputs

A single GitHub PR with:

- `public/llms.txt` - structured site map for AI assistants.
- Canonical / redirect patches for the handful of pages flagged in `TECH_INDEX_SIGNALS`.
- `[AGENTS.md](../../AGENTS.md)` rule line added to the repo root doc.
- PR check rule for future changes.

## Decision rules

- **Per URL** - skip if `noindex`, non-200, canonical points elsewhere, or outside approved namespaces (no auth/admin/checkout). Otherwise include in `llms.txt`, grouped by surface.
- **Per URL canonical/redirect** - only patch the specific URLs `TECH_INDEX_SIGNALS` flags as broken. Leave healthy ones alone.
- **Abort PR** - if diff exceeds 50 files or the `llms.txt` parse check fails.

## Guardrails

- **Parser-bound output** - `llms.txt` must parse cleanly against the llmstxt.org spec and every URL must return 200 before it lands in the PR (deterministic check, not LLM-judged).
- **URL hygiene** - Every URL must be canonical (not a redirect, not `noindex`) and outside blocked namespaces (auth, admin, staging) - keeps AI crawlers off the wrong pages.
- **No copy edits** - Agent touches `llms.txt`, canonicals, and redirects only; never user-facing body content (that's Parts 1 and 2a's job).

## How you'd know it's working

- **Leading** - `llms.txt` returns 200
- **Lagging** - AI-assistant citations of [bold.org](http://bold.org) trend up over 60 days

## Graduation

The backfill PR is always human-merged - this is a dev tool, not an autonomous system. The two recurring pieces (LLM rule and PR check) start as "file a PR / leave a comment" and can graduate to auto-merge once the team believes it's reliable and beneficial.

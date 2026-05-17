# Part 2b - AI-Discoverability PR Generator

**Shape:** one-shot generator.  
**One-liner:** one PR fixes `llms.txt`, adds JSON-LD, patches canonicals; an `AGENTS.md` rule + a PR check keep future changes compliant.

## Problem and why this one

`llms.txt` 404s. Result: Bold gets crawled but not *cited* by Google rich results or AI assistants. This is a quick, low effort improvement that has potential for medium impact.

## Why one-shot (not loop or event-triggered)

Structural fix. Run once to backfill, including:

- **`AGENTS.md` rule** — new page types must ship with JSON-LD + an `llms.txt` entry.
- **PR check** - CI agent comments when template/sitemap diffs miss structured data.

Re-run only when the catalog shape changes (new page type or URL namespace).

## Data and tools

- **Sitemap + crawler** - enumerate every indexable URL by page type.
- **`TECH_INDEX_SIGNALS`** — per-URL canonical, redirect, robots, JSON-LD state.
- **LLM** - generator (drafts `llms.txt` sections, JSON-LD blocks per page type), reviewer (validates schema.org compliance + factual accuracy against the live page).

## What it outputs

A single GitHub PR with:

- `public/llms.txt` - structured site map for AI assistants.
- JSON-LD blocks injected into page templates per type (SGP, scholarship-detail, blog).
- Canonical / redirect patches for the handful of pages flagged in `TECH_INDEX_SIGNALS`.
- [`AGENTS.md`](../AGENTS.md) rule line added to the repo root doc.
- PR check rule.

## Guardrails

- **Schema-bound output.** JSON-LD must validate against schema.org before it lands in the PR (deterministic check, not LLM-judged).
- **No copy edits.** Agent touches structured data and `<head>` only; never user-facing body content (that's Parts 1 and 2a's job).

## How you'd know it's working

- **Leading:** `llms.txt` returns 200
- **Lagging:** AI-assistant citations of [bold.org](http://bold.org) trend up over 60 days


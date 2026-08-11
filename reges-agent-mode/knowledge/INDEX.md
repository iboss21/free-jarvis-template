---
id: kb-index
title: Knowledge pack index and staleness policy
verified_on: 2026-08-11
ttl_days: 30
---

# Knowledge pack

Volatile world-facts the model cannot know from training. Loaded on demand, never baked into weights, never baked into the system prompt.

## Why this exists separately from skills

A skill is a procedure. Procedures are stable — bake them anywhere you like.
An entry here is a fact about a third party who can change it without telling you. Three entries below changed within thirty days of writing. One changed four days before.

**Never fine-tune on this directory.** Fine-tuning a fact means you cannot expire it. Everything here must stay retrievable, dated, and deletable.

## Staleness contract

| Field | Meaning |
|---|---|
| `verified_on` | Date a human or a verification run last confirmed this against the primary source |
| `ttl_days` | After this many days the entry is treated as ABSENT, not as approximately right |
| `source` | Primary URL. Vendor docs or the platform's own help pages. Never a blog summarising them |
| `volatility` | high / medium / low — sets the default ttl |

Agent mode behaviour on stale: `reverify` + halt the dependent action. See AGENT-MODE.md §2.

## Entries

| id | topic | volatility | ttl |
|---|---|---|---|
| kb-001 | Platform monetization policy | high | 30d |
| kb-002 | Publishing APIs, quotas, approval lead times | high | 30d |
| kb-003 | Monetization rails and payment infrastructure | medium | 60d |
| kb-004 | Agent architecture findings (benchmarks) | low | 180d |
| kb-005 | Compliance hard-lines | low | 365d |
| kb-006 | Design-asset marketplaces — AI policy, payout, review | medium | 60d |

## Re-verification

`reverify` tasks are worked by a WORKER with web access, one entry per cycle. The worker replaces the body, bumps `verified_on`, and appends to the changelog at the bottom of the entry. It never deletes changelog lines — the history of what changed is itself signal about which platforms are unstable.

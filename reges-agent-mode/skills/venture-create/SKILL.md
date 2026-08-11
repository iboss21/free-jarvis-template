---
name: venture-create
description: Turn an approved candidate into a venture with a binding contract. Kill criteria are written before launch, never after.
role: OPERATOR
tier: 1
triggers: ["launch venture", "create venture", "start experiment"]
requires_kb: [kb-001, kb-003]
allowed_tools: ["Read", "Write"]
cost_ceiling_usd: 0.30
schema: schemas/venture.schema.json
---

# Venture create

A venture is an experiment with a contract. No contract, no launch.

## Required before state moves to BUILDING

- `thesis.md` — niche, ICP, angle, why we win, **numeric success criteria**, **kill criteria**, budget, deadline
- `voice.md` — tone, POV, banned phrases, structural variety rules. This is the input that makes output pass originality bars
- `rails.md` — which kb-003 rails are active, tracking params
- Autonomy level, defaulting to L1

## Kill criteria rules

Write them as evaluable predicates over stored metrics. Not adjectives.

Good: `revenue_usd < 25 by day 45`, `cost_per_asset > revenue_per_asset for 21 consecutive days`, `policy_warning_count >= 1`
Bad: `if it's not working`, `if growth stalls`

Every venture carries at minimum: a revenue floor with a date, a unit-margin condition, and `policy_warning_count >= 1`.

## Autonomy defaults

| Action class | Level |
|---|---|
| Produce assets, stage publishes | L1 |
| Publish approved formats to approved channels | L2 |
| Launch new series inside a live venture, run pricing tests | L3 |
| Discover and kill ventures in approved categories | L4 |

Permanently L1 regardless of setting: entity formation, payment method changes, anything creating a legal or tax obligation, anything published in the operator's personal name, and any post to X (kb-001).

A venture starts at L1 and may be promoted only after 30 days with zero policy incidents.

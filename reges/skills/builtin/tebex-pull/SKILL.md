---
name: tebex-pull
description: Pulls Lux Empire sales per resource from Tebex, records them to metrics, and flags resources whose 7-day trend broke their 28-day baseline.
triggers: [tebex, metrics pull, my sales, how are sales, lux empire numbers, week review]
needs: [vault, secret:tebex_secret, network]
writes: [.reges/metrics.sqlite, raw/]
---

# tebex-pull

## What it does

1. Pulls recent payments from the Tebex API using the stored `tebex_secret`.
2. Records one metric row per resource per day: `source="tebex"`, `key="<package>"`.
3. Compares the 7-day mean against the 28-day baseline for each resource.
4. Writes a capture to `raw/` with the full table.
5. **Speaks only the outliers.** A list of eighteen unchanged resources read aloud
   is noise; two that moved is information.

## Outlier rule

Flag a resource when the 7-day mean deviates from the 28-day baseline by more than
one standard deviation of the 28-day window, and the 28-day window has at least 10
non-zero days. The second condition matters — without it, every newly listed
resource flags on day one, and after a week of false alarms the user stops
listening to the skill entirely.

## Reporting

- Never state a percentage change off a baseline of fewer than 10 data points.
  Say "not enough history yet" instead. A confident number from three data points
  is worse than an admitted gap.
- Report gross, and note that it is gross. Tebex fees, chargebacks, and tax are
  not modelled here and pretending otherwise makes the number a lie.
- If the API call fails, say so plainly. Never fill the gap with the previous
  day's figures — a silently stale number is the worst possible output.

## Unverified

Tebex API endpoint shapes and field names must be confirmed against current Tebex
documentation before this skill's implementation is trusted. Nothing in this file
should be treated as a verified API contract.

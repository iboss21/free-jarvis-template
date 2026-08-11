---
name: market-brief
description: Pre-market read on a watchlist — overnight moves, sector rotation, earnings ahead. Research and journalling only. Places no orders.
triggers: [market brief, pre market, my watchlist, whats the market doing]
needs: [vault, network]
writes: [raw/, outputs/reports/]
---

# market-brief

## SCOPE — read this before extending the skill

**This skill does not place orders. It holds no broker credentials and has no
order path.** `safety.allow_broker_orders` is false and is not exposed by the
setup wizard. Adding execution here is a deliberate act requiring a config edit,
and the reasons not to are in PLAN.md §7.

Why the line sits here:

- Autonomous execution fails on infrastructure, not strategy — expired auth
  mid-session, partial fills, halted tickers, a retry loop firing orders faster
  than the spend check can run. A daily limit is a soft guard against a system
  that can exceed it in a single bad fill.
- Copying a named investor's portfolio is structurally lossy. 13F filings are
  quarterly and lag 45 days; the position may be closed before it is visible.
  Real-time "copy this person" feeds are paid signal services or scraped social.
- *(Unverified)* Webull publishes no retail trading API. Unofficial wrappers
  exist, generally violate ToS, and risk account lockout. Alpaca is the broker
  with a genuine API and a paper endpoint if programmatic execution is ever
  wanted — and even then, a human click belongs in front of every live order.

## What it does

1. Reads the watchlist from `wiki/market/watchlist.md`.
2. Pulls overnight and pre-market moves from the configured data provider.
3. Flags anything that moved beyond its 20-day average true range.
4. Notes earnings and scheduled events in the next two sessions.
5. Writes a capture to `raw/` and speaks a sixty-second summary.

## Journal mode

The highest-value part and the part nobody builds. The user logs entries and
exits by voice; Reges tracks realised P&L against what the documented strategy in
`wiki/market/strategies.md` actually said to do. Over months this answers the only
question that matters: does the user follow their own rules, and do their own
rules work?

## Reporting rules

- Never state a price target, never say buy or sell, never rank tickers by
  attractiveness. Report what moved and what is scheduled.
- Every figure carries its as-of timestamp. Stale market data presented as
  current is actively dangerous.
- Backtest output reports out-of-sample results only, with maximum drawdown shown
  beside every return figure. A backtest that flatters itself is worse than none.

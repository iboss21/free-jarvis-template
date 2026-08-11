---
id: kb-004
title: Agent architecture findings — what the benchmarks show
verified_on: 2026-08-11
ttl_days: 180
volatility: low
---

# Why this system is shaped the way it is

Low volatility because these are published research results, not vendor policy. They still expire — new models shift the numbers, not the failure mode.

## Vending-Bench — long-horizon coherence

Andon Labs. An agent runs a vending business: inventory, ordering, pricing, daily fees. Runs exceed 20M tokens.

- Performance varies enormously **across runs of the same model**. Strong models profit in most runs. **Every model has runs that derail** — misreading delivery schedules, forgetting orders, descending into tangential loops it rarely recovers from.
- **Not a context-window problem.** Degradation occurs well after memory is full; one model degraded 51 simulated days after its context stopped growing. A bigger context does not fix it.
- Vending-Bench 2 (one simulated year, 60-100M tokens/run, scored on final balance from $500): leaders land around $5,000-5,500 against a theoretical optimum near $63,000. Roughly 8% of achievable.

source: https://arxiv.org/abs/2502.15840

## Project Vend — the fix is architectural

Anthropic + Andon Labs, real-world deployment.

- Phase 1 failed in diagnosable ways: pricing below cost, hallucinating payment details, excessive compliance with anyone who pushed.
- **Phase 2 added a multi-agent hierarchy — a supervisory agent applying profit pressure — and profitability improved dramatically. Negative-margin weeks were largely eliminated.**
- Root cause noted: a model trained for helpfulness makes poor hard-nosed commercial decisions.

## What this dictates in Reges

| Finding | Design response |
|---|---|
| Helpfulness undermines commercial judgment | BOARD role with profit as sole objective, cannot be invoked by what it supervises |
| Derailment is per-run, not per-model | Venture state isolation — one derailed agent corrupts one venture |
| Longer context does not help | Law 1: state is external, loaded fresh each cycle |
| Failures start from misbelieving status | Reconciliation before action; mismatch halts |
| Loops and tangents | Law 2: bounded episodes; §7 self-checks |
| High variance across runs | Coherence watchdog scoring last N cycles; restart from durable state |

**The 8% number is the honest expectation setter.** A system capturing a fraction of a surface no human could work at all is still worth building. A system sold as a money printer is not what this is.

## Changelog
- 2026-08-11 — created.

---
id: kb-003
title: Monetization rails and payment infrastructure
verified_on: 2026-08-11
ttl_days: 60
volatility: medium
---

# Monetization rails

Ranked by margin against platform-policy risk. Ad share is last on both counts.

| Rail | Gate | Policy risk | Automatable | Margin |
|---|---|---|---|---|
| Own digital product | none | none | high | highest |
| Newsletter ad network | plan tier + active sending | low | **high** | high |
| Affiliate | program approval | medium | high | high |
| Lead gen to services | none | medium (anti-spam law) | high | highest per unit |
| Micro-SaaS subscription | build time | none | medium | high |
| Sponsorship | audience size | low | medium | high |
| Platform ad share | see kb-001 thresholds | **highest** | high | **lowest** |

## Infrastructure

- **beehiiv** — newsletter platform with an API. Ad Network available on Scale plan and above while actively sending; offers surface automatically in the dashboard, publisher chooses which to run. Platform takes **0% of earnings**. The cleanest automatable rail in the list.
- **Lemon Squeezy** — merchant of record. Collects payment, handles VAT across jurisdictions and US state sales tax, files and remits. Subscription billing, usage-based pricing, license keys, API and webhooks. Verification 1-4 weeks, sometimes longer. MoR status removes per-jurisdiction tax filing from every venture — significant for a portfolio.
- **Gumroad** — faster to start, higher fees, weaker subscription tooling. Fine for a first product, poor for scale.
- **Payhip** — instant account setup, useful when verification wait is the blocker.
- **doola Company Formation API** — programmatic entity formation, whitelabel, paperwork returned via API. Partner program, pricing by call. Jurisdiction determines availability.

**Operational consequence:** entity formation is permanently autonomy L1. It costs money, creates a legal obligation in the operator's name, and generates ongoing filing duties. Agent prepares, human confirms. No configuration changes this.

## Changelog
- 2026-08-11 — created.

---
id: kb-006
title: Design-asset marketplaces — AI policy, payout, review
verified_on: 2026-08-11
ttl_days: 60
volatility: medium
---

# Design-asset marketplaces

Applies to VENTURE-001 (design asset factory) and any venture whose deliverable is a template, UI kit, mockup, or design file.

## The controlling distinction

**AI-generated PREVIEWS are permitted almost everywhere. AI-generated DELIVERABLES are not.**

Any skill producing assets for these rails must know which side of that line each artifact falls on. Cover art, hero renders, mockups, promo screenshots = preview. Anything inside the download zip = deliverable.

## Rails

| Rail | AI policy | Payout | Review | Status |
|---|---|---|---|---|
| Own storefront (Lemon Squeezy, Gumroad, self-hosted) | none — operator sets it | ~95% after fees | none | **OPEN** |
| Framer Marketplace | quality/originality/completeness review; no AI-specific ban found **[unverified]** | **100% to creator** | application + review | **OPEN**, non-exclusive |
| Webflow Marketplace | quality rubric, must score "Good" on every section | **95%** (raised from 80%) | 3-5 days typical | **OPEN**. Exclusivity contested **[unverified]** |
| Envato Market / Elements | **AI content permitted in previews ONLY. Must not be in the download file.** Demo content imported from your server is allowed; the item zip is not | varies | slow | **CLOSED to AI deliverables** |
| Figma Community — paid | requires approved-creator status; **"currently not approving new creators to sell paid files"** | — | content review | **CLOSED to new sellers** |
| Figma Community — free | — | $0 | — | **OPEN as a distribution/audience rail only** |
| Framer affiliate | — | 50% of referred subscriptions | signup | OPEN, stacks |
| Webflow affiliate | — | 50%, up to +15% at higher tiers | signup | OPEN, stacks |

## Hard operational facts

- **Webflow: a business address, once added to a template, cannot be removed, and such a template cannot remain in the marketplace.** One-way door — QC check must catch it pre-build.
- **Webflow: failing 5 or more submission requirements = rejection, and the rejected submission does not count toward the monthly submission quota.**
- **Webflow: Interactions powered by GSAP became the default for marketplace templates on 2026-05-01. Legacy interactions fail review.**
- **Figma: paid files cannot be converted to free later, and cannot be unpublished — only delisted.** Publish-as-paid is irreversible.
- **Figma: paid resources cannot be published from team or organization profiles**, only individual approved accounts, and a Stripe account must be active first.
- Lemon Squeezy verification runs 1-4 weeks, occasionally longer.

## Labor baseline

A documented seller reported **~30 hours** for one Webflow template end to end, including research and learning the submission rules. Any pipeline claiming to beat this must be measured against it in human-rescue hours per asset, not in machine time.

## Traffic (SimilarWeb estimates, treat as rough)

Webflow ~10.4M monthly vs Framer ~1.7M monthly. Roughly 6x, against Framer's 100% payout and non-exclusivity.

## Changelog
- 2026-08-11 — created. Envato AI-in-deliverable ban and Figma paid-creator freeze are the two facts that reshape this venture.

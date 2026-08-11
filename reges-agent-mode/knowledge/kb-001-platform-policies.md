---
id: kb-001
title: Platform monetization policy
verified_on: 2026-08-11
ttl_days: 30
volatility: high
---

# Platform monetization policy

## X — automated content is INELIGIBLE

- Creator Revenue Sharing stopped accepting new enrollments **2026-08-07**, retires after **2026-09-07**.
- Replacement: **Original Content Rewards Program**. Existing members can apply from 2026-09-08.
- Eligibility: active Premium subscription + 500 verified followers + 500,000 verified Home Timeline impressions in 90 days, replies excluded. Minimum payout $30, biweekly.
- Qualified impressions = unique views from Premium subscribers on the Home Timeline with at least 50% of the post visible.
- **Excluded: content copied, reuploaded without authorship, GENERATED THROUGH AUTOMATED MEANS, or reposted with only minor edits.**

**Operational consequence:** X is draft-only in this system. Agent drafts, human posts. Never emit a `publish` intent targeting X. A `publish.draft` intent is valid.

source: https://help.x.com/en/using-x/original-content-rewards
source: https://help.x.com/en/using-x/creator-revenue-sharing

## YouTube — AI allowed, mass production not

Policy renamed from "repetitious content" to "inauthentic content" 2025-07-15, clarified 2026-07-16. Three ineligible classes:

1. Repetitive, generic, or template-based uploads with little variation
2. Emotionally manipulative or deliberately distressing view-farming
3. **AI-generated personas discussing sensitive topics — health, finance, legal**

Enforcement is **channel-level** and escalates: warning, then 90-day suspension, then permanent removal from the Partner Program.

YPP thresholds: 500 subs + 3 public videos + 3,000 watch hours OR 3M Shorts views in 90 days (fan funding tier). 1,000 subs + 4,000 watch hours OR 10M Shorts views (ad revenue).

Synthetic content requires the "altered or synthetic content" disclosure in Studio.

**Operational consequence:** class 3 forbids the AI-voiced finance/health channel archetype outright. QC gate check 4 enforces it.

source: https://support.google.com/youtube/answer/1311392

## Google Search — scaled content abuse

- Introduced March 2024 alongside site reputation abuse and expired domain abuse.
- **Method-agnostic by design.** The prior "automatically generated content" qualifier was deliberately removed. Thin content at scale violates it whether produced by a model, a human, or both.
- Enforcement debut: 837 of 49,345 monitored sites deindexed — removed, not demoted. 100% showed AI-generated content; roughly half had 90-100% AI-generated posts.
- **Enforcement is sitewide, not per-page.** One bad section can take the domain.
- August 2025 spam update strengthened detection of thin content. January 2025 rater guidelines added explicit AI-content evaluation on effort, originality, added value.
- Bing states large-scale content without oversight or editorial review may be excluded from indexing.

**Operational consequence:** programmatic web ventures are viable ONLY where every page carries original data the venture generated. No AI rewrites of ranking pages. Highest-risk surface in the system.

source: https://developers.google.com/search/docs/essentials/spam-policies

## Changelog
- 2026-08-11 — created. X Revenue Sharing retirement captured 4 days after announcement.

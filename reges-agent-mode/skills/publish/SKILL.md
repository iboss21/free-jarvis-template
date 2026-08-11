---
name: publish
description: Emit publish intents against official APIs, inside quota, with idempotency. Never posts to X.
role: WORKER
tier: 2
triggers: ["publish", "post", "schedule"]
requires_kb: [kb-001, kb-002]
allowed_tools: ["Read"]
cost_ceiling_usd: 0.05
schema: schemas/publish.schema.json
---

# Publish

## Preconditions — all must hold or emit halt

1. QC gate returned `pass: true` this cycle
2. Required disclosures present
3. Target platform's kb-002 entry is fresh (not past ttl)
4. Quota remaining for platform and account today
5. `idem_key` supplied by host
6. Venture autonomy >= L2 for a live publish; L1 emits `publish.draft` instead

## Platform routing

| Target | Intent | Note |
|---|---|---|
| YouTube | `publish.youtube` | Units budget per project, see kb-002 |
| TikTok | `publish.tiktok` | Direct Post requires app approval; if unapproved, emit `publish.tiktok.draft` |
| Instagram | `publish.instagram` | Two-step container; media must already be at a public URL. If not, emit `halt` with `reason: media_not_hosted` |
| X | `publish.draft` **only** | kb-001: automated posting is ineligible for rewards. Never emit a live X publish |
| Newsletter | `publish.newsletter` | |

## On failure

Never retry inside the cycle. Emit the failure, let the executor's backoff handle it. A silent posting failure is the most expensive bug in this system — always surface it.

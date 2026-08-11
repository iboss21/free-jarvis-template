---
id: kb-002
title: Publishing APIs, quotas, approval lead times
verified_on: 2026-08-11
ttl_days: 30
volatility: high
---

# Publishing APIs

| Platform | Interface | Quota | Approval | Notes |
|---|---|---|---|---|
| YouTube | Data API, OAuth | 10,000 units/day per Google Cloud project. Uploads are expensive — per-call cost UNVERIFIED, budget ~6/day/project or shard projects | Google OAuth verification can be slow for sensitive scopes; unverified apps limited to 100 users | Resumable upload protocol |
| TikTok | Content Posting API | ~15-25 posts/day/account, shared across all API clients using Direct Post | **App review required before production, 2-6 weeks** | `video.publish` = Direct Post; `video.upload` = draft to inbox |
| Instagram | Graph API, Business/Creator account | 25 API posts/account/24h | Meta app review | Two-step: create media container from a PUBLICLY REACHABLE URL, then publish. No direct file upload |
| X | API | Free tier ~500 posts/month | — | **Pay-per-request as of Feb 2026: ~$0.015 per text post, $0.20 per post containing a URL.** See kb-001 — publishing here is draft-only anyway |
| Facebook Groups | Graph API | — | — | **UNVERIFIED — third-party group posting permissions must be confirmed before any group venture is scoped** |

## Aggregation layer

- **Postiz** — open source, self-hostable free under Docker, 30+ platforms, REST API and an official MCP server on every plan. You supply your own platform developer app approvals. Default choice: own the stack, no per-profile bill, agent-native.
- Ayrshare — mature, SDKs in several languages, per-profile pricing. Requires you to supply your own X API keys from 2026-03-31.
- Blotato, Upload-Post, Zernio — hosted alternatives with MCP servers.

## Browser fallback — measured ceiling

Where no API exists:

- WebBench (5,750 tasks, 452 sites): best published result across the field **64.4%**.
- ClawBench (153 live-site write tasks): frontier models cap at **33.3%**.
- Write-heavy tasks — login, forms, downloads — are where every agent struggles most.
- DOM-driven (Playwright + Claude, Stagehand) runs **12-17 percentage points more reliable** than vision-driven (Computer Use, CUA), and is cheaper and easier to debug.
- Meaningful share of failures are infrastructure: proxies, CAPTCHAs, auth blocks.

**Operational consequence:** browser tasks must be idempotent, retryable, and reversible or they do not run unattended. A browser task never spends money and never creates a permanent public artifact without confirmation.

source: https://www.skyvern.com/blog/web-bench-a-new-way-to-compare-ai-browser-agents/

## Changelog
- 2026-08-11 — created.

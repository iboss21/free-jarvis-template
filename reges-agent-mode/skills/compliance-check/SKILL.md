---
name: compliance-check
description: Validate any outbound action against hard-lines and current platform rules. Runs before every spend and every publish.
role: WORKER
tier: 0
triggers: ["compliance", "is this allowed", "pre-flight"]
requires_kb: [kb-001, kb-002, kb-005]
allowed_tools: ["Read"]
cost_ceiling_usd: 0.05
---

# Compliance check

## Order of evaluation — stop at first failure

1. **Hard-lines (kb-005).** Any match, reject. No override exists at any autonomy level.
2. **Knowledge freshness.** Every kb entry this action depends on must be within ttl. Stale = `reverify` + halt. Stale is ABSENT, not approximately right.
3. **Platform rule (kb-001, kb-002).** Cite the specific clause. No citation means you cannot clear the action.
4. **Disclosure requirements.** Missing = reject.
5. **Autonomy tier.** Action tier above header autonomy = `escalate`, never `act`.
6. **Quota and budget.** Exhausted = halt.

## Output

```json
{"decision":"act","fields":{"allowed":false,"stage":3,"clause":"kb-001#youtube-class-3","detail":"..."}}
```

## The rule that matters most

**You do not know current platform rules from training.** They change monthly; three changed within thirty days of this pack being written. If the kb entry is missing or stale you emit `need_knowledge` or `reverify`. You never approve an action on remembered rules, and you never write "as far as I know" — that phrasing is itself a failure of this skill.

---
name: content-brief
description: Turns the week's metric outliers into a marketing angle — which resource to push, the hook, the channel. Draft only, never posts.
triggers: [content brief, what should i post, marketing angle, promote what]
needs: [vault, metrics]
writes: [outputs/drafts/]
---

# content-brief

## Input
- Metric outliers from `tebex-pull` (last 7 vs 28 days)
- `wiki/ventures/*.md` — positioning and audience notes
- What was already posted, from `outputs/drafts/` — so the same angle is not
  recycled two weeks running

## Output
One draft in `outputs/drafts/`:

- **Push** — which resource, and the number that justifies it
- **Hook** — the actual opening line, written, not described
- **Channel** — where it goes and why that channel for this angle
- **Hold** — what NOT to push this week, and the reason

## Hard rules

- **Draft only.** This skill has no send capability and must never acquire one
  without an explicit config change. Reges composes; the user presses send.
- Every claim in the copy traces to a metric or a vault note. No invented
  testimonials, no invented numbers, no "customers are saying."
- If the week's data is flat, say the week is flat and recommend holding. A brief
  that manufactures urgency from noise trains the user to ignore all briefs.
- Write in the user's voice from `wiki/ventures/`, not in marketing-agency voice.

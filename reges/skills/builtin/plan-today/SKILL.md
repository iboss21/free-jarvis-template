---
name: plan-today
description: Reads yesterday's outputs and the open queue, writes today's top 3 to system/today.md, and reads it aloud.
triggers: [plan my day, plan today, what should i do today, plan tomorrow, top three]
needs: [vault]
writes: [system/today.md, raw/]
---

# plan-today

## Input
- `system/queue.md` — intents that were parked
- yesterday's `raw/` captures — what actually happened
- `outputs/drafts/` — anything drafted but not shipped
- calendar, if a connector is configured

## Output
Rewrites `system/today.md` as a flat list. Format matters — the HUD parses this
file directly, so it is the source of truth and the HUD is only a view of it:

```
- [ ] 09:00 Ship the lxr-hud preset migration
- [ ] 14:00 Record the voice-control demo
- [ ]       Reply to the three Tebex tickets
```

Timed entries appear in the HUD schedule rail with a NOW marker on the current
slot. Untimed entries still show; they just do not get a time column.

## Rules

- **Three items.** Not five, not "and also." A list of nine is a list of zero.
  If the user pushes for more, write three and park the rest in `queue.md`.
- Anything carried over from yesterday gets flagged as carried, not silently
  re-listed. Two carries in a row is a signal worth speaking aloud.
- Never invent a task. Every item traces to a queue entry, an unfinished draft,
  or something the user said. An agent that fabricates plausible-looking work
  is worse than an empty list.
- Speak only the three. The reasoning stays in the file.

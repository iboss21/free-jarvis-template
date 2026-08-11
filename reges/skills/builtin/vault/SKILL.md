---
name: vault
description: Read, write, and search the markdown memory. Every other skill calls this one.
triggers: [search the vault, what do i know about, remember that, look up in my notes, vault clean]
needs: [vault]
writes: [raw/, wiki/]
---

# vault

The memory primitive. Nothing else in Reges touches the filesystem directly.

## Operations

**search** — plain substring search across `wiki/`, `raw/`, `outputs/`, `system/`.
Returns path + excerpt, newest first. Not embeddings: if grep cannot find it, the
note is badly written, and semantic search would hide that instead of fixing it.
Revisit when grep genuinely fails, not before.

**capture** — append a raw note to `raw/YYYY-MM-DD/HHMM-slug.md`. Never overwrites.
A same-minute collision suffixes `-2`, `-3`. Raw is the audit trail; it is the one
thing in the vault that is never edited after the fact.

**promote** — take a pattern that has appeared across several raw captures and draft
a `wiki/` note for it. **Always a draft.** Reges proposes; the user approves. The
vault is the user's, and an agent that silently rewrites someone's notes is a
liability, not a feature.

**clean** — weekly. Finds raw captures older than 30 days whose content never got
promoted, and lists them for review. Deletes nothing.

## Rules

- Every file gets frontmatter: `type`, `skill`, `created`, `tags`, `links`.
- Cross-references use `[[wikilinks]]` so Obsidian indexes them with no config.
- Paths are clamped to the vault root. A skill cannot write outside it.
- Metrics go to `.reges/metrics.sqlite`, never to markdown. Time-series in
  markdown is how a vault becomes unreadable by month three.

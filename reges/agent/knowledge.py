"""Knowledge pack loader and the staleness gate.

This is the most important safety module in Reges.

The executing model's training data is stale on every platform rule this
system depends on. Three of them changed within thirty days of this being
written; one changed four days before. So world-facts never live in weights
or in the system prompt — they live here, dated, and they expire.

A kb entry past its ttl is treated as ABSENT, not as approximately right.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Entry:
    id: str
    title: str
    verified_on: dt.date
    ttl_days: int
    volatility: str
    path: Path
    body: str

    def expires_on(self) -> dt.date:
        return self.verified_on + dt.timedelta(days=self.ttl_days)

    def days_left(self, today: dt.date | None = None) -> int:
        return (self.expires_on() - (today or dt.date.today())).days

    def is_stale(self, today: dt.date | None = None) -> bool:
        return self.days_left(today) < 0


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        meta[k.strip()] = v
    return meta, text[m.end():]


def _as_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip())


def load_all(knowledge_dir: Path) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}
    if not knowledge_dir.exists():
        return entries
    for path in sorted(knowledge_dir.glob("kb-*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        kid = str(meta.get("id") or path.stem.split("-")[0])
        try:
            verified = _as_date(meta.get("verified_on"))
        except Exception:
            # No parseable date means we cannot prove freshness. Treat as
            # maximally stale rather than trusting it.
            verified = dt.date(1970, 1, 1)
        entries[kid] = Entry(
            id=kid,
            title=str(meta.get("title", path.stem)),
            verified_on=verified,
            ttl_days=int(meta.get("ttl_days", 30) or 30),
            volatility=str(meta.get("volatility", "high")),
            path=path,
            body=body,
        )
    return entries


class StaleKnowledge(Exception):
    """Raised when a required kb entry has expired."""

    def __init__(self, stale: list[str], missing: list[str]):
        self.stale = stale
        self.missing = missing
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if stale:
            parts.append(f"stale: {', '.join(stale)}")
        super().__init__("; ".join(parts))


@dataclass
class GateResult:
    ok: bool
    loaded: dict[str, Entry]
    stale: list[str]
    missing: list[str]

    def decision(self, cycle: str, role: str) -> dict:
        """The contract-shaped refusal to hand back when the gate fails."""
        if self.missing:
            return {
                "cycle": cycle, "role": role, "decision": "need_knowledge",
                "intents": [],
                "fields": {"missing": self.missing},
                "reason": (
                    "Required knowledge entries are not present. Current platform "
                    "rules cannot be answered from model memory."
                ),
                "confidence": "high",
            }
        return {
            "cycle": cycle, "role": role, "decision": "reverify",
            "intents": [],
            "fields": {"stale": self.stale},
            "reason": (
                "Required knowledge entries are past their ttl. A stale entry is "
                "treated as absent. Re-verify against the primary source before "
                "this action proceeds."
            ),
            "confidence": "high",
        }


def gate(knowledge_dir: Path, required: list[str], *, enforce: bool = True,
         today: dt.date | None = None) -> GateResult:
    """Load the required kb entries, or explain exactly why we cannot proceed."""
    all_entries = load_all(knowledge_dir)
    loaded: dict[str, Entry] = {}
    stale: list[str] = []
    missing: list[str] = []

    for kid in required:
        entry = all_entries.get(kid)
        if entry is None:
            missing.append(kid)
            continue
        if enforce and entry.is_stale(today):
            stale.append(kid)
            continue
        loaded[kid] = entry

    return GateResult(ok=not stale and not missing, loaded=loaded,
                      stale=stale, missing=missing)


def status(knowledge_dir: Path, today: dt.date | None = None) -> list[dict]:
    rows = []
    for entry in load_all(knowledge_dir).values():
        rows.append({
            "id": entry.id,
            "title": entry.title,
            "verified_on": entry.verified_on.isoformat(),
            "ttl_days": entry.ttl_days,
            "days_left": entry.days_left(today),
            "stale": entry.is_stale(today),
        })
    return sorted(rows, key=lambda r: r["days_left"])

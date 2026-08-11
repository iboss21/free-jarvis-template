"""Skill loading and intent routing.

Two ideas do all the work here:

1. **Progressive disclosure.** The router only ever sees each skill's frontmatter
   (name, description, triggers). The SKILL.md body -- the expensive part -- is
   loaded only after that skill wins. This is what keeps the router prompt small
   enough to run on a 7B local model.

2. **A confidence floor.** Below `router_confidence_floor` the router asks
   instead of guessing. Silently running the wrong skill is the failure that
   kills trust in a voice agent; asking one short question does not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import RegesConfig
from .state import BUS, State

BUILTIN_DIR = Path(__file__).resolve().parent / "skills" / "builtin"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    triggers: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    _body: str | None = None

    @property
    def body(self) -> str:
        """Loaded lazily -- this is the whole point of the manifest split."""
        if self._body is None:
            m = _FM_RE.match(self.path.read_text(encoding="utf-8"))
            self._body = (m.group(2) if m else self.path.read_text(encoding="utf-8")).strip()
        return self._body

    def manifest_line(self) -> str:
        trig = f"  triggers: {', '.join(self.triggers)}" if self.triggers else ""
        return f"- {self.name}: {self.description}{trig}"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Minimal YAML: scalars and inline lists. A SKILL.md that needs more
    structure than this is a skill that should be two skills."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key] = val.strip("'\"")
    return out


def load_skills(cfg: RegesConfig) -> dict[str, Skill]:
    dirs = [BUILTIN_DIR] + [Path(d) for d in cfg.skills.extra_skill_dirs]
    found: dict[str, Skill] = {}
    for base in dirs:
        if not base.exists():
            continue
        for sk_file in sorted(base.glob("*/SKILL.md")):
            fm = _parse_frontmatter(sk_file.read_text(encoding="utf-8"))
            name = fm.get("name") or sk_file.parent.name
            if name not in cfg.skills.enabled:
                continue
            found[name] = Skill(
                name=name,
                description=fm.get("description", ""),
                path=sk_file,
                triggers=fm.get("triggers", []) or [],
                needs=fm.get("needs", []) or [],
                writes=fm.get("writes", []) or [],
            )
    return found


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

ROUTER_SYSTEM = """You are the router for a personal automation agent.
Pick exactly one skill for the user's intent, or none if nothing fits.

Available skills:
{manifest}

Reply with ONLY a JSON object, no prose, no markdown fence:
{{"skill": "<name or null>", "confidence": <0.0-1.0>, "args": {{}}, "why": "<8 words max>"}}

Rules:
- confidence is how sure you are this is the RIGHT skill, not how sure you are it exists.
- If two skills fit equally, pick neither: return null with confidence 0.4.
- Never invent a skill name that is not in the list above."""


@dataclass
class Route:
    skill: str | None
    confidence: float
    args: dict[str, Any]
    why: str = ""

    @property
    def ok(self) -> bool:
        return self.skill is not None


def _keyword_route(intent: str, skills: dict[str, Skill]) -> Route | None:
    """Cheap pre-pass. An exact trigger phrase should not cost an LLM call -- on a
    cold local model that is the difference between 40ms and 4s, and a command-deck
    button must be deterministic, never a roundtrip that might route elsewhere.

    Word-boundary matching, not substring: raw `in` made "tebex" fire on
    "tebexish" and forced a length floor high enough to exclude legitimate short
    proper nouns. Boundaries make short distinctive tokens safe again.
    """
    low = intent.lower()
    best: tuple[int, str] | None = None
    for name, sk in skills.items():
        for trig in sk.triggers:
            t = trig.lower().strip()
            if len(t) < 4:
                continue  # too generic to trust regardless of boundaries
            if not re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low):
                continue
            score = len(t)
            if best is None or score > best[0]:
                best = (score, name)
    if best:
        return Route(best[1], 0.95, {}, "exact trigger match")
    return None


def route(intent: str, skills: dict[str, Skill], llm, cfg: RegesConfig) -> Route:
    if not skills:
        return Route(None, 0.0, {}, "no skills enabled")

    hit = _keyword_route(intent, skills)
    if hit:
        BUS.log("router", f"{hit.skill} (trigger)")
        return hit

    manifest = "\n".join(s.manifest_line() for s in skills.values())
    with BUS.during(State.THINKING, "routing"):
        raw = llm.complete(
            system=ROUTER_SYSTEM.format(manifest=manifest),
            user=intent,
            tier=cfg.models.router_tier,
            max_tokens=200,
            temperature=0.0,
        )

    parsed = _extract_json(raw)
    if not parsed:
        BUS.log("router", "no skill matched — chatting")
        return Route(None, 0.0, {}, "router parse failed")

    name = parsed.get("skill")
    if name not in skills:
        name = None
    conf = float(parsed.get("confidence") or 0.0)
    r = Route(name, conf, parsed.get("args") or {}, str(parsed.get("why") or ""))

    if r.ok and conf < cfg.skills.router_confidence_floor:
        BUS.log("warn", f"{name} at {conf:.2f} -- below floor, asking instead")
        return Route(None, conf, {}, f"unsure between skills ({conf:.2f})")

    BUS.log("router", f"{r.skill or 'none'} ({conf:.2f}) {r.why}")
    return r


def _extract_json(text: str) -> dict | None:
    """Local models wrap JSON in fences, prose, or <think> blocks. Take the first
    balanced object rather than trusting the model to have obeyed the format."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    return None

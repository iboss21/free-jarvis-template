"""Decision-object validation.

No jsonschema dependency: the core has to run on a bare embeddable Python.
This is a hand-rolled validator for the one schema that matters.
"""
from __future__ import annotations

import json
import re

ROLES = {"BOARD", "OPERATOR", "VENTURE", "WORKER"}
DECISIONS = {"act", "split", "halt", "need_knowledge", "reverify", "escalate"}
CONFIDENCE = {"high", "medium", "low"}

HEDGES = re.compile(
    r"\b(as far as i know|to my knowledge|i think|i believe|may have changed|"
    r"might be outdated|probably still)\b", re.I,
)

FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class Invalid(Exception):
    pass


def extract_json(text: str) -> dict:
    """Pull the decision object out of a model response.

    Tolerant of a code fence because local models add them habitually, but
    NOT tolerant of prose plus JSON — that is a contract violation and the
    caller should see it as one.
    """
    if not text or not text.strip():
        raise Invalid("empty response")
    stripped = text.strip()
    m = FENCE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise Invalid(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise Invalid("top level must be an object")
    return obj


def validate(obj: dict, *, strict_hedges: bool = True) -> list[str]:
    """Return a list of problems. Empty list means valid."""
    problems: list[str] = []

    for key in ("cycle", "role", "decision", "reason", "confidence"):
        if key not in obj:
            problems.append(f"missing required key: {key}")

    if obj.get("role") not in ROLES and "role" in obj:
        problems.append(f"role must be one of {sorted(ROLES)}")
    if obj.get("decision") not in DECISIONS and "decision" in obj:
        problems.append(f"decision must be one of {sorted(DECISIONS)}")
    if obj.get("confidence") not in CONFIDENCE and "confidence" in obj:
        problems.append(f"confidence must be one of {sorted(CONFIDENCE)}")

    intents = obj.get("intents", [])
    if not isinstance(intents, list):
        problems.append("intents must be a list")
        intents = []
    if len(intents) > 8:
        problems.append("intents exceeds maxItems 8")

    for i, intent in enumerate(intents):
        if not isinstance(intent, dict):
            problems.append(f"intents[{i}] must be an object")
            continue
        for key in ("type", "idem_key", "evidence", "reversible"):
            if key not in intent:
                problems.append(f"intents[{i}] missing {key}")
        ev = intent.get("evidence")
        if isinstance(ev, list) and not ev:
            problems.append(f"intents[{i}].evidence is empty — an intent without evidence is invalid")
        elif ev is not None and not isinstance(ev, list):
            problems.append(f"intents[{i}].evidence must be a list")

    if obj.get("decision") == "act" and not intents:
        problems.append("decision 'act' with no intents")

    reason = obj.get("reason", "")
    if isinstance(reason, str):
        if len(reason) > 2000:
            problems.append("reason exceeds 2000 chars")
        if strict_hedges and HEDGES.search(reason):
            problems.append("reason contains hedging language — uncertainty belongs in confidence")

    return problems


def halt(cycle: str, role: str, reason: str, **fields) -> dict:
    return {
        "cycle": cycle,
        "role": role,
        "decision": "halt",
        "intents": [],
        "fields": fields,
        "reason": reason,
        "confidence": "high",
    }

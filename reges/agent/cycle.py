"""One bounded episode.

Law 2: load state -> one unit of work -> emit decision -> exit. There is no
loop in this module and there must never be one.

Gate order is deliberate and cheapest-first. Everything that can refuse
without spending a token refuses before the model is called. A stale
knowledge entry costs nothing to catch and is the most likely failure this
system has.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import db, knowledge, validate
from .paths import AgentPaths

AUTONOMY_MAX_TIER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 3}
# Tier 4 (market orders) is unreachable from any autonomy level by design.
# It requires the separate arming ceremony in the risk process.

ROLES = {"BOARD", "OPERATOR", "VENTURE", "WORKER"}


def new_cycle() -> str:
    return uuid.uuid4().hex[:16]


def agent_header(*, role: str, venture: str, autonomy: str, cycle: str,
                 knowledge_index: Path) -> str:
    return (
        "REGES-AGENT-MODE/1\n"
        f"role: {role}\n"
        f"venture: {venture or 'none'}\n"
        f"autonomy: {autonomy}\n"
        f"cycle: {cycle}\n"
        f"knowledge_index: {knowledge_index}\n"
    )


def load_state(paths: AgentPaths, venture: str | None) -> dict:
    """Everything the model is permitted to believe about the world.

    If it is not in here, the model does not have it. Law 1.
    """
    state: dict = {
        "ventures": [
            {"slug": v["slug"], "state": v["state"], "autonomy": v["autonomy"],
             "policy_warnings": v["policy_warnings"]}
            for v in db.list_ventures(paths.db)
        ],
        "spend_today_usd": round(db.spend_today(paths.db), 4),
    }
    if venture:
        # Venture isolation: full detail for this venture only. Every other
        # venture appears as a name. No cross-venture memory.
        state["venture"] = db.get_venture(paths.db, venture)
    return state


def assemble(*, contract: str, header: str, skill_bodies: list[tuple[str, str]],
             kb: dict, state: dict, task: str) -> str:
    parts: list[str] = []

    if kb:
        parts.append("# KNOWLEDGE (loaded this cycle — cite these ids)")
        for kid, entry in kb.items():
            parts.append(
                f"## {kid} — {entry.title}\n"
                f"verified_on: {entry.verified_on.isoformat()}  "
                f"days_left: {entry.days_left()}\n\n{entry.body.strip()}"
            )

    if skill_bodies:
        parts.append("# SKILLS (selected for this cycle)")
        for name, body in skill_bodies:
            parts.append(f"## {name}\n{body.strip()}")

    parts.append("# STATE (loaded this cycle — Law 1: you do not remember)")
    parts.append("```json\n" + json.dumps(state, indent=2, default=str) + "\n```")

    # Contract and activation go last. The base RegesCore template declares
    # the host system prompt authoritative over persona, and agent mode has
    # to occupy that authoritative position.
    parts.append("# CONTRACT\n" + contract.strip())
    parts.append("# ACTIVATION\n" + header)
    parts.append(
        "# TASK\n" + task.strip() +
        "\n\nRespond with exactly one JSON object matching the decision schema. "
        "No prose before or after it."
    )
    return "\n\n".join(parts)


def run(cfg, task: str, *, role: str = "WORKER", venture: str | None = None,
        autonomy: str = "L1", bus=None, llm=None, skills: dict | None = None,
        dry_run: bool = False, enforce_staleness: bool = True) -> dict:
    """Run one cycle. Returns a validated decision object, always."""
    role = role.upper()
    if role not in ROLES:
        return validate.halt("none", "WORKER", f"unknown role {role}")

    paths = AgentPaths(cfg)
    paths.ensure()
    cycle = new_cycle()

    def log(kind: str, msg: str, **extra):
        if bus is not None:
            try:
                bus.log(kind, msg, **extra)
            except Exception:
                pass

    log("cycle", "start", cycle=cycle, role=role, autonomy=autonomy)

    # gate 0 — panic sentinel
    if paths.halt.exists():
        return _finish(paths, validate.halt(cycle, role,
                       "HALT sentinel present. All queues stopped."), log)

    # gate 1 — role/skill selection
    skills = skills or {}
    selected = _select(skills, task, role)
    if not selected:
        return _finish(paths, validate.halt(cycle, role,
                       "No skill matched this request."), log)

    top_name, top = selected[0]
    tier = int(getattr(top, "tier", 0) or 0)

    # gate 2 — autonomy vs capability tier
    max_tier = AUTONOMY_MAX_TIER.get(autonomy.upper(), 1)
    if tier > max_tier:
        d = {
            "cycle": cycle, "role": role, "decision": "escalate", "intents": [],
            "fields": {"skill": top_name, "required_tier": tier,
                       "autonomy": autonomy, "max_tier": max_tier},
            "reason": (f"Skill {top_name} requires tier {tier}; autonomy {autonomy} "
                       f"permits at most tier {max_tier}. Human authorisation required."),
            "confidence": "high",
        }
        log("approval", "tier exceeded", skill=top_name, tier=tier)
        return _finish(paths, d, log)

    # gate 3 — knowledge staleness. Cheapest gate that can save the most.
    required: list[str] = []
    for _, sk in selected:
        for kid in (getattr(sk, "requires_kb", None) or []):
            if kid not in required:
                required.append(kid)

    gate = knowledge.gate(paths.knowledge, required, enforce=enforce_staleness)
    if not gate.ok:
        log("knowledge", "gate failed", stale=gate.stale, missing=gate.missing)
        db.record_incident(paths.db, "knowledge_gate",
                           f"stale={gate.stale} missing={gate.missing} skill={top_name}",
                           venture)
        return _finish(paths, gate.decision(cycle, role), log)

    # assemble
    contract = paths.contract.read_text(encoding="utf-8") if paths.contract.exists() else ""
    header = agent_header(role=role, venture=venture or "none", autonomy=autonomy,
                          cycle=cycle, knowledge_index=paths.knowledge / "INDEX.md")
    state = load_state(paths, venture)
    bodies = [(n, getattr(s, "body", "") or "") for n, s in selected]
    system = assemble(contract=contract, header=header, skill_bodies=bodies,
                      kb=gate.loaded, state=state, task=task)

    if dry_run:
        return {
            "cycle": cycle, "role": role, "decision": "halt", "intents": [],
            "fields": {"dry_run": True, "skills": [n for n, _ in selected],
                       "kb": sorted(gate.loaded), "system_chars": len(system)},
            "reason": "Dry run. Gates passed and prompt assembled; no model was called.",
            "confidence": "high",
        }

    if llm is None:
        return _finish(paths, validate.halt(cycle, role,
                       "No LLM client supplied to the cycle."), log)

    # execute
    try:
        text = llm.reason(system, task)
    except Exception as exc:
        log("error", "executor failed", detail=str(exc)[:300])
        return _finish(paths, validate.halt(cycle, role,
                       f"Executor failed: {str(exc)[:300]}"), log)

    # validate
    try:
        decision = validate.extract_json(text)
    except validate.Invalid as exc:
        db.record_incident(paths.db, "contract_violation", str(exc), venture)
        return _finish(paths, validate.halt(cycle, role,
                       f"Model did not return a valid decision object: {exc}"), log)

    decision.setdefault("cycle", cycle)
    decision.setdefault("role", role)
    problems = validate.validate(decision)
    if problems:
        db.record_incident(paths.db, "schema_violation", "; ".join(problems), venture)
        d = validate.halt(cycle, role,
                          "Decision failed validation: " + "; ".join(problems[:5]))
        d["fields"]["raw"] = decision
        return _finish(paths, d, log)

    return _finish(paths, decision, log)


def _select(skills: dict, task: str, role: str, limit: int = 3):
    """Deterministic lexical selection, filtered by role.

    Kept model-free on purpose: routing is cheap and testable, and this is the
    baseline the 50-utterance eval scores against.
    """
    t = task.lower()
    words = set(w for w in t.replace("/", " ").split() if w)
    scored = []
    for name, sk in skills.items():
        sk_role = str(getattr(sk, "role", "WORKER") or "WORKER").upper()
        if sk_role != role and sk_role != "WORKER":
            continue
        score = 0.0
        for trig in (getattr(sk, "triggers", None) or []):
            trig = str(trig).lower()
            if trig and trig in t:
                score += 2.0 + 0.05 * len(trig)
            elif set(trig.split()) & words:
                score += 0.5
        if name.lower() in t:
            score += 3.0
        if score > 0:
            scored.append((score, name, sk))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return [(n, s) for _, n, s in scored[:limit]]


def _finish(paths: AgentPaths, decision: dict, log) -> dict:
    db.record_decision(paths.db, decision)
    log("cycle", "end", decision=decision.get("decision"))
    return decision

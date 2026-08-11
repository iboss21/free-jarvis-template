"""Agent-layer tests. Stdlib unittest, no deps."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from reges.agent import cycle, db, knowledge, validate  # noqa: E402
from reges.agent.paths import AgentPaths  # noqa: E402


@dataclass
class FakePaths:
    app_dir: str = ""
    vault_dir: str = ""


@dataclass
class FakeCfg:
    paths: FakePaths = field(default_factory=FakePaths)


@dataclass
class FakeSkill:
    role: str = "WORKER"
    tier: int = 0
    triggers: list = field(default_factory=list)
    requires_kb: list = field(default_factory=list)
    body: str = "test skill body"


class FakeLLM:
    def __init__(self, text): self.text = text
    def reason(self, system, user, max_tokens=2048): return self.text


KB = """---
id: kb-001
title: Platform monetization policy
verified_on: {date}
ttl_days: 30
volatility: high
---

X retired Creator Revenue Sharing on 2026-08-07.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = FakeCfg(FakePaths(app_dir=str(self.tmp), vault_dir=str(self.tmp / "vault")))
        self.p = AgentPaths(self.cfg)
        self.p.ensure()
        db.init(self.p.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_kb(self, days_ago: int):
        d = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
        (self.p.knowledge / "kb-001-platform.md").write_text(KB.format(date=d), encoding="utf-8")


class TestStalenessGate(Base):
    """S1 — the highest-value eval. A stale entry is ABSENT, not roughly right."""

    def test_fresh_entry_passes(self):
        self.write_kb(1)
        g = knowledge.gate(self.p.knowledge, ["kb-001"])
        self.assertTrue(g.ok)
        self.assertIn("kb-001", g.loaded)

    def test_expired_entry_blocks_and_never_reaches_model(self):
        self.write_kb(40)  # ttl is 30
        skills = {"publish": FakeSkill(triggers=["publish"], requires_kb=["kb-001"])}
        llm = FakeLLM('{"cycle":"x","role":"WORKER","decision":"act",'
                      '"intents":[],"reason":"should never run","confidence":"high"}')
        d = cycle.run(self.cfg, "publish this now", skills=skills, llm=llm)
        self.assertEqual(d["decision"], "reverify")
        self.assertEqual(d["fields"]["stale"], ["kb-001"])

    def test_missing_entry_asks_instead_of_guessing(self):
        skills = {"publish": FakeSkill(triggers=["publish"], requires_kb=["kb-001"])}
        d = cycle.run(self.cfg, "publish this now", skills=skills, llm=FakeLLM("{}"))
        self.assertEqual(d["decision"], "need_knowledge")
        self.assertEqual(d["fields"]["missing"], ["kb-001"])

    def test_undated_entry_treated_as_maximally_stale(self):
        (self.p.knowledge / "kb-009-x.md").write_text(
            "---\nid: kb-009\ntitle: no date\nttl_days: 30\n---\n\nbody\n", encoding="utf-8")
        g = knowledge.gate(self.p.knowledge, ["kb-009"])
        self.assertFalse(g.ok)
        self.assertEqual(g.stale, ["kb-009"])


class TestAutonomyGate(Base):
    def test_tier_above_autonomy_escalates(self):
        skills = {"publish": FakeSkill(tier=2, triggers=["publish"])}
        d = cycle.run(self.cfg, "publish it", skills=skills, autonomy="L1", llm=FakeLLM("{}"))
        self.assertEqual(d["decision"], "escalate")
        self.assertEqual(d["fields"]["required_tier"], 2)

    def test_tier_within_autonomy_proceeds(self):
        skills = {"draft": FakeSkill(tier=1, triggers=["draft"])}
        good = json.dumps({"cycle": "c", "role": "WORKER", "decision": "act",
                           "intents": [{"type": "publish.draft", "idem_key": "k",
                                        "evidence": ["kb-001"], "reversible": True}],
                           "reason": "Drafting the asset.", "confidence": "high"})
        d = cycle.run(self.cfg, "draft it", skills=skills, autonomy="L1", llm=FakeLLM(good))
        self.assertEqual(d["decision"], "act")


class TestHaltSentinel(Base):
    def test_halt_file_stops_everything(self):
        self.p.halt.write_text("stop", encoding="utf-8")
        skills = {"draft": FakeSkill(triggers=["draft"])}
        d = cycle.run(self.cfg, "draft it", skills=skills, llm=FakeLLM("{}"))
        self.assertEqual(d["decision"], "halt")
        self.assertIn("HALT sentinel", d["reason"])


class TestContract(Base):
    def test_prose_plus_json_is_a_violation(self):
        with self.assertRaises(validate.Invalid):
            validate.extract_json("Sure! Here you go:\n{\"a\":1}")

    def test_code_fence_tolerated(self):
        obj = validate.extract_json('```json\n{"a": 1}\n```')
        self.assertEqual(obj["a"], 1)

    def test_intent_without_evidence_rejected(self):
        problems = validate.validate({
            "cycle": "c", "role": "WORKER", "decision": "act",
            "intents": [{"type": "publish", "idem_key": "k", "evidence": [], "reversible": True}],
            "reason": "x", "confidence": "high"})
        self.assertTrue(any("evidence is empty" in p for p in problems))

    def test_hedging_in_reason_rejected(self):
        problems = validate.validate({
            "cycle": "c", "role": "WORKER", "decision": "halt", "intents": [],
            "reason": "As far as I know X still pays revenue share.",
            "confidence": "high"})
        self.assertTrue(any("hedging" in p for p in problems))

    def test_act_with_no_intents_rejected(self):
        problems = validate.validate({
            "cycle": "c", "role": "WORKER", "decision": "act", "intents": [],
            "reason": "x", "confidence": "high"})
        self.assertIn("decision 'act' with no intents", problems)


class TestVentureContract(Base):
    def test_venture_without_kill_criteria_refused(self):
        with self.assertRaises(ValueError):
            db.create_venture(self.p.db, slug="v1", name="v1")

    def test_illegal_state_transition_refused(self):
        db.create_venture(self.p.db, slug="v1", name="v1",
                          kill_criteria=["revenue_usd < 25 by day 45"])
        with self.assertRaises(ValueError):
            db.set_state(self.p.db, "v1", "SCALING")

    def test_legal_transition_allowed(self):
        db.create_venture(self.p.db, slug="v1", name="v1",
                          kill_criteria=["revenue_usd < 25 by day 45"])
        v = db.set_state(self.p.db, "v1", "RESEARCHING")
        self.assertEqual(v["state"], "RESEARCHING")


class TestVentureIsolation(Base):
    def test_state_shows_other_ventures_by_name_only(self):
        for slug in ("a", "b"):
            db.create_venture(self.p.db, slug=slug, name=slug,
                              niche="secret-" + slug, kill_criteria=["x"])
        state = cycle.load_state(self.p, "a")
        self.assertEqual(state["venture"]["slug"], "a")
        others = [v for v in state["ventures"] if v["slug"] == "b"][0]
        self.assertNotIn("niche", others)


if __name__ == "__main__":
    unittest.main(verbosity=2)

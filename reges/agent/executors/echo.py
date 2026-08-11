"""Deterministic executor. No model, no network, no cost.

Exists so the whole pipeline — routing, knowledge gate, validation, events,
vault write, ledger — can be tested and demoed before any model is wired up.
It always returns a contract-valid halt, which is the correct default for a
system that has not actually reasoned about anything.
"""
from __future__ import annotations

import json
import re
import time

from .base import Executor, Result

CYCLE = re.compile(r"^cycle:\s*(\S+)", re.M)
ROLE = re.compile(r"^role:\s*(\S+)", re.M)


class EchoExecutor(Executor):
    name = "echo"

    def run(self, system: str, user: str, *, on_event=None) -> Result:
        t0 = time.time()
        cycle = (CYCLE.search(system) or [None, "unknown"])[1] if CYCLE.search(system) else "unknown"
        role = (ROLE.search(system) or [None, "WORKER"])[1] if ROLE.search(system) else "WORKER"

        decision = {
            "cycle": cycle,
            "role": role,
            "decision": "halt",
            "intents": [],
            "fields": {"executor": "echo", "system_chars": len(system)},
            "reason": (
                "Echo executor is active. No model reasoned about this cycle, so "
                "no action is taken. Set models.executor.mode to claude_code or "
                "lmstudio in config.toml to run for real."
            ),
            "confidence": "high",
        }
        if on_event:
            on_event({"type": "result", "payload": {"executor": "echo"}})
        return Result(
            text=json.dumps(decision),
            model="echo",
            latency_ms=int((time.time() - t0) * 1000),
        )

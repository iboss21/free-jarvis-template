"""Agent mode — the autonomous operator layer.

Sits on top of the existing Reges core (config, StateBus, router, vault) and
adds the four things the operator architecture needs and the base agent does
not have:

  db          durable venture / experiment / asset / ledger state
  knowledge   the staleness gate — expiring world-facts, never trusted from memory
  validate    the decision-object contract
  cycle       one bounded episode with gates ordered cheapest-first

Nothing here replaces anything in reges/. It is additive.
"""
from __future__ import annotations

from . import db, knowledge, validate  # noqa: F401

__all__ = ["db", "knowledge", "validate", "cycle", "paths"]

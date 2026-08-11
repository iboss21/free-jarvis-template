"""Durable state.

Law 1 of the agent contract is 'state is external'. This module is that
external state. The model never remembers; it loads from here every cycle.

Structured truth lives in SQLite. Narrative lives in the markdown vault.
Never the reverse.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ventures (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'DISCOVERED',
    autonomy        TEXT NOT NULL DEFAULT 'L1',
    niche           TEXT,
    budget_usd      REAL NOT NULL DEFAULT 0,
    deadline        TEXT,
    rails           TEXT NOT NULL DEFAULT '[]',
    kill_criteria   TEXT NOT NULL DEFAULT '[]',
    policy_warnings INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id           TEXT PRIMARY KEY,
    venture      TEXT NOT NULL REFERENCES ventures(slug) ON DELETE CASCADE,
    hypothesis   TEXT,
    budget_usd   REAL NOT NULL DEFAULT 0,
    deadline     TEXT,
    success      TEXT NOT NULL DEFAULT '{}',
    kill_if      TEXT NOT NULL DEFAULT '[]',
    outcome      TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id          TEXT PRIMARY KEY,
    venture     TEXT NOT NULL REFERENCES ventures(slug) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    title       TEXT,
    path        TEXT,
    qc_pass     INTEGER,
    qc_failed   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publishes (
    idem_key     TEXT PRIMARY KEY,
    venture      TEXT NOT NULL,
    asset_id     TEXT,
    platform     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    platform_id  TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id          TEXT PRIMARY KEY,
    venture     TEXT,
    direction   TEXT NOT NULL,
    amount_usd  REAL NOT NULL,
    rail        TEXT,
    asset_id    TEXT,
    note        TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics_daily (
    day        TEXT NOT NULL,
    venture    TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      REAL NOT NULL,
    PRIMARY KEY (day, venture, metric)
);

CREATE TABLE IF NOT EXISTS incidents (
    id          TEXT PRIMARY KEY,
    venture     TEXT,
    kind        TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    cycle       TEXT PRIMARY KEY,
    role        TEXT NOT NULL,
    venture     TEXT,
    decision    TEXT NOT NULL,
    reason      TEXT,
    confidence  TEXT,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id           TEXT PRIMARY KEY,
    cycle        TEXT,
    skill        TEXT,
    model        TEXT,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cache_read   INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL NOT NULL DEFAULT 0,
    latency_ms   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_day  ON ledger(created_at);
CREATE INDEX IF NOT EXISTS idx_assets_v    ON assets(venture);
CREATE INDEX IF NOT EXISTS idx_pub_v       ON publishes(venture);
"""

VENTURE_STATES = [
    "DISCOVERED", "RESEARCHING", "VALIDATED", "BUILDING", "LAUNCHED",
    "GROWING", "MONETIZING", "SCALING", "PAUSED", "KILLED",
]

AUTONOMY_LEVELS = ["L0", "L1", "L2", "L3", "L4"]


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@contextmanager
def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '1')"
        )


# --------------------------------------------------------------------
# ventures
# --------------------------------------------------------------------

def create_venture(path: Path, *, slug: str, name: str, niche: str = "",
                   autonomy: str = "L1", budget_usd: float = 0.0,
                   deadline: str = "", rails: list[str] | None = None,
                   kill_criteria: list[str] | None = None) -> dict:
    if autonomy not in AUTONOMY_LEVELS:
        raise ValueError(f"autonomy must be one of {AUTONOMY_LEVELS}")
    kill_criteria = kill_criteria or []
    if not kill_criteria:
        # Contract rule: no venture launches without kill criteria written first.
        raise ValueError("kill_criteria is required — a venture with no kill criteria is not an experiment")
    ts = now()
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO ventures(slug,name,state,autonomy,niche,budget_usd,
                                    deadline,rails,kill_criteria,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, name, "DISCOVERED", autonomy, niche, budget_usd, deadline,
             json.dumps(rails or []), json.dumps(kill_criteria), ts, ts),
        )
    return get_venture(path, slug)


def get_venture(path: Path, slug: str) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM ventures WHERE slug=?", (slug,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["rails"] = json.loads(d["rails"])
    d["kill_criteria"] = json.loads(d["kill_criteria"])
    return d


def list_ventures(path: Path) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM ventures ORDER BY created_at").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["rails"] = json.loads(d["rails"])
        d["kill_criteria"] = json.loads(d["kill_criteria"])
        out.append(d)
    return out


TRANSITIONS = {
    "DISCOVERED": {"RESEARCHING", "KILLED"},
    "RESEARCHING": {"VALIDATED", "KILLED"},
    "VALIDATED": {"BUILDING", "KILLED"},
    "BUILDING": {"LAUNCHED", "PAUSED", "KILLED"},
    "LAUNCHED": {"GROWING", "PAUSED", "KILLED"},
    "GROWING": {"MONETIZING", "PAUSED", "KILLED"},
    "MONETIZING": {"SCALING", "PAUSED", "KILLED"},
    "SCALING": {"PAUSED", "KILLED"},
    "PAUSED": {"BUILDING", "LAUNCHED", "GROWING", "MONETIZING", "SCALING", "KILLED"},
    "KILLED": set(),
}


def set_state(path: Path, slug: str, state: str) -> dict:
    v = get_venture(path, slug)
    if not v:
        raise KeyError(slug)
    if state not in VENTURE_STATES:
        raise ValueError(f"unknown state {state}")
    allowed = TRANSITIONS.get(v["state"], set())
    if state not in allowed:
        raise ValueError(f"illegal transition {v['state']} -> {state}")
    with connect(path) as conn:
        conn.execute("UPDATE ventures SET state=?, updated_at=? WHERE slug=?",
                     (state, now(), slug))
    return get_venture(path, slug)


# --------------------------------------------------------------------
# ledger / decisions / incidents
# --------------------------------------------------------------------

def record_ledger(path: Path, *, cycle: str, skill: str, model: str,
                  tokens_in: int = 0, tokens_out: int = 0, cache_read: int = 0,
                  cost_usd: float = 0.0, latency_ms: int = 0) -> None:
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO ledger(id,cycle,skill,model,tokens_in,tokens_out,
                                  cache_read,cost_usd,latency_ms,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (new_id("led"), cycle, skill, model, tokens_in, tokens_out,
             cache_read, cost_usd, latency_ms, now()),
        )


def spend_today(path: Path) -> float:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS s FROM ledger WHERE created_at LIKE ?",
            (day + "%",),
        ).fetchone()
    return float(row["s"])


def record_decision(path: Path, decision: dict) -> None:
    with connect(path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO decisions(cycle,role,venture,decision,reason,
                                                confidence,payload,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (decision.get("cycle"), decision.get("role", "WORKER"),
             decision.get("venture"), decision.get("decision", "halt"),
             decision.get("reason", ""), decision.get("confidence", "low"),
             json.dumps(decision), now()),
        )


def record_incident(path: Path, kind: str, detail: str, venture: str | None = None) -> str:
    iid = new_id("inc")
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO incidents(id,venture,kind,detail,created_at) VALUES(?,?,?,?,?)",
            (iid, venture, kind, detail, now()),
        )
    return iid

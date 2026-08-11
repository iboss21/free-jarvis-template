# Agent layer

Additive. Nothing here replaces the existing `reges` core (config, StateBus,
router, vault, voice, HUD, installer). It adds the four things the autonomous
operator architecture needs and the base agent does not have.

| Module | Job |
|---|---|
| `knowledge.py` | The staleness gate. Expiring world-facts, never trusted from model memory |
| `db.py` | Durable venture / experiment / asset / publish / ledger state (Law 1) |
| `validate.py` | The decision-object contract |
| `cycle.py` | One bounded episode with gates ordered cheapest-first (Law 2) |
| `executors/` | echo, claude_code (`-p --output-format stream-json`), lmstudio |

## Gate order — this is the design

```
0  HALT sentinel        file on disk stops everything
1  skill routing        deterministic, model-free, testable
2  autonomy vs tier     L1 cannot publish. Tier 4 unreachable from any level
3  knowledge staleness  stale == absent, never "roughly right"
--- only now is a model called ---
4  contract extraction  prose + JSON is a violation, not a tolerance
5  schema validation    no evidence -> invalid. Hedging in reason -> invalid
```

Every gate that can refuse without a token refuses before the model runs.
A stale kb entry costs zero to catch and is the most likely failure this
system has.

## Commands

```
reges agent install --pack <dir>     contract + skills + knowledge
reges agent knowledge                freshness table, exit 1 if anything stale
reges agent venture create <slug> --kill "..." --kill "..."
reges agent venture list
reges agent venture state <slug> <STATE>
reges agent cycle "..." --role VENTURE --autonomy L1 [--dry-run] [--json]
```

`--dry-run` assembles the prompt and runs every gate without calling a model.
Use it to see exactly what the model would receive.

## Tests

```
python tests_agent.py
```

16 tests, stdlib only, no network. The suite that matters most is
`TestStalenessGate` — it asserts the model is never reached when knowledge
has expired.

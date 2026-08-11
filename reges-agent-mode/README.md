# Reges Agent Mode Pack v1.0

One pack, two runtimes: **Reges** (Windows agent, Claude Agent SDK) and **RegesCore** (local Qwen-family model via LM Studio).

```
AGENT-MODE.md              the operating contract — four laws, roles, output contract, halt conditions
INTEGRATION-REGESCORE.md   how to load it locally; the bake-vs-retrieve split; fine-tuning reality
knowledge/                 dated, expiring world-facts. NEVER fine-tune on this directory
skills/                    seven skills, progressive disclosure, 1-3 loaded per cycle
schemas/                   deliberately small — GBNF repetition cap is why
eval/                      promote a role to the local model only when these pass
```

## The one-line summary

Bake behaviour, retrieve facts. The model's training data is stale on every platform rule this system depends on — three of them changed within thirty days of writing, one within four days — so the contract is built to make "answering from memory" structurally impossible rather than merely discouraged.

## Load order

1. `AGENT-MODE.md` as host system prompt, emitted last (your template already declares host authoritative over persona)
2. Per-cycle header: role, venture, autonomy, cycle id
3. Router loads 1-3 skills by trigger
4. Skills declare `requires_kb`; only those entries load
5. Stale entry → `reverify` + halt. Stale is treated as absent, not as approximately right

## Before going autonomous

Run `eval/AGENT-MODE-EVALS.md`. S1 (staleness), S3 (roles) and S4 (hard-lines) are hard gates — a model that fails any of them does not get an autonomous role no matter how well it scores elsewhere.

# REGES aka JARVIS

<img width="1920" height="1002" alt="image" src="https://github.com/user-attachments/assets/663c520e-a89d-444b-ac3a-21c7f3e51647" />

Windows-first AI automation agent. Speak, it routes, the vault remembers, the HUD shows.

> **Not Reges.Core / RegesCore.** Separate project, separate codebase, shared name only.
> Package namespace `reges`, env prefix `REGES_`.

---

## Install

```powershell
powershell -ExecutionPolicy Bypass -File install\bootstrap.ps1
```

The bootstrap finds or installs Python, then runs a nine-screen wizard: preflight,
install location, vault location, model backend, keys, voice, appearance, budgets,
skills. Every screen has a default and takes Enter.

**Nothing is written to disk until you confirm on the final screen.** Abort at
screen seven and you have no half-configured install to clean up.

Already have Python:

```powershell
python install\wizard.py            # interactive
python install\wizard.py --quiet    # accept every default
python install\wizard.py --repair   # keep existing answers, re-run preflight
```

## Use

```
reges start                  # HUD + agent
reges say "plan my day"      # one intent, print, exit
reges doctor                 # check config against reality
reges budget --reset         # clear the session token meter
reges secrets set tebex_secret
```

HUD at `http://127.0.0.1:7717`. Push-to-talk on whatever combo you set in the wizard.

## Architecture

```
PTT ─▶ whisper.cpp ─▶ ROUTER ─▶ SKILL ─▶ vault write ─▶ Piper ─▶ speakers
                         │                    │
                         └──── state bus ─────┴──▶ SSE ──▶ HUD + orb
```

| Piece | File | What it is |
|---|---|---|
| State bus | `reges/state.py` | Single event bus. Orb, gauge, and log all render from it. |
| Vault | `reges/vault.py` | Markdown memory. Append-only `raw/`, path-clamped, SQLite for metrics only. |
| Router | `reges/router.py` | Keyword pre-pass, then LLM with a confidence floor. |
| LLM | `reges/llm/client.py` | Local OpenAI-compatible + Anthropic. Budget checked before spending. |
| Server | `reges/server.py` | Stdlib HTTP + SSE. No FastAPI, no uvicorn. |
| HUD | `hud/` | Canvas orb, vitals rail, command deck, token gauge. |
| Wizard | `install/wizard.py` | Nine screens, zero third-party imports. |

### Design decisions worth knowing

**The orb is a readout, not decoration.** Six states, each with its own colour *and*
its own motion signature — motion reads faster than hue at a glance. The whole HUD
palette derives from one CSS variable the state bus rewrites, so the interface
changes temperature with the agent.

**Skills disclose progressively.** The router sees only frontmatter. The SKILL.md
body loads after that skill wins. This is what keeps the router prompt small enough
to run on a 7B local model.

**The router asks when unsure.** Below `router_confidence_floor` it returns nothing
and asks. Silently running the wrong skill is what kills trust in a voice agent;
one short question does not.

**Deck buttons never hit the LLM.** Every button's intent contains a literal trigger
phrase, and `build_deck()` asserts this at boot. A drifted string would otherwise
become a silent LLM roundtrip that might route somewhere else entirely.

**Budget is checked before the call, not after.** Discovering you blew the cap by
reading the response is not a budget.

**Stdlib only in the core.** No `requests`, no SDK, no FastAPI. The fewer things
that can fail to install on a fresh Windows box, the better.

## Scope — read this

**Reges does not place trades.** No broker credentials, no order API, no autopilot,
no portfolio copying. `safety.allow_broker_orders` is `false` and the wizard does
not offer to change it.

What it does build on the market side: pre-market briefs, a documented strategy
library in `wiki/market/`, an out-of-sample backtest harness, and a voice-logged
trade journal that tracks your real P&L against what your own rules said to do.

Full reasoning in [PLAN.md §7](PLAN.md). Short version: autonomous execution fails
on infrastructure rather than strategy — expired auth mid-session, partial fills,
halted tickers, a retry loop that outruns the spend check. 13F-based portfolio
copying is quarterly and lags 45 days. *(Unverified: Webull publishes no retail
trading API; unofficial wrappers generally violate ToS.)* And "find a way to make
money" is not a resolvable instruction — a model handed that goal produces
confident, plausible, unprofitable plans.

The business-ops skills are the version of that instruction that has an answer:
compound the revenue that already exists.

## Status

Working now: wizard, config + DPAPI secrets, vault, state bus, token meter, HUD,
orb, SSE, router, skill loader, CLI.

Wired, needs binaries: voice (whisper.cpp + Piper).

Needs your keys: Tebex and wolves.land connectors.

Not built: market module, packaging, autostart.

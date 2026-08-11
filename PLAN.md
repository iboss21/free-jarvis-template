# REGES — Build Plan v1

Windows-first AI automation agent. Voice in, skills route, vault remembers, HUD shows.

**Not** Reges.Core / RegesCore. Separate codebase, separate lineage, shared name only.
Internal namespace for this project: `reges_agent` (package), `REGES_` (env prefix).

---

## 0. Defaults I locked in

You didn't answer the questions, so I picked. Every one of these is reversible; each is flagged so
you can veto without re-reading the code.

| # | Question | Default chosen | Why |
|---|---|---|---|
| 1 | App shape | Python backend + local web HUD served over localhost, wrapped by pywebview | No Node toolchain, no Electron 200MB, HUD is just HTML you can hack |
| 2 | Memory | Markdown vault for knowledge, SQLite for time-series only | You can read the vault with Notepad. Metrics need real queries. |
| 3 | Models | Hybrid: local (OpenAI-compatible endpoint) for routing/voice/cheap turns, Claude API for heavy reasoning, hard offline fallback | Routing on a 7B is fine. Analysis is not. |
| 4 | Install target | Assume near-fresh Windows; wizard detects and offers to fetch what's missing | The wizard is the product's first impression |
| 5 | Dependencies | Wizard verifies + configures; downloads models on request, never silently | Silent multi-GB downloads are how you lose trust in an installer |
| 6 | Orb | Colour **and** motion per state; always-on-top widget + embedded in HUD | Motion reads faster than colour at a glance |
| 7 | Voice trigger | Push-to-talk default. Wake word shipped but **off** | Wake word = a model hot on your mic all day |
| 8 | First venture | Lux Empire / Tebex | Real API, clean data, highest leverage |
| 9 | Write access | Draft-only in v1. Reges composes, you send | An agent that can send is an agent that can send the wrong thing to your customer list |
| 10 | Market data | yfinance free tier for v1, pluggable provider interface | Enough for research; swap in a paid feed later without touching skills |
| 11 | Broker | **None connected.** Research + journal layer only | See §7 |
| 12 | First skills | `plan-today`, `vault`, `tebex-pull`, `content-brief`, `market-brief` | Yours, not the carousel's generic five |
| 13 | Distribution | Personal tool. Packaging hooks left in, licensing not built | Selling adds licensing, auto-update, telemetry, support. 5x slower. |
| 14 | Voice engines | whisper.cpp (STT) + Piper (TTS) | Boring, fast, fully local, no API latency |

---

## 1. The loop

```
   PTT held ──▶ local STT ──▶ intent text
                                  │
                                  ▼
                            ROUTER (local model)
                    picks 1 skill from the loaded manifest
                                  │
                                  ▼
                      SKILL executes (python + LLM)
                    ├─ reads vault for context
                    ├─ calls tools / APIs
                    └─ writes result to vault
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
              local TTS speaks            HUD panel updates
```

Every stage pushes a state event to the orb. That is the whole design: **the orb is a live
readout of where you are in this loop**, not decoration.

---

## 2. Orb state machine

Six states. One accent colour + one motion signature each. The HUD's entire palette is derived
from the active state via a single CSS variable, so the whole interface breathes with the agent.

| State | Colour | Motion | Fires when |
|---|---|---|---|
| `IDLE` | dim cyan | slow drift, low density | nothing running |
| `LISTENING` | ice white | particles pull inward, pulse to mic RMS | PTT held |
| `THINKING` | violet | fast orbital churn | router deciding |
| `REASONING` | amber | expansion + contraction, wide radius | LLM generating |
| `WORKING` | green | tight lattice rotation, particle streaks | tool/API/file work |
| `SPEAKING` | electric blue | waveform-modulated radius | TTS playing |
| `ERROR` | red | jitter, decay | anything raised |

Token counting rides on the same bus: every LLM turn emits `tokens.in`, `tokens.out`, running
session total, and cost estimate. Displayed as a hairline gauge under the orb — it fills toward
the configured session budget and turns amber at 80%, red at 100%, at which point Reges refuses
further paid calls until you clear it.

Transport: Server-Sent Events on `/stream`. One-way, reconnects itself, no WebSocket ceremony.

---

## 3. Vault layout

Written by the installer wizard at a path you choose.

```
<vault>/
  raw/            every capture, timestamped, never edited
    2026-08-11/
      0731-morning-brief.md
      1402-metrics-pull.md
  wiki/           distilled knowledge, hand-editable, linked
    ventures/lux-empire.md
    ventures/wolves-land.md
    market/strategies.md
  outputs/        anything Reges produces for you to use
    drafts/
    reports/
  system/
    queue.md      intents waiting to run
    today.md      today's top 3
  .reges/
    metrics.sqlite   time-series only
    state.json
```

Rules the code enforces:
- `raw/` is append-only. Reges never rewrites a raw capture.
- Every file gets YAML frontmatter: `type`, `skill`, `created`, `tags`, `links`.
- Wikilinks `[[...]]` so it opens in Obsidian with zero config. Obsidian is optional, not required.
- No database for knowledge. If you can't grep it, it isn't memory.

---

## 4. Skills

One folder, one `SKILL.md`, loaded into the router manifest by frontmatter only. The body is
pulled into context **only when that skill is selected** — that's what keeps the router prompt
small enough to run on a local model.

```
skills/<name>/
  SKILL.md        frontmatter: name, description, triggers, needs, writes
  run.py          optional — python entrypoint if the skill does real work
```

The rule from your reference deck holds and I'd go further: a skill that needs more than one
page of SKILL.md is two skills.

---

## 5. Installer wizard

`install/bootstrap.ps1` → `install/wizard.py`. Nine screens, every one skippable with a sane
default, full config written only at the end (no half-configured state on abort).

1. Welcome + preflight (Python version, RAM, GPU, disk, existing install detection)
2. **Install location** — where the app lives
3. **Vault location** — where your data lives (deliberately a separate question; most people want
   the vault in OneDrive/Dropbox and the app on the fast disk)
4. Model backend — local endpoint URL + model id, test connection live
5. Claude API key — optional, stored via Windows DPAPI, never in plaintext TOML
6. Voice — STT model size, TTS voice, PTT hotkey capture, live mic test
7. **Appearance** — accent per orb state, orb density, always-on-top, theme; live preview
8. Budgets — session token cap, monthly USD cap, refuse-vs-warn behaviour
9. Skills — which of the five to enable, then write config, scaffold vault, register autostart

Preflight is not decoration. It is the thing that stops "it doesn't work" three days later.

---

## 6. Business-ops modules

This is the part that actually makes money, and it does it by compounding what you already run —
not by inventing revenue.

- **`tebex-pull`** — daily Lux Empire sales, per-resource. Writes to metrics.sqlite, flags any
  lxr-* resource whose 7-day trend broke its 28-day baseline. Speaks the outliers only.
- **`server-health`** — wolves.land: player count curve, crash markers, resource timing. Ties
  revenue events to server health so you can see "the day the crash loop cost you eleven sales."
- **`content-brief`** — takes the week's metric outliers and drafts the marketing angle: which
  resource to push, what the hook is, which channel. **Draft only.**
- **`plan-today`** — reads yesterday's outputs, open queue, and calendar; writes top 3 to
  `system/today.md` and reads it aloud.
- **`vault`** — read/write/search memory. The skill every other skill calls.

Roadmap after v1: `invoice-chase` (consultancy), `geoclothe-ops`, `repo-triage` across your 40+ repos.

---

## 7. Market module — scope and the hard line

**Reges will not place orders. No broker credentials, no order API, no autopilot.**

What it does build:

- `market-brief` — pre-market read: your watchlist, overnight moves, sector rotation, earnings
  ahead. Spoken in ~60 seconds.
- Strategy library in `wiki/market/` — documented, testable rules, versioned as markdown.
- Backtest harness — run a documented strategy over historical data, output honest stats
  (drawdown, hit rate, Sharpe) into `outputs/reports/`. Backtests that flatter themselves are
  worse than none, so the harness reports out-of-sample only.
- Trade journal — you log entries and exits by voice; Reges tracks your actual P&L against what
  the strategy said to do. This is the highest-value part and nobody builds it.

Why the line is where it is, stated once so it's on the record:

- Autonomous execution fails on the boring stuff — auth expiring mid-session, partial fills,
  halted tickers, a retry loop that fires 200 orders before the spend check runs. A daily limit
  is a soft guard on a system that can exceed it in one bad fill.
- Portfolio copying is structurally lossy. 13F filings are quarterly, lagged 45 days — you'd buy
  what someone may have already exited a quarter ago. Real-time "copy this person" feeds are paid
  signal services or scraped social, and both are worse.
- Webull has no public retail trading API. *(Unverified: unofficial reverse-engineered wrappers
  exist; using them generally violates ToS and risks account lockout.)* If you later want
  programmatic execution done legitimately, Alpaca is the broker with a real API and a paper
  endpoint — and I'd still put a human click in front of every live order.
- "Find a way to make money" is not a resolvable instruction. A model handed that goal produces
  confident, plausible, unprofitable plans. The business-ops modules in §6 are the version of
  that instruction that actually has an answer.

---

## 8. Build order

| Phase | Ships | Est. |
|---|---|---|
| **P0** | Repo, config schema, paths, vault writer, state bus, token meter | done in this drop |
| **P1** | Installer wizard, all 9 screens, config write, vault scaffold | done in this drop |
| **P2** | HUD + orb, SSE stream, command deck, live vitals | done in this drop |
| **P3** | Router + skill loader + the 5 SKILL.md files | done in this drop |
| **P4** | Voice: whisper.cpp STT, Piper TTS, PTT hotkey | wired, needs binaries |
| **P5** | Tebex + wolves.land live connectors | needs your API keys |
| **P6** | Market brief, backtest harness, trade journal | after P5 |
| **P7** | Packaging: PyInstaller one-file, code signing, autostart | when you decide it's a product |

---

## 9. Known risks

- **Local model too weak to route reliably.** Mitigation: router returns a confidence score;
  below threshold it asks you instead of guessing. Guessing wrong silently is the failure mode
  that kills trust in a voice agent.
- **Vault sprawl.** 400 raw captures and no distillation and it's a junk drawer. Mitigation:
  `vault-clean` runs weekly, promotes patterns to `wiki/`, and the promotion is a draft you approve.
- **PTT hotkey conflicts** with games/RedM. Mitigation: hotkey is captured in the wizard, not
  hardcoded, and conflicts are detected at capture time.
- **Windows autostart + GPU model load** = slow logins. Mitigation: autostart launches the HUD
  and state bus only; models load lazily on first intent.
- **Second project named Reges.** Mitigation: distinct package namespace and env prefix from
  day one, noted at the top of this file.

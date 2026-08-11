# Run Reges

No install. No dependencies. No wizard.

## Windows

Double-click **START.bat**

or:

```powershell
python run.py
```

## What happens

1. Writes `.reges\config.toml` with working defaults next to this folder
2. Creates the vault, data, skills and knowledge folders
3. Installs the agent-mode pack if `reges-agent-mode\` is sitting beside it
4. Starts the HUD on **http://127.0.0.1:7717** and opens your browser

Nothing calls out to the internet on boot. No API key is needed to start.

## Options

```
python run.py --port 7718
python run.py --app-dir D:\Reges
python run.py --no-browser
```

## Pointing it at your model

Edit `.reges\config.toml`:

```toml
[models]
local_base_url = "http://127.0.0.1:2126/v1"
local_model    = "your-model-id"
```

LM Studio holds 2126 and 2140 on your machine, so Reges binds 7717 and only
ever talks *out* to those.

## Agent layer

```
python -m reges agent knowledge      knowledge freshness (exit 1 if stale)
python -m reges agent venture list
python -m reges agent cycle "run the qc gate" --dry-run
python tests_agent.py                16 tests, no network
```

## First run

The first time you open it you get a setup screen, not a cockpit.

It reads your CPU, memory, graphics card and free disk, then tells you in plain
language what this machine can actually run — and recommends **local** or
**an AI provider** based on the answer. Nothing downloads until you choose.

Sizes are computed from bits-per-weight, so it works the same on a 4GB laptop
GPU, a 5090, a DGX Spark, an M-series Mac, or a machine with no GPU at all.

| Machine | Verdict |
|---|---|
| GTX 1650 4GB | 4B at Q4_K_M, ~2.3 GB |
| RTX 3060 / 4070 12GB | 14B at Q5_K_M, ~9.5 GB |
| RTX 5090 32GB | 30B at Q6_K, ~23.6 GB |
| DGX Spark 128GB unified | 70B at Q8_0, ~71 GB |
| MacBook Air M2 8GB | 8B at Q4_K_M, ~4.6 GB |
| No GPU, 8GB RAM | 4B at Q6_K, ~3.1 GB (slow) |

Re-run it any time at `/welcome.html`.

## Chat

**Chat is the default.** Type anything. If it clearly matches a skill the skill
runs; otherwise Reges just talks — and the exchange appears on screen above the input line.

```
you    hi
reges  Hey. What do you need?
```

It keeps the last dozen turns of context, so follow-ups work. Voice replies land
in the same place. Nothing forces you to phrase things as commands.

## The token meter

Local and paid are counted separately, because only one of them costs money.

```
TOKENS  110,300   +2,626 LOCAL · FREE   ...   44%   $0.444
```

| Reading | Meaning |
|---|---|
| `TOKENS 110,300` | **billable** tokens — paid API calls only |
| `+2,626 LOCAL · FREE` | tokens on your own hardware. Counted, never priced |
| `$0.444` | real spend. Click it for the per-model breakdown |

Click the dollar figure:

```
SESSION SPEND
claude-opus-5      12,000 in · 3,400 out · 40,000 cached — $0.165
claude-sonnet-5    80,000 in · 9,000 out                 — $0.250
mystery-model-v9    5,000 in ·   900 out                 — $0.029 est
qwen3-1.7b          1,800 in ·   826 out                 — free
total                                                      $0.444
```

Every model is priced at **its own rate**, not one global number. Cached input
is billed at the cache rate, which is a tenth of standard on the Claude line.

### Rates

Settings → **PRICING**. Built-in rates are dated and only include models whose
price was actually checked. A model with no rate on file is billed at the
fallback and marked **est** — never silently priced wrong. Add or override any
rate there; it writes to `config.toml` as a plain inline table you can hand-edit:

```toml
[pricing]
overrides = { "gpt-4o" = { input = 2.5, output = 10.0 } }
```

Local models are never charged regardless of what any table says.

## Settings

**http://127.0.0.1:7717/settings.html** — or the SETTINGS link top-right of the HUD.

- **Local provider**: LM Studio, LM Studio (Anthropic-compatible), Ollama,
  llama.cpp, vLLM, or any OpenAI-compatible URL
- **API provider**: Anthropic, OpenAI, OpenRouter, Groq, DeepSeek, Together,
  or any custom base URL
- **FETCH MODELS** reads the live model list off the endpoint
- **TEST CONNECTION** does a real round trip and reports latency and token counts.
  Not a ping
- Keys are written to the encrypted secret store beside your config and are
  never sent back to the browser
- **Routing**: pick which tier routes and which tier reasons. Router local +
  reasoning API is the sane default

## Orb speed

Settings → **APPEARANCE — NEURAL ORB**.

Default is one revolution every ~40 seconds. Slider goes 0 (frozen) to 2×.
Particle count and a reduce-motion mode are there too. Saved to config, applied
on next HUD load.

## Applications

The settings page lists what's installed and how Reges will control it.

| Tier | What | Reliability |
|---|---|---|
| Launch / focus / close | os-level | works |
| Official API | Photoshop UXP, Webull OpenAPI, Discord REST, obs-websocket, Figma REST | works |
| GUI automation | clicking through a window | last resort, gated |

The rule: if an app has an official surface, Reges uses it and never touches
the GUI. Webull orders go through the OpenAPI, never through the desktop
client. That isn't caution — driving a trading window with a 33-64% success
rate is how you get a wrong order.

## Voice

**Hold SPACE anywhere in the HUD, speak, release.** Or hold the mic button.

The mic is the browser's — no sounddevice, no keyboard hook, no admin rights.
Audio POSTs to 127.0.0.1 and is transcribed locally. It never leaves the machine.

**Ears** — first one found wins:

| Engine | Install |
|---|---|
| faster-whisper | `pip install faster-whisper` — best, no binary, uses your GPU |
| whisper.cpp | if `whisper-cli` is already on PATH |
| none | the HUD tells you, and typing still works |

**Mouth** — first one found wins:

| Engine | Install |
|---|---|
| Piper | binary + a `.onnx` voice in your models folder — best quality |
| Windows SAPI | **already on your machine. Nothing to install.** |
| browser speechSynthesis | final fallback, still local |

So on a clean Windows box: `pip install faster-whisper` and voice works. That is
the whole setup.

Check what it found: Settings → **VOICE**, or `/api/voice/status`.

### Language — read this if voice writes nonsense

**Reges pins English by default.** If you speak something else, set it in
Settings → VOICE → LANGUAGE before you use the mic.

Whisper auto-detects language from the clip. On a two-second phrase it guesses,
commits to the guess, and transcribes phonetically into whatever alphabet it
picked — which is how "hey Jarvis" comes back as Cyrillic. Pinning the language
removes the guess entirely, and picking English switches to English-only
weights that *cannot* emit another language.

Measured on the same recording:

| Setting | Result |
|---|---|
| auto-detect | `Hey, novice.` |
| English pinned | `Hey Jarvis.` |

Near-silence now returns nothing instead of an invented sentence.

### GPU

Reges tries your GPU and falls back to CPU on its own. It never fails because
CUDA is half-installed.

If you see `cublas64_12.dll is not found or cannot be loaded`, that means
CTranslate2 saw your card but the CUDA runtime DLLs aren't on the search path.
Reges now catches that, switches to CPU, and tells you. To get the GPU back:

```
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

then restart Reges — it looks inside site-packages for those DLLs and adds them
to the search path itself. CPU on `base` runs a few seconds per clip; GPU is
roughly 5-10x faster. Neither one uploads anything.

## What works right now

- HUD renders: orb, command deck, schedule, activity feed, token meter
- Type an intent, it routes to a skill by keyword and writes to the vault
- Eight deck buttons wired to skills
- Settings screen: 13 providers, live model fetch, real connection test, app inventory
- Voice: hold-space PTT, local transcription, spoken reply, mic level drives the orb
- Agent layer: staleness gate, venture registry, decision contract, all gates

## What does not work yet

- **No model is wired by default.** Every intent routes and logs, but the
  reasoning step needs `local_base_url` pointing at something real
- Publishing, marketplaces, scout — none of it is built. That's M5+

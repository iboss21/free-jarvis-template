# Teaching this to RegesCore

RegesCore is a local Qwen-family model served by LM Studio behind an Anthropic-compatible endpoint. Its weights were trained before every fact in `knowledge/`. This document is how you get correct behaviour out of it anyway, and where the real limits are.

---

## 1. The split that decides everything

There are three ways to put knowledge into a served model, and picking wrong here is the most expensive mistake available.

| Method | Good for | Wrong for | Cost to change |
|---|---|---|---|
| **Weights (fine-tune)** | Output format discipline, role protocol, refusal reflexes, JSON adherence, house style | Any fact about a third party | Full retrain |
| **System prompt** | Contract, laws, halt conditions, role definition | Volatile facts, long reference tables | Restart |
| **Retrieval (kb + skills)** | Everything that has an expiry date | Behaviour you need reliably every turn | Edit a file |

**The rule: bake behaviour, retrieve facts.**

A fine-tune that "knows" X pays revenue share is a fine-tune you cannot correct without retraining. That fact expired on 2026-08-07. Every entry in `knowledge/` has an expiry date and a `reverify` path precisely so no part of it ever ends up in weights.

So: `AGENT-MODE.md` is a candidate for weights eventually. `knowledge/` never is.

---

## 2. Loading — do it in this order

### Stage 1: prompt-only (do this first, it costs nothing)

`AGENT-MODE.md` goes in as the **host application system prompt**, emitted last.

Your base template contract already declares the host system prompt authoritative over persona — that's exactly the property agent mode needs. The persona stays intact; the contract wins where they conflict. No template change required for this stage.

Header per cycle, as the last system block:

```
REGES-AGENT-MODE/1
role: VENTURE
venture: newsletter-001
autonomy: L1
cycle: 0f3c...
knowledge_index: knowledge/INDEX.md
```

### Stage 2: skills on demand

Never load all seven SKILL.md at once. The router picks 1-3 by trigger match and loads only those.

At roughly 700-1,400 tokens each, the whole pack is a few thousand tokens — survivable, but it displaces the working context the model actually needs for the task. Progressive disclosure isn't a nicety here; on a 12GB card with the 35B offloading to CPU, prompt length is directly your time-to-first-token.

### Stage 3: knowledge on demand

`INDEX.md` is always loaded — it's small and it's the router. Individual `kb-###` entries load only when a skill declares `requires_kb` or the model emits `need_knowledge`.

### Stage 4: fine-tune (only after Stage 1-3 are measured)

See §5. Do not start here.

---

## 3. Constraints specific to your stack

These come from problems you have already hit, and the pack is designed around them.

**Tool schemas must stay small.** Claude's schemas blow llama.cpp's GBNF repetition cap and 400 every tool turn, which is why your grammar-fix proxy clamps `maxLength`, `maximum`, and `maxItems`. Every schema in `schemas/` is deliberately flat and short — no nested arrays of objects, no unbounded strings. If you add skills, keep that discipline or you reintroduce the 400s.

**Ports.** LM Studio holds both 2126 and 2140 on this machine. Any agent-mode service binds 2141+. Never stop the process holding 2140.

**Tool call format.** LM Studio's auto-derived parser expects Hermes-style JSON. Agent mode's output contract is a single JSON object per cycle, which is friendlier to that parser than multi-tool-call turns and is the reason the contract is shaped that way.

**Template edits.** If you eventually want the agent-mode header recognised structurally rather than as prose, that's a template change — and per your notes the live template is the per-quant JSON override at `.load.fields[N].value.jinjaPromptTemplate.template`, LM Studio rewrites the file on exit, and the safe edit is a raw-text splice rather than `ConvertFrom-Json`/`ConvertTo-Json`. **You do not need a template change for Stage 1.** Don't take that risk until prompt-only is measured.

**Queue depth.** You have seen `+13 QUEUED at Parallel 1`. Agent mode's bounded episodes help here — short cycles queue better than one long agentic run — but if Reges and Claude Code both point at 2126 they contend. A dedicated llama.cpp instance for the router tier on 2153 is worth the VRAM.

---

## 4. Which roles RegesCore should hold

Do not give a local model the BOARD role on day one. kb-004 is explicit that the supervisory agent is what makes the difference between profitable and not; it is the least forgiving position in the hierarchy.

| Role | Runs on | Why |
|---|---|---|
| BOARD | Claude, initially | Highest consequence, adversarial reasoning, must not be accommodating |
| OPERATOR | Claude → RegesCore after evals pass | Routing and allocation fields |
| VENTURE | RegesCore | Bounded, isolated, cheap, high volume |
| WORKER | RegesCore, or deterministic code | Most workers shouldn't be a model at all |

Promote a role to RegesCore when the eval suite passes at the stated threshold, not before. That's what `eval/` is for.

---

## 5. Fine-tuning — the honest version

If you decide to bake `AGENT-MODE.md` into weights:

**You cannot train the MXFP4_MOE quant.** Train the BF16 base, then requantize. You already have both the BF16 split and the imatrix file in the repo, so the path exists: BF16 base → LoRA → merge → requantize with imatrix → new GGUF ladder.

**A 35B MoE LoRA will not fit on a 12GB card.** Not with any offload trick worth the debugging. That's rented GPU time. Budget accordingly, and note that you'll repeat it every time the contract changes.

**Train on behaviour, never on facts.** A defensible dataset:
- Cycle transcripts where the correct output was `halt`, `need_knowledge`, or `reverify`
- Correct JSON-only outputs under the §4 contract, including malformed-input cases
- Role-boundary refusals (BOARD asked to write content → halt)
- Hard-line refusals from kb-005
- Arithmetic deferral — asked for a number, emits `fields` instead

Every example should be one where the *shape* of the answer is what's being learned. If an example's correctness depends on a platform rule, it belongs in retrieval, not the dataset.

**Do it after Stage 1-3, not instead.** Prompt-only tells you whether the contract is right. Fine-tuning a contract you haven't validated bakes in your mistakes.

---

## 6. Portability

The same pack loads into Reges unchanged:

| Layer | Reges | RegesCore |
|---|---|---|
| Contract | Agent SDK system prompt | Host system prompt, emitted last |
| Skills | skills/ dir, router picks 1-3 | Same dir, same router logic |
| Knowledge | Same files, same ttl gate | Same |
| Output | Same JSON contract | Same |
| Execution | Claude Agent SDK | LM Studio endpoint |

One pack, two runtimes, and the contract is written so a weaker executor fails *loudly* instead of quietly. That's the whole point: on a local model the halt conditions matter more, not less.

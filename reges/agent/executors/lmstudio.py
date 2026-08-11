"""LM Studio executor — OpenAI-compatible /v1/chat/completions.

Ports 2126 and 2140 are already held by LM Studio itself on the target
machine, so Reges binds 2151+ and only ever talks OUT to 2126.

If you prefer the Anthropic-compatible surface (/v1/messages), set
models.executor.api = "anthropic" — the request shape differs and is
handled below.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import Executor, Result


class LMStudioExecutor(Executor):
    name = "lmstudio"

    def run(self, system: str, user: str, *, on_event=None) -> Result:
        endpoint = self.cfg.get("endpoint", "http://127.0.0.1:2126").rstrip("/")
        model = self.cfg.get("model", "")
        api = (self.cfg.get("api") or "openai").lower()
        timeout = float(self.cfg.get("timeout_s", 300))

        if api == "anthropic":
            url = f"{endpoint}/v1/messages"
            body = {
                "model": model,
                "max_tokens": int(self.cfg.get("max_tokens", 2048)),
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        else:
            url = f"{endpoint}/v1/chat/completions"
            body = {
                "model": model,
                "max_tokens": int(self.cfg.get("max_tokens", 2048)),
                "temperature": float(self.cfg.get("temperature", 0.2)),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            return Result(text="", model=model, error=f"HTTP {exc.code}: {detail}")
        except Exception as exc:
            return Result(text="", model=model, error=str(exc))

        latency = int((time.time() - t0) * 1000)

        if api == "anthropic":
            text = "".join(
                b.get("text", "") for b in payload.get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            )
            usage = payload.get("usage", {}) or {}
            tin = int(usage.get("input_tokens", 0) or 0)
            tout = int(usage.get("output_tokens", 0) or 0)
        else:
            choices = payload.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content", "") or ""
            usage = payload.get("usage", {}) or {}
            tin = int(usage.get("prompt_tokens", 0) or 0)
            tout = int(usage.get("completion_tokens", 0) or 0)

        if on_event:
            on_event({"type": "result", "payload": {"model": model}})

        # Local inference has no per-token billing. Cost stays 0 on purpose —
        # the ledger's job is to show what CLOUD calls cost, and pretending
        # local tokens have a dollar price would corrupt that.
        return Result(text=text, model=model or "lmstudio", tokens_in=tin,
                      tokens_out=tout, cost_usd=0.0, latency_ms=latency)

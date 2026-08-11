"""Provider registry.

One place that knows how to talk to every backend, so the settings screen has
something real to configure and the LLM client has something real to call.

Two shapes only:

  openai      POST {base}/chat/completions   (LM Studio, Ollama, llama.cpp,
                                              vLLM, OpenRouter, Groq, xAI,
                                              DeepSeek, Together, OpenAI)
  anthropic   POST {base}/messages           (Anthropic, and LM Studio's
                                              Anthropic-compatible surface)

Everything else is a base URL, a header name, and a default model. Adding a
provider is a dict entry, not a code path.

Nothing here is guessed: each entry's `docs` field is where the shape came
from. If a provider changes, fix the entry, not the client.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Provider:
    id: str
    label: str
    kind: str                    # "local" | "hosted"
    api: str                     # "openai" | "anthropic"
    base_url: str
    auth: str = ""               # "" | "bearer" | "x-api-key"
    secret_key: str = ""         # SecretStore key name
    models_path: str = "/models"  # GET here to list models, "" if unsupported
    default_model: str = ""
    extra_headers: dict = field(default_factory=dict)
    docs: str = ""
    note: str = ""


PROVIDERS: dict[str, Provider] = {
    # ---------------- local ----------------
    "lmstudio": Provider(
        id="lmstudio", label="LM Studio", kind="local", api="openai",
        base_url="http://127.0.0.1:1234/v1",
        docs="https://lmstudio.ai/docs",
        note="LM Studio's default port is 1234. On this machine it also holds "
             "2126 and 2140 — point at whichever one is actually serving.",
    ),
    "lmstudio_anthropic": Provider(
        id="lmstudio_anthropic", label="LM Studio (Anthropic-compatible)",
        kind="local", api="anthropic",
        base_url="http://127.0.0.1:2126/v1", models_path="/models",
        note="Use when LM Studio is serving /v1/messages for Claude clients.",
    ),
    "ollama": Provider(
        id="ollama", label="Ollama", kind="local", api="openai",
        base_url="http://127.0.0.1:11434/v1",
        docs="https://github.com/ollama/ollama/blob/main/docs/openai.md",
    ),
    "llamacpp": Provider(
        id="llamacpp", label="llama.cpp server", kind="local", api="openai",
        base_url="http://127.0.0.1:8080/v1",
        docs="https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
    ),
    "vllm": Provider(
        id="vllm", label="vLLM", kind="local", api="openai",
        base_url="http://127.0.0.1:8000/v1",
        docs="https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html",
    ),
    "custom_openai": Provider(
        id="custom_openai", label="Custom (OpenAI-compatible)", kind="local",
        api="openai", base_url="http://127.0.0.1:8080/v1", auth="bearer",
        secret_key="custom_api_key",
        note="Any server exposing /chat/completions. Set your own base URL.",
    ),

    # ---------------- hosted ----------------
    "anthropic": Provider(
        id="anthropic", label="Anthropic (Claude)", kind="hosted", api="anthropic",
        base_url="https://api.anthropic.com/v1", auth="x-api-key",
        secret_key="anthropic_api_key", models_path="/models",
        default_model="claude-sonnet-4-6",
        extra_headers={"anthropic-version": "2023-06-01"},
        docs="https://docs.claude.com/en/api/overview",
    ),
    "openai": Provider(
        id="openai", label="OpenAI", kind="hosted", api="openai",
        base_url="https://api.openai.com/v1", auth="bearer",
        secret_key="openai_api_key", docs="https://platform.openai.com/docs/api-reference",
    ),
    "openrouter": Provider(
        id="openrouter", label="OpenRouter", kind="hosted", api="openai",
        base_url="https://openrouter.ai/api/v1", auth="bearer",
        secret_key="openrouter_api_key", docs="https://openrouter.ai/docs",
        note="One key, many models. Useful for comparing without new accounts.",
    ),
    "groq": Provider(
        id="groq", label="Groq", kind="hosted", api="openai",
        base_url="https://api.groq.com/openai/v1", auth="bearer",
        secret_key="groq_api_key", docs="https://console.groq.com/docs",
    ),
    "deepseek": Provider(
        id="deepseek", label="DeepSeek", kind="hosted", api="openai",
        base_url="https://api.deepseek.com/v1", auth="bearer",
        secret_key="deepseek_api_key", docs="https://api-docs.deepseek.com/",
    ),
    "together": Provider(
        id="together", label="Together AI", kind="hosted", api="openai",
        base_url="https://api.together.xyz/v1", auth="bearer",
        secret_key="together_api_key", docs="https://docs.together.ai/docs",
    ),
    "custom_hosted": Provider(
        id="custom_hosted", label="Custom hosted (OpenAI-compatible)",
        kind="hosted", api="openai", base_url="", auth="bearer",
        secret_key="custom_api_key",
    ),
}


def listing() -> list[dict]:
    return [
        {"id": p.id, "label": p.label, "kind": p.kind, "api": p.api,
         "base_url": p.base_url, "needs_key": bool(p.auth),
         "secret_key": p.secret_key, "default_model": p.default_model,
         "docs": p.docs, "note": p.note}
        for p in PROVIDERS.values()
    ]


def get(pid: str) -> Provider | None:
    return PROVIDERS.get(pid)


def _headers(p: Provider, key: str | None) -> dict:
    h = {"Content-Type": "application/json"}
    h.update(p.extra_headers)
    if p.auth == "bearer" and key:
        h["Authorization"] = f"Bearer {key}"
    elif p.auth == "x-api-key" and key:
        h["x-api-key"] = key
    return h


def _request(url: str, headers: dict, payload: dict | None, timeout: float):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 method="POST" if data else "GET")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models(p: Provider, key: str | None = None, base_url: str = "",
                timeout: float = 10.0) -> tuple[list[str], str]:
    """Return (models, error). Never raises."""
    base = (base_url or p.base_url).rstrip("/")
    if not p.models_path or not base:
        return [], "this provider does not expose a model list"
    try:
        data = _request(base + p.models_path, _headers(p, key), None, timeout)
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:
        return [], str(exc)

    items = data.get("data") or data.get("models") or []
    out = []
    for it in items:
        if isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
            if mid:
                out.append(str(mid))
        elif isinstance(it, str):
            out.append(it)
    return sorted(set(out)), ""


def test(p: Provider, key: str | None, base_url: str, model: str,
         timeout: float = 30.0) -> dict:
    """Real round trip, not a ping. Returns a result dict, never raises."""
    base = (base_url or p.base_url).rstrip("/")
    if not base:
        return {"ok": False, "error": "no base URL set"}
    if p.auth and not key:
        return {"ok": False, "error": f"no API key stored for {p.secret_key}"}

    t0 = time.time()
    try:
        if p.api == "anthropic":
            payload = {"model": model or p.default_model, "max_tokens": 16,
                       "messages": [{"role": "user", "content": "Reply with the single word: ok"}]}
            data = _request(base + "/messages", _headers(p, key), payload, timeout)
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if isinstance(b, dict) and b.get("type") == "text")
            usage = data.get("usage", {}) or {}
            tin = usage.get("input_tokens", 0)
            tout = usage.get("output_tokens", 0)
        else:
            payload = {"model": model, "max_tokens": 16, "temperature": 0,
                       "messages": [{"role": "user", "content": "Reply with the single word: ok"}]}
            data = _request(base + "/chat/completions", _headers(p, key), payload, timeout)
            choices = data.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content", "") or ""
            usage = data.get("usage", {}) or {}
            tin = usage.get("prompt_tokens", 0)
            tout = usage.get("completion_tokens", 0)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"HTTP {exc.code}: {body}",
                "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300],
                "latency_ms": int((time.time() - t0) * 1000)}

    return {"ok": True, "reply": (text or "").strip()[:120],
            "tokens_in": tin, "tokens_out": tout,
            "latency_ms": int((time.time() - t0) * 1000)}

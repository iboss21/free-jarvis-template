"""LLM access.

Two tiers behind one call. `tier="local"` hits an OpenAI-compatible endpoint;
`tier="remote"` hits the Anthropic Messages API. Both report tokens to the state
bus, so the gauge under the orb is a real measurement, not an estimate.

Budget is checked *before* the request, not after. Discovering you blew the cap
by reading the response is not a budget.

stdlib urllib only -- no requests, no anthropic SDK. One fewer thing to fail at
install time on a fresh box.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import RegesConfig, SecretStore
from ..state import BUS, State

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(RuntimeError):
    pass


def _estimate_tokens(text: str) -> int:
    """~4 chars/token. Used only to pre-check the budget before a call; the real
    counts come back from the API and overwrite this."""
    return max(1, len(text) // 4)


class LLM:
    def __init__(self, cfg: RegesConfig, secrets: SecretStore | None = None):
        self.cfg = cfg
        self.secrets = secrets

    # -- public ------------------------------------------------------------ #
    def complete(self, system: str, user: str, tier: str = "local",
                 max_tokens: int = 1024, temperature: float = 0.2) -> str:
        if tier == "remote" and not self.cfg.models.remote_enabled:
            tier = "local"

        projected = _estimate_tokens(system + user) + max_tokens
        if tier == "remote":
            BUS.check_budget(projected)   # raises BudgetExceeded before spending

        try:
            if tier == "remote":
                return self._remote(system, user, max_tokens, temperature)
            return self._local(system, user, max_tokens, temperature)
        except LLMError:
            if tier == "remote" and self.cfg.models.offline_fallback:
                BUS.log("warn", "remote unreachable -- degrading to local")
                return self._local(system, user, max_tokens, temperature)
            raise

    # -- local -------------------------------------------------------------- #
    def _local(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        m = self.cfg.models
        if not m.local_model:
            raise LLMError("no local model configured (run: reges setup)")

        payload = {
            "model": m.local_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        data = self._post(m.local_base_url.rstrip("/") + "/chat/completions",
                          payload, {}, m.local_timeout_s)

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"unexpected local response shape: {str(data)[:200]}")

        usage = data.get("usage") or {}
        # Runs on the user's own hardware. Counted, never charged.
        BUS.add_tokens(usage.get("prompt_tokens", _estimate_tokens(system + user)),
                       usage.get("completion_tokens", _estimate_tokens(text)),
                       m.local_model, billable=False)
        return text

    # -- remote ------------------------------------------------------------- #
    def _remote(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        key = self.secrets.get("anthropic_api_key") if self.secrets else None
        if not key:
            raise LLMError("no API key (run: reges secrets set anthropic_api_key)")

        m = self.cfg.models
        payload = {
            "model": m.remote_model,
            "max_tokens": min(max_tokens, m.remote_max_tokens),
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        data = self._post(ANTHROPIC_URL, payload, headers, 180)

        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

        usage = data.get("usage") or {}
        BUS.add_tokens(usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                       m.remote_model, billable=True,
                       cache_read=usage.get("cache_read_input_tokens", 0) or 0)
        return text

    # -- transport ---------------------------------------------------------- #
    @staticmethod
    def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:400]
            except Exception:
                pass
            raise LLMError(f"HTTP {e.code}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise LLMError(f"unreachable: {getattr(e, 'reason', e)}")
        except json.JSONDecodeError:
            raise LLMError("response was not JSON")

    # -- convenience --------------------------------------------------------- #
    def reason(self, system: str, user: str, max_tokens: int = 2048) -> str:
        """Heavy turn. Goes to whichever tier the config says handles reasoning."""
        with BUS.during(State.REASONING, "reasoning"):
            return self.complete(system, user, tier=self.cfg.models.reasoning_tier,
                                 max_tokens=max_tokens, temperature=0.3)

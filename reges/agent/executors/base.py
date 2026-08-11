from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Result:
    text: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    events: list = field(default_factory=list)
    error: str = ""


class Executor:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def run(self, system: str, user: str, *, on_event=None) -> Result:
        raise NotImplementedError

"""Where the agent layer keeps its files, derived from the existing RegesConfig."""
from __future__ import annotations

from pathlib import Path


class AgentPaths:
    def __init__(self, cfg):
        app = Path(cfg.paths.app_dir) if getattr(cfg.paths, "app_dir", "") else Path.cwd()
        vault = Path(cfg.paths.vault_dir) if getattr(cfg.paths, "vault_dir", "") else app / "vault"
        self.app = app
        self.vault = vault
        self.data = app / "data"
        self.knowledge = app / "knowledge"
        self.skills = app / "skills"
        self.contract = app / "AGENT-MODE.md"

    @property
    def db(self) -> Path:
        return self.data / "reges.db"

    @property
    def events(self) -> Path:
        return self.data / "events.jsonl"

    @property
    def halt(self) -> Path:
        return self.data / "HALT"

    def ensure(self) -> None:
        for d in (self.data, self.knowledge, self.skills, self.vault):
            d.mkdir(parents=True, exist_ok=True)

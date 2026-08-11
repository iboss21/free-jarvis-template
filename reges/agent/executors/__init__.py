"""Executor backends. One interface, three implementations."""
from __future__ import annotations

from .base import Executor, Result
from .echo import EchoExecutor
from .claude_code import ClaudeCodeExecutor
from .lmstudio import LMStudioExecutor


def build(cfg: dict) -> Executor:
    mode = (cfg.get("mode") or "echo").lower()
    if mode == "echo":
        return EchoExecutor(cfg)
    if mode == "claude_code":
        return ClaudeCodeExecutor(cfg)
    if mode == "lmstudio":
        return LMStudioExecutor(cfg)
    raise ValueError(f"unknown executor mode: {mode}")


__all__ = ["Executor", "Result", "build", "EchoExecutor",
           "ClaudeCodeExecutor", "LMStudioExecutor"]

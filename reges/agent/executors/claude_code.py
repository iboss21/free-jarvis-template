"""Claude Code executor.

Wraps the documented non-interactive CLI:

    claude -p "<prompt>" --output-format stream-json --allowedTools ... --permission-mode ...

stream-json emits each message as it arrives and the final result object
carries usage and total_cost_usd, which is exactly what the orb and the
ledger need. No estimation, no drift.

Docs: https://docs.claude.com/en/docs/claude-code/overview

Deliberately never passes --dangerously-skip-permissions. Narrow the surface
with --allowedTools instead; that is what a skill's capability tier compiles
down to.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time

from .base import Executor, Result


class ClaudeCodeExecutor(Executor):
    name = "claude_code"

    def run(self, system: str, user: str, *, on_event=None) -> Result:
        binary = self.cfg.get("binary", "claude")
        if not shutil.which(binary):
            return Result(text="", error=f"{binary} not found on PATH")

        cmd = [
            binary, "-p", f"{system}\n\n{user}",
            "--output-format", "stream-json",
            "--permission-mode", self.cfg.get("permission_mode", "default"),
        ]
        tools = self.cfg.get("allowed_tools")
        if tools:
            cmd += ["--allowedTools", ",".join(tools) if isinstance(tools, list) else str(tools)]
        max_turns = self.cfg.get("max_turns")
        if max_turns:
            cmd += ["--max-turns", str(max_turns)]

        t0 = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            return Result(text="", error=str(exc))

        out_text = ""
        result = Result(text="", model="claude-code")
        events: list = []

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(msg)
            if on_event:
                on_event(msg)

            mtype = msg.get("type")
            if mtype == "result":
                out_text = msg.get("result", "") or out_text
                usage = msg.get("usage") or {}
                result.tokens_in = int(usage.get("input_tokens", 0) or 0)
                result.tokens_out = int(usage.get("output_tokens", 0) or 0)
                result.cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
                result.cost_usd = float(msg.get("total_cost_usd", 0.0) or 0.0)
            elif mtype == "assistant":
                for block in (msg.get("message", {}) or {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        out_text += block.get("text", "")

        proc.wait(timeout=self.cfg.get("timeout_s", 300))
        stderr = (proc.stderr.read() if proc.stderr else "") or ""
        if proc.returncode != 0 and not out_text:
            result.error = stderr.strip()[:2000] or f"exit {proc.returncode}"

        result.text = out_text
        result.events = events
        result.latency_ms = int((time.time() - t0) * 1000)
        return result

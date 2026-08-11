"""Agent state bus.

One process-wide bus. Everything -- router, skills, voice, LLM clients -- pushes
events here; the HUD subscribes over SSE. The orb is a direct rendering of this
bus, not a decoration driven separately.

Design notes:
  * States are a stack, not a scalar. A skill that goes WORKING -> REASONING ->
    WORKING pops back correctly instead of getting stuck amber.
  * Subscribers get a bounded queue. A slow/dead HUD drops frames rather than
    blocking the agent -- backpressure must never reach the work.
  * Every event carries the full snapshot. A HUD that reconnects mid-task
    renders correctly from the first frame without a replay protocol.
"""

from __future__ import annotations

import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator


class State(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    REASONING = "reasoning"
    WORKING = "working"
    SPEAKING = "speaking"
    ERROR = "error"


def _row(local: bool) -> dict:
    return {"in": 0, "out": 0, "cache_read": 0, "calls": 0,
            "usd": 0.0, "priced": True, "local": local}


@dataclass
class TokenMeter:
    """Running token + cost accounting for the session.

    Local and cloud tokens are counted SEPARATELY and only cloud tokens cost
    money. A model running on your own GPU has no per-token bill; showing a
    dollar figure for it is just wrong, and it corrupts the one number that
    actually matters — what this month is costing you.
    """
    tokens_in: int = 0            # cloud only, billable
    tokens_out: int = 0           # cloud only, billable
    cache_read: int = 0
    local_in: int = 0             # your own hardware, free
    local_out: int = 0
    calls: int = 0
    local_calls: int = 0
    session_cap: int = 250_000
    price_in_per_mtok: float = 3.0     # fallback only, for unpriced models
    price_out_per_mtok: float = 15.0
    # Per-model accounting. One global rate was wrong for every model but one.
    by_model: dict = field(default_factory=dict)
    price_overrides: dict = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Billable tokens. The cap exists to stop spend, so local is excluded."""
        return self.tokens_in + self.tokens_out

    @property
    def local_total(self) -> int:
        return self.local_in + self.local_out

    @property
    def usd(self) -> float:
        return round(sum(m["usd"] for m in self.by_model.values()), 6)

    @property
    def unpriced(self) -> list:
        return sorted(k for k, m in self.by_model.items() if not m["priced"])

    @property
    def pct(self) -> float:
        if self.session_cap <= 0:
            return 0.0
        return min(self.total / self.session_cap * 100.0, 999.0)

    def add(self, tin: int, tout: int, billable: bool = True,
            model: str = "", cache_read: int = 0) -> None:
        tin, tout, cache_read = max(0, int(tin)), max(0, int(tout)), max(0, int(cache_read))
        if not billable:
            self.local_in += tin
            self.local_out += tout
            self.local_calls += 1
            row = self.by_model.setdefault(model or "local", _row(True))
            row["in"] += tin; row["out"] += tout; row["calls"] += 1
            row["local"] = True
            return

        from . import pricing
        self.tokens_in += tin
        self.tokens_out += tout
        self.cache_read += cache_read
        self.calls += 1
        usd, priced = pricing.cost_of(model, tin, tout, cache_read,
                                      self.price_overrides)
        if not priced:
            # Unknown model: fall back to the configured default rate but SAY
            # it is a fallback, so a wrong figure is never presented as fact.
            usd = (tin / 1e6 * self.price_in_per_mtok
                   + tout / 1e6 * self.price_out_per_mtok)
        row = self.by_model.setdefault(model or "unknown", _row(False))
        row["in"] += tin; row["out"] += tout; row["cache_read"] += cache_read
        row["calls"] += 1; row["usd"] += usd; row["priced"] = priced

    def snapshot(self) -> dict[str, Any]:
        models = []
        for name, m in sorted(self.by_model.items()):
            models.append({"model": name, "local": m["local"],
                           "in": m["in"], "out": m["out"],
                           "cache_read": m["cache_read"], "calls": m["calls"],
                           "usd": round(m["usd"], 6), "priced": m["priced"]})
        return {
            "in": self.tokens_in,
            "out": self.tokens_out,
            "cache_read": self.cache_read,
            "models": models,
            "unpriced": self.unpriced,
            "total": self.total,
            "calls": self.calls,
            "local_in": self.local_in,
            "local_out": self.local_out,
            "local_total": self.local_total,
            "local_calls": self.local_calls,
            "all_total": self.total + self.local_total,
            "cap": self.session_cap,
            "pct": round(self.pct, 1),
            "usd": round(self.usd, 4),
        }


class BudgetExceeded(RuntimeError):
    pass


class StateBus:
    def __init__(self, session_cap: int = 250_000):
        self._lock = threading.RLock()
        self._stack: list[tuple[State, str]] = [(State.IDLE, "")]
        self._subs: list[queue.Queue] = []
        self._tokens = TokenMeter(session_cap=session_cap)
        self._level: float = 0.0          # mic/audio RMS 0..1, drives orb pulse
        self._activity: list[dict] = []   # rolling log for the HUD
        self._started = time.time()
        self._on_cap = "refuse"
        self._warned = False

    # -- config ------------------------------------------------------------ #
    def configure(self, *, session_cap: int, price_in: float, price_out: float,
                  on_cap: str) -> None:
        with self._lock:
            self._tokens.session_cap = session_cap
            self._tokens.price_in_per_mtok = price_in
            self._tokens.price_out_per_mtok = price_out
            self._on_cap = on_cap

    # -- subscription ------------------------------------------------------ #
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subs.append(q)
            snap = self.snapshot()
        q.put(snap)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self) -> None:
        snap = self.snapshot()
        dead = []
        for q in list(self._subs):
            try:
                q.put_nowait(snap)
            except queue.Full:
                # Drop the oldest frame and retry once. A stalled HUD must never
                # apply backpressure to the agent doing real work.
                try:
                    q.get_nowait()
                    q.put_nowait(snap)
                except (queue.Empty, queue.Full):
                    dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # -- state ------------------------------------------------------------- #
    @property
    def state(self) -> State:
        with self._lock:
            return self._stack[-1][0]

    def push(self, state: State, label: str = "") -> None:
        with self._lock:
            self._stack.append((state, label))
        self._publish()

    def pop(self) -> None:
        with self._lock:
            if len(self._stack) > 1:
                self._stack.pop()
        self._publish()

    @contextmanager
    def during(self, state: State, label: str = "") -> Iterator[None]:
        """with bus.during(State.WORKING, "tebex pull"): ..."""
        self.push(state, label)
        try:
            yield
        except Exception as exc:
            self.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self.pop()

    def say(self, role: str, text: str) -> None:
        """Put a conversation turn on the wire so the HUD can render it.

        Without this the agent answers into the void: the vault has the reply,
        the log has a token count, and the screen has nothing.
        """
        self.log("chat", (text or "")[:4000], role=role, chat=True)

    def error(self, message: str) -> None:
        self.log("error", message)
        with self._lock:
            self._stack.append((State.ERROR, message))
        self._publish()
        # Auto-clear so the orb doesn't sit red forever after a handled failure.
        threading.Timer(4.0, self._clear_error).start()

    def _clear_error(self) -> None:
        with self._lock:
            self._stack = [(s, l) for s, l in self._stack if s is not State.ERROR] or [(State.IDLE, "")]
        self._publish()

    # -- signals ----------------------------------------------------------- #
    def set_level(self, level: float) -> None:
        """Audio RMS 0..1. Published without a full snapshot broadcast storm."""
        with self._lock:
            self._level = max(0.0, min(1.0, level))
        self._publish()

    def log(self, kind: str, message: str, **extra: Any) -> None:
        entry = {"t": time.time(), "kind": kind, "msg": message, **extra}
        with self._lock:
            self._activity.append(entry)
            del self._activity[:-200]
        self._publish()

    # -- tokens ------------------------------------------------------------ #
    def check_budget(self, projected: int = 0) -> None:
        """Raise before a PAID call would breach the cap. Local calls never
        reach here — they cost nothing, so capping them protects nothing."""
        with self._lock:
            if self._tokens.session_cap <= 0:
                return
            if self._tokens.total + projected < self._tokens.session_cap:
                return
            on_cap = self._on_cap
        if on_cap == "refuse":
            raise BudgetExceeded(
                f"session token cap reached ({self._tokens.total:,}/{self._tokens.session_cap:,}). "
                "Clear it with `reges budget --reset` or raise the cap."
            )
        self.log("warn", "session token cap exceeded -- continuing (on_cap=warn)")

    def add_tokens(self, tin: int, tout: int, model: str = "",
                   billable: bool = True, cache_read: int = 0) -> None:
        """billable=False for anything running on the user's own hardware."""
        with self._lock:
            self._tokens.add(tin, tout, billable, model, cache_read)
            pct = self._tokens.pct
            warn = (not self._warned) and pct >= 80
            if warn:
                self._warned = True
        if warn:
            self.log("warn", f"token budget at {pct:.0f}% of session cap")
        if billable:
            from . import pricing
            with self._lock:
                row = self._tokens.by_model.get(model or "unknown", {})
            tag = f" · {pricing.fmt_usd(row.get('usd', 0))}"
            if not row.get("priced", True):
                tag += " (est — no rate on file)"
        else:
            tag = " (local, free)"
        self.log("tokens", f"{model or 'llm'} +{tin}/{tout}{tag}",
                 tin=tin, tout=tout, billable=billable)

    def reset_budget(self) -> None:
        with self._lock:
            cap = self._tokens.session_cap
            pin, pout = self._tokens.price_in_per_mtok, self._tokens.price_out_per_mtok
            self._tokens = TokenMeter(session_cap=cap, price_in_per_mtok=pin,
                                      price_out_per_mtok=pout)
            self._warned = False
        self._publish()

    # -- snapshot ---------------------------------------------------------- #
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state, label = self._stack[-1]
            return {
                "state": state.value,
                "label": label,
                "depth": len(self._stack) - 1,
                "level": round(self._level, 3),
                "tokens": self._tokens.snapshot(),
                "uptime_s": int(time.time() - self._started),
                "activity": self._activity[-40:],
                "ts": time.time(),
            }


BUS = StateBus()

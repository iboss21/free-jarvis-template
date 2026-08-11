"""What a token actually costs.

Two rules this module exists to enforce:

  1. Local models cost nothing. A model on your own GPU has no per-token bill,
     so it is counted and never priced. That is handled in state.py; nothing
     here should ever be applied to a local call.

  2. Paid models cost what THEY cost, not what some hardcoded default cost.
     One global $3/$15 was wrong for every model except one.

Rates are seeded only where they were actually checked, with the date. Anything
not in the table is reported as UNPRICED rather than guessed — a confidently
wrong cost figure is worse than an honest blank. Override or add any rate in
Settings; overrides win over the table.
"""
from __future__ import annotations

from dataclasses import dataclass

PRICES_VERIFIED_ON = "2026-08-11"


@dataclass(frozen=True)
class Rate:
    """USD per million tokens."""
    input: float
    output: float
    cache_read: float = 0.0     # 0 means "same as input"
    note: str = ""

    def cost(self, tin: int, tout: int, cache_read: int = 0) -> float:
        cr = self.cache_read if self.cache_read else self.input
        return (max(0, tin) / 1e6 * self.input
                + max(0, tout) / 1e6 * self.output
                + max(0, cache_read) / 1e6 * cr)


# Matched longest-pattern-first against a lowercased model id.
# Only entries verified on PRICES_VERIFIED_ON. Everything else stays unpriced.
TABLE: dict[str, Rate] = {
    "claude-opus-5":   Rate(5.00, 25.00, 0.50),
    "claude-sonnet-5": Rate(2.00, 10.00, 0.20,
                            "introductory rate, listed through 2026-08-31"),
    "claude-haiku-4-5": Rate(1.00, 5.00, 0.10),
    "claude-fable-5":  Rate(10.00, 50.00, 1.00),
    "claude-opus":     Rate(5.00, 25.00, 0.50, "opus family fallback"),
    "claude-sonnet":   Rate(3.00, 15.00, 0.30, "sonnet 4.x fallback"),
    "claude-haiku":    Rate(1.00, 5.00, 0.10, "haiku family fallback"),
}

BATCH_DISCOUNT = 0.5   # Batch API is half price across the Claude line


def lookup(model: str, overrides: dict | None = None) -> Rate | None:
    """Return the rate for a model id, or None if we genuinely don't know."""
    if not model:
        return None
    key = str(model).strip().lower()

    if overrides:
        for pat, val in overrides.items():
            if pat and pat.lower() in key:
                try:
                    return Rate(float(val.get("input", 0)),
                                float(val.get("output", 0)),
                                float(val.get("cache_read", 0) or 0),
                                "user override")
                except (AttributeError, TypeError, ValueError):
                    continue

    for pat in sorted(TABLE, key=len, reverse=True):
        if pat in key:
            return TABLE[pat]
    return None


def cost_of(model: str, tin: int, tout: int, cache_read: int = 0,
            overrides: dict | None = None) -> tuple[float, bool]:
    """Returns (usd, priced). priced=False means the model is not in the table
    and has no override — cost is reported as 0 and flagged, never invented."""
    rate = lookup(model, overrides)
    if rate is None:
        return 0.0, False
    return rate.cost(tin, tout, cache_read), True


def describe(model: str, overrides: dict | None = None) -> dict:
    rate = lookup(model, overrides)
    if rate is None:
        return {"model": model, "priced": False,
                "note": "no rate on file — set one in Settings"}
    return {
        "model": model, "priced": True,
        "input": rate.input, "output": rate.output,
        "cache_read": rate.cache_read or rate.input,
        "note": rate.note, "verified_on": PRICES_VERIFIED_ON,
    }


def catalog(overrides: dict | None = None) -> list[dict]:
    rows = [describe(pat, None) | {"pattern": pat} for pat in TABLE]
    for pat in (overrides or {}):
        rows.append(describe(pat, overrides) | {"pattern": pat, "user": True})
    return rows


def fmt_usd(v: float) -> str:
    """Money the user can actually read.

    $0.0000 for everything is useless when a call costs eight ten-thousandths
    of a cent, and $0.00001234 is useless when the bill is real.
    """
    v = float(v or 0)
    if v <= 0:
        return "$0.00"
    if v < 0.01:
        return f"${v:.4f}".rstrip("0").rstrip(".") or "$0.00"
    if v < 1:
        return f"${v:.3f}"
    if v < 100:
        return f"${v:.2f}"
    return f"${v:,.2f}"


def fmt_rate(rate: Rate) -> str:
    return f"${rate.input:g} / ${rate.output:g} per Mtok"

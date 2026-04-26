"""Bank-settlement simulator.

The assignment specifies the distribution: 70% success, 20% fail, 10% hang.
Probabilities are configurable via env vars (settings.PAYOUT_*_RATE) so
tests can pin the outcome deterministically.
"""

from __future__ import annotations

import enum
import random

from django.conf import settings


class SettlementOutcome(enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    HANG = "hang"


def simulate_settlement(rng: random.Random | None = None) -> SettlementOutcome:
    """Pick an outcome weighted by settings.

    A random `Random` instance can be injected for deterministic tests.
    """

    rng = rng or random
    rates = (
        settings.PAYOUT_SUCCESS_RATE,
        settings.PAYOUT_FAILURE_RATE,
        settings.PAYOUT_HANG_RATE,
    )
    total = sum(rates)
    if total <= 0:  # pragma: no cover - misconfiguration
        raise RuntimeError("PAYOUT_*_RATE settings must sum to > 0")
    roll = rng.random() * total
    if roll < rates[0]:
        return SettlementOutcome.SUCCESS
    if roll < rates[0] + rates[1]:
        return SettlementOutcome.FAILURE
    return SettlementOutcome.HANG

"""Payout state machine.

Two layers of enforcement:

1. `assert_can_transition()` is a Python guard - it raises before we even
   issue an UPDATE if the caller is requesting an illegal pair.
2. Every transition is also written as a conditional UPDATE
   (`.filter(status=expected).update(status=new)`) so the database itself
   refuses to overwrite a state that another worker may have already moved.

Both are required: the Python guard catches programmer errors with a clear
exception, and the conditional UPDATE catches concurrent writers racing on
the same row.
"""

from __future__ import annotations

from apps.payouts.exceptions import IllegalStateTransitionError


class PayoutStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]

    TERMINAL = frozenset({COMPLETED, FAILED})


# Allowed (from -> {to,...}). Anything not listed here is illegal,
# including:
#   - completed -> pending  (backwards)
#   - failed    -> completed (backwards)
#   - processing -> pending (retries don't revert; they re-run in PROCESSING)
#   - any self-loop except as explicitly allowed below.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    PayoutStatus.PENDING: frozenset({PayoutStatus.PROCESSING}),
    PayoutStatus.PROCESSING: frozenset(
        {PayoutStatus.COMPLETED, PayoutStatus.FAILED}
    ),
    PayoutStatus.COMPLETED: frozenset(),
    PayoutStatus.FAILED: frozenset(),
}


def is_legal(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def assert_can_transition(from_status: str, to_status: str) -> None:
    if not is_legal(from_status, to_status):
        raise IllegalStateTransitionError(
            f"illegal transition: {from_status} -> {to_status}"
        )

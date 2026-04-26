"""State machine tests.

Allowed transitions:
  pending -> processing
  processing -> completed
  processing -> failed

Everything else is illegal and must be rejected. We assert both layers:
  - The Python guard (`assert_can_transition`) raises.
  - The conditional UPDATE in services.* refuses to mutate the row.
"""

from __future__ import annotations

import pytest

from apps.ledger.models import LedgerEntry
from apps.payouts.exceptions import IllegalStateTransitionError
from apps.payouts.models import Payout
from apps.payouts.services import (
    claim_for_processing,
    settle_failure,
    settle_success,
)
from apps.payouts.state import (
    ALLOWED_TRANSITIONS,
    PayoutStatus,
    assert_can_transition,
    is_legal,
)


pytestmark = pytest.mark.django_db


def test_allowed_pairs_are_exactly_three():
    legal = {(f, t) for f, ts in ALLOWED_TRANSITIONS.items() for t in ts}
    assert legal == {
        (PayoutStatus.PENDING, PayoutStatus.PROCESSING),
        (PayoutStatus.PROCESSING, PayoutStatus.COMPLETED),
        (PayoutStatus.PROCESSING, PayoutStatus.FAILED),
    }


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        # Backwards transitions
        (PayoutStatus.COMPLETED, PayoutStatus.PENDING),
        (PayoutStatus.FAILED, PayoutStatus.COMPLETED),
        (PayoutStatus.COMPLETED, PayoutStatus.PROCESSING),
        (PayoutStatus.FAILED, PayoutStatus.PROCESSING),
        (PayoutStatus.PROCESSING, PayoutStatus.PENDING),
        # Skipping the queue
        (PayoutStatus.PENDING, PayoutStatus.COMPLETED),
        (PayoutStatus.PENDING, PayoutStatus.FAILED),
        # Self-loops
        (PayoutStatus.PENDING, PayoutStatus.PENDING),
        (PayoutStatus.COMPLETED, PayoutStatus.COMPLETED),
    ],
)
def test_illegal_transitions_rejected_by_guard(from_status, to_status):
    assert not is_legal(from_status, to_status)
    with pytest.raises(IllegalStateTransitionError):
        assert_can_transition(from_status, to_status)


def test_claim_for_processing_only_works_from_pending(merchant, bank_account):
    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=1_000,
        status=Payout.Status.PROCESSING,  # already past pending
    )
    assert claim_for_processing(p.id) is False  # row not in PENDING


def test_settle_success_writes_debit_atomically(merchant, bank_account):
    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=2_500,
        status=Payout.Status.PROCESSING,
    )
    assert settle_success(p.id) is True

    p.refresh_from_db()
    assert p.status == PayoutStatus.COMPLETED

    debit = LedgerEntry.objects.get(payout=p)
    assert debit.entry_type == LedgerEntry.EntryType.DEBIT
    assert debit.amount_paise == 2_500


def test_settle_success_refuses_when_row_not_in_processing(merchant, bank_account):
    """The conditional UPDATE (CAS) refuses to mutate a row whose status
    has already moved on. This is the layer that catches concurrent
    workers, not the Python guard."""

    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=500,
        status=Payout.Status.PENDING,  # not yet PROCESSING
    )
    # The Python guard for PROCESSING -> COMPLETED is fine; what should
    # refuse is the WHERE clause in services.settle_success.
    assert settle_success(p.id) is False
    p.refresh_from_db()
    assert p.status == PayoutStatus.PENDING
    assert not LedgerEntry.objects.filter(payout=p).exists()


def test_settle_failure_writes_no_ledger(merchant, bank_account):
    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=500,
        status=Payout.Status.PROCESSING,
    )
    assert settle_failure(p.id, reason="bank down") is True
    p.refresh_from_db()
    assert p.status == PayoutStatus.FAILED
    assert p.failure_reason == "bank down"
    assert not LedgerEntry.objects.filter(payout=p).exists()


def test_double_settle_only_first_wins(merchant, bank_account):
    """Two workers racing to settle the same payout: only one succeeds."""

    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=300,
        status=Payout.Status.PROCESSING,
    )
    assert settle_success(p.id) is True
    # Second attempt finds the row in COMPLETED, can't transition.
    assert settle_success(p.id) is False
    assert LedgerEntry.objects.filter(payout=p).count() == 1

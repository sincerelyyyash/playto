"""Stuck-payout watchdog tests.

Spec:
  - Payouts stuck in PROCESSING for >30s should be retried.
  - Exponential backoff, max 3 attempts, then move to FAILED.
  - On final FAILED, held funds return to the merchant balance.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.ledger.services import get_balance
from apps.payouts.models import Payout
from apps.payouts.tasks import retry_payout, scan_stuck_payouts


pytestmark = pytest.mark.django_db


def _make_stuck_payout(merchant, bank_account, *, attempt_count: int) -> Payout:
    p = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=4_000,
        status=Payout.Status.PROCESSING,
        attempt_count=attempt_count,
        processing_started_at=timezone.now() - timedelta(seconds=120),
    )
    return p


def test_stuck_payout_retries_with_exponential_backoff(merchant, bank_account, settings):
    settings.PAYOUT_RETRY_BASE_DELAY_SECONDS = 5
    p = _make_stuck_payout(merchant, bank_account, attempt_count=1)

    with mock.patch("apps.payouts.tasks.retry_payout.apply_async") as enqueue:
        summary = scan_stuck_payouts()

    assert summary == {"retried": 1, "failed": 0}
    enqueue.assert_called_once()
    args, kwargs = enqueue.call_args
    # Args is the positional tuple to apply_async: ((payout_id,),)
    assert args[0] == (str(p.id),)
    # 5 * 2^1 = 10s
    assert kwargs["countdown"] == 10


def test_stuck_payout_at_max_attempts_marked_failed(merchant, bank_account, settings):
    settings.PAYOUT_MAX_ATTEMPTS = 3
    p = _make_stuck_payout(merchant, bank_account, attempt_count=3)

    pre = get_balance(merchant.id)
    assert pre.held_paise == 4_000  # held while PROCESSING

    summary = scan_stuck_payouts()
    assert summary == {"retried": 0, "failed": 1}

    p.refresh_from_db()
    assert p.status == Payout.Status.FAILED
    assert "max retry attempts" in p.failure_reason

    post = get_balance(merchant.id)
    # No debit was written; held drops to zero, so the funds are "returned"
    # to available without changing the ledger total.
    assert post.total_paise == pre.total_paise
    assert post.held_paise == 0
    assert post.available_paise == pre.available_paise + 4_000


def test_only_old_processing_payouts_are_picked_up(merchant, bank_account, settings):
    """Fresh PROCESSING rows (< stuck threshold) are left alone."""

    settings.PAYOUT_STUCK_AFTER_SECONDS = 30
    Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=1_000,
        status=Payout.Status.PROCESSING,
        attempt_count=1,
        processing_started_at=timezone.now(),  # just started, not stuck
    )
    summary = scan_stuck_payouts()
    assert summary == {"retried": 0, "failed": 0}


def test_retry_payout_increments_attempt_count(merchant, bank_account, settings):
    """The retry task itself bumps attempt_count and re-runs settlement."""

    settings.PAYOUT_SUCCESS_RATE = 1.0
    settings.PAYOUT_FAILURE_RATE = 0.0
    settings.PAYOUT_HANG_RATE = 0.0

    p = _make_stuck_payout(merchant, bank_account, attempt_count=1)
    retry_payout(str(p.id))
    p.refresh_from_db()
    assert p.attempt_count == 2
    assert p.status == Payout.Status.COMPLETED

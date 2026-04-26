"""Celery tasks for payout processing and stuck-payout retries.

Two task families:

  - `process_payout(payout_id)` is the worker body. It claims the payout
    via a conditional UPDATE (PENDING -> PROCESSING), simulates the bank
    settlement, then either commits success (atomic state change + DEBIT
    ledger entry) or commits failure (state change only; held funds
    auto-release because they're no longer counted as held).

  - `scan_stuck_payouts()` runs every 10s on Beat. It finds payouts that
    have been PROCESSING for longer than `PAYOUT_STUCK_AFTER_SECONDS`
    and either retries them (with exponential backoff) or marks them
    FAILED if `attempt_count >= PAYOUT_MAX_ATTEMPTS`. Watchdog rows are
    locked with `skip_locked` so two beat ticks can't fight over the
    same row.

  - `cleanup_expired_idempotency_keys()` runs daily and prunes records
    whose 24h window has elapsed.

The Beat schedule is registered on the Celery app via the
`@app.on_after_configure.connect` signal at module import time.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payouts.exceptions import IllegalStateTransitionError
from apps.payouts.models import IdempotencyKey, Payout
from apps.payouts.services import (
    claim_for_processing,
    claim_for_retry,
    settle_failure,
    settle_success,
)
from apps.payouts.simulator import SettlementOutcome, simulate_settlement
from apps.payouts.state import PayoutStatus

log = logging.getLogger(__name__)


@shared_task(name="payouts.process_payout")
def process_payout(payout_id: str) -> str:
    """Worker body: claim, simulate, settle.

    Returns a short status string for log/observability:
      - "claimed_then_<outcome>"  - we successfully claimed the payout.
      - "not_claimable"           - someone else already moved it on.
    """

    if not claim_for_processing(payout_id):
        # Either already claimed by another worker, already settled, or
        # the row doesn't exist. Either way: nothing for us to do.
        log.info("process_payout.skip id=%s reason=not_claimable", payout_id)
        return "not_claimable"

    return _settle(payout_id)


@shared_task(name="payouts.retry_payout")
def retry_payout(payout_id: str) -> str:
    """Stuck-payout retry: bumps attempt and re-runs the simulation.

    The payout stays in PROCESSING throughout - we don't move it back to
    PENDING because the assignment forbids backwards transitions.
    """

    if not claim_for_retry(payout_id):
        log.info("retry_payout.skip id=%s reason=not_processing", payout_id)
        return "not_claimable"
    return _settle(payout_id)


def _settle(payout_id: str) -> str:
    """Run the simulation and apply the resulting state transition."""

    outcome = simulate_settlement()
    log.info("settle.run id=%s outcome=%s", payout_id, outcome.value)

    if outcome is SettlementOutcome.SUCCESS:
        try:
            settle_success(payout_id)
        except IllegalStateTransitionError:
            log.warning("settle_success.illegal id=%s", payout_id)
        return "claimed_then_success"

    if outcome is SettlementOutcome.FAILURE:
        try:
            settle_failure(payout_id, reason="bank declined (simulated)")
        except IllegalStateTransitionError:
            log.warning("settle_failure.illegal id=%s", payout_id)
        return "claimed_then_failure"

    # HANG: leave the row in PROCESSING with an old `processing_started_at`
    # so the stuck-payout watchdog will pick it up.
    return "claimed_then_hang"


@shared_task(name="payouts.scan_stuck_payouts")
def scan_stuck_payouts() -> dict:
    """Find payouts stuck in PROCESSING and either retry or fail them.

    Logic:
      - If `attempt_count >= PAYOUT_MAX_ATTEMPTS` -> transition to FAILED.
        Held funds are released by the status change.
      - Otherwise -> enqueue `retry_payout` with exponential backoff:
        delay = PAYOUT_RETRY_BASE_DELAY_SECONDS * 2^attempt_count.

    The query uses `select_for_update(skip_locked=True)` so concurrent
    beat ticks (or a worker mid-settlement) don't collide on the same row.
    """

    cutoff = timezone.now() - timedelta(seconds=settings.PAYOUT_STUCK_AFTER_SECONDS)
    summary = {"retried": 0, "failed": 0}

    with transaction.atomic():
        stuck = list(
            Payout.objects.select_for_update(skip_locked=True).filter(
                status=PayoutStatus.PROCESSING,
                processing_started_at__lt=cutoff,
            )
        )
        for p in stuck:
            if p.attempt_count >= settings.PAYOUT_MAX_ATTEMPTS:
                if settle_failure(
                    p.id, reason="max retry attempts reached"
                ):
                    summary["failed"] += 1
                continue

            delay = settings.PAYOUT_RETRY_BASE_DELAY_SECONDS * (2**p.attempt_count)
            retry_payout.apply_async((str(p.id),), countdown=delay)
            summary["retried"] += 1

    if summary["retried"] or summary["failed"]:
        log.info("scan_stuck_payouts %s", summary)
    return summary


@shared_task(name="payouts.cleanup_expired_idempotency_keys")
def cleanup_expired_idempotency_keys() -> int:
    """Drop idempotency records whose 24h dedup window has elapsed."""

    deleted, _ = IdempotencyKey.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()
    if deleted:
        log.info("idempotency.cleanup deleted=%s", deleted)
    return deleted


# Beat schedule lives in `settings.CELERY_BEAT_SCHEDULE`. Putting it there
# (vs. wiring it up via `@app.on_after_configure.connect` in this module)
# means the schedule is visible in one place, doesn't depend on subtle
# import-order semantics, and works correctly with django-celery-beat's
# DatabaseScheduler.

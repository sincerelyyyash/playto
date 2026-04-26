"""Payout services.

`create_payout` is the only path that reserves funds. The whole reservation
runs inside `transaction.atomic()` with a `SELECT ... FOR UPDATE` on the
merchant row, so two simultaneous requests serialise at the database. The
balance check itself is two SQL aggregates (no Python arithmetic on fetched
rows). Insufficient funds raise a typed exception that maps to 422.

`settle_success` and `settle_failure` are used by the worker (Phase 3) and
are kept here so the state-machine transitions live in one module. Each
performs a conditional UPDATE (CAS) so concurrent settlement attempts
cannot corrupt state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.ledger.models import LedgerEntry
from apps.ledger.services import get_balance
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.exceptions import (
    DomainError,
    InsufficientBalanceError,
)
from apps.payouts.models import Payout
from apps.payouts.state import PayoutStatus, assert_can_transition

log = logging.getLogger(__name__)


class BankAccountInvalidError(DomainError):
    error_code = "bank_account_invalid"


class InvalidAmountError(DomainError):
    error_code = "invalid_amount"


@dataclass
class CreatePayoutInput:
    merchant: Merchant
    amount_paise: int
    bank_account_id: str


def create_payout(payload: CreatePayoutInput) -> Payout:
    """Atomically reserve funds and create a PENDING payout.

    Steps inside one transaction:
      1. lock the merchant row (SELECT ... FOR UPDATE)
      2. resolve and validate the bank account
      3. compute total + held at the DB; reject if available < amount
      4. INSERT the payout row in PENDING state
    """

    if not isinstance(payload.amount_paise, int) or payload.amount_paise <= 0:
        raise InvalidAmountError("amount_paise must be a positive integer")

    with transaction.atomic():
        # (1) Pessimistic lock on the merchant. Two concurrent payout
        # requests for the same merchant serialise here.
        merchant = Merchant.objects.select_for_update().get(pk=payload.merchant.pk)

        # (2) Bank account belongs to merchant and is active.
        try:
            bank_account = BankAccount.objects.get(
                pk=payload.bank_account_id,
                merchant_id=merchant.pk,
                is_active=True,
            )
        except BankAccount.DoesNotExist as exc:
            raise BankAccountInvalidError(
                "bank_account not found or not active"
            ) from exc

        # (3) DB-level balance check. No Python arithmetic over rows.
        balance = get_balance(merchant.pk)
        if balance.available_paise < payload.amount_paise:
            raise InsufficientBalanceError(
                f"available={balance.available_paise} requested={payload.amount_paise}"
            )

        # (4) Create the payout. Status defaults to PENDING. From this point
        # the funds are "held" because the balance service counts
        # PENDING/PROCESSING amounts as held.
        payout = Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=payload.amount_paise,
        )
        log.info(
            "payout.created id=%s merchant=%s amount=%s",
            payout.id,
            merchant.id,
            payout.amount_paise,
        )
        return payout


def claim_for_processing(payout_id) -> bool:
    """Atomically transition PENDING -> PROCESSING. Returns True if claimed.

    Uses a conditional UPDATE so two workers competing for the same row
    can't both win; whichever issues UPDATE first turns the WHERE clause
    false for the other.
    """

    from django.db.models import F

    assert_can_transition(PayoutStatus.PENDING, PayoutStatus.PROCESSING)
    rows = Payout.objects.filter(
        pk=payout_id, status=PayoutStatus.PENDING
    ).update(
        status=PayoutStatus.PROCESSING,
        attempt_count=F("attempt_count") + 1,
        processing_started_at=timezone.now(),
        last_attempt_at=timezone.now(),
    )
    return rows == 1


def claim_for_retry(payout_id) -> bool:
    """Bump attempt_count for an already-PROCESSING payout (stuck retry).

    Stays in PROCESSING (going back to PENDING would be an illegal backwards
    transition per the assignment spec).
    """

    from django.db.models import F

    rows = Payout.objects.filter(
        pk=payout_id, status=PayoutStatus.PROCESSING
    ).update(
        attempt_count=F("attempt_count") + 1,
        last_attempt_at=timezone.now(),
        processing_started_at=timezone.now(),
    )
    return rows == 1


def settle_success(payout_id) -> bool:
    """Atomically: PROCESSING -> COMPLETED + write DEBIT ledger entry.

    Both effects happen in a single `transaction.atomic()` so the ledger
    invariant (SUM(credits) - SUM(debits) == settled balance) is never
    transiently violated.
    """

    assert_can_transition(PayoutStatus.PROCESSING, PayoutStatus.COMPLETED)
    with transaction.atomic():
        payout = (
            Payout.objects.select_for_update()
            .filter(pk=payout_id, status=PayoutStatus.PROCESSING)
            .first()
        )
        if payout is None:
            return False

        rows = Payout.objects.filter(
            pk=payout_id, status=PayoutStatus.PROCESSING
        ).update(status=PayoutStatus.COMPLETED)
        if rows != 1:  # pragma: no cover - guarded by select_for_update
            return False

        LedgerEntry.objects.create(
            merchant_id=payout.merchant_id,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount_paise=payout.amount_paise,
            description=f"Payout {payout.id}",
            payout_id=payout.id,
        )
        log.info("payout.completed id=%s amount=%s", payout.id, payout.amount_paise)
        return True


def settle_failure(payout_id, *, reason: str) -> bool:
    """Atomically: PROCESSING -> FAILED. No ledger entry written.

    Held funds are released purely by the status change: `held_paise` is
    `SUM(amount_paise)` over PENDING/PROCESSING payouts, so the moment we
    move to FAILED the amount stops being held.
    """

    assert_can_transition(PayoutStatus.PROCESSING, PayoutStatus.FAILED)
    with transaction.atomic():
        rows = Payout.objects.filter(
            pk=payout_id, status=PayoutStatus.PROCESSING
        ).update(
            status=PayoutStatus.FAILED,
            failure_reason=reason or "",
        )
        if rows == 1:
            log.info("payout.failed id=%s reason=%s", payout_id, reason)
            return True
        return False

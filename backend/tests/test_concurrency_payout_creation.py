"""The headline concurrency test.

Spec: a merchant with 100 INR (10,000 paise) submits two simultaneous
60 INR (6,000 paise) payout requests. Exactly one must succeed; the other
must be rejected cleanly.

We use real threads + Postgres `SELECT ... FOR UPDATE`. The
`transactional_db` fixture gives each test a real database transaction
boundary instead of pytest-django's default savepoint, so locks behave
the way they would in production.
"""

from __future__ import annotations

import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections

from apps.ledger.models import LedgerEntry
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.exceptions import InsufficientBalanceError
from apps.payouts.models import Payout
from apps.payouts.services import CreatePayoutInput, create_payout


User = get_user_model()


def _setup_merchant(opening_credit_paise: int) -> tuple[Merchant, BankAccount]:
    user = User.objects.create_user(
        username=f"u_{opening_credit_paise}", password="pw"
    )
    m = Merchant.objects.create(
        user=user, name="Race Co", email=f"u_{opening_credit_paise}@example.com"
    )
    ba = BankAccount.objects.create(
        merchant=m,
        account_holder_name=m.name,
        account_number_last4="0000",
        ifsc_code="HDFC0000000",
    )
    LedgerEntry.objects.create(
        merchant=m,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount_paise=opening_credit_paise,
        description="Opening credit",
    )
    return m, ba


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_payouts_only_one_succeeds():
    merchant, bank_account = _setup_merchant(10_000)

    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def attempt(i: int):
        # Each thread gets its own DB connection.
        try:
            barrier.wait(timeout=5)
            payout = create_payout(
                CreatePayoutInput(
                    merchant=merchant,
                    amount_paise=6_000,
                    bank_account_id=str(bank_account.id),
                )
            )
            results[i] = ("ok", payout)
        except InsufficientBalanceError as exc:
            results[i] = ("err", str(exc))
        finally:
            close_old_connections()

    t1 = threading.Thread(target=attempt, args=(0,))
    t2 = threading.Thread(target=attempt, args=(1,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    outcomes = sorted(r[0] for r in results)
    assert outcomes == ["err", "ok"], (
        f"expected exactly one ok and one err, got {results!r}"
    )

    payouts = list(Payout.objects.filter(merchant=merchant))
    assert len(payouts) == 1
    assert payouts[0].amount_paise == 6_000


@pytest.mark.django_db(transaction=True)
def test_three_simultaneous_payouts_only_those_that_fit_succeed():
    """100p balance, three 40p requests: two succeed, one rejected."""

    merchant, bank_account = _setup_merchant(100)

    barrier = threading.Barrier(3)
    results: list[object] = [None, None, None]

    def attempt(i: int):
        try:
            barrier.wait(timeout=5)
            create_payout(
                CreatePayoutInput(
                    merchant=merchant,
                    amount_paise=40,
                    bank_account_id=str(bank_account.id),
                )
            )
            results[i] = "ok"
        except InsufficientBalanceError:
            results[i] = "err"
        finally:
            close_old_connections()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    oks = sum(1 for r in results if r == "ok")
    errs = sum(1 for r in results if r == "err")
    assert oks == 2 and errs == 1, (
        f"expected 2 ok / 1 err, got {results!r}"
    )
    # Held = 80, available = 20, so the third 40p couldn't fit.
    assert (
        Payout.objects.filter(merchant=merchant).count() == 2
    )

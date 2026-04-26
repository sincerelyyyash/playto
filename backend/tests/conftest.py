"""Test fixtures.

These tests run against the real Postgres database (started via
docker-compose). pytest-django wraps most tests in a transaction it rolls
back, but several of our tests hit concurrency / `transaction.on_commit`
behaviour that requires real commits. Those tests use the
`transactional_db` fixture explicitly.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.ledger.models import LedgerEntry
from apps.merchants.models import BankAccount, Merchant


User = get_user_model()


def _make_merchant(*, username: str, opening_credit_paise: int = 0) -> Merchant:
    user = User.objects.create_user(username=username, password=username)
    merchant = Merchant.objects.create(
        user=user,
        name=f"{username.title()} Co",
        email=f"{username}@example.com",
    )
    BankAccount.objects.create(
        merchant=merchant,
        account_holder_name=merchant.name,
        account_number_last4="0001",
        ifsc_code="HDFC0000001",
    )
    if opening_credit_paise:
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=opening_credit_paise,
            description="Opening credit",
        )
    return merchant


@pytest.fixture
def merchant_factory(db):
    used = {"i": 0}

    def _factory(opening_credit_paise: int = 0) -> Merchant:
        used["i"] += 1
        username = f"m{used['i']}_{uuid.uuid4().hex[:6]}"
        return _make_merchant(
            username=username, opening_credit_paise=opening_credit_paise
        )

    return _factory


@pytest.fixture
def merchant(merchant_factory):
    """A merchant with 100 INR (10000 paise) opening credit."""
    return merchant_factory(opening_credit_paise=10_000)


@pytest.fixture
def bank_account(merchant):
    return merchant.bank_accounts.first()


@pytest.fixture
def api_client(merchant):
    """Authenticated DRF test client for the default merchant."""
    token, _ = Token.objects.get_or_create(user=merchant.user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.fixture
def fresh_uuid():
    return lambda: uuid.uuid4()

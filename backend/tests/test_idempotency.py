"""Idempotency contract:

  1. Same key + same body -> exact same response, no duplicate payout.
  2. Same key + different body -> still returns the cached response (the
     spec says "second call returns the exact same response", and we take
     that literally; body fingerprint is logged for audit only).
  3. Different key + same body -> two distinct payouts.
  4. Missing or malformed Idempotency-Key header -> 400.
  5. Keys are scoped per merchant.
  6. Expired keys (> 24h) treated as fresh; new payout permitted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.payouts.models import IdempotencyKey, Payout


pytestmark = pytest.mark.django_db


def _post_payout(client, *, key, amount, bank_account_id):
    return client.post(
        "/api/v1/payouts/",
        data={"amount_paise": amount, "bank_account_id": str(bank_account_id)},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )


def test_same_key_same_body_returns_cached_response(api_client, bank_account):
    key = uuid.uuid4()
    r1 = _post_payout(api_client, key=key, amount=2_000, bank_account_id=bank_account.id)
    assert r1.status_code == 201, r1.content
    r2 = _post_payout(api_client, key=key, amount=2_000, bank_account_id=bank_account.id)
    assert r2.status_code == 201
    assert r1.json() == r2.json()
    assert Payout.objects.count() == 1


def test_same_key_different_body_returns_cached_response(api_client, bank_account):
    """Strict spec semantics: replay returns the first response verbatim,
    even if the body is different. The fingerprint is stored for audit
    but does not gate the replay path."""

    key = uuid.uuid4()
    r1 = _post_payout(api_client, key=key, amount=1_000, bank_account_id=bank_account.id)
    assert r1.status_code == 201, r1.content
    r2 = _post_payout(api_client, key=key, amount=2_000, bank_account_id=bank_account.id)
    assert r2.status_code == r1.status_code
    assert r2.json() == r1.json()
    assert Payout.objects.count() == 1


def test_different_keys_create_distinct_payouts(api_client, bank_account):
    r1 = _post_payout(api_client, key=uuid.uuid4(), amount=1_000, bank_account_id=bank_account.id)
    r2 = _post_payout(api_client, key=uuid.uuid4(), amount=1_000, bank_account_id=bank_account.id)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
    assert Payout.objects.count() == 2


def test_missing_header_returns_400(api_client, bank_account):
    resp = api_client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 1_000, "bank_account_id": str(bank_account.id)},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "idempotency_key_required"


def test_malformed_key_returns_400(api_client, bank_account):
    resp = _post_payout(
        api_client, key="not-a-uuid", amount=1_000, bank_account_id=bank_account.id
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "idempotency_key_required"


def test_keys_are_scoped_per_merchant(merchant_factory, bank_account):
    """Two merchants reusing the same UUID key get independent payouts."""

    other = merchant_factory(opening_credit_paise=10_000)
    other_token, _ = Token.objects.get_or_create(user=other.user)
    other_client = APIClient()
    other_client.credentials(HTTP_AUTHORIZATION=f"Token {other_token.key}")

    key = uuid.uuid4()

    # Merchant 1 (the default fixture) goes first.
    from apps.merchants.models import Merchant
    m1 = bank_account.merchant
    m1_token, _ = Token.objects.get_or_create(user=m1.user)
    m1_client = APIClient()
    m1_client.credentials(HTTP_AUTHORIZATION=f"Token {m1_token.key}")

    r1 = _post_payout(m1_client, key=key, amount=1_000, bank_account_id=bank_account.id)
    assert r1.status_code == 201

    # Merchant 2 reuses the same key but with their own bank account.
    other_ba = other.bank_accounts.first()
    r2 = _post_payout(other_client, key=key, amount=2_000, bank_account_id=other_ba.id)
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


def test_expired_key_allows_new_payout(api_client, bank_account, settings):
    key = uuid.uuid4()
    r1 = _post_payout(api_client, key=key, amount=1_000, bank_account_id=bank_account.id)
    assert r1.status_code == 201

    # Manually age the record past TTL.
    record = IdempotencyKey.objects.get(key=key)
    record.expires_at = timezone.now() - timedelta(hours=1)
    record.save(update_fields=["expires_at"])

    r2 = _post_payout(api_client, key=key, amount=1_000, bank_account_id=bank_account.id)
    assert r2.status_code == 201
    # Old payout is still around as historical data, plus a new one.
    assert Payout.objects.count() == 2

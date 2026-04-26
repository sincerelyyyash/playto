"""End-to-end API tests for the payouts endpoint."""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from apps.payouts.models import Payout


pytestmark = pytest.mark.django_db


def _post(client, *, key, body):
    return client.post(
        "/api/v1/payouts/", data=body, format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )


def test_create_payout_happy_path(api_client, bank_account):
    with mock.patch("apps.payouts.views._enqueue_processing") as enq:
        resp = _post(
            api_client,
            key=uuid.uuid4(),
            body={"amount_paise": 5_000, "bank_account_id": str(bank_account.id)},
        )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["status"] == "pending"
    assert body["amount_paise"] == 5_000
    assert Payout.objects.filter(id=body["id"]).exists()
    enq.assert_called_once()


def test_insufficient_balance_returns_422(api_client, bank_account):
    resp = _post(
        api_client,
        key=uuid.uuid4(),
        body={"amount_paise": 999_999, "bank_account_id": str(bank_account.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "insufficient_balance"
    assert Payout.objects.count() == 0


def test_balance_endpoint_reflects_pending_hold(api_client, bank_account):
    with mock.patch("apps.payouts.views._enqueue_processing"):
        _post(
            api_client,
            key=uuid.uuid4(),
            body={"amount_paise": 3_000, "bank_account_id": str(bank_account.id)},
        )
    resp = api_client.get("/api/v1/me/balance/")
    body = resp.json()
    assert body["total_paise"] == 10_000
    assert body["held_paise"] == 3_000
    assert body["available_paise"] == 7_000


def test_payout_detail_endpoint(api_client, bank_account):
    with mock.patch("apps.payouts.views._enqueue_processing"):
        create = _post(
            api_client,
            key=uuid.uuid4(),
            body={"amount_paise": 1_000, "bank_account_id": str(bank_account.id)},
        )
    pid = create.json()["id"]
    resp = api_client.get(f"/api/v1/payouts/{pid}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


def test_unauthenticated_request_rejected(bank_account):
    from rest_framework.test import APIClient
    client = APIClient()
    resp = client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 1_000, "bank_account_id": str(bank_account.id)},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp.status_code == 401

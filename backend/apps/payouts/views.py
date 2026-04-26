"""Payout API views.

`PayoutCreateListView` is the interesting one. POST runs the full payout
creation under one `transaction.atomic()`:

  1. Resolve the idempotency key (header). On replay we return the cached
     response untouched - same status, same body.
  2. Validate the request body and call `services.create_payout`, which
     locks the merchant row, runs the DB-level balance check, and inserts
     the PENDING payout.
  3. Persist the response on the idempotency record so any future retry
     is a pure read.
  4. After the transaction commits, enqueue the worker task. We use
     `transaction.on_commit` so we never enqueue a task pointing at a
     row that doesn't exist (rolled-back rows look real to in-flight
     code).
"""

from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.merchants.permissions import merchant_for_request
from apps.payouts import idempotency
from apps.payouts.models import Payout
from apps.payouts.serializers import (
    CreatePayoutRequestSerializer,
    PayoutSerializer,
)
from apps.payouts.services import CreatePayoutInput, create_payout

log = logging.getLogger(__name__)


class PayoutCreateListView(APIView):
    """POST /api/v1/payouts/  + GET /api/v1/payouts/"""

    def get(self, request):
        merchant = merchant_for_request(request)
        qs = Payout.objects.filter(merchant_id=merchant.id).order_by("-created_at")
        page_size = min(int(request.query_params.get("limit", 25)), 100)
        offset = int(request.query_params.get("offset", 0))
        items = list(qs[offset : offset + page_size])
        return Response(
            {
                "count": qs.count(),
                "results": PayoutSerializer(items, many=True).data,
            }
        )

    def post(self, request):
        merchant = merchant_for_request(request)
        key = idempotency.parse_key(request.headers.get(idempotency.HEADER_NAME))

        with transaction.atomic():
            resolution = idempotency.begin(merchant, key, request.data)
            if resolution.cached is not None:
                return Response(
                    resolution.cached.body, status=resolution.cached.status
                )

            serializer = CreatePayoutRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            payout = create_payout(
                CreatePayoutInput(
                    merchant=merchant,
                    amount_paise=serializer.validated_data["amount_paise"],
                    bank_account_id=str(
                        serializer.validated_data["bank_account_id"]
                    ),
                )
            )

            body = PayoutSerializer(payout).data
            idempotency.persist_response(
                resolution.record,
                status=status.HTTP_201_CREATED,
                body=body,
                payout_id=payout.id,
            )

            transaction.on_commit(lambda: _enqueue_processing(payout.id))

            return Response(body, status=status.HTTP_201_CREATED)


class PayoutDetailView(generics.RetrieveAPIView):
    """GET /api/v1/payouts/{id}/  - frontend polls this for live status."""

    serializer_class = PayoutSerializer
    lookup_field = "pk"

    def get_queryset(self):
        merchant = merchant_for_request(self.request)
        return Payout.objects.filter(merchant_id=merchant.id)


def _enqueue_processing(payout_id) -> None:
    """Enqueue the Celery worker task. Imported lazily so importing this
    module never triggers a Celery / Redis connection (e.g. during tests
    that don't need the broker)."""

    from apps.payouts.tasks import process_payout

    process_payout.delay(str(payout_id))

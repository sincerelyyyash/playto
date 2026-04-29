"""Payout + IdempotencyKey models.

`Payout` is the core unit of work the processor moves through a state
machine. While in PENDING or PROCESSING it represents *held* funds that
the merchant cannot spend. A DEBIT ledger entry is written if and only if
the payout reaches COMPLETED, so the ledger invariant
`SUM(credits) - SUM(debits) == settled balance` holds at every instant.

`IdempotencyKey` lets a merchant safely retry a flaky network call:
the same key + same body returns the cached response; the same key with
a different body is rejected so we never silently alias different
intents to the same payout.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.merchants.models import BankAccount, Merchant
from apps.payouts.state import PayoutStatus


class Payout(models.Model):
    class Status(models.TextChoices):
        PENDING = PayoutStatus.PENDING, "Pending"
        PROCESSING = PayoutStatus.PROCESSING, "Processing"
        COMPLETED = PayoutStatus.COMPLETED, "Completed"
        FAILED = PayoutStatus.FAILED, "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    attempt_count = models.PositiveSmallIntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payouts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
            models.Index(fields=["status", "processing_started_at"]),
            models.Index(fields=["merchant", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_paise__gt=0),
                name="payout_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Payout({self.id}, {self.status}, {self.amount_paise}p)"


class IdempotencyKey(models.Model):
    """Merchant-scoped, 24-hour TTL idempotency record.

    `request_fingerprint` is sha256 of the canonical request body (audit).
    Replays with the same key return the cached response regardless of body.
    `response_status` / `response_body` are set when the handler finishes.
    """

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    payout = models.ForeignKey(
        Payout,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idempotency_keys",
    )
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "idempotency_keys"
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "key"],
                name="idempotency_unique_merchant_key",
            ),
        ]
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def is_expired(self, now=None) -> bool:
        return (now or timezone.now()) >= self.expires_at

    def has_response(self) -> bool:
        return self.response_status is not None and self.response_body is not None

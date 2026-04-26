"""Merchant + BankAccount models.

`Merchant` is the actor that owns a balance and submits payouts. We link to
`auth.User` one-to-one so we can leverage DRF's `TokenAuthentication` without
inventing our own auth scheme.
"""

import uuid

from django.conf import settings
from django.db import models


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merchant",
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "merchants"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class BankAccount(models.Model):
    """Indian bank account a merchant withdraws to.

    We store the masked account number (last 4) only; the assignment doesn't
    require us to actually move money, and storing PII would be a liability.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name="bank_accounts",
    )
    account_holder_name = models.CharField(max_length=255)
    account_number_last4 = models.CharField(max_length=4)
    ifsc_code = models.CharField(max_length=11)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bank_accounts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.account_holder_name} ****{self.account_number_last4}"

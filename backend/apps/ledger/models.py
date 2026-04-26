"""Ledger model.

The ledger is the source of truth for merchant balances. Every credit
(simulated customer payment) and every debit (completed payout) is a row
here. Rows are immutable once written. The merchant's settled balance is
always derived from `SUM(credits) - SUM(debits)` at the database, never
from cached numbers in Python.
"""

from django.db import models

from apps.merchants.models import Merchant


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    amount_paise = models.BigIntegerField()
    description = models.CharField(max_length=255, blank=True)
    external_ref = models.CharField(max_length=128, blank=True, default="")

    payout = models.ForeignKey(
        "payouts.Payout",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_entries"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
            models.Index(fields=["merchant", "entry_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_paise__gt=0),
                name="ledger_amount_positive",
            ),
            # A debit must be tied to a payout; a credit must not be.
            models.CheckConstraint(
                check=(
                    models.Q(entry_type="credit", payout__isnull=True)
                    | models.Q(entry_type="debit", payout__isnull=False)
                ),
                name="ledger_debit_requires_payout",
            ),
        ]

    def __str__(self) -> str:
        sign = "+" if self.entry_type == self.EntryType.CREDIT else "-"
        return f"{sign}{self.amount_paise}p {self.merchant_id}"

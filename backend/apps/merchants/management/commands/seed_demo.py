"""Seed 3 demo merchants with bank accounts, credit history, and API tokens.

Idempotent: safe to run multiple times. Existing merchants are reused; new
credit entries are only added if the merchant has no ledger history yet.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework.authtoken.models import Token

from apps.ledger.models import LedgerEntry
from apps.merchants.models import BankAccount, Merchant

User = get_user_model()


# Each tuple: (username, name, email, [credits in paise], [bank_account_specs])
DEMO_DATA = [
    (
        "alice",
        "Alice Studio",
        "alice@example.com",
        # 5 customer payments totalling 1,50,000 paise = 1500 INR
        [50_000, 25_000, 30_000, 20_000, 25_000],
        [("Alice Studio LLP", "1234", "HDFC0001234")],
    ),
    (
        "bob",
        "Bob Freelance",
        "bob@example.com",
        # 4 payments totalling 80,000 paise = 800 INR
        [10_000, 20_000, 25_000, 25_000],
        [("Bob Freelance", "5678", "ICIC0005678")],
    ),
    (
        "carol",
        "Carol Agency",
        "carol@example.com",
        # 6 payments totalling 3,75,000 paise = 3750 INR
        [50_000, 75_000, 50_000, 100_000, 50_000, 50_000],
        [
            ("Carol Agency Pvt Ltd", "9012", "AXIS0009012"),
            ("Carol Agency Pvt Ltd", "3456", "SBIN0003456"),
        ],
    ),
]


class Command(BaseCommand):
    help = "Seed demo merchants, bank accounts, ledger credits, and API tokens."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding demo data..."))

        rows = []
        for username, name, email, credits, banks in DEMO_DATA:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": email},
            )
            user.set_password(username)
            user.save()

            merchant, _ = Merchant.objects.get_or_create(
                user=user,
                defaults={"name": name, "email": email},
            )
            for holder, last4, ifsc in banks:
                BankAccount.objects.get_or_create(
                    merchant=merchant,
                    account_number_last4=last4,
                    defaults={
                        "account_holder_name": holder,
                        "ifsc_code": ifsc,
                        "is_active": True,
                    },
                )

            if not LedgerEntry.objects.filter(merchant=merchant).exists():
                for i, amount in enumerate(credits, start=1):
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        entry_type=LedgerEntry.EntryType.CREDIT,
                        amount_paise=amount,
                        description=f"Customer payment #{i}",
                        external_ref=f"seed_{username}_{i}",
                    )

            token, _ = Token.objects.get_or_create(user=user)
            rows.append((merchant.name, merchant.email, token.key, sum(credits)))

        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Merchant tokens:"))
        for name, email, token, total in rows:
            self.stdout.write(
                f"  {name:<20} {email:<25} total={total:>8}p   token={token}"
            )
        self.stdout.write("")
        self.stdout.write(
            "Use as:  Authorization: Token <token>"
        )

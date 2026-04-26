import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("merchants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payout",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("amount_paise", models.BigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("processing_started_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "merchant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payouts",
                        to="merchants.merchant",
                    ),
                ),
                (
                    "bank_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payouts",
                        to="merchants.bankaccount",
                    ),
                ),
            ],
            options={
                "db_table": "payouts",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(
                fields=["merchant", "-created_at"], name="payouts_merchan_b1234a_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(
                fields=["status", "processing_started_at"],
                name="payouts_status_b9c1d2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(
                fields=["merchant", "status"], name="payouts_merchan_3d4e5f_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="payout",
            constraint=models.CheckConstraint(
                check=models.Q(("amount_paise__gt", 0)),
                name="payout_amount_positive",
            ),
        ),
        migrations.CreateModel(
            name="IdempotencyKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.UUIDField()),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("response_status", models.IntegerField(blank=True, null=True)),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "merchant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="idempotency_keys",
                        to="merchants.merchant",
                    ),
                ),
                (
                    "payout",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="idempotency_keys",
                        to="payouts.payout",
                    ),
                ),
            ],
            options={
                "db_table": "idempotency_keys",
            },
        ),
        migrations.AddIndex(
            model_name="idempotencykey",
            index=models.Index(
                fields=["expires_at"], name="idempotenc_expires_a1b2c3_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="idempotencykey",
            constraint=models.UniqueConstraint(
                fields=("merchant", "key"),
                name="idempotency_unique_merchant_key",
            ),
        ),
    ]

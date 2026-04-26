import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("merchants", "0001_initial"),
        ("payouts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LedgerEntry",
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
                (
                    "entry_type",
                    models.CharField(
                        choices=[("credit", "Credit"), ("debit", "Debit")],
                        max_length=10,
                    ),
                ),
                ("amount_paise", models.BigIntegerField()),
                ("description", models.CharField(blank=True, max_length=255)),
                ("external_ref", models.CharField(blank=True, default="", max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "merchant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ledger_entries",
                        to="merchants.merchant",
                    ),
                ),
                (
                    "payout",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ledger_entries",
                        to="payouts.payout",
                    ),
                ),
            ],
            options={
                "db_table": "ledger_entries",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(
                fields=["merchant", "-created_at"],
                name="ledger_entr_merchan_a1b2c3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(
                fields=["merchant", "entry_type"],
                name="ledger_entr_merchan_d4e5f6_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="ledgerentry",
            constraint=models.CheckConstraint(
                check=models.Q(("amount_paise__gt", 0)),
                name="ledger_amount_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="ledgerentry",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(entry_type="credit", payout__isnull=True)
                    | models.Q(entry_type="debit", payout__isnull=False)
                ),
                name="ledger_debit_requires_payout",
            ),
        ),
    ]

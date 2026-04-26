from django.contrib import admin

from apps.ledger.models import LedgerEntry


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "entry_type", "amount_paise", "description", "payout", "created_at")
    list_filter = ("entry_type",)
    search_fields = ("description", "external_ref")
    readonly_fields = ("created_at",)

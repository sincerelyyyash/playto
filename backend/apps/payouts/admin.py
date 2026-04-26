from django.contrib import admin

from apps.payouts.models import IdempotencyKey, Payout


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "merchant",
        "amount_paise",
        "status",
        "attempt_count",
        "processing_started_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("id", "merchant__name", "merchant__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ("merchant", "key", "payout", "response_status", "expires_at")
    search_fields = ("key", "merchant__email")
    readonly_fields = ("created_at",)

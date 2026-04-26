from django.contrib import admin

from apps.merchants.models import BankAccount, Merchant


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "user", "created_at")
    search_fields = ("name", "email")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("account_holder_name", "account_number_last4", "ifsc_code", "merchant", "is_active")
    list_filter = ("is_active",)
    search_fields = ("account_holder_name", "ifsc_code")

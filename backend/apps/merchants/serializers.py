from rest_framework import serializers

from apps.merchants.models import BankAccount, Merchant


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "created_at"]
        read_only_fields = fields


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = [
            "id",
            "account_holder_name",
            "account_number_last4",
            "ifsc_code",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class BalanceSerializer(serializers.Serializer):
    total_paise = serializers.IntegerField()
    held_paise = serializers.IntegerField()
    available_paise = serializers.IntegerField()


class LedgerEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    entry_type = serializers.CharField()
    amount_paise = serializers.IntegerField()
    description = serializers.CharField()
    payout_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()

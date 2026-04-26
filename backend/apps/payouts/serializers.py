from rest_framework import serializers

from apps.payouts.models import Payout


class PayoutSerializer(serializers.ModelSerializer):
    bank_account_id = serializers.UUIDField(source="bank_account.id", read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "amount_paise",
            "status",
            "bank_account_id",
            "attempt_count",
            "failure_reason",
            "processing_started_at",
            "last_attempt_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreatePayoutRequestSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.UUIDField()

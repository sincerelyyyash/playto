from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ledger.models import LedgerEntry
from apps.ledger.services import get_balance
from apps.merchants.models import BankAccount
from apps.merchants.permissions import merchant_for_request
from apps.merchants.serializers import (
    BalanceSerializer,
    BankAccountSerializer,
    LedgerEntrySerializer,
    MerchantSerializer,
)


class MeView(APIView):
    """GET /api/v1/me/ - returns the authenticated merchant."""

    def get(self, request):
        merchant = merchant_for_request(request)
        return Response(MerchantSerializer(merchant).data)


class BalanceView(APIView):
    """GET /api/v1/me/balance/ - balance broken down into total/held/available."""

    def get(self, request):
        merchant = merchant_for_request(request)
        balance = get_balance(merchant.id)
        return Response(BalanceSerializer(balance.as_dict()).data)


class LedgerListView(generics.ListAPIView):
    """GET /api/v1/me/ledger/ - paginated recent credits and debits."""

    serializer_class = LedgerEntrySerializer

    def get_queryset(self):
        merchant = merchant_for_request(self.request)
        qs = (
            LedgerEntry.objects.filter(merchant_id=merchant.id)
            .order_by("-created_at", "-id")
            .values(
                "id",
                "entry_type",
                "amount_paise",
                "description",
                "payout_id",
                "created_at",
            )
        )
        return qs


class BankAccountListView(generics.ListAPIView):
    """GET /api/v1/bank-accounts/ - the merchant's active bank accounts."""

    serializer_class = BankAccountSerializer

    def get_queryset(self):
        merchant = merchant_for_request(self.request)
        return BankAccount.objects.filter(merchant_id=merchant.id, is_active=True)

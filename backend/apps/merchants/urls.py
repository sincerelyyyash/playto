from django.urls import path

from apps.merchants.views import (
    BalanceView,
    BankAccountListView,
    LedgerListView,
    MeView,
)

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/balance/", BalanceView.as_view(), name="me-balance"),
    path("me/ledger/", LedgerListView.as_view(), name="me-ledger"),
    path("bank-accounts/", BankAccountListView.as_view(), name="bank-accounts"),
]

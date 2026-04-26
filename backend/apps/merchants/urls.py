from django.urls import path

from apps.merchants.views import (
    BalanceView,
    BankAccountListView,
    LedgerListView,
    MeView,
)

# See apps/payouts/urls.py for why every route has a no-slash twin.
urlpatterns = [
    path("me", MeView.as_view()),
    path("me/", MeView.as_view(), name="me"),
    path("me/balance", BalanceView.as_view()),
    path("me/balance/", BalanceView.as_view(), name="me-balance"),
    path("me/ledger", LedgerListView.as_view()),
    path("me/ledger/", LedgerListView.as_view(), name="me-ledger"),
    path("bank-accounts", BankAccountListView.as_view()),
    path("bank-accounts/", BankAccountListView.as_view(), name="bank-accounts"),
]

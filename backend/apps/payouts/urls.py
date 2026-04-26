from django.urls import path

from apps.payouts.views import PayoutCreateListView, PayoutDetailView

# Each route is registered both with and without a trailing slash so the
# spec's `/api/v1/payouts` works as written and the conventional Django
# `/api/v1/payouts/` keeps working too. Only the slash form holds the
# named route to avoid reverse-resolution ambiguity.
urlpatterns = [
    path("payouts", PayoutCreateListView.as_view()),
    path("payouts/", PayoutCreateListView.as_view(), name="payouts"),
    path("payouts/<uuid:pk>", PayoutDetailView.as_view()),
    path("payouts/<uuid:pk>/", PayoutDetailView.as_view(), name="payout-detail"),
]

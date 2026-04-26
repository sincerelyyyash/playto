from django.urls import path

from apps.payouts.views import PayoutCreateListView, PayoutDetailView

urlpatterns = [
    path("payouts/", PayoutCreateListView.as_view(), name="payouts"),
    path("payouts/<uuid:pk>/", PayoutDetailView.as_view(), name="payout-detail"),
]

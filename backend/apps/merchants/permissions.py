"""Helpers to look up the `Merchant` for the authenticated user."""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from apps.merchants.models import Merchant


def merchant_for_request(request) -> Merchant:
    """Return the Merchant linked to the authenticated user, or raise 403."""

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise PermissionDenied("authentication required")
    try:
        return user.merchant
    except Merchant.DoesNotExist as exc:  # pragma: no cover - defensive
        raise PermissionDenied("user is not a merchant") from exc

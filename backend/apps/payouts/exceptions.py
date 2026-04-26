"""Custom exceptions and DRF exception handler for the payouts app.

The handler is wired up in `REST_FRAMEWORK['EXCEPTION_HANDLER']` and converts
domain errors into clean HTTP responses without leaking stack traces.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


class DomainError(Exception):
    """Base for domain-level errors that should map to 4xx responses."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "bad_request"

    def __init__(self, message: str = "", *, error_code: str | None = None):
        super().__init__(message or self.error_code)
        self.message = message or self.error_code
        if error_code:
            self.error_code = error_code

    def to_response(self) -> Response:
        return Response(
            {"error": self.error_code, "detail": self.message},
            status=self.status_code,
        )


class InsufficientBalanceError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "insufficient_balance"


class IdempotencyKeyConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "idempotency_key_conflict"


class IdempotencyKeyMissingError(DomainError):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "idempotency_key_required"


class IllegalStateTransitionError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "illegal_state_transition"


def payout_exception_handler(exc, context):
    """DRF exception handler that knows about our domain errors."""

    if isinstance(exc, DomainError):
        return exc.to_response()
    return drf_default_handler(exc, context)

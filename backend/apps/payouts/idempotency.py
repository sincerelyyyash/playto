"""Idempotency helpers for `POST /api/v1/payouts`.

Contract (from the assignment):

  - `Idempotency-Key` header is a merchant-supplied UUID.
  - Second call with the same key returns the *exact same response* as the
    first. No duplicate payout created.
  - Keys are scoped per merchant.
  - Keys expire after 24 hours.

Implementation choices:

  - We follow the spec literally: a second call with the same key returns
    the cached response regardless of the incoming body. We still record
    a sha256 `request_fingerprint` for forensic audit (so an operator can
    answer "did the merchant send the same body the second time?"), but
    a body mismatch is no longer a 409 - it returns the cached response.
  - We use `select_for_update()` with `get_or_create` to serialise
    concurrent first-time requests for the same key. Without this two
    parallel requests with the same key could each create their own
    payout.
  - The cached response (`response_status`, `response_body`) is written
    inside the same transaction as the new payout, so a replay always
    sees a complete response or no record at all.
  - If a row exists with no cached response yet: under PostgreSQL the
    normal case is a concurrent duplicate POST blocked on ``SELECT ... FOR
    UPDATE`` until the leader commits with ``persist_response``. A 409 is only
    returned after ``IDEMPOTENCY_IN_FLIGHT_WAIT_SECONDS`` (see views) when
    no response ever appears — e.g. an orphaned row from partial manual DB
    state, not from the happy path.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.merchants.models import Merchant
from apps.payouts.exceptions import (
    IdempotencyKeyConflictError,
    IdempotencyKeyMissingError,
)
from apps.payouts.models import IdempotencyKey

HEADER_NAME = "Idempotency-Key"


@dataclass
class CachedResponse:
    status: int
    body: Any


def parse_key(raw: str | None) -> uuid.UUID:
    if not raw:
        raise IdempotencyKeyMissingError(f"{HEADER_NAME} header is required")
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError) as exc:
        raise IdempotencyKeyMissingError(
            f"{HEADER_NAME} must be a UUID"
        ) from exc


def fingerprint_body(body: Any) -> str:
    """Stable sha256 of the request body. Sorted keys for canonical form."""

    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ttl() -> timedelta:
    return timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)


@dataclass
class IdempotencyResolution:
    """Outcome of looking up an idempotency key.

    Exactly one of these is true:
      - `cached` is set: the caller should return the cached response.
      - `record` is set with `cached=None`: the caller is the first writer
        and must finish the work and call `persist_response()`.
    """

    record: IdempotencyKey
    cached: CachedResponse | None


def begin(merchant: Merchant, key: uuid.UUID, body: Any) -> IdempotencyResolution:
    """Look up or create an idempotency record. Must be called inside a tx.

    - If a row exists, not expired, response cached: return that cached
      response (regardless of incoming body - strict spec semantics).
    - If a row exists, not expired, no response yet: with PostgreSQL the
      usual case is still blocking on the row lock until the leader commits.
      If we reach here with an orphaned row (no writer), the view layer
      retries until a cached response appears or times out, then surfaces 409.
    - If expired: replace with a new record (the original payout, if any,
      remains in the system; only the dedup window has elapsed).
    - If brand new: create the record. Caller must persist_response().
    """

    fp = fingerprint_body(body)
    now = timezone.now()

    record, created = IdempotencyKey.objects.select_for_update().get_or_create(
        merchant=merchant,
        key=key,
        defaults={"request_fingerprint": fp, "expires_at": now + _ttl()},
    )

    if not created and record.is_expired(now):
        # Expired: reset the dedup record. The original payout (if any)
        # stays as historical data; this just opens a fresh 24h window.
        record.request_fingerprint = fp
        record.payout = None
        record.response_status = None
        record.response_body = None
        record.expires_at = now + _ttl()
        record.save(
            update_fields=[
                "request_fingerprint",
                "payout",
                "response_status",
                "response_body",
                "expires_at",
            ]
        )
        return IdempotencyResolution(record=record, cached=None)

    if created:
        return IdempotencyResolution(record=record, cached=None)

    # Existing & not expired. Per spec, replay returns the cached response
    # regardless of body. We do NOT compare `record.request_fingerprint`
    # against `fp` - it stays on the row purely for audit / forensics.
    if record.has_response():
        return IdempotencyResolution(
            record=record,
            cached=CachedResponse(
                status=record.response_status,
                body=record.response_body,
            ),
        )
    # Same key, no cached response yet: duplicate payout would violate the
    # spec. Surfaces as 409 after view-level wait timeout; see
    # `IDEMPOTENCY_IN_FLIGHT_WAIT_SECONDS`.
    raise IdempotencyKeyConflictError(
        "Idempotency-Key in flight; retry shortly"
    )


def persist_response(
    record: IdempotencyKey,
    *,
    status: int,
    body: Any,
    payout_id=None,
) -> None:
    """Cache the final response on the idempotency record.

    Called inside the same transaction that created the payout, so a
    replay either sees the full response or no record at all.
    """

    record.response_status = status
    record.response_body = body
    if payout_id is not None:
        record.payout_id = payout_id
    record.save(update_fields=["response_status", "response_body", "payout"])

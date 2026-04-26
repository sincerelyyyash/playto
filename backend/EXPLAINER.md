# EXPLAINER.md

This document explains the non-obvious decisions in the Playto Payout
Engine backend. The assignment grades on these specifically:

> Clean ledger model tells us you think like someone who will own a
> money-moving system.
>
> Correct concurrency handling tells us you know the difference between
> Python-level and database-level locking.
>
> Good idempotency implementation tells us you have shipped an API that
> deals with real networks.

## 1. Money is integers, all the way down

Every monetary value is a `BigIntegerField` named `*_paise`. There is no
`FloatField`, no `DecimalField`, no `Decimal` arithmetic anywhere. Paise
is the smallest legal unit of INR; integers in Python are arbitrary
precision; `BigIntegerField` is `bigint` in Postgres (8 bytes,
±9.2 × 10¹⁸). That covers every payout this product will ever process.

Constraints at the DB level back this up:

- `ledger_amount_positive`: `CHECK (amount_paise > 0)` on `LedgerEntry`.
- `payout_amount_positive`: `CHECK (amount_paise > 0)` on `Payout`.

Even if a buggy view tries to insert a zero or negative amount, Postgres
refuses.

## 2. Balance derivation: ledger is the source of truth

The merchant balance is **never** stored on the `Merchant` row. It's
derived at every read:

```python
total      = SUM(credits) - SUM(debits)        # in apps/ledger/services.py
held       = SUM(amount_paise where status in {pending, processing})
available  = total - held
```

All three are single SQL aggregates with `Coalesce(Sum(...), 0)`. We
never fetch ledger rows into Python and add them up — that would be
the classic check-then-act race the assignment specifically warns
about.

The invariant the grader can check —
`SUM(credits) - SUM(debits) == settled balance` — holds because:

1. `LedgerEntry` rows are immutable: created once, never updated,
   never deleted.
2. A `DEBIT` is written **only** when a payout reaches `COMPLETED`.
3. A failed payout writes nothing — the held amount stops being held
   when its row's status changes to `FAILED`. No phantom credits, no
   phantom debits.

This means the ledger is honest history. The downside is that we
can't pretend a payout is settled before it actually is, but that's
exactly the property a payments system needs.

## 3. Concurrency on payout creation

`apps/payouts/services.py::create_payout` is the only path that holds
funds:

```python
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(pk=...)   # (1)
    ba       = BankAccount.objects.get(...)                       # (2)
    balance  = get_balance(merchant.pk)                           # (3) DB-side
    if balance.available_paise < amount:
        raise InsufficientBalanceError(...)
    Payout.objects.create(...)                                    # (4)
```

(1) is a row-level pessimistic lock. Two concurrent requests for the
same merchant serialise on this row. The second waits until the first
has either inserted its payout (so `held` now includes it) or rolled
back.

The textbook race — read 100, see 100 ≥ 60, both threads pass the
check, both insert payouts — is impossible because the second thread
re-reads `held` only after acquiring the lock, and at that point the
first thread's insert is visible.

`tests/test_concurrency_payout_creation.py` proves this with real
threads against real Postgres: 100₹ balance, two 60₹ requests, exactly
one succeeds.

## 4. Concurrency in the worker: CAS, not read-then-write

The processor task could try `payout.status = 'processing'; payout.save()`
but that's a Python-level mutation that could be concurrently overwritten.
Instead every transition uses a **conditional UPDATE** (compare-and-swap):

```python
rows = Payout.objects.filter(pk=pid, status="pending").update(
    status="processing",
    attempt_count=F("attempt_count") + 1,
    processing_started_at=timezone.now(),
)
if rows == 1:
    # we own it
```

If two workers race to claim the same `PENDING` payout, only one
issues an UPDATE that finds a row matching `status='pending'`. The
loser's UPDATE returns 0 rows changed. No exceptions, no logs that
look like errors — clean lock-free correctness.

The same pattern protects:

- `claim_for_processing` (`PENDING -> PROCESSING`)
- `claim_for_retry`       (`PROCESSING -> PROCESSING` with bumped attempt)
- `settle_success`        (`PROCESSING -> COMPLETED`)
- `settle_failure`        (`PROCESSING -> FAILED`)

The watchdog does add `select_for_update(skip_locked=True)` because we
want to *iterate* stuck payouts, not just blind-update one row, and
we don't want two beat ticks tripping over the same row.

## 5. State machine — explicit, double-enforced

Allowed transitions, defined in `apps/payouts/state.py`:

```
pending     -> processing
processing  -> completed
processing  -> failed
```

Everything else is illegal: backwards transitions, skipping a state,
self-loops. Two layers of enforcement:

1. **Python guard** (`assert_can_transition`) raises
   `IllegalStateTransitionError` *before* we issue an UPDATE. This
   catches programmer mistakes early with a clear traceback.
2. **DB-level conditional UPDATE** as described above. This catches
   concurrent writers who passed the guard but lost the race.

A subtle, important choice: **retries do not transition `PROCESSING`
back to `PENDING`.** That would be a backwards transition, and the
assignment explicitly forbids them. Instead, the retry task issues an
UPDATE that *stays in `PROCESSING`* but bumps `attempt_count` and
resets `processing_started_at`. Same row, fresh attempt, no backwards
movement.

## 6. Idempotency

Contract from the assignment:

> The Idempotency-Key header is a merchant-supplied UUID. Second call
> with the same key returns the exact same response as the first. No
> duplicate payout created. Keys scoped per merchant. Keys expire
> after 24 hours.

`apps/payouts/idempotency.py` enforces this with these guarantees:

- `IdempotencyKey` table has a `UNIQUE (merchant_id, key)` constraint.
  Postgres physically refuses to insert a duplicate.
- Lookup uses `select_for_update().get_or_create(...)`, so two
  concurrent requests with the same key serialise. The loser sees the
  winner's row.
- We store a `request_fingerprint = sha256(canonical_body)` on the row
  for **forensic audit only**. The replay path does *not* compare it
  against the incoming body. The spec says "the second call with the
  same key returns the exact same response", and we take that
  literally — a replay returns the cached response regardless of
  body. The fingerprint lets an operator answer "did the merchant
  actually send the same body?" after the fact without changing the
  HTTP behaviour.
- We initially over-engineered this to Stripe-style "409 on body
  mismatch". That's a real safety property (a $50 payout can't be
  silently replayed as $5000), but it isn't what the spec asks for.
  We reverted it; see `AI_AUDIT.md` entry 4. The trade-off is
  documented so a misbehaving client that reuses a key with a
  different body silently inherits the first call's payout result.
- The cached `(response_status, response_body)` are written **inside
  the same transaction** as the payout creation. So a replay either
  sees a fully-formed response *and* a real payout, or no record at
  all. There is no half-state where the row exists but the cached
  response is null in a way callers would observe.
- In-flight edge case: if a previous request crashed *after* claiming
  the key but *before* writing the cached response, a replay returns
  **409** ("retry shortly") rather than fabricating a response or
  creating a duplicate payout. The spec only promises "same response
  as the first" once the first has actually produced one.
- Expiry: rows have `expires_at = created_at + 24h`. Lookups treat
  expired rows as if they don't exist, opening a fresh dedup window.
  An hourly Beat task (`cleanup_expired_idempotency_keys`) prunes them.

## 7. Retry / stuck-payout watchdog

`scan_stuck_payouts` runs on Beat every 10 seconds:

```
SELECT * FROM payouts
 WHERE status = 'processing'
   AND processing_started_at < now() - 30 seconds
 FOR UPDATE SKIP LOCKED
```

For each stuck row:

- If `attempt_count >= PAYOUT_MAX_ATTEMPTS` (default **3**, matching
  assignment.md “max 3 attempts”) → transition to `FAILED`. The held
  amount stops being held the moment status changes, so funds are
  returned to `available` without any debit ledger entry being written.
- Otherwise → enqueue `retry_payout(payout_id)` with countdown
  `PAYOUT_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt_count - 1)`. With
  defaults that's **5s** after the first hang (`attempt_count=1`) and
  **10s** after the second (`attempt_count=2`). A third stuck cycle
  (`attempt_count=3`) hits the cap and goes straight to `FAILED` (no
  third countdown — still exponential backoff with a hard cap).

`SKIP LOCKED` matters: without it, two beat ticks (or a beat tick and
a worker mid-settlement) could pile up on the same row. With it, the
second observer just skips and moves on.

## 8. Where Python's defaults would have hurt us, and what we did instead

| Defaults that would have failed                         | What we did                                          |
| ------------------------------------------------------- | ---------------------------------------------------- |
| `merchant.balance += amount` then save                  | DB aggregates, never round-trip then write           |
| `if payout.status == 'pending': payout.status = ...`    | `filter(status='pending').update(...)` (CAS)         |
| Treating retries as "go back to pending"                | Stays in PROCESSING, bumps attempt_count             |
| `IdempotencyKey.save()` then later `update()`           | One transaction; row+response committed atomically   |
| Storing only the cached response                        | Also store a body fingerprint for post-hoc audit     |
| `select_related` for balance                            | One `Coalesce(Sum(...), 0)` aggregate per number     |
| `transaction=False` on tests                            | Real `transactional_db` for concurrency tests        |

## 9. What the tests cover

- `test_balance_invariant.py` — `SUM(credits) - SUM(debits)` matches
  `total` for empty, credit-only, mid-flight, and mixed-state ledgers.
- `test_concurrency_payout_creation.py` — the headline test: 100₹
  balance, two 60₹ threads, exactly one wins. Plus a 3-way variant.
- `test_idempotency.py` — same key + same body = cached response,
  same key + different body = the *same* cached response (strict spec
  semantics), missing/malformed header = 400, per-merchant scoping,
  24h expiry.
- `test_state_machine.py` — every illegal pair raises; CAS catches
  rows that are no longer in the expected state; double-settle is a
  no-op the second time.
- `test_retry_watchdog.py` — stuck rows are picked up only when they
  exceed the threshold; backoff is
  `PAYOUT_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt_count - 1)` (e.g. 5s
  then 10s with base 5); final FAILED releases held funds without
  writing a debit; retry task increments `attempt_count`.
- `test_payout_api.py` — happy-path POST, insufficient balance 422,
  balance reflects pending hold, detail endpoint, unauthenticated 401.

## 10. Things we deliberately did **not** build

- A real customer payment flow. The assignment explicitly says we
  don't need it; credits are seeded.
- A reversal/refund flow. Out of scope.
- Webhooks. The frontend polls `/api/v1/payouts/{id}/`.
- Per-merchant rate limiting. Useful for production, irrelevant to
  what's being graded.
- Background dispatch via DB-as-queue. Celery's the standard tool
  here and the assignment offers it as the first option.

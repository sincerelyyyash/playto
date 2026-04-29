# EXPLAINER.md

This document explains the non-obvious decisions in the Playto Payout Engine
backend. The assignment grades on these specifically:

> Clean ledger model tells us you think like someone who will own a
> money-moving system.
>
> Correct concurrency handling tells us you know the difference between
> Python-level and database-level locking.
>
> Good idempotency implementation tells us you have shipped an API that
> deals with real networks.

The section **Assignment deliverables — questions 1–5** answers the
prompts in `assignment.md` verbatim (paste + explanation). Everything
after that is optional depth.

---

## Assignment deliverables — questions 1–5

### 1. The Ledger — balance calculation + why credits and debits

**Paste (actual code):** `apps/ledger/services.py` — totals and held amounts
are each a single Django `aggregate()`; `available` is `total - held` in Python
only after those two SQL round-trips return scalars.

```python
def _ledger_total(merchant_id) -> int:
    """SUM(credits) - SUM(debits) at the DB, returns 0 for empty ledger."""

    agg = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        credits=Coalesce(
            Sum("amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.CREDIT)),
            Value(0),
        ),
        debits=Coalesce(
            Sum("amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.DEBIT)),
            Value(0),
        ),
    )
    return int(agg["credits"]) - int(agg["debits"])


def _held_amount(merchant_id) -> int:
    """SUM of amount_paise over payouts that haven't settled yet."""

    from apps.payouts.models import Payout

    held_statuses = [Payout.Status.PENDING, Payout.Status.PROCESSING]
    agg = Payout.objects.filter(
        merchant_id=merchant_id,
        status__in=held_statuses,
    ).aggregate(held=Coalesce(Sum("amount_paise"), Value(0)))
    return int(agg["held"])


def get_balance(merchant_id) -> Balance:
    total = _ledger_total(merchant_id)
    held = _held_amount(merchant_id)
    return Balance(
        total_paise=total,
        held_paise=held,
        available_paise=total - held,
    )
```

**Why credits and debits:** The ledger is an **append-only** history.
`CREDIT` rows represent money entering the merchant balance (seeded customer
payments in this assignment). `DEBIT` rows represent money leaving upon a
**completed** payout only. We never store a separate “balance” column on
`Merchant` — that would be a second source of truth and a classic concurrent
read–modify–write footgun. The grader’s invariant
`SUM(credits) − SUM(debits) == settled balance` holds because debits are
written **exactly once** when a payout reaches `COMPLETED`, and failed /
cancelled-in-flight payouts do not get a debit (they stop being “held” when
status leaves `pending`/`processing`).

---

### 2. The Lock — exact code that prevents two concurrent payouts overdrawing

**Paste:** `apps/payouts/services.py::create_payout` — the merchant row is
locked first; balance is recomputed while holding that lock; only then do we
insert the `PENDING` payout.

```python
def create_payout(payload: CreatePayoutInput) -> Payout:
    if not isinstance(payload.amount_paise, int) or payload.amount_paise <= 0:
        raise InvalidAmountError("amount_paise must be a positive integer")

    with transaction.atomic():
        merchant = Merchant.objects.select_for_update().get(pk=payload.merchant.pk)

        try:
            bank_account = BankAccount.objects.get(
                pk=payload.bank_account_id,
                merchant_id=merchant.pk,
                is_active=True,
            )
        except BankAccount.DoesNotExist as exc:
            raise BankAccountInvalidError(
                "bank_account not found or not active"
            ) from exc

        balance = get_balance(merchant.pk)
        if balance.available_paise < payload.amount_paise:
            raise InsufficientBalanceError(
                f"available={balance.available_paise} requested={payload.amount_paise}"
            )

        payout = Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=payload.amount_paise,
        )
        log.info(
            "payout.created id=%s merchant=%s amount=%s",
            payout.id,
            merchant.id,
            payout.amount_paise,
        )
        return payout
```

**Database primitive:** **`SELECT … FOR UPDATE`** (row-level lock) on the
merchant’s row inside a transaction. Two concurrent requests for the same
merchant **serialize** at step one; the second cannot read `get_balance`
and insert until the first commits or rolls back, so both cannot pass
`available >= amount` for overspending. Proof: `tests/test_concurrency_payout_creation.py`.

---

### 3. The Idempotency — how we know we’ve seen a key; second request while first is in flight

**How we know:** Each `(merchant, Idempotency-Key UUID)` maps to at most one
row in `IdempotencyKey` (`UNIQUE (merchant_id, key)`). On first use we run
`select_for_update().get_or_create(...)` so concurrent first-seen serialise.
We store `response_status` and `response_body` once the handler finishes;
any later POST with the same key returns that cached HTTP payload without
creating another payout.

**Second request while first is in flight (PostgreSQL):** The follower
blocks on the same row lock until the leader’s transaction commits with
`persist_response()`, then reads the cached response — same status and JSON
as the first call.

**Orphan / rare path:** `begin()` can raise `IdempotencyKeyConflictError`
if a row exists without a cached response and no writer will complete it.
`PayoutCreateListView.post` catches that, **sleeps briefly, and retries**
until `IDEMPOTENCY_IN_FLIGHT_WAIT_SECONDS`; then returns **409**. That
bridges “wait for the first response” without ever double-creating a payout.

```python
# apps/payouts/idempotency.py (core lookup)
record, created = IdempotencyKey.objects.select_for_update().get_or_create(
    merchant=merchant,
    key=key,
    defaults={"request_fingerprint": fp, "expires_at": now + _ttl()},
)
# … if existing and record.has_response(): return cached …
```

---

### 4. The State Machine — where `failed → completed` is blocked

**Paste:** Allowed transitions are data in `apps/payouts/state.py`. Terminal
states `completed` and `failed` map to **empty** sets — no outgoing
transitions, so `failed → completed` is not in the map and is rejected.

```python
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    PayoutStatus.PENDING: frozenset({PayoutStatus.PROCESSING}),
    PayoutStatus.PROCESSING: frozenset(
        {PayoutStatus.COMPLETED, PayoutStatus.FAILED}
    ),
    PayoutStatus.COMPLETED: frozenset(),
    PayoutStatus.FAILED: frozenset(),
}


def assert_can_transition(from_status: str, to_status: str) -> None:
    if not is_legal(from_status, to_status):
        raise IllegalStateTransitionError(
            f"illegal transition: {from_status} -> {to_status}"
        )
```

For **`failed → completed`**: `ALLOWED_TRANSITIONS["failed"]` is `frozenset()`,
so `is_legal("failed", "completed")` is **False** and
`assert_can_transition` raises **`IllegalStateTransitionError`** before any
`UPDATE`. Settlement code also uses **conditional `UPDATE … WHERE status = …`**
so a concurrent writer cannot promote a row that is no longer in the
expected state.

---

### 5. The AI Audit — one concrete wrong suggestion, what we caught, what shipped

**What AI suggested:** Put **`balance_paise` on `Merchant`** and do
`merchant.balance_paise -= amount; merchant.save()` when creating a payout —
cheaper than scanning ledger aggregates.

**Why it was wrong:** That is a **read–modify–write in Python**. Two threads
can both read `100`, both subtract `60`, both save — the grader’s balance
and concurrency tests fail. It also **collapses** “settled” vs “available”
with no clean place for **held** funds.

**What we shipped instead:** **No cached balance column.** Only
`apps/ledger/services.py::get_balance` (see question 1) — `Coalesce(Sum(...))`
aggregates on `LedgerEntry` plus held sums on `Payout` in **SQL**.

(Full discussion: `AI_AUDIT.md` section 1.)

---

## Further context (deeper dives)

### Money is integers, all the way down

Every monetary value is a `BigIntegerField` named `*_paise`. There is no
`FloatField`, no `DecimalField`, no `Decimal` arithmetic in the money path.
Constraints: `CHECK (amount_paise > 0)` on `LedgerEntry` and `Payout`.

### Concurrency in the worker: CAS, not read-then-write

Every transition uses a **conditional `UPDATE`** (compare-and-swap), e.g.
`Payout.objects.filter(pk=pid, status="pending").update(status="processing", …)` — only one
worker wins; the other updates zero rows.

Code: `apps/payouts/services.py` (`claim_for_processing`, `settle_success`,
`settle_failure`, etc.).

### Retries do not go backwards

Stuck payouts stay in **`PROCESSING`**; `claim_for_retry` bumps `attempt_count`
and refreshes timestamps — never `PROCESSING → PENDING` (illegal).

### Retry / stuck-payout watchdog

`scan_stuck_payouts` (Beat, every 10s) selects `PROCESSING` rows older than
`PAYOUT_STUCK_AFTER_SECONDS` with `FOR UPDATE SKIP LOCKED`, then either
enqueues `retry_payout` with exponential backoff or marks **FAILED** after
`PAYOUT_MAX_ATTEMPTS`. See `apps/payouts/tasks.py`.

### Where Python’s defaults would have hurt us

| Default failure mode | What we did |
| ------------------- | ----------- |
| Cached balance on `Merchant` | DB aggregates only (`get_balance`) |
| `payout.status = …; save()` in worker | `filter(status=expected).update(...)` |
| Retry = reset to `PENDING` | Stay in `PROCESSING`, bump attempts |

### What the tests cover

- `test_balance_invariant.py` — ledger invariant under mixed workloads.
- `test_concurrency_payout_creation.py` — 100₹ / two 60₹ threads, one wins.
- `test_idempotency.py` — strict replay, scoping, expiry, concurrent same-key POSTs.
- `test_state_machine.py` — illegal pairs and CAS behavior.
- `test_retry_watchdog.py` — stuck payouts, backoff, cap, fund release.
- `test_payout_api.py` — HTTP-level payout and auth behaviors.

### Things we deliberately did **not** build

Real inbound pay-in flow, refunds, webhooks, production rate limits — out of
scope for the assignment brief.

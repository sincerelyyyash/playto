# AI_AUDIT.md

The assignment specifically asks for an honest audit:

> Honest AI audit tells us you are senior enough to not trust the
> machine blindly.

This is a log of places where the obvious / first-draft AI suggestion
would have been wrong, and what was actually shipped. Each entry has
the failure mode, why it's wrong, and the fix that's now in the code.

---

## 1. "Just store balance on the Merchant row and increment/decrement"

**Tempting AI suggestion:** add `balance_paise` to `Merchant`, do
`merchant.balance_paise -= amount; merchant.save()` on payout
creation. Cheaper than aggregates.

**Why it's wrong:** this is the canonical money-movement footgun.

- It creates two sources of truth (the cached number and the ledger),
  which drift the moment any code path forgets to update both.
- `merchant.balance_paise -= amount` is a Python read-modify-write.
  Two concurrent payouts both read `100`, both subtract `60`, both
  save `40`. The grader's invariant fails.
- It hides the held/available split — you can't ask the cached
  number "is this the settled balance or the spendable balance?"

**Shipped instead:** `apps/ledger/services.py::get_balance` — three
single-aggregate queries on the ledger and the payout table. No
cached number. The grader's invariant
`SUM(credits) - SUM(debits) == settled balance` is true by construction.

---

## 2. "Update payout status with `payout.status = 'processing'; payout.save()`"

**Tempting AI suggestion:** worker fetches the payout, sets the
status, calls `.save()`.

**Why it's wrong:** that's a Python-level write with no concurrency
control. Two workers can both fetch the same `PENDING` row, both
flip it to `PROCESSING`, both run the simulation, both write a debit
ledger entry. The merchant gets debited twice.

**Shipped instead:** every transition uses a conditional UPDATE
(compare-and-swap) — `apps/payouts/services.py`:

```python
rows = Payout.objects.filter(pk=pid, status="pending").update(
    status="processing", attempt_count=F("attempt_count")+1, ...
)
if rows == 1:  # we own it
```

The DB itself enforces "exactly one writer wins". The loser's UPDATE
matches zero rows; no exception, no double-settle.

---

## 3. "Retry stuck payouts by moving them back to PENDING"

**Tempting AI suggestion:** stuck payout? Reset to `PENDING` so the
worker can pick it up again.

**Why it's wrong:** the assignment explicitly says
`processing -> pending` is an illegal backwards transition.

**Shipped instead:** the retry task stays in `PROCESSING` and bumps
`attempt_count` + `processing_started_at`. The state machine never
goes backwards. See `apps/payouts/services.py::claim_for_retry`.

---

## 4. "Idempotency: 409 on body mismatch, like Stripe does"

**Tempting AI suggestion:** the merchant could replay the same key
with a different body — same UUID, but `amount_paise` changed from
5000 to 500000. Returning the cached response would silently report
success on a request the merchant *did not actually send*. So store
`sha256(canonical_body)` alongside the key, return 409 on mismatch
(Stripe / Square style).

**Why I initially shipped that and then reverted:** the assignment
spec says, verbatim,

> "Second call with the same key returns the *exact same response*
> as the first."

That's strict pure-key dedup, not Stripe-style "key + body" dedup.
The first draft over-engineered the safety property the spec asks for
and ended up *not* matching the spec. A grader running the obvious
test (POST with key K, then POST with key K and a tweaked body) would
see a 409 where the spec says they should see the cached response.

**Shipped instead:** `apps/payouts/idempotency.py` still computes and
stores `sha256(canonical_body)` on the row, but uses it for **forensic
audit only** — the replay path returns the cached response regardless
of the incoming body. The trade-off (a misbehaving client that reuses
a key with a different body silently inherits the first call's
result) is documented in `EXPLAINER.md` section 6.

The one case we still 409 on is "key seen, no cached response yet"
(the original request crashed mid-flight). The spec only promises
"same response as the first" *after* the first has produced one;
fabricating a response or letting a duplicate payout through would
both be worse.

---

## 5. "Just `IdempotencyKey.objects.get_or_create(...)` — no lock needed"

**Tempting AI suggestion:** the unique constraint prevents
duplicates, so `get_or_create` is enough.

**Why it's wrong:** the unique constraint prevents duplicate *rows*,
but not duplicate *payouts*. Two threads with the same key, same
body could both call `get_or_create` "first": one INSERTs the
idempotency row, the other catches IntegrityError and re-fetches.
But before the winner has time to create a payout and write the
cached response, the loser could see the row exists, see no cached
response, and proceed to create *its own* payout.

**Shipped instead:** `select_for_update().get_or_create(...)` plus
caching the response in the same transaction as the payout. A second
caller either sees a complete response (replay-safe) or has to wait
on the lock; if the original transaction rolled back, no row exists
at all and the caller becomes the new "first writer".

---

## 6. "Write the debit ledger entry on payout creation, write a credit on failure"

**Tempting AI suggestion:** double-entry style — debit on creation,
reversal credit on failure.

**Why it's wrong:** it works, but it makes the invariant subtle. You
have to define "settled" as "after final state", and an auditor
reading the ledger sees pairs of opposed entries that look like
mistakes. More importantly, transient state (between the debit
write and the failure-credit write) violates the invariant.

**Shipped instead:** the ledger only ever records terminal state —
seeded credits, and debits for `COMPLETED` payouts. Held funds are
expressed as `SUM(amount_paise)` over `PENDING/PROCESSING` payouts.
Failure releases the hold without writing anything. `SUM(credits) -
SUM(debits)` is the settled balance at every instant, never
transiently wrong.

---

## 7. "Use `select_related` to fetch all the merchant's ledger entries and sum them"

**Tempting AI suggestion:** `merchant.ledger_entries.all()` then sum
in Python.

**Why it's wrong:** quadratic in ledger size, fetched into Python
memory, and crucially — *not* a database-level operation, which is
what the assignment grades on.

**Shipped instead:** `Coalesce(Sum("amount_paise", filter=Q(...)), 0)`.
One aggregate per number, computed by Postgres, total round-trips:
two.

---

## 8. "Tests can use SQLite — Postgres is overkill"

**Tempting AI suggestion:** SQLite for tests, Postgres for prod.
Faster, no Docker.

**Why it's wrong:**

- SQLite doesn't support `SELECT FOR UPDATE` (it's a no-op).
  Concurrency tests would silently pass while never exercising the
  actual locking.
- SQLite's transaction isolation is different. Bugs that show up
  under Postgres' `READ COMMITTED` won't show up at all.

**Shipped instead:** tests run against the same Postgres image used
in development (Docker Compose). The concurrency tests use
`@pytest.mark.django_db(transaction=True)` so each thread gets a
real transaction boundary, the way it would in production.

---

## 9. "transaction.on_commit isn't necessary — just call .delay() inline"

**Tempting AI suggestion:** in the view, call `process_payout.delay(payout.id)`
right after `Payout.objects.create(...)`.

**Why it's wrong:** if the surrounding transaction rolls back (any
later statement raises), the `delay()` call has *already* sent a
message to Redis. The worker will pick up a payout ID for a row
that no longer exists, log a confusing error, and possibly cause
alerts to fire on a phantom payout.

**Shipped instead:** `transaction.on_commit(lambda: process_payout.delay(...))`
in the view. The enqueue runs only if the transaction actually
commits; if it rolls back, no message is sent.

---

## 10. "Register Beat periodic tasks via `@app.on_after_configure` in `tasks.py`"

**Tempting AI suggestion:** connect a signal handler on the Celery app
at import time so the schedule lives next to the task definitions.

**Why we moved away from that:** subtle import-order issues, the
schedule is invisible to anyone grepping settings, and
`django-celery-beat`'s `DatabaseScheduler` is easier to reason about
when the declared schedule is the dict Django loads at startup.

**Shipped instead:** `CELERY_BEAT_SCHEDULE` in `config/settings.py`
(`scan-stuck-payouts-every-10s`, `cleanup-expired-idempotency-keys-hourly`).
Trade-off: task renames need a matching edit in settings — acceptable
for a small, assignment-sized codebase.

---

## What I'd revisit if this were production

- The watchdog runs every 10s and scans Postgres. At scale this is
  fine for thousands of in-flight payouts, but at millions a
  dedicated job queue per merchant or a Redis sorted-set scheduler
  would be cheaper.
- Idempotency keys are pruned hourly via Beat; very high-volume
  merchants might still fill the table between sweeps. A `pg_cron`
  job at the DB level, or partitioning by `expires_at`, would handle
  that.
- The settlement simulator is hard-coded to three outcomes; a real
  bank integration would need an idempotent webhook handler with
  its own dedup table — same pattern, different actor.
- TokenAuthentication is fine for the assignment but production
  would use rotating short-lived tokens / OAuth.

# Playto Payout Engine — Backend

Django + DRF + PostgreSQL + Celery (Redis) implementation of the Playto Payout Engine.

See [EXPLAINER.md](EXPLAINER.md) for the why behind every non-obvious choice
(locking, ledger semantics, idempotency, state machine, retries) and
[AI_AUDIT.md](AI_AUDIT.md) for an honest log of where AI suggestions had to be
corrected.

## Stack

- Django 5 + DRF, `TokenAuthentication`
- PostgreSQL 16 (real money problems demand real `SELECT ... FOR UPDATE`)
- Celery 5 + Redis broker, Celery Beat for periodic tasks
- pytest + pytest-django

## Run it

Prerequisites: Docker + Docker Compose.

```bash
cd backend
cp .env.example .env

# Build images and apply migrations.
make build
make up
make migrate

# Seed 3 merchants with credit history. Prints the API tokens.
make seed
```

The web API is on http://localhost:8000. Expected output of `make seed`:

```
Alice Studio         alice@example.com         total=  150000p   token=abcdef...
Bob Freelance        bob@example.com           total=   80000p   token=ghijkl...
Carol Agency         carol@example.com         total=  375000p   token=mnopqr...
```

## API

All endpoints (except `/healthz` and `/api/v1/auth/token/`) require
`Authorization: Token <token>`.

| Method | Path                               | Purpose                                    |
| ------ | ---------------------------------- | ------------------------------------------ |
| POST   | `/api/v1/auth/token/`              | Username/password -> token (DRF builtin)   |
| GET    | `/api/v1/me/`                      | Current merchant                           |
| GET    | `/api/v1/me/balance/`              | `{ total_paise, held_paise, available_paise }` |
| GET    | `/api/v1/me/ledger/`               | Recent credits/debits                      |
| GET    | `/api/v1/bank-accounts/`           | Merchant's bank accounts                   |
| POST   | `/api/v1/payouts/`                 | Create payout (requires `Idempotency-Key`) |
| GET    | `/api/v1/payouts/`                 | History                                    |
| GET    | `/api/v1/payouts/{id}/`            | Single payout (poll for live status)       |

### Quick example

```bash
TOKEN=...
BANK=...   # from /api/v1/bank-accounts/

curl -X POST http://localhost:8000/api/v1/payouts/ \
  -H "Authorization: Token $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d "{\"amount_paise\": 5000, \"bank_account_id\": \"$BANK\"}"
```

## Tests

```bash
make test
```

Highlights:

- `tests/test_balance_invariant.py` — verifies `SUM(credits) - SUM(debits) == settled balance` under mixed workloads.
- `tests/test_concurrency_payout_creation.py` — real threads, real Postgres locks: exactly one of two simultaneous 60₹ requests wins on a 100₹ balance.
- `tests/test_idempotency.py` — replays, body-mismatch 409, per-merchant scoping, expiry.
- `tests/test_state_machine.py` — every illegal transition rejected by both the Python guard and the conditional UPDATE.
- `tests/test_retry_watchdog.py` — exponential backoff, max-3 attempts, funds returned on final failure.

## Tunable knobs

All env-driven (see `.env.example`):

| Var                                | Default | Meaning                                       |
| ---------------------------------- | ------- | --------------------------------------------- |
| `PAYOUT_SUCCESS_RATE`              | 0.7     | Simulated bank settlement success probability |
| `PAYOUT_FAILURE_RATE`              | 0.2     | Simulated failure probability                 |
| `PAYOUT_HANG_RATE`                 | 0.1     | Simulated hang probability (worker drops it)  |
| `PAYOUT_STUCK_AFTER_SECONDS`       | 30      | Watchdog cutoff                               |
| `PAYOUT_MAX_ATTEMPTS`              | 3       | Max retries before FAILED                     |
| `PAYOUT_RETRY_BASE_DELAY_SECONDS`  | 5       | Base for exponential backoff: `base * 2^attempt` |
| `IDEMPOTENCY_TTL_HOURS`            | 24      | Idempotency-Key dedup window                  |

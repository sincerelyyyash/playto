# Playto Payout Engine

Minimal payout engine per [`assignment.md`](assignment.md): Django backend + React merchant dashboard.

## Quick start

1. **Backend** (Docker): see [`backend/README.md`](backend/README.md) — `cp .env.example .env`, `make build`, `make up`, `make migrate`, `make seed`.
2. **Frontend**: see [`frontend/README.md`](frontend/README.md) — `cd frontend && npm install && npm run dev`.

Run the **Celery worker** (included in `docker compose up`) so payouts progress past `pending` and the dashboard polling shows live status.

# Playto Payout Engine — Frontend

React + Vite + Tailwind merchant dashboard for the assignment ([`../assignment.md`](../assignment.md)): balance (available / held / total), ledger, payout request with `Idempotency-Key`, and payout history with live polling for `pending` / `processing` rows.

## Prerequisites

- Node 20+ (or current LTS)
- Backend running with API on port **8000** (see [`../backend/README.md`](../backend/README.md): `make up`, `make migrate`, `make seed`). **Celery worker** must be up so payouts leave `pending`.

## Setup

```bash
cd frontend
cp .env.example .env   # optional; defaults proxy to http://localhost:8000
npm install
npm run dev
```

Open **http://localhost:5173** (Vite default). The dev server proxies `/api/*` to Django (`VITE_API_PROXY_TARGET`), so the browser does not need CORS on the backend.

## Demo login

After `make seed` in `backend/`, use any seeded user; password equals username (e.g. `alice` / `alice`).

## Scripts

| Command       | Purpose                |
| ------------- | ---------------------- |
| `npm run dev` | Vite dev server + HMR  |
| `npm run build` | Typecheck + production bundle |
| `npm run preview` | Preview production build |
| `npm run lint` | ESLint                 |

## Production API note

`npm run build` emits static assets; you must serve them behind the same host as the API or configure a production API base URL and CORS on Django—out of scope for the assignment dev loop.

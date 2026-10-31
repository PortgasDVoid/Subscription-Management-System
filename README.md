# Brightloop Subscription Management System

PostgreSQL schema + FastAPI backend + React/Vite frontend covering the full billing month: signup/login, catalog, quotations,
subscriptions, automated billing, discounts/tax, payments, customer portal and finance reporting.

## Quick start

```bash
cp .env.example .env          # compose reads it; change JWT_SECRET and the DB password
docker compose up --build -d  # Postgres (schema + seeds) + API :8000 + frontend :5173
```
Open http://localhost:5173 (API docs: http://localhost:8000/docs).

Seeded logins (password `Password@123`): `admin@brightloop.test` (admin), `priya.nair@brightloop.test` (staff),
`anjali.varma@nilatech.test` (customer). If the seeded hash does not verify on your machine run
`docker compose exec api python -m scripts.set_demo_passwords`.

Init scripts only run on an **empty** volume. To rebuild a disposable demo DB: `docker compose down -v && docker compose up --build -d`
(this deletes the data). An existing DB created before the lifecycle change needs `optional/migrate_subscription_status.sql`.

## What each scene of the brief maps to

| Scene | Where |
|---|---|
| Signup / login / reset / roles | `POST /api/auth/signup|login|forgot-password|reset-password`, `GET /api/auth/me`; roles enforced by `app/deps.py`; only admin can create staff (`POST /api/resources/users`) |
| New product, variants, plans | `/api/resources/products|product_variants|plans` (admin write); plan flags `auto_renew`, `pause_allowed`, `early_termination_allowed` are enforced by the lifecycle endpoint |
| Quote → subscription | `POST /api/quotations/from-template` → `/status` (send/approve) → `/convert` → `POST /api/subscriptions/{id}/lines` → `/transition` (`activate`, `pause`, `resume`, `renew`, `close`) |
| Billing day | `POST /api/billing/run?run_date=` (also optional scheduler): invoices, lines, tax, discounts generated from subscriptions; unique index + savepoints = nothing billed twice or skipped; missed periods are caught up |
| Invoice actions | `POST /api/invoices/{id}/confirm|cancel|send`, `GET /api/invoices/{id}/pdf` (print) |
| Discounts | admin-only creation; applied automatically by the billing run (whole subscription or product-scoped; min purchase/qty, dates, usage + per-customer limits) |
| Payments | `POST /api/payments` with method, amount, date, note and invoice allocations; triggers move invoices to paid/overdue |
| Finance lead | `/api/dashboard/summary`, `/api/reports/invoices|subscriptions|payments` (filters + paging), UI "Dashboard" and "Reports" |
| Customer portal | `/api/portal/subscriptions|invoices`; customers only ever see their own rows and PDFs |

## Security model
Every `/api/*` route except `/`, `/health`, `/api/auth/*` and the stateless calculators needs a bearer token. Staff manage
operational data, only the admin writes catalog/tax/discount/user data and deletes, invoices/payments/subscriptions/quotations can
never be deleted (cancel or close them), and balances/statuses/numbers cannot be edited through the generic API.
Passwords are bcrypt-hashed (old scrypt hashes still verify). Five failed logins lock the account for 15 minutes.
Reset tokens are stored hashed and expire after 60 minutes. Set `DEV_RETURN_RESET_TOKEN=0` and configure SMTP outside demos.

## Billing behaviour worth knowing
* Billing dates are anchored to the subscription start date (Jan 31 → Feb 28 → Mar 31).
* A discount with no product restriction applies to the whole subscription; minimums are checked across its eligible lines;
  a fixed amount is spent once across lines, a percentage applies per line; the best auto-apply discount wins per line.
* Contracts with `auto_renew` extend `expiry_date` and bump `renewal_count`; others close with reason `expired`.
* Resuming a paused subscription never back-bills the pause.
* Auto-confirm is on by default (`auto_confirm=false` leaves invoices as drafts for review).

## Tests
```bash
pip install -r requirements.txt && pytest -q
```
Unit tests cover pricing, discount planning, billing dates, auth and PDF. API tests check that protected routes reject
unauthenticated calls. **There are still no automated tests against a live PostgreSQL** - see `docs/acceptance_checklist.md`.

## Performance evidence (<2 s with thousands of subscriptions)
```bash
docker compose exec -T db psql -U sms_user -d subscription_db < optional/load_test_seed.sql   # ~4,800 subscriptions
# sign in, then GET /api/performance/benchmark (needs a token) and keep the output with the dataset counts
```

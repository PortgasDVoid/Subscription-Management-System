# Subscription Management System: backend (Brightloop Software)

Developer 3 scope: pricing, tax, discounts, invoice generation, payments, subscription lifecycle,
invoice PDF, database seeding, query timing, QA. Database design is the team's `db/01_schema.sql`.

## Layout

```
backend/
├── app/
│   ├── db.py                          engine + scope() transaction helper (swap for the team's session module)
│   ├── repositories/                  SQL only: billing, payment, lifecycle
│   ├── services/
│   │   ├── pricing_service.py         base + variant price, plan minimum quantity
│   │   ├── tax_service.py             rate from the taxes table, per line
│   │   ├── discount_service.py        pinned + auto-apply, limits, expiry
│   │   ├── invoice_service.py         run_billing(): duplicate-safe invoice generation
│   │   ├── payment_service.py         record + allocate payments, friendly errors
│   │   ├── subscription_lifecycle_service.py   renew / close expired subscriptions
│   │   ├── pdf_service.py             invoice PDF from saved values
│   │   └── errors.py
│   └── utils/calculations.py          pure money / tax / period maths
├── db/                                schema, seed, views, quick checks, docker-compose
├── scripts/
│   ├── seed_database.py               demo-scale data (idempotent)
│   └── benchmark_queries.py           page-query timing vs the 2 s budget
├── tests/                             see CHANGES.md for what has and has not been run
├── docs/                              DATABASE_MAPPING.md, FILE_FLOW.md (diagrams)
├── requirements.txt  pytest.ini  CHANGES.md
```

Not built yet: `app/main.py`, `app/api/invoice_routes.py` (framework and auth to agree with the team).

## Run it (from `backend/`)

```bash
pip install -r requirements.txt
docker compose -f db/docker-compose.yml up -d            # PostgreSQL with schema + seed loaded
export DATABASE_URL=postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db

python scripts/seed_database.py                          # 120 active subscriptions, history, payments
python scripts/benchmark_queries.py                      # p95 per page query vs 2 s
python scripts/seed_database.py --subscriptions 5000 --customers 2500   # thousands scale
python scripts/seed_database.py --reset                  # remove ONLY seeded rows, then re-seed
```

## Tests

```bash
python -m unittest tests.test_calculations tests.test_seed_plan tests.test_pdf      # no database
TEST_DATABASE_URL=postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_test pytest -q
```

The test database is dropped and rebuilt from `db/*.sql` every session; never point it at real data.

## Nightly order

`run_billing(scope)` → `run_lifecycle(scope)` → `SELECT mark_overdue_invoices();`

Demo logins (password `Password@123`): `admin@brightloop.test`, `priya.nair@brightloop.test`,
`anjali.varma@nilatech.test`, and the seeded `custNNNN@seed.brightloop.test`.

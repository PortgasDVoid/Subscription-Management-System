# Brightloop Subscription Management — Developer 3 demo script

## Before the demo

1. Run `docker compose up --build -d` and wait for both services to become healthy.
2. Open `http://localhost:8000/docs` and run `GET /health`.
3. Confirm seeded volume: `SELECT count(*) FROM subscriptions WHERE status='active';` (expected >= 100).
4. Keep one subscription due on the demo date, then call `POST /api/billing/run?run_date=YYYY-MM-DD`.

## Demonstration flow (5–7 minutes)

1. **Variant price:** POST `/api/calculations/variant-price` with `{"base_price":1000,"extra_price":560}`. Expected unit price: 1560.00.
2. **Discount + tax:** POST `/api/calculations/line` with `{"unit_price":1000,"quantity":2,"tax_rate":18,"discount":100}`. Expected total: 2242.00.
3. **Discount eligibility:** POST `/api/calculations/discount` with a percentage or fixed discount and show a rejected expired / minimum-quantity example.
4. **Recurring billing:** call `/api/billing/run` for a date when one or more subscriptions are due. Show run ID, created/skipped counts and any errors.
5. **Invoice PDF:** select a created invoice ID and open `/api/invoices/{id}/pdf`.
6. **Dashboard:** GET `/api/dashboard/summary` to show active subscriptions, collected, outstanding and overdue totals.
7. **Performance:** GET `/api/performance/benchmark` and show measured query timings on this actual environment.

## Evidence to capture

- API `/docs` with successful calculation calls.
- Billing-run response and corresponding invoice rows.
- A downloaded PDF opened in a PDF viewer.
- SQL output proving at least 100 active subscriptions.
- Performance endpoint output with dataset size and timings.
- `pytest -q` output.

## Important

Do not demo a billing run against a date that has no due subscriptions and claim invoices were generated. Do not claim the two-second target is achieved until the performance endpoint has been run on the target deployment environment with representative load. The provided source archive had no frontend; this demo is API/Swagger based.

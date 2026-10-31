# DATABASE_MAPPING.md (v3, aligned to the real database)
**Project:** Subscription Management System, Brightloop Software
**Owner:** Developer 3 (pricing, discounts, tax, invoicing, PDF, seeding, QA)
**Source of truth:** `01_schema.sql` + `02_seed.sql` from the team (PostgreSQL 16, 29 tables, 3 views, triggers).

This replaces v1, which was based only on the ER diagram. The diagram showed a small subset of the real schema, so most of the "gaps" in v1 do not exist. **No existing table or column was changed.** v3 adds one read-only view (`db/03_subscription_stage_view.sql`).

## 1. Verification
The two SQL files were loaded into a clean PostgreSQL 16 and the README's checks reproduced exactly: invoice statuses cancelled 1 / confirmed 1 / overdue 3 / paid 26, and `SUM(mrr) = 21783.33`. All code and tests below run against that database.

## 2. v1 gaps vs the real schema

| v1 gap | Real schema |
|---|---|
| quantity on lines | `subscription_lines.quantity`, `quotation_lines.quantity`, `invoice_lines.quantity` (all `>= 1`) |
| variant on subscription line | `subscription_lines.variant_id` (also on quotation and invoice lines) |
| discount tables | `discounts`, `discount_products`, `discount_redemptions` exist |
| invoice number / dates / period | `invoice_number` (sequence default), `issue_date`, `due_date`, `billing_period_start/end` |
| invoice subtotal / discount / tax totals | `subtotal`, `discount_total`, `tax_total`, `total`, plus generated `amount_due` |
| tax amount snapshot | `invoice_lines.tax_id`, `tax_rate`, `tax_amount` |
| line detail for PDF | `invoice_lines.description`, `product_id`, `variant_id`, `unit_price`, `discount_amount` |
| duplicate guard | partial unique index `uq_invoice_period (subscription_id, billing_period_start) WHERE status <> 'cancelled'` |
| active flags | `is_active` on taxes, products, variants, plans, discounts, customers |
| payment date / note | `payments.transaction_date`, `payments.notes` (+ `payment_number`, `status`, `gateway_reference`) |
| subscription dates / terms | `start_date`, `expiry_date`, `payment_term_id`, `last_billed_through`, `auto_renew`, `closure_reason` |
| customer billing info | `customers.company_name`, `tax_id`, `billing_*`, `currency`, own `email` |

## 3. Tables used by Developer 3's modules

| Table | Columns that matter here |
|---|---|
| `plans` | `billing_period` (enum daily/weekly/monthly/yearly), `billing_interval` (every N periods; quarterly = monthly x 3), `min_quantity`, `auto_renew` |
| `payment_terms` | `due_days` (due_date = issue_date + due_days) |
| `products` / `product_variants` | `sales_price`, `extra_price`, `default_tax_id`, `is_active` |
| `taxes` | `rate_percent` (0..100 CHECK), `is_active` |
| `subscriptions` | `status` (draft/active/paused/closed), `next_billing_date`, `last_billed_through`, `start_date`, `expiry_date`; CHECK active => next_billing_date NOT NULL |
| `subscription_lines` | `quantity`, `unit_price` (locked at conversion), `variant_id`, `discount_id`, `tax_id`, `description` |
| `discounts` | `discount_type`, `value`, `min_purchase_amount`, `min_quantity`, `valid_from/until`, `usage_limit`, `per_customer_limit`, `auto_apply` |
| `discount_products` | optional product restriction |
| `discount_redemptions` | `UNIQUE (discount_id, invoice_id)`; usage is counted from here (there is no counter column) |
| `invoices` / `invoice_lines` | DB CHECKs: `total = subtotal - discount_total + tax_total`; `line_total = quantity*unit_price - discount_amount + tax_amount`; `0 <= amount_paid <= total` |
| `payments` / `payment_allocations` | triggers recompute `invoices.amount_paid` and status (paid / confirmed / overdue), block over-allocation and payments on draft/cancelled invoices |
| `billing_runs` | run log: counts, `errors` JSONB, status |

## 4. How each requirement is implemented

| Requirement | Where | How |
|---|---|---|
| Money math | `app/utils/calculations.py` | `Decimal` only (floats rejected), cents rounded half-up per line, header totals = sums of lines, so every DB CHECK passes |
| Pricing | `pricing_service.py` | base + variant extra; variant must belong to product; inactive/unknown rejected; plan `min_quantity`. Billing uses the locked `subscription_lines.unit_price` |
| Tax | `tax_service.py` | line `tax_id`, else product default, else 0%; inactive/unknown tax = configuration error; computed on amount **after** discount; rate and amount snapshotted on invoice lines |
| Discounts | `discount_service.py` | pinned (`subscription_lines.discount_id`) plus `auto_apply`; expiry, min purchase, min quantity, total and per-customer limits; fixed capped at eligible amount, split in whole cents; row-locked for concurrency; redemptions recorded |
| Invoicing | `invoice_service.py` | per-subscription transaction; locks the subscription row; checks status, due date, expiry, already billed; writes invoice, lines, redemptions; advances `next_billing_date` / `last_billed_through`; logs to `billing_runs` |
| Duplicate / concurrent safety | `invoice_service.py` + DB | `FOR UPDATE` (batch: `SKIP LOCKED`), state re-check after lock, then `uq_invoice_period` as backstop. Tested with 4 threads: exactly 1 invoice |
| Rollback | `invoice_service.py` | all writes inside a SAVEPOINT; tested by failing mid-invoice |

## 5. Decisions that need confirmation (my assumptions)

1. **Auto-apply discounts change existing demo invoices. DECISION (v3): keep ON.** `LOYAL5` is `auto_apply` (5%, product 1, qty >= 5). Subscription 1's CRM line (qty 5) has no pinned discount, so its Nov-2026 invoice gets 500.00 off (total 11,918.00 instead of the historical 12,508.00). The brief says a qualifying discount "should appear on the next invoice on its own", so this is the behaviour to demo. Seed history (Mar-Oct) shows no discount because it was loaded as plain history. `apply_auto_discounts=False` remains the switch. Tell the team before the demo so the 500.00 does not look like a bug.
2. **Pinned vs scope.** A discount pinned on a line applies to that line only (and only if its product is in `discount_products`, when such rows exist). Auto discounts apply to unpinned lines. A line holds one discount (the schema has one `discount_id` per line). Whole-subscription fixed discounts are split proportionally across lines.
3. **Locked prices.** Invoices use `subscription_lines.unit_price`, not today's catalog price. Catalog changes never alter existing subscriptions.
4. **Inactive product/variant/tax blocks billing** for that subscription (recorded as an error in `billing_runs`). `allow_inactive_products=True` overrides it for products.
5. **New invoices are created `confirmed`** (as in the seed), with `confirmed_at`. `auto_confirm=False` creates drafts. Zero-total invoices are created `paid` because payments cannot be allocated to them (`amount > 0`).
6. **Expired subscriptions: billing only skips them; closing/renewing is now `subscription_lifecycle_service.py` (v3).** If `next_billing_date > expiry_date` the billing run reports `expired`. The lifecycle job then renews (subscription and plan `auto_renew`, plan `term_periods` known) or closes (`closure_reason='expired'`), writing a `subscription_events` row. It never closes a subscription that still has unbilled periods, and never guesses a missing term. **Please confirm with Dev 2** that this job is ours; if Dev 2 already has one, delete ours. **Assumption to confirm:** `plans.term_periods` counts units of `billing_period` (4 for the weekly trial = 4 weeks).
7. **No proration.** A full period is billed; one period per call (run again to catch up several missed periods).
8. **Cancelled invoices free their redemptions** in limit counts (rows stay, they are just ignored).
9. **Overdue** flipping is the nightly `mark_overdue_invoices()` (Celery); not part of invoice generation.

## 6. Status of deliverables

| Item | Status |
|---|---|
| `calculations.py` | Done (32 unit tests) |
| Pricing, tax, discount, invoice services | Done, tested on the real schema |
| Tests: pricing, tax, discount, invoice | v2 reported **91 passed** (36 pure + 55 DB) against the original helper files. Not re-run after v3 (see below) |
| v3 pure tests (`test_calculations`, `test_payment_allocation`, `test_lifecycle_decision`) | **43 passed** (no database needed) |
| v3 in-memory engine tests (`test_invoice_engine_inmemory`) | **9 passed**: seed invoices 12,508.00 / 11,918.00 / 6,608.00, no double billing, per-run cache, failure isolation |
| v3 PostgreSQL tests (`test_payment_service`, `test_lifecycle_service`) | **Written, NOT RUN** (no database where they were written). Run them before relying on them |
| Payment service (`payment_service.py`) | Done in code, DB tests not yet run |
| Subscription lifecycle job (`subscription_lifecycle_service.py`) | Done in code, DB tests not yet run |
| Stage view `v_subscription_stage` | Written, not yet run |
| PDF service (`pdf_service.py`, ReportLab) + `test_pdf.py` | **Done (v4)**: 7 rendering tests pass; the one database test is NOT RUN |
| Seeding script (`scripts/seed_database.py`) | **Written (v4)**: 12 planning tests pass; the SQL has NOT been run on PostgreSQL yet |
| API routes (`invoice_routes.py`) | **Not started** (framework/auth dependency to confirm with the team; README suggests FastAPI + SQLAlchemy + Celery) |
| Performance measurement (`scripts/benchmark_queries.py`) | **Written (v4)**, not yet run. No timing is claimed until it is |

## 7. Running it

    # database (team files, unchanged copies are in db/)
    docker compose -f db/docker-compose.yml up -d   # now also loads 03_subscription_stage_view.sql

    # tests (the test database is DROPPED and rebuilt from db/*.sql each session)
    pip install pytest sqlalchemy psycopg2-binary
    TEST_DATABASE_URL=postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_test pytest -q

Nightly order (Celery): `run_billing(...)` -> `run_lifecycle(...)` -> `SELECT mark_overdue_invoices();`

Pure tests (no database, no Docker): `python -m pytest tests/test_calculations.py tests/test_payment_allocation.py tests/test_lifecycle_decision.py tests/test_invoice_engine_inmemory.py`

Billing from code: `run_billing(engine.begin, as_of=date.today())`; single subscription: `InvoiceService(conn).generate_for_subscription(id, as_of)` inside `with engine.begin() as conn`. Services take a SQLAlchemy `Connection` and never commit; swap `app/db.py` for the team's session module if there is one.

## 8. Notes for the remaining work
- **Seeding:** must respect `customers.user_id` UNIQUE, `users.email`/`products.sku`/`taxes.name` UNIQUE, and the triggers: insert invoices as `confirmed`, then create payments + allocations so the triggers produce `paid`, partial (`confirmed`/`overdue`) and `overdue`. Re-runs must be idempotent (fixed keys, `ON CONFLICT DO NOTHING`).
- **PDF:** every needed field is already stored on `invoices`, `invoice_lines`, `customers`; the PDF will read persisted values only.

## 9. v3 changes (this revision)

| # | Item | What changed | Files |
|---|---|---|---|
| 1 | Files missing from the upload | Rebuilt `calculations.py`, `errors.py`, `conftest.py`, `db.py` from how the code and tests call them. **They are stand-ins: if you have the originals, keep those** and run the suite | `app/utils/calculations.py`, `app/services/errors.py`, `app/db.py`, `tests/conftest.py` |
| 2 | Lifecycle stages in the brief (Draft / Quotation / Confirmed / Active / Closed) | Additive view combining `subscriptions.status` + `quotations.status`; no table changed | `db/03_subscription_stage_view.sql` |
| 3 | Expired subscriptions never closed/renewed | New nightly lifecycle service + tests | `subscription_lifecycle_service.py`, `lifecycle_repository.py` |
| 4 | Billing run re-read reference data per subscription | `ReferenceCache` shared across one run (plans, payment terms, taxes, auto-discount definitions). Live data (subscription lock, customer, redemption counts, discount locks) is still read per invoice | `invoice_service.py`, `tax_service.py`, `discount_service.py` |
| 5 | Over-payment gave raw database errors | `record_payment` validates first and raises coded errors; DB rules stay as backstop | `payment_service.py`, `payment_repository.py`, `errors.py` |
| 6 | Date-dependent demo checks | Date-independent checks | `db/04_quick_checks.sql` |
| 7 | Auto-discount decision | Recorded above (keep ON) | this file |

**Performance honesty:** the cache removes repeated reads but billing is still one transaction per subscription. Nothing has been timed. The "under 2 seconds" requirement is about pages; measure list/invoice/dashboard queries on the seeded 100+ subscriptions, and run billing in the background.

## 10. v4 changes (merge)

| # | Item | Files |
|---|---|---|
| 1 | Invoice PDF from persisted values (reads invoice, lines, customer, allocations) | `app/services/pdf_service.py`, `tests/test_pdf.py` |
| 2 | Idempotent seeder: real billing engine for history, payments + triggers for paid / part-paid / overdue | `scripts/seed_database.py`, `tests/test_seed_plan.py` |
| 3 | Query timing against the 2 s budget | `scripts/benchmark_queries.py` |
| 4 | Project glue: README, requirements, pytest config, file-flow diagram | `README.md`, `requirements.txt`, `pytest.ini`, `docs/FILE_FLOW.md` |

Still open: `api/invoice_routes.py` and `main.py` (framework and auth to agree with the team), end-to-end scenario
tests, demo script and slides.

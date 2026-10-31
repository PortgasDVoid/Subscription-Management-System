# Subscription Management System - database

PostgreSQL 15 or newer (Docker file uses 16). 29 tables, 3 reporting views, database-level
business-rule triggers, and demo data.

| File | Purpose |
|---|---|
| `01_schema.sql` | Full structure: enums, tables, constraints, indexes, triggers, views, reference rows (taxes, payment terms) |
| `02_seed.sql` | Demo data: 8 users, 6 customers, 5 products, 6 subscriptions, 31 invoices, 28 payments, 10 months of revenue snapshots |
| `docker-compose.yml` | One-command PostgreSQL that loads both files |

## Run it

**Docker (easiest)**

    docker compose up -d

**Existing PostgreSQL**

    createdb subscription_db
    psql -d subscription_db -f 01_schema.sql
    psql -d subscription_db -f 02_seed.sql

**Reset everything**

    docker compose down -v && docker compose up -d

Connection string: `postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db`

## Demo logins

Every seeded user has the password `Password@123` (bcrypt hash, so it works with passlib/bcrypt).

| Role | Email |
|---|---|
| Admin | admin@brightloop.test |
| Staff | priya.nair@brightloop.test, rohan.das@brightloop.test |
| Customer | anjali.varma@nilatech.test, suresh.kumar@keralidigital.test, meera.iyer@bluewave.test, vivek.pillai@greenfield.test, divya.menon@sahyadriretail.test |

## What the demo data covers

- Subscription states: 4 active, 1 paused, 1 closed (terminated early)
- Plans: monthly, quarterly (monthly x 3), yearly, weekly trial (unused)
- Invoices: paid, overdue, one part-paid, one cancelled duplicate
- Payments: succeeded, failed, pending, and one payment split across two invoices
- Discounts: a fixed discount and a percentage discount actually applied to invoices
- Quotations: converted, sent, draft, rejected, expired
- AI tables (`revenue_forecasts`, `model_metrics`, `anomaly_flags`) are empty on purpose

## Quick checks after loading

    -- Expect: cancelled 1, confirmed 1, overdue 3, paid 26
    -- (the part-paid invoice turns overdue once the date passes 31 Oct 2026)
    SELECT status, COUNT(*) FROM invoices GROUP BY status ORDER BY status;

    -- Expect 21783.33
    SELECT SUM(mrr) FROM v_subscription_mrr;

    SELECT * FROM v_overdue_invoices;

    -- Must FAIL with "duplicate key ... uq_invoice_period"
    BEGIN;
    INSERT INTO invoices (subscription_id, customer_id, billing_period_start, billing_period_end, due_date)
    VALUES (1, 1, '2026-10-01', '2026-10-31', '2026-10-16');
    ROLLBACK;

## Rules the database enforces by itself

- One live invoice per subscription per billing period (cancelled invoices are exempt)
- `total = subtotal - discount + tax` on quotations, invoices and every line
- An invoice can never be overpaid, and a payment can never be over-allocated
- Allocating a payment recalculates `amount_paid` and moves the invoice to `paid` / `confirmed` / `overdue`
- Payments cannot be allocated to draft or cancelled invoices
- Call `SELECT mark_overdue_invoices();` nightly (from Celery) to flip past-due invoices to `overdue`

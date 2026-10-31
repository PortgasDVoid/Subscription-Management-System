# Brightloop Subscription Management System

A local-first subscription operations app: PostgreSQL data model, FastAPI services, invoice PDF generation, billing runner, reporting endpoints, and a premium React/Vite admin frontend.

## Included

- Original `01_schema.sql` and `02_seed.sql` preserved from the supplied project archive.
- `03_scale_seed.sql` for a larger local demonstration dataset (review its generated record counts before applying).
- FastAPI API: health, dashboard summary, calculation utilities, billing run, invoice PDF, performance benchmark, and allow-listed CRUD resources.
- Decimal-based variant, tax and discount calculations; billing/invoice/PDF modules from the Developer 3 extension.
- Premium responsive React frontend with dashboard, navigation, searchable resource tables, create forms, CSV export, API health indicator, and billing-run action.
- Tests and demo/acceptance documentation.

## Quick start (Docker)

1. Install Docker Desktop and start it.
2. In this folder, copy `.env.example` to `.env` and change the local database password if desired. Keep the `DATABASE_URL` password in sync.
3. Run `docker compose up --build -d`.
4. Open the frontend at http://localhost:5173 (if using the dev server below) and API docs at http://localhost:8000/docs.

The compose file starts PostgreSQL and FastAPI. For the frontend, use the local dev server:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. The API base URL is `VITE_API_BASE_URL` and defaults to `http://localhost:8000`.

## Alternative: run API outside Docker

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start PostgreSQL with `docker compose up -d db` first.

## Database initialization

Postgres initialization scripts are mounted in lexical order and run only when the database volume is empty: schema, base seed, then scale seed. To reset a disposable local demo database and re-run them:

```bash
docker compose down -v
docker compose up --build -d
```

**Warning:** `down -v` deletes the local database volume and all records in it. Back up anything you need first. If you already have a populated volume, apply `03_scale_seed.sql` manually only after checking whether its rows have already been inserted.

## Main API routes

- `GET /health`
- `GET /api/dashboard/summary`
- `GET /api/resources/{customers|products|product_variants|plans|quotations|subscriptions|discounts|invoices|payments|users}`
- `POST /api/resources/{resource}`; `PATCH` and `DELETE /api/resources/{resource}/{id}`
- `POST /api/calculations/variant-price`
- `POST /api/calculations/line`
- `POST /api/calculations/discount`
- `POST /api/billing/run`
- `GET /api/invoices/{id}/pdf`
- `GET /api/performance/benchmark`

Swagger UI: http://localhost:8000/docs

## Important implementation notes / known limitations

- This is a local development and demonstration build, not a production deployment. Do not expose it publicly as-is.
- The generic resource API is allow-listed and validates column names, but full role-based authorization, login/session lifecycle, password reset email delivery, audit coverage, and customer self-service portal still require production hardening. Staff creation hashes the supplied password using scrypt; the frontend does not yet provide a login screen.
- Resource create forms are generic. Complex workflows such as quotation-to-subscription conversion, subscription line editing, payment allocation, and tax/discount application should use dedicated transactional endpoints before production use.
- Billing logic is designed to use the provided schema and its database constraints. Validate it against your actual PostgreSQL version and seed state before relying on scheduled billing. Billing is manually triggered in this build; no scheduler is enabled by default.
- Invoice PDF endpoint is present. Validate customer/company details and tax presentation against your institution's expected invoice format.
- Performance benchmark measures a few indexed queries on the local database. A sub-2-second result is environment-dependent and must be measured with the target dataset and hardware; it is not guaranteed by source code alone.
- Demo charts use illustrative monthly trend points. Live KPI cards use database summary data.

## QA

```bash
pytest -q
```

Run the tests with the dependencies in `requirements.txt`. For end-to-end QA, start the stack, create records, run billing, inspect generated invoices and download a PDF from the API docs. See `docs/acceptance_checklist.md` and `docs/demo_script.md`.

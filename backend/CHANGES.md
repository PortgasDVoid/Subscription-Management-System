# Changes

## v4 (merged project)
Everything from v3 plus:

- `app/services/pdf_service.py` + `tests/test_pdf.py`: invoice PDF (ReportLab)
- `scripts/seed_database.py` + `tests/test_seed_plan.py`: idempotent demo-scale seeding
- `scripts/benchmark_queries.py`: page-query timing vs the 2 s budget
- `README.md`, `requirements.txt`, `pytest.ini`, `.gitignore`, `docs/FILE_FLOW.md`

## Test status

| Status | What |
|---|---|
| VERIFIED (no database) | `test_calculations` (24), `test_seed_plan` (12), `test_pdf` rendering (7) |
| WRITTEN, needs SQLAlchemy / PostgreSQL to run | `test_payment_allocation`, `test_lifecycle_decision`, `test_invoice_engine_inmemory` (SQLAlchemy only); `test_invoice`, `test_payment_service`, `test_lifecycle_service`, the DB test in `test_pdf`, `db/03_*`, `db/04_*`, `seed_database.py`, `benchmark_queries.py` (PostgreSQL) |

Stand-ins for originals missing from the first upload: `app/utils/calculations.py`, `app/services/errors.py`,
`app/db.py`, `tests/conftest.py`. Keep your originals if you have them and check the names the services import.

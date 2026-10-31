# Developer 3 acceptance checklist

- [x] Decimal-based variant, line, discount, tax and invoice total calculations.
- [x] Discount checks for active dates, minimum spend/quantity, usage and per-customer limits in calculation service.
- [x] Billing-run implementation with per-subscription transaction savepoints, subscription row locking and unique period guard.
- [x] Invoice PDF rendering endpoint.
- [x] 120 additional active subscription seed records.
- [x] Unit and API tests for calculation and date edge cases.
- [x] Dashboard summary and performance measurement endpoints.
- [x] Demo script and acceptance evidence guide.
- [ ] Execute PostgreSQL schema + seed + scale seed in Docker / target PostgreSQL.
- [ ] Verify billing run against live PostgreSQL, including concurrent worker test.
- [ ] Verify PDF endpoint against a real seeded/generated invoice.
- [ ] Run performance benchmark against target hardware and thousands of records; retain actual timings.
- [ ] Add/verify frontend UI, auth and role-based access. No frontend or app source was included in the original upload.
- [ ] Configure protected scheduler, email delivery and any payment gateway credentials if required.

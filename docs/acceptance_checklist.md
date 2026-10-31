# Acceptance checklist

Legend: [x] implemented and unit-tested · [~] implemented, needs a live-Postgres run · [ ] not done

## Brief coverage
- [~] Signup (unique email, password >8 chars with upper/lower/special), login, lockout, reset-by-email link
- [~] Roles: admin / staff / customer; only admin creates staff; customers see only their own data
- [~] Products, variants (brand +560 style), plans (period, min qty, dates, auto-close / pause / early close / renew)
- [~] Quotation from template → approve → convert → confirmed subscription → activate → closed (status visible everywhere)
- [~] Billing run: invoices from subscriptions, auto tax, auto discounts, no duplicates, catch-up of missed periods
- [~] Invoice confirm / cancel / send (email log or SMTP) / print PDF
- [~] Payments by method with allocation to invoices; paid / outstanding / overdue visible
- [~] Finance dashboard + filtered reports (active subs, revenue, payments, overdue)
- [x] Decimal pricing, tax and discount rules (unit tests)
- [x] Anchored billing dates, discount planning, password policy, token handling (unit tests)

## Must still be proven on a real database (do these before the demo)
- [ ] `docker compose up` loads schema + both seeds without errors
- [ ] Log in as admin, staff and customer; confirm a customer cannot read another customer's invoice (expect 404)
- [ ] Walk the chain: quote from template → approve → convert → add line → activate → billing run → pay → status paid
- [ ] Run billing twice for the same date: second run creates 0 invoices
- [ ] Two simultaneous billing runs create no duplicates
- [ ] Load `optional/load_test_seed.sql`, run `/api/performance/benchmark`, keep timings + dataset counts
- [ ] `npm install && npm run build` succeeds in `frontend/`
- [ ] Production items: real SMTP, `DEV_RETURN_RESET_TOKEN=0`, strong `JWT_SECRET`, HTTPS, payment gateway if wanted

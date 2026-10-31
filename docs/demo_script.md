# Demo script (7 minutes)

1. **Sign up** a new customer in the UI (show the password rules and the duplicate-email error), then sign out.
2. **Admin**: sign in as `admin@brightloop.test`; add a product + a brand variant (+560) and a plan; create a discount rule.
3. **Staff**: Quotations -> "Quote from template" -> Send -> Approve -> Convert. Subscriptions -> Add line -> Activate. Status chips show where it stands.
4. **Billing day**: Subscriptions -> Run billing with a date on/after the next billing date. Show created / skipped / errors. Run it again: 0 created.
5. **Invoices**: open the PDF, Send, then Pay (records a payment against the invoice; status flips to paid).
6. **Discount**: show the invoice line carrying the auto-applied discount and its use count increasing.
7. **Finance**: Dashboard (MRR, active, collected, owed, overdue) then Reports -> Invoices with "Overdue only".
8. **Customer portal**: sign in as the customer; show only their subscriptions, invoices and PDF.
9. **Performance**: `GET /api/performance/benchmark` after loading `optional/load_test_seed.sql`; quote the measured numbers and dataset size.

Do not claim a figure you have not measured, and do not demo billing for a date with nothing due.

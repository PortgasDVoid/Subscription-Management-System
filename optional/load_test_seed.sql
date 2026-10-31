-- OPTIONAL load-test data: ~2,000 customers, ~4,800 active subscriptions, ~9,600 invoices, ~7,000 payments.
-- Run AFTER 01/02/03 so the <2s requirement can be measured with thousands of subscriptions:
--   docker compose exec -T db psql -U sms_user -d subscription_db < optional/load_test_seed.sql
-- Safe to re-run (skips if already loaded). Every load subscription bills monthly on the 1st, so a billing run dated
-- 2026-11-01 or later creates ~4,800 invoices at once ("hundreds due on billing day").
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM customers WHERE email = 'load00001@loadtest.example') THEN
    RAISE NOTICE 'Load-test data already present - skipping';
    RETURN;
  END IF;

  INSERT INTO customers(name, company_name, email, billing_line1, billing_city, billing_state, billing_postal)
  SELECT 'Load Customer ' || g, 'Load Co ' || g, 'load' || lpad(g::text, 5, '0') || '@loadtest.example',
         '1 Test Street', 'Kochi', 'Kerala', '682001'
  FROM generate_series(1, 2000) g;

  INSERT INTO subscriptions(subscription_number, customer_id, plan_id, payment_term_id, status, start_date, next_billing_date,
                            last_billed_through, auto_renew, closure_reason, closed_at, created_by)
  SELECT 'SUB-LOAD-' || lpad(g::text, 5, '0'),
         (SELECT id FROM customers WHERE email = 'load' || lpad((((g - 1) % 2000) + 1)::text, 5, '0') || '@loadtest.example'),
         1, 2 + (g % 2),
         CASE WHEN g % 25 = 0 THEN 'closed'::subscription_status ELSE 'active'::subscription_status END,
         (DATE '2026-01-01' + ((g % 9) * INTERVAL '1 month'))::date,           -- always the 1st: anchored billing stays on day 1
         CASE WHEN g % 25 = 0 THEN NULL ELSE DATE '2026-11-01' END,
         DATE '2026-10-31', TRUE,
         CASE WHEN g % 25 = 0 THEN 'terminated_early'::closure_reason END,
         CASE WHEN g % 25 = 0 THEN now() END,
         1
  FROM generate_series(1, 5000) g;

  INSERT INTO subscription_lines(subscription_id, product_id, description, quantity, unit_price, tax_id)
  SELECT s.id, p.id, p.name, 1 + (s.n % 4), p.sales_price, p.default_tax_id
  FROM (SELECT id, substring(subscription_number from '[0-9]+$')::int AS n FROM subscriptions WHERE subscription_number LIKE 'SUB-LOAD-%') s
  JOIN products p ON p.id = 1 + (s.n % 5);

  -- September + October invoices for every active load subscription
  INSERT INTO invoices(subscription_id, customer_id, status, billing_period_start, billing_period_end, issue_date, due_date, currency,
                       subtotal, discount_total, tax_total, total, confirmed_at)
  SELECT s.id, s.customer_id, 'confirmed', m.ps, (m.ps + INTERVAL '1 month' - INTERVAL '1 day')::date, m.ps,
         m.ps + CASE WHEN s.payment_term_id = 2 THEN 15 ELSE 30 END, 'INR',
         l.amt, 0, ROUND(l.amt * 0.18, 2), l.amt + ROUND(l.amt * 0.18, 2), m.ps::timestamptz
  FROM subscriptions s
  JOIN (SELECT subscription_id, SUM(quantity * unit_price) AS amt FROM subscription_lines GROUP BY 1) l ON l.subscription_id = s.id
  CROSS JOIN (VALUES (DATE '2026-09-01'), (DATE '2026-10-01')) AS m(ps)
  WHERE s.subscription_number LIKE 'SUB-LOAD-%' AND s.status = 'active';

  INSERT INTO invoice_lines(invoice_id, subscription_line_id, product_id, description, quantity, unit_price, discount_amount, tax_id,
                            tax_rate, tax_amount, line_total)
  SELECT i.id, sl.id, sl.product_id, sl.description, sl.quantity, sl.unit_price, 0, sl.tax_id, 18,
         ROUND(sl.quantity * sl.unit_price * 0.18, 2), sl.quantity * sl.unit_price + ROUND(sl.quantity * sl.unit_price * 0.18, 2)
  FROM invoices i
  JOIN subscriptions s ON s.id = i.subscription_id AND s.subscription_number LIKE 'SUB-LOAD-%'
  JOIN subscription_lines sl ON sl.subscription_id = s.id;

  -- ~92% of September and ~55% of October invoices get paid in full; the allocation triggers flip them to 'paid'
  INSERT INTO payments(customer_id, amount, method, status, transaction_date, notes, recorded_by)
  SELECT i.customer_id, i.total, (ARRAY['cash','bank_transfer','card','upi','cheque','online_gateway'])[1 + (i.id % 6)]::payment_method,
         'succeeded', i.issue_date + 3 + (i.id % 5), 'LOADINV-' || i.id, 2
  FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id AND s.subscription_number LIKE 'SUB-LOAD-%'
  WHERE (i.billing_period_start = DATE '2026-09-01' AND i.id % 100 < 92) OR (i.billing_period_start = DATE '2026-10-01' AND i.id % 100 < 55);

  INSERT INTO payment_allocations(payment_id, invoice_id, amount)
  SELECT p.id, substring(p.notes from '[0-9]+$')::bigint, p.amount FROM payments p WHERE p.notes LIKE 'LOADINV-%';

  PERFORM mark_overdue_invoices();
  RAISE NOTICE 'Load-test data loaded';
END $$;
ANALYZE;
SELECT (SELECT count(*) FROM subscriptions) AS subscriptions, (SELECT count(*) FROM invoices) AS invoices, (SELECT count(*) FROM payments) AS payments;

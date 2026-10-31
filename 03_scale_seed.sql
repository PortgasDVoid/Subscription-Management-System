-- Adds 120 additional active subscriptions to the original demo dataset.
-- Safe to rerun: fixed subscription_number values are guarded by ON CONFLICT.
BEGIN;
WITH generated AS (
  INSERT INTO subscriptions(subscription_number,customer_id,plan_id,payment_term_id,status,start_date,
    expiry_date,next_billing_date,auto_renew,created_by)
  SELECT 'SUB-SCALE-' || lpad(g.n::text,4,'0'),
         ((g.n-1) % 6)+1,
         ((g.n-1) % 3)+1,
         3,'active',
         DATE '2026-01-01' + ((g.n-1) % 250),
         NULL,
         DATE '2026-11-01' + ((g.n-1) % 20),
         TRUE,1
  FROM generate_series(1,120) AS g(n)
  ON CONFLICT (subscription_number) DO NOTHING
  RETURNING id, subscription_number
)
INSERT INTO subscription_lines(subscription_id,product_id,variant_id,description,quantity,unit_price,tax_id)
SELECT s.id,
       ((substring(s.subscription_number from '[0-9]+$')::int - 1) % 5)+1,
       NULL,
       p.name,
       ((substring(s.subscription_number from '[0-9]+$')::int - 1) % 5)+1,
       p.sales_price,
       p.default_tax_id
FROM generated s
JOIN products p ON p.id=(((substring(s.subscription_number from '[0-9]+$')::int - 1) % 5)+1);
COMMIT;

-- Verification: should return at least 100 active subscriptions.
DO $$ DECLARE n integer; BEGIN
  SELECT count(*) INTO n FROM subscriptions WHERE status='active';
  IF n < 100 THEN RAISE EXCEPTION 'Expected >=100 active subscriptions, found %', n; END IF;
END $$;

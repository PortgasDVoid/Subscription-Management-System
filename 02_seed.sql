-- =====================================================================
--  SUBSCRIPTION MANAGEMENT SYSTEM  -  DEMO SEED DATA
--  Run AFTER 01_schema.sql.
--
--  Demo logins (all share one password):  Password@123
--     admin@brightloop.test        (admin)
--     priya.nair@brightloop.test   (staff)
--     rohan.das@brightloop.test    (staff)
--     anjali.varma@nilatech.test   (customer)   ... and 4 more customers
--
--  Notes
--    * Uses OVERRIDING SYSTEM VALUE so every id is predictable; identity
--      sequences are re-synced at the end of this file.
--    * Relies on the reference rows inserted by 01_schema.sql:
--      taxes (1 No Tax, 2 GST 5%, 3 GST 12%, 4 GST 18%) and
--      payment_terms (1 Immediate, 2 Net 15, 3 Net 30).
--    * Data is anchored to Oct 2026. Invoice statuses 'paid' / 'overdue'
--      are produced by the real triggers + mark_overdue_invoices().
--    * AI tables (forecasts, metrics, anomaly flags) are left empty on
--      purpose: the ML module fills them.
-- =====================================================================

BEGIN;


-- ------------------------------------------------------------------
-- users + customers
-- ------------------------------------------------------------------

INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, email_verified_at, created_by, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'admin@brightloop.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'admin', 'Aarav Menon', '+91 98470 00001', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30'),
  (2, 'priya.nair@brightloop.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'staff', 'Priya Nair', '+91 98470 00002', TRUE, '2026-01-02 09:00:00+05:30', 1, '2026-01-02 09:00:00+05:30'),
  (3, 'rohan.das@brightloop.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'staff', 'Rohan Das', '+91 98470 00003', TRUE, '2026-01-02 09:00:00+05:30', 1, '2026-01-02 09:00:00+05:30'),
  (4, 'anjali.varma@nilatech.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'customer', 'Anjali Varma', '+91 98950 10001', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30'),
  (5, 'suresh.kumar@keralidigital.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'customer', 'Suresh Kumar', '+91 98950 10002', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30'),
  (6, 'meera.iyer@bluewave.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'customer', 'Meera Iyer', '+91 98950 10003', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30'),
  (7, 'vivek.pillai@greenfield.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'customer', 'Vivek Pillai', '+91 98950 10004', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30'),
  (8, 'divya.menon@sahyadriretail.test', '$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm', 'customer', 'Divya Menon', '+91 98950 10005', TRUE, '2026-01-02 09:00:00+05:30', NULL, '2026-01-02 09:00:00+05:30');

INSERT INTO customers (id, user_id, name, company_name, email, phone, tax_id, billing_line1, billing_city, billing_state, billing_postal, billing_country, currency, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 4, 'Anjali Varma', 'Nila Technologies Pvt Ltd', 'anjali.varma@nilatech.test', '+91 98950 10001', '32AAACN1111A1Z5', '12 MG Road', 'Ernakulam', 'Kerala', '682011', 'IN', 'INR', '2026-01-05 09:00:00+05:30'),
  (2, 5, 'Suresh Kumar', 'Kerali Digital Solutions', 'suresh.kumar@keralidigital.test', '+91 98950 10002', '32AAACK2222B1Z3', '45 Marine Drive', 'Kochi', 'Kerala', '682031', 'IN', 'INR', '2026-01-05 09:00:00+05:30'),
  (3, 6, 'Meera Iyer', 'BlueWave Studios', 'meera.iyer@bluewave.test', '+91 98950 10003', '29AAACB3333C1Z1', '7 Brigade Road', 'Bengaluru', 'Karnataka', '560001', 'IN', 'INR', '2026-01-05 09:00:00+05:30'),
  (4, 7, 'Vivek Pillai', 'Greenfield Analytics LLP', 'vivek.pillai@greenfield.test', '+91 98950 10004', '33AAACG4444D1Z9', '88 Anna Salai', 'Chennai', 'Tamil Nadu', '600002', 'IN', 'INR', '2026-01-05 09:00:00+05:30'),
  (5, 8, 'Divya Menon', 'Sahyadri Retail Pvt Ltd', 'divya.menon@sahyadriretail.test', '+91 98950 10005', '27AAACS5555E1Z7', '21 FC Road', 'Pune', 'Maharashtra', '411004', 'IN', 'INR', '2026-01-05 09:00:00+05:30'),
  (6, NULL, 'Joseph Mathew', 'Malabar Logistics', 'accounts@malabarlogistics.test', '+91 98950 10006', '32AAACM6666F1Z2', '3 Beach Road', 'Kozhikode', 'Kerala', '673032', 'IN', 'INR', '2026-01-05 09:00:00+05:30');


-- ------------------------------------------------------------------
-- catalog: products, variants, plans, discounts
-- ------------------------------------------------------------------

INSERT INTO products (id, sku, name, description, product_type, sales_price, cost_price, default_tax_id) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'BL-CRM', 'Brightloop CRM', 'Customer relationship management suite', 'service', 1500.00, 400.00, 4),
  (2, 'BL-HELPDESK', 'Brightloop Helpdesk', 'Ticketing and customer support desk', 'service', 1200.00, 350.00, 4),
  (3, 'BL-ANALYTICS', 'Brightloop Analytics', 'Business intelligence dashboards', 'service', 2500.00, 800.00, 4),
  (4, 'BL-STORAGE', 'Extra storage (100 GB)', 'Additional cloud storage block', 'addon', 300.00, 100.00, 4),
  (5, 'BL-SUPPORT', 'Priority support', '24x7 priority support add-on', 'addon', 800.00, 300.00, 4);

INSERT INTO product_variants (id, product_id, attribute, value, extra_price) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 'Tier', 'Starter', 0.00),
  (2, 1, 'Tier', 'Pro', 500.00),
  (3, 1, 'Tier', 'Enterprise', 1500.00),
  (4, 2, 'Tier', 'Standard', 0.00),
  (5, 2, 'Tier', 'Pro', 400.00),
  (6, 3, 'Tier', 'Standard', 0.00),
  (7, 3, 'Tier', 'Premium', 1000.00);

INSERT INTO plans (id, name, description, billing_period, billing_interval, term_periods, min_quantity, available_from, available_to, auto_renew, pause_allowed, early_termination_allowed) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'Monthly Standard', 'Billed every month', 'monthly', 1, NULL, 1, '2026-01-01', NULL, TRUE, TRUE, TRUE),
  (2, 'Quarterly Saver', 'Billed every 3 months', 'monthly', 3, NULL, 1, '2026-01-01', NULL, TRUE, TRUE, TRUE),
  (3, 'Yearly Annual', 'Billed once a year', 'yearly', 1, 1, 1, '2026-01-01', NULL, TRUE, TRUE, TRUE),
  (4, 'Weekly Trial', '4-week weekly trial', 'weekly', 1, 4, 1, '2026-01-01', '2026-12-31', FALSE, FALSE, TRUE);

INSERT INTO discounts (id, code, name, discount_type, value, min_purchase_amount, min_quantity, valid_from, valid_until, usage_limit, per_customer_limit, auto_apply) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'WELCOME10', 'Welcome 10% off', 'percentage', 10.00, 1000.00, 0, '2026-01-01', '2026-12-31', 100, 1, FALSE),
  (2, 'ANNUAL500', 'Annual plan Rs 500 off', 'fixed', 500.00, 5000.00, 0, '2026-01-01', '2026-12-31', 50, 1, TRUE),
  (3, 'LOYAL5', 'Loyalty 5% off (5+ seats)', 'percentage', 5.00, 0.00, 5, '2026-01-01', '2026-12-31', NULL, NULL, TRUE);

INSERT INTO discount_products (discount_id, product_id)
VALUES
  (2, 3),
  (3, 1);


-- ------------------------------------------------------------------
-- quotation templates
-- ------------------------------------------------------------------

INSERT INTO quotation_templates (id, name, validity_days, plan_id, payment_term_id, terms_text) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'Standard monthly SaaS', 30, 1, 2, 'Billed monthly. Cancel anytime with 30 days notice.'),
  (2, 'Annual bundle', 30, 3, 2, 'Billed annually in advance. Renews automatically.');

INSERT INTO quotation_template_lines (id, template_id, product_id, variant_id, quantity) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 1, 1, 1),
  (2, 1, 4, NULL, 1),
  (3, 2, 3, 7, 1);


-- ------------------------------------------------------------------
-- quotations + lines
-- ------------------------------------------------------------------

INSERT INTO quotations (id, quotation_number, customer_id, template_id, plan_id, payment_term_id, status, issue_date, valid_until, subtotal, discount_total, tax_total, total, notes, created_by, approved_at, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'QUO-2026-00001', 1, 1, 1, 2, 'converted', '2026-02-19', '2026-03-21', 10600.00, 0.00, 1908.00, 12508.00, NULL, 2, '2026-02-24 11:00:00+05:30', '2026-02-19 09:00:00+05:30'),
  (2, 'QUO-2026-00002', 2, 1, 1, 3, 'converted', '2026-04-21', '2026-05-21', 5600.00, 0.00, 1008.00, 6608.00, NULL, 2, '2026-04-26 11:00:00+05:30', '2026-04-21 09:00:00+05:30'),
  (3, 'QUO-2026-00003', 3, 2, 3, 2, 'converted', '2026-01-22', '2026-02-21', 7000.00, 500.00, 1170.00, 7670.00, NULL, 2, '2026-01-27 11:00:00+05:30', '2026-01-22 09:00:00+05:30'),
  (4, 'QUO-2026-00004', 4, NULL, 2, 2, 'converted', '2025-12-22', '2026-01-21', 15000.00, 750.00, 2565.00, 16815.00, NULL, 2, '2025-12-27 11:00:00+05:30', '2025-12-22 09:00:00+05:30'),
  (5, 'QUO-2026-00005', 5, 1, 1, 3, 'converted', '2026-05-22', '2026-06-21', 7000.00, 0.00, 1260.00, 8260.00, NULL, 2, '2026-05-27 11:00:00+05:30', '2026-05-22 09:00:00+05:30'),
  (6, 'QUO-2026-00006', 6, 1, 1, 2, 'converted', '2025-12-22', '2026-01-21', 4800.00, 0.00, 864.00, 5664.00, NULL, 2, '2025-12-27 11:00:00+05:30', '2025-12-22 09:00:00+05:30'),
  (7, 'QUO-2026-00007', 2, NULL, 1, 3, 'sent', '2026-10-20', '2026-11-19', 5000.00, 0.00, 900.00, 5900.00, 'Add analytics to existing helpdesk setup', 2, NULL, '2026-10-20 09:00:00+05:30'),
  (8, 'QUO-2026-00008', 4, 1, 1, 2, 'draft', '2026-10-28', '2026-11-27', 8000.00, 0.00, 1440.00, 9440.00, NULL, 3, NULL, '2026-10-28 09:00:00+05:30'),
  (9, 'QUO-2026-00009', 3, NULL, 1, 2, 'rejected', '2026-09-01', '2026-10-01', 3000.00, 0.00, 540.00, 3540.00, 'Customer declined extra storage', 3, NULL, '2026-09-01 09:00:00+05:30'),
  (10, 'QUO-2026-00010', 6, 2, 3, 2, 'expired', '2026-09-01', '2026-09-30', 6000.00, 0.00, 1080.00, 7080.00, 'No response before validity ended', 2, NULL, '2026-09-01 09:00:00+05:30');

INSERT INTO quotation_lines (id, quotation_id, product_id, variant_id, description, quantity, unit_price, discount_id, discount_amount, tax_id, tax_rate, tax_amount, line_total) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (2, 1, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (3, 2, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (4, 2, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (5, 3, 3, 7, 'Brightloop Analytics - Premium', 2, 3500.00, 2, 500, 4, 18, 1170.00, 7670.00),
  (6, 4, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 750.00, 4, 18, 2565.00, 16815.00),
  (7, 5, 3, 6, 'Brightloop Analytics - Standard', 1, 2500.00, NULL, 0.00, 4, 18, 450.00, 2950.00),
  (8, 5, 1, 1, 'Brightloop CRM - Starter', 3, 1500.00, NULL, 0.00, 4, 18, 810.00, 5310.00),
  (9, 6, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (10, 7, 3, 6, 'Brightloop Analytics - Standard', 2, 2500.00, NULL, 0.00, 4, 18, 900.00, 5900.00),
  (11, 8, 2, 5, 'Brightloop Helpdesk - Pro', 5, 1600.00, NULL, 0.00, 4, 18, 1440.00, 9440.00),
  (12, 9, 4, NULL, 'Extra storage (100 GB)', 10, 300.00, NULL, 0.00, 4, 18, 540.00, 3540.00),
  (13, 10, 1, 3, 'Brightloop CRM - Enterprise', 2, 3000.00, NULL, 0.00, 4, 18, 1080.00, 7080.00);


-- ------------------------------------------------------------------
-- subscriptions + lines + lifecycle events
-- ------------------------------------------------------------------

INSERT INTO subscriptions (id, subscription_number, customer_id, quotation_id, plan_id, payment_term_id, status, start_date, expiry_date, next_billing_date, last_billed_through, auto_renew, renewal_count, paused_at, closed_at, closure_reason, closure_note, created_by, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'SUB-2026-000001', 1, 1, 1, 2, 'active', '2026-03-01', NULL, '2026-11-01', '2026-10-31', TRUE, 0, NULL, NULL, NULL, NULL, 2, '2026-02-24 11:00:00+05:30'),
  (2, 'SUB-2026-000002', 2, 2, 1, 3, 'active', '2026-05-01', NULL, '2026-11-01', '2026-10-31', TRUE, 0, NULL, NULL, NULL, NULL, 2, '2026-04-26 11:00:00+05:30'),
  (3, 'SUB-2026-000003', 3, 3, 3, 2, 'active', '2026-02-01', '2027-01-31', '2027-02-01', '2027-01-31', TRUE, 0, NULL, NULL, NULL, NULL, 2, '2026-01-27 11:00:00+05:30'),
  (4, 'SUB-2026-000004', 4, 4, 2, 2, 'active', '2026-01-01', NULL, '2027-01-01', '2026-12-31', TRUE, 0, NULL, NULL, NULL, NULL, 2, '2025-12-27 11:00:00+05:30'),
  (5, 'SUB-2026-000005', 5, 5, 1, 3, 'paused', '2026-06-01', NULL, '2026-09-01', '2026-08-31', TRUE, 0, '2026-09-15 10:00:00+05:30', NULL, NULL, NULL, 2, '2026-05-27 11:00:00+05:30'),
  (6, 'SUB-2026-000006', 6, 6, 1, 2, 'closed', '2026-01-01', NULL, NULL, '2026-08-31', TRUE, 0, NULL, '2026-08-20 16:00:00+05:30', 'terminated_early', 'Customer terminated early', 2, '2025-12-27 11:00:00+05:30');

INSERT INTO subscription_lines (id, subscription_id, product_id, variant_id, description, quantity, unit_price, discount_id, tax_id) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 4),
  (2, 1, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 4),
  (3, 2, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 4),
  (4, 2, 5, NULL, 'Priority support', 1, 800.00, NULL, 4),
  (5, 3, 3, 7, 'Brightloop Analytics - Premium', 2, 3500.00, 2, 4),
  (6, 4, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 4),
  (7, 5, 3, 6, 'Brightloop Analytics - Standard', 1, 2500.00, NULL, 4),
  (8, 5, 1, 1, 'Brightloop CRM - Starter', 3, 1500.00, NULL, 4),
  (9, 6, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 4);

INSERT INTO subscription_events (id, subscription_id, from_status, to_status, event_type, reason, actor_user_id, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-03-01 09:00:00+05:30'),
  (2, 2, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-05-01 09:00:00+05:30'),
  (3, 3, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-02-01 09:00:00+05:30'),
  (4, 4, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-01-01 09:00:00+05:30'),
  (5, 5, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-06-01 09:00:00+05:30'),
  (6, 5, 'active', 'paused', 'paused', 'Customer requested pause', 2, '2026-09-15 10:00:00+05:30'),
  (7, 6, 'draft', 'active', 'activated', 'Subscription activated', 2, '2026-01-01 09:00:00+05:30'),
  (8, 6, 'active', 'closed', 'closed', 'Customer terminated early', 2, '2026-08-20 16:00:00+05:30');


-- ------------------------------------------------------------------
-- billing runs (scheduler executions)
-- ------------------------------------------------------------------

INSERT INTO billing_runs (id, run_date, status, subscriptions_checked, invoices_created, invoices_skipped, error_count, started_at, finished_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, '2026-01-01', 'completed', 2, 2, 0, 0, '2026-01-01 02:00:00+05:30', '2026-01-01 02:03:00+05:30'),
  (2, '2026-02-01', 'completed', 3, 2, 1, 0, '2026-02-01 02:00:00+05:30', '2026-02-01 02:03:00+05:30'),
  (3, '2026-03-01', 'completed', 4, 2, 2, 0, '2026-03-01 02:00:00+05:30', '2026-03-01 02:03:00+05:30'),
  (4, '2026-04-01', 'completed', 4, 3, 1, 0, '2026-04-01 02:00:00+05:30', '2026-04-01 02:03:00+05:30'),
  (5, '2026-05-01', 'completed', 5, 3, 2, 0, '2026-05-01 02:00:00+05:30', '2026-05-01 02:03:00+05:30'),
  (6, '2026-06-01', 'completed', 6, 4, 2, 0, '2026-06-01 02:00:00+05:30', '2026-06-01 02:03:00+05:30'),
  (7, '2026-07-01', 'completed', 6, 5, 1, 0, '2026-07-01 02:00:00+05:30', '2026-07-01 02:03:00+05:30'),
  (8, '2026-08-01', 'completed', 6, 4, 2, 0, '2026-08-01 02:00:00+05:30', '2026-08-01 02:03:00+05:30'),
  (9, '2026-09-01', 'completed', 5, 2, 3, 0, '2026-09-01 02:00:00+05:30', '2026-09-01 02:03:00+05:30'),
  (10, '2026-10-01', 'completed', 4, 3, 1, 0, '2026-10-01 02:00:00+05:30', '2026-10-01 02:03:00+05:30');


-- ------------------------------------------------------------------
-- invoices + lines (all start as confirmed; triggers move them to paid/overdue)
-- ------------------------------------------------------------------

INSERT INTO invoices (id, invoice_number, subscription_id, customer_id, billing_run_id, status, billing_period_start, billing_period_end, issue_date, due_date, currency, subtotal, discount_total, tax_total, total, sent_at, confirmed_at, cancelled_at, cancel_reason, created_by, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'INV-2026-000001', 4, 4, 1, 'confirmed', '2026-01-01', '2026-03-31', '2026-01-01', '2026-01-16', 'INR', 15000.00, 750.00, 2565.00, 16815.00, '2026-01-01 09:05:00+05:30', '2026-01-01 09:00:00+05:30', NULL, NULL, NULL, '2026-01-01 02:03:00+05:30'),
  (2, 'INV-2026-000002', 6, 6, 1, 'confirmed', '2026-01-01', '2026-01-31', '2026-01-01', '2026-01-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-01-01 09:05:00+05:30', '2026-01-01 09:00:00+05:30', NULL, NULL, NULL, '2026-01-01 02:03:00+05:30'),
  (3, 'INV-2026-000003', 3, 3, 2, 'confirmed', '2026-02-01', '2027-01-31', '2026-02-01', '2026-02-16', 'INR', 7000.00, 500.00, 1170.00, 7670.00, '2026-02-01 09:05:00+05:30', '2026-02-01 09:00:00+05:30', NULL, NULL, NULL, '2026-02-01 02:03:00+05:30'),
  (4, 'INV-2026-000004', 6, 6, 2, 'confirmed', '2026-02-01', '2026-02-28', '2026-02-01', '2026-02-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-02-01 09:05:00+05:30', '2026-02-01 09:00:00+05:30', NULL, NULL, NULL, '2026-02-01 02:03:00+05:30'),
  (5, 'INV-2026-000005', 1, 1, 3, 'confirmed', '2026-03-01', '2026-03-31', '2026-03-01', '2026-03-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-03-01 09:05:00+05:30', '2026-03-01 09:00:00+05:30', NULL, NULL, NULL, '2026-03-01 02:03:00+05:30'),
  (6, 'INV-2026-000006', 6, 6, 3, 'confirmed', '2026-03-01', '2026-03-31', '2026-03-01', '2026-03-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-03-01 09:05:00+05:30', '2026-03-01 09:00:00+05:30', NULL, NULL, NULL, '2026-03-01 02:03:00+05:30'),
  (7, 'INV-2026-000007', 1, 1, 4, 'confirmed', '2026-04-01', '2026-04-30', '2026-04-01', '2026-04-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-04-01 09:05:00+05:30', '2026-04-01 09:00:00+05:30', NULL, NULL, NULL, '2026-04-01 02:03:00+05:30'),
  (8, 'INV-2026-000008', 4, 4, 4, 'confirmed', '2026-04-01', '2026-06-30', '2026-04-01', '2026-04-16', 'INR', 15000.00, 750.00, 2565.00, 16815.00, '2026-04-01 09:05:00+05:30', '2026-04-01 09:00:00+05:30', NULL, NULL, NULL, '2026-04-01 02:03:00+05:30'),
  (9, 'INV-2026-000009', 6, 6, 4, 'confirmed', '2026-04-01', '2026-04-30', '2026-04-01', '2026-04-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-04-01 09:05:00+05:30', '2026-04-01 09:00:00+05:30', NULL, NULL, NULL, '2026-04-01 02:03:00+05:30'),
  (10, 'INV-2026-000010', 1, 1, 5, 'confirmed', '2026-05-01', '2026-05-31', '2026-05-01', '2026-05-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-05-01 09:05:00+05:30', '2026-05-01 09:00:00+05:30', NULL, NULL, NULL, '2026-05-01 02:03:00+05:30'),
  (11, 'INV-2026-000011', 2, 2, NULL, 'cancelled', '2026-05-01', '2026-05-31', '2026-05-01', '2026-05-31', 'INR', 5600.00, 0.00, 1008.00, 6608.00, NULL, NULL, '2026-05-01 09:20:00+05:30', 'Duplicate created by a manual run - cancelled', 2, '2026-05-01 09:00:00+05:30'),
  (12, 'INV-2026-000012', 2, 2, 5, 'confirmed', '2026-05-01', '2026-05-31', '2026-05-01', '2026-05-31', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-05-01 09:05:00+05:30', '2026-05-01 09:00:00+05:30', NULL, NULL, NULL, '2026-05-01 02:03:00+05:30'),
  (13, 'INV-2026-000013', 6, 6, 5, 'confirmed', '2026-05-01', '2026-05-31', '2026-05-01', '2026-05-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-05-01 09:05:00+05:30', '2026-05-01 09:00:00+05:30', NULL, NULL, NULL, '2026-05-01 02:03:00+05:30'),
  (14, 'INV-2026-000014', 1, 1, 6, 'confirmed', '2026-06-01', '2026-06-30', '2026-06-01', '2026-06-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-06-01 09:05:00+05:30', '2026-06-01 09:00:00+05:30', NULL, NULL, NULL, '2026-06-01 02:03:00+05:30'),
  (15, 'INV-2026-000015', 2, 2, 6, 'confirmed', '2026-06-01', '2026-06-30', '2026-06-01', '2026-07-01', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-06-01 09:05:00+05:30', '2026-06-01 09:00:00+05:30', NULL, NULL, NULL, '2026-06-01 02:03:00+05:30'),
  (16, 'INV-2026-000016', 5, 5, 6, 'confirmed', '2026-06-01', '2026-06-30', '2026-06-01', '2026-07-01', 'INR', 7000.00, 0.00, 1260.00, 8260.00, '2026-06-01 09:05:00+05:30', '2026-06-01 09:00:00+05:30', NULL, NULL, NULL, '2026-06-01 02:03:00+05:30'),
  (17, 'INV-2026-000017', 6, 6, 6, 'confirmed', '2026-06-01', '2026-06-30', '2026-06-01', '2026-06-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-06-01 09:05:00+05:30', '2026-06-01 09:00:00+05:30', NULL, NULL, NULL, '2026-06-01 02:03:00+05:30'),
  (18, 'INV-2026-000018', 1, 1, 7, 'confirmed', '2026-07-01', '2026-07-31', '2026-07-01', '2026-07-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-07-01 09:05:00+05:30', '2026-07-01 09:00:00+05:30', NULL, NULL, NULL, '2026-07-01 02:03:00+05:30'),
  (19, 'INV-2026-000019', 2, 2, 7, 'confirmed', '2026-07-01', '2026-07-31', '2026-07-01', '2026-07-31', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-07-01 09:05:00+05:30', '2026-07-01 09:00:00+05:30', NULL, NULL, NULL, '2026-07-01 02:03:00+05:30'),
  (20, 'INV-2026-000020', 4, 4, 7, 'confirmed', '2026-07-01', '2026-09-30', '2026-07-01', '2026-07-16', 'INR', 15000.00, 750.00, 2565.00, 16815.00, '2026-07-01 09:05:00+05:30', '2026-07-01 09:00:00+05:30', NULL, NULL, NULL, '2026-07-01 02:03:00+05:30'),
  (21, 'INV-2026-000021', 5, 5, 7, 'confirmed', '2026-07-01', '2026-07-31', '2026-07-01', '2026-07-31', 'INR', 7000.00, 0.00, 1260.00, 8260.00, '2026-07-01 09:05:00+05:30', '2026-07-01 09:00:00+05:30', NULL, NULL, NULL, '2026-07-01 02:03:00+05:30'),
  (22, 'INV-2026-000022', 6, 6, 7, 'confirmed', '2026-07-01', '2026-07-31', '2026-07-01', '2026-07-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-07-01 09:05:00+05:30', '2026-07-01 09:00:00+05:30', NULL, NULL, NULL, '2026-07-01 02:03:00+05:30'),
  (23, 'INV-2026-000023', 1, 1, 8, 'confirmed', '2026-08-01', '2026-08-31', '2026-08-01', '2026-08-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-08-01 09:05:00+05:30', '2026-08-01 09:00:00+05:30', NULL, NULL, NULL, '2026-08-01 02:03:00+05:30'),
  (24, 'INV-2026-000024', 2, 2, 8, 'confirmed', '2026-08-01', '2026-08-31', '2026-08-01', '2026-08-31', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-08-01 09:05:00+05:30', '2026-08-01 09:00:00+05:30', NULL, NULL, NULL, '2026-08-01 02:03:00+05:30'),
  (25, 'INV-2026-000025', 5, 5, 8, 'confirmed', '2026-08-01', '2026-08-31', '2026-08-01', '2026-08-31', 'INR', 7000.00, 0.00, 1260.00, 8260.00, '2026-08-01 09:05:00+05:30', '2026-08-01 09:00:00+05:30', NULL, NULL, NULL, '2026-08-01 02:03:00+05:30'),
  (26, 'INV-2026-000026', 6, 6, 8, 'confirmed', '2026-08-01', '2026-08-31', '2026-08-01', '2026-08-16', 'INR', 4800.00, 0.00, 864.00, 5664.00, '2026-08-01 09:05:00+05:30', '2026-08-01 09:00:00+05:30', NULL, NULL, NULL, '2026-08-01 02:03:00+05:30'),
  (27, 'INV-2026-000027', 1, 1, 9, 'confirmed', '2026-09-01', '2026-09-30', '2026-09-01', '2026-09-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-09-01 09:05:00+05:30', '2026-09-01 09:00:00+05:30', NULL, NULL, NULL, '2026-09-01 02:03:00+05:30'),
  (28, 'INV-2026-000028', 2, 2, 9, 'confirmed', '2026-09-01', '2026-09-30', '2026-09-01', '2026-10-01', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-09-01 09:05:00+05:30', '2026-09-01 09:00:00+05:30', NULL, NULL, NULL, '2026-09-01 02:03:00+05:30'),
  (29, 'INV-2026-000029', 1, 1, 10, 'confirmed', '2026-10-01', '2026-10-31', '2026-10-01', '2026-10-16', 'INR', 10600.00, 0.00, 1908.00, 12508.00, '2026-10-01 09:05:00+05:30', '2026-10-01 09:00:00+05:30', NULL, NULL, NULL, '2026-10-01 02:03:00+05:30'),
  (30, 'INV-2026-000030', 2, 2, 10, 'confirmed', '2026-10-01', '2026-10-31', '2026-10-01', '2026-10-31', 'INR', 5600.00, 0.00, 1008.00, 6608.00, '2026-10-01 09:05:00+05:30', '2026-10-01 09:00:00+05:30', NULL, NULL, NULL, '2026-10-01 02:03:00+05:30'),
  (31, 'INV-2026-000031', 4, 4, 10, 'confirmed', '2026-10-01', '2026-12-31', '2026-10-01', '2026-10-16', 'INR', 15000.00, 750.00, 2565.00, 16815.00, '2026-10-01 09:05:00+05:30', '2026-10-01 09:00:00+05:30', NULL, NULL, NULL, '2026-10-01 02:03:00+05:30');

INSERT INTO invoice_lines (id, invoice_id, subscription_line_id, product_id, variant_id, description, quantity, unit_price, discount_id, discount_amount, tax_id, tax_rate, tax_amount, line_total) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 6, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 750.00, 4, 18, 2565.00, 16815.00),
  (2, 2, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (3, 3, 5, 3, 7, 'Brightloop Analytics - Premium', 2, 3500.00, 2, 500, 4, 18, 1170.00, 7670.00),
  (4, 4, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (5, 5, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (6, 5, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (7, 6, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (8, 7, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (9, 7, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (10, 8, 6, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 750.00, 4, 18, 2565.00, 16815.00),
  (11, 9, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (12, 10, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (13, 10, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (14, 11, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (15, 11, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (16, 12, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (17, 12, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (18, 13, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (19, 14, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (20, 14, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (21, 15, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (22, 15, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (23, 16, 7, 3, 6, 'Brightloop Analytics - Standard', 1, 2500.00, NULL, 0.00, 4, 18, 450.00, 2950.00),
  (24, 16, 8, 1, 1, 'Brightloop CRM - Starter', 3, 1500.00, NULL, 0.00, 4, 18, 810.00, 5310.00),
  (25, 17, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (26, 18, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (27, 18, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (28, 19, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (29, 19, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (30, 20, 6, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 750.00, 4, 18, 2565.00, 16815.00),
  (31, 21, 7, 3, 6, 'Brightloop Analytics - Standard', 1, 2500.00, NULL, 0.00, 4, 18, 450.00, 2950.00),
  (32, 21, 8, 1, 1, 'Brightloop CRM - Starter', 3, 1500.00, NULL, 0.00, 4, 18, 810.00, 5310.00),
  (33, 22, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (34, 23, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (35, 23, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (36, 24, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (37, 24, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (38, 25, 7, 3, 6, 'Brightloop Analytics - Standard', 1, 2500.00, NULL, 0.00, 4, 18, 450.00, 2950.00),
  (39, 25, 8, 1, 1, 'Brightloop CRM - Starter', 3, 1500.00, NULL, 0.00, 4, 18, 810.00, 5310.00),
  (40, 26, 9, 2, 4, 'Brightloop Helpdesk - Standard', 4, 1200.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (41, 27, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (42, 27, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (43, 28, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (44, 28, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (45, 29, 1, 1, 2, 'Brightloop CRM - Pro', 5, 2000.00, NULL, 0.00, 4, 18, 1800.00, 11800.00),
  (46, 29, 2, 4, NULL, 'Extra storage (100 GB)', 2, 300.00, NULL, 0.00, 4, 18, 108.00, 708.00),
  (47, 30, 3, 2, 5, 'Brightloop Helpdesk - Pro', 3, 1600.00, NULL, 0.00, 4, 18, 864.00, 5664.00),
  (48, 30, 4, 5, NULL, 'Priority support', 1, 800.00, NULL, 0.00, 4, 18, 144.00, 944.00),
  (49, 31, 6, 1, 1, 'Brightloop CRM - Starter', 10, 1500.00, 3, 750.00, 4, 18, 2565.00, 16815.00);


-- ------------------------------------------------------------------
-- discount redemptions
-- ------------------------------------------------------------------

INSERT INTO discount_redemptions (id, discount_id, invoice_id, customer_id, amount, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 3, 1, 4, 750.00, '2026-01-01 02:03:00+05:30'),
  (2, 2, 3, 3, 500, '2026-02-01 02:03:00+05:30'),
  (3, 3, 8, 4, 750.00, '2026-04-01 02:03:00+05:30'),
  (4, 3, 20, 4, 750.00, '2026-07-01 02:03:00+05:30'),
  (5, 3, 31, 4, 750.00, '2026-10-01 02:03:00+05:30');


-- ------------------------------------------------------------------
-- payments, then allocations (allocation triggers update the invoices)
-- ------------------------------------------------------------------

INSERT INTO payments (id, payment_number, customer_id, amount, method, status, transaction_date, gateway_reference, notes, recorded_by, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 'PAY-2026-000001', 4, 16815.00, 'upi', 'succeeded', '2026-01-06', NULL, NULL, 2, '2026-01-06 11:00:00+05:30'),
  (2, 'PAY-2026-000002', 6, 5664.00, 'bank_transfer', 'succeeded', '2026-01-09', NULL, NULL, 2, '2026-01-09 11:00:00+05:30'),
  (3, 'PAY-2026-000003', 3, 7670.00, 'card', 'succeeded', '2026-02-05', 'pay_TEST000001', NULL, 2, '2026-02-05 11:00:00+05:30'),
  (4, 'PAY-2026-000004', 6, 5664.00, 'online_gateway', 'succeeded', '2026-02-08', 'pay_TEST000002', NULL, NULL, '2026-02-08 11:00:00+05:30'),
  (5, 'PAY-2026-000005', 1, 12508.00, 'upi', 'succeeded', '2026-03-04', NULL, NULL, 2, '2026-03-04 11:00:00+05:30'),
  (6, 'PAY-2026-000006', 6, 5664.00, 'bank_transfer', 'succeeded', '2026-03-07', NULL, NULL, 2, '2026-03-07 11:00:00+05:30'),
  (7, 'PAY-2026-000007', 1, 12508.00, 'card', 'succeeded', '2026-04-03', 'pay_TEST000003', NULL, 2, '2026-04-03 11:00:00+05:30'),
  (8, 'PAY-2026-000008', 4, 16815.00, 'online_gateway', 'succeeded', '2026-04-06', 'pay_TEST000004', NULL, NULL, '2026-04-06 11:00:00+05:30'),
  (9, 'PAY-2026-000009', 6, 5664.00, 'upi', 'succeeded', '2026-04-09', NULL, NULL, 2, '2026-04-09 11:00:00+05:30'),
  (10, 'PAY-2026-000010', 2, 6608.00, 'card', 'succeeded', '2026-05-04', 'pay_TEST000005', NULL, 2, '2026-05-04 11:00:00+05:30'),
  (11, 'PAY-2026-000011', 1, 12508.00, 'bank_transfer', 'succeeded', '2026-05-05', NULL, NULL, 2, '2026-05-05 11:00:00+05:30'),
  (12, 'PAY-2026-000012', 6, 5664.00, 'online_gateway', 'succeeded', '2026-05-07', 'pay_TEST000006', NULL, NULL, '2026-05-07 11:00:00+05:30'),
  (13, 'PAY-2026-000013', 1, 12508.00, 'upi', 'succeeded', '2026-06-03', NULL, NULL, 2, '2026-06-03 11:00:00+05:30'),
  (14, 'PAY-2026-000014', 6, 5664.00, 'online_gateway', 'succeeded', '2026-06-05', 'pay_TEST000007', NULL, NULL, '2026-06-05 11:00:00+05:30'),
  (15, 'PAY-2026-000015', 2, 6608.00, 'bank_transfer', 'succeeded', '2026-06-06', NULL, NULL, 2, '2026-06-06 11:00:00+05:30'),
  (16, 'PAY-2026-000016', 5, 8260.00, 'card', 'succeeded', '2026-06-09', 'pay_TEST000008', NULL, 2, '2026-06-09 11:00:00+05:30'),
  (17, 'PAY-2026-000017', 5, 8260.00, 'online_gateway', 'succeeded', '2026-07-03', 'pay_TEST000009', NULL, NULL, '2026-07-03 11:00:00+05:30'),
  (18, 'PAY-2026-000018', 2, 6608.00, 'bank_transfer', 'succeeded', '2026-07-04', NULL, NULL, 2, '2026-07-04 11:00:00+05:30'),
  (19, 'PAY-2026-000019', 4, 16815.00, 'card', 'succeeded', '2026-07-07', 'pay_TEST000010', NULL, 2, '2026-07-07 11:00:00+05:30'),
  (20, 'PAY-2026-000020', 1, 12508.00, 'upi', 'succeeded', '2026-07-08', NULL, NULL, 2, '2026-07-08 11:00:00+05:30'),
  (21, 'PAY-2026-000021', 2, 6608.00, 'bank_transfer', 'succeeded', '2026-08-05', NULL, NULL, 2, '2026-08-05 11:00:00+05:30'),
  (22, 'PAY-2026-000022', 1, 12508.00, 'upi', 'succeeded', '2026-08-09', NULL, NULL, 2, '2026-08-09 11:00:00+05:30'),
  (23, 'PAY-2026-000023', 6, 11328.00, 'bank_transfer', 'succeeded', '2026-08-10', NULL, 'Single transfer covering July and August invoices', 2, '2026-08-10 11:00:00+05:30'),
  (24, 'PAY-2026-000024', 2, 6608.00, 'online_gateway', 'succeeded', '2026-09-03', 'pay_TEST000011', NULL, NULL, '2026-09-03 11:00:00+05:30'),
  (25, 'PAY-2026-000025', 1, 12508.00, 'card', 'succeeded', '2026-09-07', 'pay_TEST000012', NULL, 2, '2026-09-07 11:00:00+05:30'),
  (26, 'PAY-2026-000026', 2, 6608.00, 'card', 'failed', '2026-10-05', 'pay_FAILED_TEST', 'Card declined by issuer', NULL, '2026-10-05 11:00:00+05:30'),
  (27, 'PAY-2026-000027', 2, 3304.00, 'bank_transfer', 'succeeded', '2026-10-12', NULL, 'Part payment - balance pending', 2, '2026-10-12 11:00:00+05:30'),
  (28, 'PAY-2026-000028', 1, 12508.00, 'bank_transfer', 'pending', '2026-10-30', NULL, 'Awaiting bank confirmation', 2, '2026-10-30 11:00:00+05:30');

INSERT INTO payment_allocations (id, payment_id, invoice_id, amount, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 1, 16815.00, '2026-01-06 11:05:00+05:30'),
  (2, 2, 2, 5664.00, '2026-01-09 11:05:00+05:30'),
  (3, 3, 3, 7670.00, '2026-02-05 11:05:00+05:30'),
  (4, 4, 4, 5664.00, '2026-02-08 11:05:00+05:30'),
  (5, 5, 5, 12508.00, '2026-03-04 11:05:00+05:30'),
  (6, 6, 6, 5664.00, '2026-03-07 11:05:00+05:30'),
  (7, 7, 7, 12508.00, '2026-04-03 11:05:00+05:30'),
  (8, 8, 8, 16815.00, '2026-04-06 11:05:00+05:30'),
  (9, 9, 9, 5664.00, '2026-04-09 11:05:00+05:30'),
  (10, 10, 12, 6608.00, '2026-05-04 11:05:00+05:30'),
  (11, 11, 10, 12508.00, '2026-05-05 11:05:00+05:30'),
  (12, 12, 13, 5664.00, '2026-05-07 11:05:00+05:30'),
  (13, 13, 14, 12508.00, '2026-06-03 11:05:00+05:30'),
  (14, 14, 17, 5664.00, '2026-06-05 11:05:00+05:30'),
  (15, 15, 15, 6608.00, '2026-06-06 11:05:00+05:30'),
  (16, 16, 16, 8260.00, '2026-06-09 11:05:00+05:30'),
  (17, 17, 21, 8260.00, '2026-07-03 11:05:00+05:30'),
  (18, 18, 19, 6608.00, '2026-07-04 11:05:00+05:30'),
  (19, 19, 20, 16815.00, '2026-07-07 11:05:00+05:30'),
  (20, 20, 18, 12508.00, '2026-07-08 11:05:00+05:30'),
  (21, 21, 24, 6608.00, '2026-08-05 11:05:00+05:30'),
  (22, 22, 23, 12508.00, '2026-08-09 11:05:00+05:30'),
  (23, 23, 22, 5664.00, '2026-08-10 11:05:00+05:30'),
  (24, 23, 26, 5664.00, '2026-08-10 11:05:00+05:30'),
  (25, 24, 28, 6608.00, '2026-09-03 11:05:00+05:30'),
  (26, 25, 27, 12508.00, '2026-09-07 11:05:00+05:30'),
  (27, 27, 30, 3304.00, '2026-10-12 11:05:00+05:30');


-- Historical paid_at = date of the last settling payment (trigger used now())
UPDATE invoices i
SET paid_at = (SELECT MAX(p.transaction_date) FROM payment_allocations pa
               JOIN payments p ON p.id = pa.payment_id
               WHERE pa.invoice_id = i.id) + TIME '10:30'
WHERE i.status = 'paid';

-- Flip unpaid, past-due invoices to overdue (same function the nightly job uses)
SELECT mark_overdue_invoices();


-- ------------------------------------------------------------------
-- audit + email logs
-- ------------------------------------------------------------------

INSERT INTO audit_logs (id, actor_user_id, action, entity_type, entity_id, old_values, new_values, created_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, 1, 'user.create', 'users', 2, NULL, '{"role": "staff", "email": "priya.nair@brightloop.test"}'::jsonb, '2026-01-02 10:00:00+05:30'),
  (2, 2, 'quotation.approve', 'quotations', 1, '{"status": "sent"}'::jsonb, '{"status": "approved"}'::jsonb, '2026-02-24 11:00:00+05:30'),
  (3, 2, 'subscription.activate', 'subscriptions', 1, '{"status": "draft"}'::jsonb, '{"status": "active"}'::jsonb, '2026-03-01 09:00:00+05:30'),
  (4, 2, 'invoice.cancel', 'invoices', 11, '{"status": "draft"}'::jsonb, '{"status": "cancelled"}'::jsonb, '2026-05-01 09:20:00+05:30'),
  (5, 2, 'subscription.pause', 'subscriptions', 5, '{"status": "active"}'::jsonb, '{"status": "paused"}'::jsonb, '2026-09-15 10:00:00+05:30'),
  (6, 2, 'subscription.close', 'subscriptions', 6, '{"status": "active"}'::jsonb, '{"status": "closed"}'::jsonb, '2026-08-20 16:00:00+05:30'),
  (7, NULL, 'billing_run.complete', 'billing_runs', 10, NULL, '{"invoices_created": 3}'::jsonb, '2026-10-01 02:03:00+05:30');

INSERT INTO email_logs (id, user_id, to_email, template, subject, status, error, related_type, related_id, created_at, sent_at) OVERRIDING SYSTEM VALUE
VALUES
  (1, NULL, 'anjali.varma@nilatech.test', 'invoice_sent', 'Invoice INV-2026-000029 from Brightloop', 'sent', NULL, 'invoice', 29, '2026-10-01 09:05:00+05:30', '2026-10-01 09:05:00+05:30'),
  (2, NULL, 'suresh.kumar@keralidigital.test', 'invoice_sent', 'Invoice INV-2026-000030 from Brightloop', 'sent', NULL, 'invoice', 30, '2026-10-01 09:05:00+05:30', '2026-10-01 09:05:00+05:30'),
  (3, NULL, 'vivek.pillai@greenfield.test', 'invoice_sent', 'Invoice INV-2026-000031 from Brightloop', 'sent', NULL, 'invoice', 31, '2026-10-01 09:05:00+05:30', '2026-10-01 09:05:00+05:30'),
  (4, NULL, 'meera.iyer@bluewave.test', 'invoice_sent', 'Invoice INV-2026-000003 from Brightloop', 'sent', NULL, 'invoice', 3, '2026-02-01 09:05:00+05:30', '2026-02-01 09:05:00+05:30'),
  (5, NULL, 'accounts@malabarlogistics.test', 'invoice_sent', 'Invoice INV-2026-000026 from Brightloop', 'failed', 'SMTP 550 mailbox unavailable', 'invoice', 26, '2026-08-01 09:05:00+05:30', NULL);


-- ------------------------------------------------------------------
-- monthly revenue snapshots (for dashboards + forecasting)
-- ------------------------------------------------------------------

INSERT INTO revenue_snapshots (snapshot_month, active_subscriptions, new_subscriptions, closed_subscriptions, mrr, billed_amount, collected_amount, outstanding_amount, overdue_amount)
VALUES
  ('2026-01-01', 2, 2, 0, 9800.00, 22479.00, 22479.00, 0.00, 0.00),
  ('2026-02-01', 3, 1, 0, 10383.33, 13334.00, 13334.00, 0.00, 0.00),
  ('2026-03-01', 4, 1, 0, 20983.33, 18172.00, 18172.00, 0.00, 0.00),
  ('2026-04-01', 4, 0, 0, 20983.33, 34987.00, 34987.00, 0.00, 0.00),
  ('2026-05-01', 5, 1, 0, 26583.33, 24780.00, 24780.00, 0.00, 0.00),
  ('2026-06-01', 6, 1, 0, 33583.33, 33040.00, 33040.00, 0.00, 0.00),
  ('2026-07-01', 6, 0, 0, 33583.33, 49855.00, 44191.00, 5664.00, 5664.00),
  ('2026-08-01', 5, 0, 1, 28783.33, 33040.00, 30444.00, 8260.00, 0.00),
  ('2026-09-01', 4, 0, 0, 21783.33, 19116.00, 19116.00, 8260.00, 8260.00),
  ('2026-10-01', 4, 0, 0, 21783.33, 35931.00, 3304.00, 40887.00, 37583.00);


-- ------------------------------------------------------------------
-- re-sync identity + number sequences
-- ------------------------------------------------------------------

SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users));
SELECT setval(pg_get_serial_sequence('customers', 'id'), (SELECT MAX(id) FROM customers));
SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT MAX(id) FROM products));
SELECT setval(pg_get_serial_sequence('product_variants', 'id'), (SELECT MAX(id) FROM product_variants));
SELECT setval(pg_get_serial_sequence('plans', 'id'), (SELECT MAX(id) FROM plans));
SELECT setval(pg_get_serial_sequence('discounts', 'id'), (SELECT MAX(id) FROM discounts));
SELECT setval(pg_get_serial_sequence('quotation_templates', 'id'), (SELECT MAX(id) FROM quotation_templates));
SELECT setval(pg_get_serial_sequence('quotation_template_lines', 'id'), (SELECT MAX(id) FROM quotation_template_lines));
SELECT setval(pg_get_serial_sequence('quotations', 'id'), (SELECT MAX(id) FROM quotations));
SELECT setval(pg_get_serial_sequence('quotation_lines', 'id'), (SELECT MAX(id) FROM quotation_lines));
SELECT setval(pg_get_serial_sequence('subscriptions', 'id'), (SELECT MAX(id) FROM subscriptions));
SELECT setval(pg_get_serial_sequence('subscription_lines', 'id'), (SELECT MAX(id) FROM subscription_lines));
SELECT setval(pg_get_serial_sequence('subscription_events', 'id'), (SELECT MAX(id) FROM subscription_events));
SELECT setval(pg_get_serial_sequence('billing_runs', 'id'), (SELECT MAX(id) FROM billing_runs));
SELECT setval(pg_get_serial_sequence('invoices', 'id'), (SELECT MAX(id) FROM invoices));
SELECT setval(pg_get_serial_sequence('invoice_lines', 'id'), (SELECT MAX(id) FROM invoice_lines));
SELECT setval(pg_get_serial_sequence('discount_redemptions', 'id'), (SELECT MAX(id) FROM discount_redemptions));
SELECT setval(pg_get_serial_sequence('payments', 'id'), (SELECT MAX(id) FROM payments));
SELECT setval(pg_get_serial_sequence('payment_allocations', 'id'), (SELECT MAX(id) FROM payment_allocations));
SELECT setval(pg_get_serial_sequence('audit_logs', 'id'), (SELECT MAX(id) FROM audit_logs));
SELECT setval(pg_get_serial_sequence('email_logs', 'id'), (SELECT MAX(id) FROM email_logs));
SELECT setval('seq_quotation_no', 10);
SELECT setval('seq_subscription_no', 6);
SELECT setval('seq_invoice_no', 31);
SELECT setval('seq_payment_no', 28);

COMMIT;

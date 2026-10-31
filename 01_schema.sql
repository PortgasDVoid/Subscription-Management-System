-- =====================================================================
--  SUBSCRIPTION MANAGEMENT SYSTEM  -  PostgreSQL 15+ schema
--  Brightloop Software hackathon project
--
--  Module ownership (matches the 4-person split):
--    [P1] Auth, users, audit, email
--    [P2] Catalog, taxes, discounts, quotations, subscriptions
--    [P3] Invoices, payments, billing runs
--    [P4] Analytics snapshots, AI/ML outputs, reporting views
--
--  Design rules:
--    * Money is NUMERIC(12,2). Never float.
--    * Prices, tax rates and descriptions are SNAPSHOTTED onto
--      subscription/invoice lines, so later catalog edits never
--      change history.
--    * Billing correctness is enforced by the DATABASE, not just
--      the app: duplicate-invoice guard, total = subtotal - discount
--      + tax check, payment over-allocation guard.
--    * AI tables are advisory only; nothing in billing reads them.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------------
-- 0. ENUM TYPES  (shared status values for the whole team)
-- ---------------------------------------------------------------------
CREATE TYPE user_role           AS ENUM ('admin', 'staff', 'customer');
CREATE TYPE billing_period      AS ENUM ('daily', 'weekly', 'monthly', 'yearly');
CREATE TYPE discount_type       AS ENUM ('fixed', 'percentage');
CREATE TYPE quotation_status    AS ENUM ('draft', 'sent', 'approved', 'rejected', 'expired', 'converted');
-- Lifecycle per the brief: Draft -> Quotation -> Confirmed -> Active -> Closed (+ paused while active)
CREATE TYPE subscription_status AS ENUM ('draft', 'quotation', 'confirmed', 'active', 'paused', 'closed');
CREATE TYPE closure_reason      AS ENUM ('expired', 'terminated_early', 'auto_closed', 'cancelled');
CREATE TYPE invoice_status      AS ENUM ('draft', 'confirmed', 'paid', 'overdue', 'cancelled');
CREATE TYPE payment_method      AS ENUM ('cash', 'bank_transfer', 'card', 'upi', 'cheque', 'online_gateway');
CREATE TYPE payment_status      AS ENUM ('pending', 'succeeded', 'failed', 'refunded');
CREATE TYPE billing_run_status  AS ENUM ('running', 'completed', 'completed_with_errors', 'failed');

-- ---------------------------------------------------------------------
-- 1. HUMAN-READABLE NUMBER SEQUENCES
-- ---------------------------------------------------------------------
CREATE SEQUENCE seq_quotation_no    START 1;
CREATE SEQUENCE seq_subscription_no START 1;
CREATE SEQUENCE seq_invoice_no      START 1;
CREATE SEQUENCE seq_payment_no      START 1;

-- ---------------------------------------------------------------------
-- 2. SHARED TRIGGER: keep updated_at fresh
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
--  [P1] AUTH, USERS, AUDIT, EMAIL
-- =====================================================================
CREATE TABLE users (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email             CITEXT       NOT NULL UNIQUE,          -- case-insensitive unique email
    password_hash     TEXT         NOT NULL,                 -- bcrypt / Argon2 only
    role              user_role    NOT NULL,
    full_name         TEXT         NOT NULL,
    phone             TEXT,
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    email_verified_at TIMESTAMPTZ,
    last_login_at     TIMESTAMPTZ,
    failed_logins     INT          NOT NULL DEFAULT 0,
    locked_until      TIMESTAMPTZ,
    created_by        BIGINT       REFERENCES users(id),     -- admin who created a staff account
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_role ON users(role);

-- Password reset and email verification tokens (store only the hash)
CREATE TABLE auth_tokens (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    purpose     TEXT        NOT NULL CHECK (purpose IN ('password_reset', 'email_verify')),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_auth_tokens_user ON auth_tokens(user_id, purpose);

-- Customer profile (1:1 with a users row whose role = 'customer')
CREATE TABLE customers (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    name           TEXT        NOT NULL,
    company_name   TEXT,
    email          CITEXT      NOT NULL,
    phone          TEXT,
    tax_id         TEXT,                                     -- GSTIN / VAT number
    billing_line1  TEXT,
    billing_line2  TEXT,
    billing_city   TEXT,
    billing_state  TEXT,
    billing_postal TEXT,
    billing_country TEXT       NOT NULL DEFAULT 'IN',
    currency       CHAR(3)     NOT NULL DEFAULT 'INR',
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_name  ON customers(lower(name));

CREATE TABLE audit_logs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    action        TEXT        NOT NULL,                      -- e.g. 'invoice.confirm', 'subscription.pause'
    entity_type   TEXT        NOT NULL,
    entity_id     BIGINT,
    old_values    JSONB,
    new_values    JSONB,
    ip_address    INET,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_actor  ON audit_logs(actor_user_id, created_at DESC);
CREATE INDEX idx_audit_time   ON audit_logs(created_at DESC);

CREATE TABLE email_logs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    to_email    CITEXT      NOT NULL,
    template    TEXT        NOT NULL,                        -- 'invoice_sent', 'password_reset', 'renewal_reminder'
    subject     TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed')),
    error       TEXT,
    related_type TEXT,
    related_id  BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ
);
CREATE INDEX idx_email_logs_status ON email_logs(status, created_at);

-- =====================================================================
--  [P2] CATALOG, TAX, DISCOUNTS, TERMS
-- =====================================================================
CREATE TABLE taxes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT          NOT NULL UNIQUE,             -- 'GST 18%'
    rate_percent  NUMERIC(5,2)  NOT NULL CHECK (rate_percent >= 0 AND rate_percent <= 100),
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE payment_terms (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,                 -- 'Net 15'
    due_days    INT         NOT NULL CHECK (due_days >= 0),  -- days from invoice date to due date
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku            TEXT          NOT NULL UNIQUE,
    name           TEXT          NOT NULL,
    description    TEXT,
    product_type   TEXT          NOT NULL DEFAULT 'service' CHECK (product_type IN ('service', 'goods', 'addon')),
    sales_price    NUMERIC(12,2) NOT NULL CHECK (sales_price >= 0),
    cost_price     NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    default_tax_id BIGINT        REFERENCES taxes(id),
    is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_active ON products(is_active);

CREATE TABLE product_variants (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id   BIGINT        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    attribute    TEXT          NOT NULL,                     -- 'Tier'
    value        TEXT          NOT NULL,                     -- 'Pro'
    extra_price  NUMERIC(12,2) NOT NULL DEFAULT 0,           -- added to product.sales_price
    sku_suffix   TEXT,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (product_id, attribute, value)
);

CREATE TABLE plans (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 TEXT           NOT NULL UNIQUE,
    description          TEXT,
    billing_period       billing_period NOT NULL,
    billing_interval     INT            NOT NULL DEFAULT 1 CHECK (billing_interval >= 1),  -- every N periods
    term_periods         INT            CHECK (term_periods IS NULL OR term_periods >= 1), -- contract length; NULL = open-ended
    min_quantity         INT            NOT NULL DEFAULT 1 CHECK (min_quantity >= 1),
    available_from       DATE,
    available_to         DATE,
    auto_renew           BOOLEAN        NOT NULL DEFAULT TRUE,
    pause_allowed        BOOLEAN        NOT NULL DEFAULT TRUE,
    early_termination_allowed BOOLEAN   NOT NULL DEFAULT TRUE,
    is_active            BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CHECK (available_to IS NULL OR available_from IS NULL OR available_to >= available_from)
);

CREATE TABLE discounts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                TEXT          NOT NULL UNIQUE,
    name                TEXT          NOT NULL,
    discount_type       discount_type NOT NULL,
    value               NUMERIC(12,2) NOT NULL CHECK (value > 0),
    min_purchase_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    min_quantity        INT           NOT NULL DEFAULT 0,
    valid_from          DATE,
    valid_until         DATE,
    usage_limit         INT           CHECK (usage_limit IS NULL OR usage_limit > 0),          -- total redemptions
    per_customer_limit  INT           CHECK (per_customer_limit IS NULL OR per_customer_limit > 0),
    auto_apply          BOOLEAN       NOT NULL DEFAULT TRUE,   -- applied automatically to eligible invoices
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (discount_type <> 'percentage' OR value <= 100),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

-- Optional restriction: if a discount has rows here it applies only to those products
CREATE TABLE discount_products (
    discount_id BIGINT NOT NULL REFERENCES discounts(id) ON DELETE CASCADE,
    product_id  BIGINT NOT NULL REFERENCES products(id)  ON DELETE CASCADE,
    PRIMARY KEY (discount_id, product_id)
);

-- =====================================================================
--  [P2] QUOTATIONS
-- =====================================================================
CREATE TABLE quotation_templates (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT        NOT NULL UNIQUE,
    validity_days    INT         NOT NULL DEFAULT 30 CHECK (validity_days > 0),
    plan_id          BIGINT      REFERENCES plans(id),
    payment_term_id  BIGINT      REFERENCES payment_terms(id),
    terms_text       TEXT,
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE quotation_template_lines (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    template_id  BIGINT NOT NULL REFERENCES quotation_templates(id) ON DELETE CASCADE,
    product_id   BIGINT NOT NULL REFERENCES products(id),
    variant_id   BIGINT REFERENCES product_variants(id),
    quantity     INT    NOT NULL DEFAULT 1 CHECK (quantity >= 1)
);
CREATE INDEX idx_qtl_template ON quotation_template_lines(template_id);

CREATE TABLE quotations (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_number TEXT           NOT NULL UNIQUE
                     DEFAULT ('QUO-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('seq_quotation_no')::text, 5, '0')),
    customer_id      BIGINT         NOT NULL REFERENCES customers(id),
    template_id      BIGINT         REFERENCES quotation_templates(id),
    plan_id          BIGINT         NOT NULL REFERENCES plans(id),
    payment_term_id  BIGINT         NOT NULL REFERENCES payment_terms(id),
    status           quotation_status NOT NULL DEFAULT 'draft',
    issue_date       DATE           NOT NULL DEFAULT CURRENT_DATE,
    valid_until      DATE           NOT NULL,
    subtotal         NUMERIC(12,2)  NOT NULL DEFAULT 0,
    discount_total   NUMERIC(12,2)  NOT NULL DEFAULT 0,
    tax_total        NUMERIC(12,2)  NOT NULL DEFAULT 0,
    total            NUMERIC(12,2)  NOT NULL DEFAULT 0,
    notes            TEXT,
    pdf_url          TEXT,
    created_by       BIGINT         NOT NULL REFERENCES users(id),
    approved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CHECK (valid_until >= issue_date),
    CHECK (total = subtotal - discount_total + tax_total)
);
CREATE INDEX idx_quotations_customer ON quotations(customer_id);
CREATE INDEX idx_quotations_status   ON quotations(status, valid_until);

CREATE TABLE quotation_lines (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id    BIGINT        NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    product_id      BIGINT        NOT NULL REFERENCES products(id),
    variant_id      BIGINT        REFERENCES product_variants(id),
    description     TEXT          NOT NULL,
    quantity        INT           NOT NULL CHECK (quantity >= 1),
    unit_price      NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),   -- snapshot: sales_price + extra_price
    discount_id     BIGINT        REFERENCES discounts(id),
    discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    tax_id          BIGINT        REFERENCES taxes(id),
    tax_rate        NUMERIC(5,2)  NOT NULL DEFAULT 0,                 -- snapshot
    tax_amount      NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_total      NUMERIC(12,2) NOT NULL,
    CHECK (line_total = quantity * unit_price - discount_amount + tax_amount)
);
CREATE INDEX idx_ql_quotation ON quotation_lines(quotation_id);

-- =====================================================================
--  [P2] SUBSCRIPTIONS
-- =====================================================================
CREATE TABLE subscriptions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_number TEXT                NOT NULL UNIQUE
                        DEFAULT ('SUB-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('seq_subscription_no')::text, 6, '0')),
    customer_id         BIGINT              NOT NULL REFERENCES customers(id),
    quotation_id        BIGINT              UNIQUE REFERENCES quotations(id),   -- one quotation converts once
    plan_id             BIGINT              NOT NULL REFERENCES plans(id),
    payment_term_id     BIGINT              NOT NULL REFERENCES payment_terms(id),
    status              subscription_status NOT NULL DEFAULT 'draft',
    start_date          DATE                NOT NULL,
    expiry_date         DATE,
    next_billing_date   DATE,                                   -- drives the billing engine
    last_billed_through DATE,                                   -- end of the last invoiced period
    auto_renew          BOOLEAN             NOT NULL DEFAULT TRUE,
    renewal_count       INT                 NOT NULL DEFAULT 0,
    paused_at           TIMESTAMPTZ,
    resumed_at          TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ,
    closure_reason      closure_reason,
    closure_note        TEXT,
    created_by          BIGINT              REFERENCES users(id),
    created_at          TIMESTAMPTZ         NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ         NOT NULL DEFAULT now(),
    CHECK (expiry_date IS NULL OR expiry_date >= start_date),
    CHECK (status <> 'closed' OR closure_reason IS NOT NULL),
    CHECK (status <> 'active' OR next_billing_date IS NOT NULL)
);
CREATE INDEX idx_sub_customer ON subscriptions(customer_id);
CREATE INDEX idx_sub_status   ON subscriptions(status);
-- the billing engine's hot query: "which active subscriptions are due?"
CREATE INDEX idx_sub_due      ON subscriptions(next_billing_date) WHERE status = 'active';
CREATE INDEX idx_sub_expiry   ON subscriptions(expiry_date)       WHERE status IN ('active', 'paused');

CREATE TABLE subscription_lines (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id BIGINT        NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    product_id      BIGINT        NOT NULL REFERENCES products(id),
    variant_id      BIGINT        REFERENCES product_variants(id),
    description     TEXT          NOT NULL,
    quantity        INT           NOT NULL CHECK (quantity >= 1),
    unit_price      NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),   -- locked at conversion time
    discount_id     BIGINT        REFERENCES discounts(id),
    tax_id          BIGINT        REFERENCES taxes(id)
);
CREATE INDEX idx_sl_subscription ON subscription_lines(subscription_id);

-- Full lifecycle history (activate, pause, resume, renew, close)
CREATE TABLE subscription_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id BIGINT              NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    from_status     subscription_status,
    to_status       subscription_status NOT NULL,
    event_type      TEXT                NOT NULL,             -- 'activated', 'paused', 'renewed', 'closed' ...
    reason          TEXT,
    actor_user_id   BIGINT              REFERENCES users(id),  -- NULL = system/scheduler
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT now()
);
CREATE INDEX idx_se_subscription ON subscription_events(subscription_id, created_at);

-- =====================================================================
--  [P3] BILLING RUNS, INVOICES, PAYMENTS
-- =====================================================================
CREATE TABLE billing_runs (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date          DATE               NOT NULL,
    status            billing_run_status NOT NULL DEFAULT 'running',
    subscriptions_checked INT            NOT NULL DEFAULT 0,
    invoices_created  INT                NOT NULL DEFAULT 0,
    invoices_skipped  INT                NOT NULL DEFAULT 0,   -- already billed (duplicate-safe)
    error_count       INT                NOT NULL DEFAULT 0,
    errors            JSONB,
    triggered_by      BIGINT             REFERENCES users(id),  -- NULL = scheduler
    started_at        TIMESTAMPTZ        NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ
);
CREATE INDEX idx_billing_runs_date ON billing_runs(run_date DESC);

CREATE TABLE invoices (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_number       TEXT           NOT NULL UNIQUE
                         DEFAULT ('INV-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('seq_invoice_no')::text, 6, '0')),
    subscription_id      BIGINT         NOT NULL REFERENCES subscriptions(id),
    customer_id          BIGINT         NOT NULL REFERENCES customers(id),
    billing_run_id       BIGINT         REFERENCES billing_runs(id),
    status               invoice_status NOT NULL DEFAULT 'draft',
    billing_period_start DATE           NOT NULL,
    billing_period_end   DATE           NOT NULL,
    issue_date           DATE           NOT NULL DEFAULT CURRENT_DATE,
    due_date             DATE           NOT NULL,
    currency             CHAR(3)        NOT NULL DEFAULT 'INR',
    subtotal             NUMERIC(12,2)  NOT NULL DEFAULT 0,
    discount_total       NUMERIC(12,2)  NOT NULL DEFAULT 0,
    tax_total            NUMERIC(12,2)  NOT NULL DEFAULT 0,
    total                NUMERIC(12,2)  NOT NULL DEFAULT 0,
    amount_paid          NUMERIC(12,2)  NOT NULL DEFAULT 0,
    amount_due           NUMERIC(12,2)  GENERATED ALWAYS AS (total - amount_paid) STORED,
    pdf_url              TEXT,
    sent_at              TIMESTAMPTZ,
    confirmed_at         TIMESTAMPTZ,
    paid_at              TIMESTAMPTZ,
    cancelled_at         TIMESTAMPTZ,
    cancel_reason        TEXT,
    notes                TEXT,
    created_by           BIGINT         REFERENCES users(id),   -- NULL = billing engine
    created_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CHECK (billing_period_end >= billing_period_start),
    CHECK (due_date >= issue_date),
    CHECK (total = subtotal - discount_total + tax_total),               -- arithmetic integrity
    CHECK (amount_paid >= 0 AND amount_paid <= total)                    -- no overpayment
);
-- DUPLICATE-INVOICE GUARD: one live invoice per subscription per billing period.
-- Cancelled invoices are excluded so a period can be legitimately re-billed.
CREATE UNIQUE INDEX uq_invoice_period
    ON invoices(subscription_id, billing_period_start)
    WHERE status <> 'cancelled';
CREATE INDEX idx_inv_customer ON invoices(customer_id, issue_date DESC);
CREATE INDEX idx_inv_status   ON invoices(status);
CREATE INDEX idx_inv_due      ON invoices(due_date) WHERE status IN ('confirmed', 'overdue');
CREATE INDEX idx_inv_sub      ON invoices(subscription_id);

CREATE TABLE invoice_lines (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id           BIGINT        NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    subscription_line_id BIGINT        REFERENCES subscription_lines(id) ON DELETE SET NULL,
    product_id           BIGINT        REFERENCES products(id),
    variant_id           BIGINT        REFERENCES product_variants(id),
    description          TEXT          NOT NULL,                  -- snapshot
    quantity             INT           NOT NULL CHECK (quantity >= 1),
    unit_price           NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    discount_id          BIGINT        REFERENCES discounts(id),
    discount_amount      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    tax_id               BIGINT        REFERENCES taxes(id),
    tax_rate             NUMERIC(5,2)  NOT NULL DEFAULT 0,        -- snapshot of rate used
    tax_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_total           NUMERIC(12,2) NOT NULL,
    CHECK (line_total = quantity * unit_price - discount_amount + tax_amount)
);
CREATE INDEX idx_il_invoice ON invoice_lines(invoice_id);

-- Tracks every discount redemption (enforces usage_limit / per_customer_limit)
CREATE TABLE discount_redemptions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discount_id BIGINT        NOT NULL REFERENCES discounts(id),
    invoice_id  BIGINT        NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    customer_id BIGINT        NOT NULL REFERENCES customers(id),
    amount      NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (discount_id, invoice_id)
);
CREATE INDEX idx_dr_discount_customer ON discount_redemptions(discount_id, customer_id);

CREATE TABLE payments (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_number     TEXT           NOT NULL UNIQUE
                       DEFAULT ('PAY-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('seq_payment_no')::text, 6, '0')),
    customer_id        BIGINT         NOT NULL REFERENCES customers(id),
    amount             NUMERIC(12,2)  NOT NULL CHECK (amount > 0),
    method             payment_method NOT NULL,
    status             payment_status NOT NULL DEFAULT 'succeeded',
    transaction_date   DATE           NOT NULL DEFAULT CURRENT_DATE,
    gateway_reference  TEXT,                                     -- Razorpay / Stripe test txn id
    notes              TEXT,
    recorded_by        BIGINT         REFERENCES users(id),      -- NULL = gateway webhook
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_payment_gateway_ref ON payments(gateway_reference) WHERE gateway_reference IS NOT NULL;
CREATE INDEX idx_pay_customer ON payments(customer_id, transaction_date DESC);
CREATE INDEX idx_pay_status   ON payments(status, transaction_date);

-- One payment can settle several invoices; one invoice can take several payments
CREATE TABLE payment_allocations (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_id  BIGINT        NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    invoice_id  BIGINT        NOT NULL REFERENCES invoices(id),
    amount      NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (payment_id, invoice_id)
);
CREATE INDEX idx_pa_invoice ON payment_allocations(invoice_id);

-- =====================================================================
--  [P4] ANALYTICS SNAPSHOTS + AI/ML (advisory only)
-- =====================================================================
-- Monthly rollup: powers cached dashboards and is the training data for forecasting
CREATE TABLE revenue_snapshots (
    snapshot_month       DATE          PRIMARY KEY,             -- first day of month
    active_subscriptions INT           NOT NULL DEFAULT 0,
    new_subscriptions    INT           NOT NULL DEFAULT 0,
    closed_subscriptions INT           NOT NULL DEFAULT 0,
    mrr                  NUMERIC(14,2) NOT NULL DEFAULT 0,
    billed_amount        NUMERIC(14,2) NOT NULL DEFAULT 0,
    collected_amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
    outstanding_amount   NUMERIC(14,2) NOT NULL DEFAULT 0,
    overdue_amount       NUMERIC(14,2) NOT NULL DEFAULT 0,
    generated_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE revenue_forecasts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name    TEXT          NOT NULL,                       -- 'holt_winters', 'arima'
    model_version TEXT          NOT NULL,
    target_month  DATE          NOT NULL,
    predicted_mrr NUMERIC(14,2) NOT NULL,
    lower_bound   NUMERIC(14,2),
    upper_bound   NUMERIC(14,2),
    actual_mrr    NUMERIC(14,2),                                -- backfilled once the month closes
    generated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (model_name, model_version, target_month)
);

CREATE TABLE model_metrics (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name    TEXT          NOT NULL,
    model_version TEXT          NOT NULL,
    metric        TEXT          NOT NULL CHECK (metric IN ('MAE', 'MAPE', 'RMSE', 'precision', 'recall', 'f1')),
    value         NUMERIC(12,6) NOT NULL,
    dataset       TEXT          NOT NULL DEFAULT 'holdout',
    evaluated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE anomaly_flags (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id    BIGINT        REFERENCES invoices(id) ON DELETE CASCADE,
    payment_id    BIGINT        REFERENCES payments(id) ON DELETE CASCADE,
    score         NUMERIC(8,5)  NOT NULL,
    reason        TEXT          NOT NULL,
    model_version TEXT          NOT NULL,
    status        TEXT          NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'dismissed')),
    reviewed_by   BIGINT        REFERENCES users(id),
    reviewed_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK ((invoice_id IS NOT NULL)::int + (payment_id IS NOT NULL)::int = 1)   -- exactly one target
);
CREATE INDEX idx_anomaly_status ON anomaly_flags(status, created_at DESC);

-- =====================================================================
--  BUSINESS-RULE TRIGGERS (data integrity enforced in the database)
-- =====================================================================

-- A) Recompute an invoice's paid amount and status from its allocations.
CREATE OR REPLACE FUNCTION recompute_invoice(p_invoice_id BIGINT) RETURNS void AS $$
DECLARE
    v_paid  NUMERIC(12,2);
    v_inv   invoices%ROWTYPE;
BEGIN
    SELECT * INTO v_inv FROM invoices WHERE id = p_invoice_id FOR UPDATE;
    IF NOT FOUND OR v_inv.status IN ('draft', 'cancelled') THEN
        RETURN;
    END IF;

    SELECT COALESCE(SUM(pa.amount), 0) INTO v_paid
    FROM payment_allocations pa
    JOIN payments p ON p.id = pa.payment_id
    WHERE pa.invoice_id = p_invoice_id AND p.status = 'succeeded';

    UPDATE invoices
    SET amount_paid = v_paid,
        status = CASE
                    WHEN v_paid >= total          THEN 'paid'::invoice_status
                    WHEN due_date < CURRENT_DATE  THEN 'overdue'::invoice_status
                    ELSE 'confirmed'::invoice_status
                 END,
        paid_at = CASE WHEN v_paid >= total THEN COALESCE(paid_at, now()) ELSE NULL END
    WHERE id = p_invoice_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_allocation_changed() RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM recompute_invoice(OLD.invoice_id); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM recompute_invoice(NEW.invoice_id); END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pa_recompute
AFTER INSERT OR UPDATE OR DELETE ON payment_allocations
FOR EACH ROW EXECUTE FUNCTION trg_allocation_changed();

-- B) When a payment's status changes (e.g. succeeded -> refunded), refresh its invoices.
CREATE OR REPLACE FUNCTION trg_payment_status_changed() RETURNS trigger AS $$
DECLARE r RECORD;
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        FOR r IN SELECT invoice_id FROM payment_allocations WHERE payment_id = NEW.id LOOP
            PERFORM recompute_invoice(r.invoice_id);
        END LOOP;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pay_status
AFTER UPDATE OF status ON payments
FOR EACH ROW EXECUTE FUNCTION trg_payment_status_changed();

-- C) Block allocating more than the payment amount, or paying a draft/cancelled invoice.
CREATE OR REPLACE FUNCTION trg_allocation_guard() RETURNS trigger AS $$
DECLARE
    v_payment_amount NUMERIC(12,2);
    v_allocated      NUMERIC(12,2);
    v_inv_status     invoice_status;
BEGIN
    SELECT amount INTO v_payment_amount FROM payments WHERE id = NEW.payment_id FOR UPDATE;
    SELECT COALESCE(SUM(amount), 0) INTO v_allocated
    FROM payment_allocations
    WHERE payment_id = NEW.payment_id AND id IS DISTINCT FROM NEW.id;

    IF v_allocated + NEW.amount > v_payment_amount THEN
        RAISE EXCEPTION 'Allocation exceeds payment amount (payment %, allocated %, new %)',
            v_payment_amount, v_allocated, NEW.amount;
    END IF;

    SELECT status INTO v_inv_status FROM invoices WHERE id = NEW.invoice_id;
    IF v_inv_status IN ('draft', 'cancelled') THEN
        RAISE EXCEPTION 'Cannot allocate a payment to a % invoice', v_inv_status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pa_guard
BEFORE INSERT OR UPDATE ON payment_allocations
FOR EACH ROW EXECUTE FUNCTION trg_allocation_guard();

-- D) Nightly job helper: flip confirmed invoices past their due date to overdue.
CREATE OR REPLACE FUNCTION mark_overdue_invoices() RETURNS INT AS $$
DECLARE v_count INT;
BEGIN
    UPDATE invoices
    SET status = 'overdue'
    WHERE status = 'confirmed' AND due_date < CURRENT_DATE AND amount_due > 0;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- E) updated_at triggers on every table that has the column
DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'updated_at'
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
    END LOOP;
END $$;

-- =====================================================================
--  [P4] REPORTING VIEWS  (dashboard reads these; cache the results)
-- =====================================================================

-- Monthly-equivalent recurring revenue per active subscription (pre-tax, after plan interval)
CREATE VIEW v_subscription_mrr AS
SELECT
    s.id AS subscription_id,
    s.customer_id,
    ROUND(
        SUM(sl.quantity * sl.unit_price)
        * CASE p.billing_period
            WHEN 'daily'   THEN 365.0 / 12
            WHEN 'weekly'  THEN 52.0 / 12
            WHEN 'monthly' THEN 1.0
            WHEN 'yearly'  THEN 1.0 / 12
          END
        / p.billing_interval
    , 2) AS mrr
FROM subscriptions s
JOIN plans p               ON p.id = s.plan_id
JOIN subscription_lines sl ON sl.subscription_id = s.id
WHERE s.status = 'active'
GROUP BY s.id, s.customer_id, p.billing_period, p.billing_interval;

CREATE VIEW v_overdue_invoices AS
SELECT
    i.id, i.invoice_number, i.customer_id, c.name AS customer_name,
    i.due_date, (CURRENT_DATE - i.due_date) AS days_overdue,
    i.total, i.amount_paid, i.amount_due
FROM invoices i
JOIN customers c ON c.id = i.customer_id
WHERE i.status IN ('confirmed', 'overdue')
  AND i.due_date < CURRENT_DATE
  AND i.amount_due > 0;

CREATE VIEW v_monthly_financials AS
WITH billed AS (
    SELECT date_trunc('month', issue_date)::date AS month,
           SUM(total) AS billed_amount, COUNT(*) AS invoice_count
    FROM invoices
    WHERE status IN ('confirmed', 'paid', 'overdue')
    GROUP BY 1
), collected AS (
    SELECT date_trunc('month', transaction_date)::date AS month,
           SUM(amount) AS collected_amount
    FROM payments
    WHERE status = 'succeeded'
    GROUP BY 1
)
SELECT COALESCE(b.month, c.month) AS month,
       COALESCE(b.billed_amount, 0)    AS billed_amount,
       COALESCE(c.collected_amount, 0) AS collected_amount,
       COALESCE(b.invoice_count, 0)    AS invoice_count
FROM billed b
FULL JOIN collected c ON c.month = b.month
ORDER BY 1;

-- =====================================================================
--  MINIMAL REFERENCE DATA
-- =====================================================================
INSERT INTO taxes (name, rate_percent) VALUES
    ('No Tax', 0), ('GST 5%', 5), ('GST 12%', 12), ('GST 18%', 18);

INSERT INTO payment_terms (name, due_days) VALUES
    ('Immediate', 0), ('Net 15', 15), ('Net 30', 30);

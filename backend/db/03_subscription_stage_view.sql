-- =====================================================================
--  03 - Subscription lifecycle stage (additive; no existing table is changed)
--
--  The brief describes: Draft -> Quotation -> Confirmed -> Active -> Closed.
--  The schema stores that journey in two places: subscriptions.status
--  (draft / active / paused / closed) and quotations.status. This view
--  combines them so the UI/API can show ONE stage per subscription.
--
--      Draft      no quotation yet, or the quotation is still a draft
--      Quotation  quotation has been sent to the customer (or was rejected / expired)
--      Confirmed  quotation approved / converted, subscription not activated yet
--      Active     subscription active (is_paused = true while paused)
--      Closed     subscription closed (see closure_reason)
-- =====================================================================
CREATE OR REPLACE VIEW v_subscription_stage AS
SELECT
    s.id                       AS subscription_id,
    s.subscription_number,
    s.customer_id,
    s.status::text             AS subscription_status,
    q.status::text             AS quotation_status,
    CASE
        WHEN s.status = 'closed'                       THEN 'Closed'
        WHEN s.status IN ('active', 'paused')          THEN 'Active'
        WHEN q.id IS NULL OR q.status = 'draft'        THEN 'Draft'
        WHEN q.status IN ('approved', 'converted')     THEN 'Confirmed'
        ELSE                                                'Quotation'
    END                        AS stage,
    CASE
        WHEN s.status = 'closed'                       THEN 5
        WHEN s.status IN ('active', 'paused')          THEN 4
        WHEN q.id IS NULL OR q.status = 'draft'        THEN 1
        WHEN q.status IN ('approved', 'converted')     THEN 3
        ELSE                                                2
    END                        AS stage_no,
    (s.status = 'paused')      AS is_paused,
    s.closure_reason::text     AS closure_reason,
    s.start_date,
    s.expiry_date,
    s.next_billing_date
FROM subscriptions s
LEFT JOIN quotations q ON q.id = s.quotation_id;

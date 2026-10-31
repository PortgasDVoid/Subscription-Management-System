-- Date-independent sanity checks for the demo data (run after 01, 02, 03).
-- The README's expected counts for confirmed/overdue move with the calendar: a part-paid invoice
-- flips from confirmed to overdue once its due date passes. These invariants always hold.

-- Run the nightly helper first so statuses reflect today's date.
SELECT mark_overdue_invoices();

-- Expect: cancelled 1, paid 26, and confirmed + overdue = 4 (the split depends on today's date).
SELECT status, COUNT(*) FROM invoices GROUP BY status ORDER BY status;
SELECT COUNT(*) AS open_invoices FROM invoices WHERE status IN ('confirmed', 'overdue');   -- expect 4

-- Expect 21783.33
SELECT SUM(mrr) FROM v_subscription_mrr;

-- Expect (seed): Active 5 (4 active + 1 paused), Closed 1
SELECT stage, COUNT(*) FROM v_subscription_stage GROUP BY stage ORDER BY MIN(stage_no);

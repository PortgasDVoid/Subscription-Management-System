"""Time the queries behind the main pages against the 2-second budget (Developer 3).

Each query is one a page would run: dashboard KPIs, subscription list, invoice lists (filtered, per
customer), overdue list, payments list, monthly financials, one invoice with its lines (the PDF read).
Every query is run once to warm up, then --runs times; the report shows min / median / p95 / max in
milliseconds and exits 1 if any p95 is over --budget (default 2.0 s).

Usage (from backend/):
    python scripts/benchmark_queries.py
    python scripts/benchmark_queries.py --runs 50 --budget 1.0
    python scripts/benchmark_queries.py --explain          # EXPLAIN ANALYZE of the slowest query
    python scripts/benchmark_queries.py --database-url postgresql+psycopg2://...

Run it after seed_database.py. For the "thousands of subscriptions" claim, seed bigger first:
    python scripts/seed_database.py --subscriptions 5000 --customers 2500
Timings depend on the machine and on warm caches; quote the row counts printed at the top with them.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# name -> (sql, needs) ; `needs` lists the sample ids resolved before timing
QUERIES = {
    "dashboard_kpis": ("""
        SELECT
          (SELECT COUNT(*) FROM subscriptions WHERE status = 'active')                          AS active_subscriptions,
          (SELECT COALESCE(SUM(mrr), 0) FROM v_subscription_mrr)                                AS mrr,
          (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded'
             AND transaction_date >= date_trunc('month', CURRENT_DATE))                         AS collected_this_month,
          (SELECT COALESCE(SUM(amount_due), 0) FROM invoices WHERE status IN ('confirmed', 'overdue')) AS outstanding,
          (SELECT COUNT(*) FROM invoices WHERE status = 'overdue')                              AS overdue_count
    """, ()),
    "subscription_list_page": ("""
        SELECT s.id, s.subscription_number, c.name AS customer, p.name AS plan, s.status, s.next_billing_date
        FROM subscriptions s JOIN customers c ON c.id = s.customer_id JOIN plans p ON p.id = s.plan_id
        WHERE s.status = 'active' ORDER BY s.next_billing_date, s.id LIMIT 25 OFFSET 0
    """, ()),
    "subscription_search_by_customer": ("""
        SELECT s.id, s.subscription_number, c.name, s.status
        FROM subscriptions s JOIN customers c ON c.id = s.customer_id
        WHERE lower(c.name) LIKE 'a%' ORDER BY s.id DESC LIMIT 25
    """, ()),
    "subscription_status_summary": ("""
        SELECT status, COUNT(*) FROM subscriptions GROUP BY status
    """, ()),
    "invoice_list_overdue_page": ("""
        SELECT i.id, i.invoice_number, c.name, i.due_date, i.total, i.amount_due
        FROM invoices i JOIN customers c ON c.id = i.customer_id
        WHERE i.status = 'overdue' ORDER BY i.due_date, i.id LIMIT 25
    """, ()),
    "invoice_list_filtered_by_date": ("""
        SELECT i.id, i.invoice_number, i.status, i.issue_date, i.total
        FROM invoices i
        WHERE i.issue_date >= CURRENT_DATE - INTERVAL '90 days' AND i.status IN ('confirmed', 'paid', 'overdue')
        ORDER BY i.issue_date DESC, i.id DESC LIMIT 25
    """, ()),
    "customer_portal_invoices": ("""
        SELECT i.id, i.invoice_number, i.status, i.issue_date, i.due_date, i.total, i.amount_due
        FROM invoices i WHERE i.customer_id = :customer_id ORDER BY i.issue_date DESC LIMIT 25
    """, ("customer_id",)),
    "customer_portal_subscriptions": ("""
        SELECT s.id, s.subscription_number, s.status, p.name FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id WHERE s.customer_id = :customer_id
    """, ("customer_id",)),
    "overdue_view_top50": ("""
        SELECT * FROM v_overdue_invoices ORDER BY days_overdue DESC LIMIT 50
    """, ()),
    "payments_recent_page": ("""
        SELECT p.id, p.payment_number, c.name, p.amount, p.method, p.status, p.transaction_date
        FROM payments p JOIN customers c ON c.id = p.customer_id
        ORDER BY p.transaction_date DESC, p.id DESC LIMIT 25
    """, ()),
    "revenue_by_month_summary": ("""
        SELECT * FROM v_monthly_financials
    """, ()),
    "mrr_total": ("""
        SELECT COALESCE(SUM(mrr), 0) FROM v_subscription_mrr
    """, ()),
    "invoice_detail_with_lines": ("""
        SELECT i.invoice_number, i.status, i.total, i.amount_paid, c.name, c.tax_id,
               l.description, l.quantity, l.unit_price, l.discount_amount, l.tax_rate, l.tax_amount, l.line_total
        FROM invoices i JOIN customers c ON c.id = i.customer_id JOIN invoice_lines l ON l.invoice_id = i.id
        WHERE i.id = :invoice_id ORDER BY l.id
    """, ("invoice_id",)),
}


def pct(sorted_ms, q):
    return sorted_ms[min(len(sorted_ms) - 1, int(round(q * (len(sorted_ms) - 1))))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--budget", type=float, default=2.0, help="seconds; p95 above this fails (default 2.0)")
    ap.add_argument("--explain", action="store_true", help="print EXPLAIN (ANALYZE, BUFFERS) for the slowest query")
    ap.add_argument("--database-url")
    args = ap.parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from sqlalchemy import text
    from app.db import get_engine
    engine = get_engine()

    with engine.connect() as conn:
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                  for t in ("customers", "subscriptions", "invoices", "invoice_lines", "payments")}
        # the customer with the most invoices and a mid-sized invoice make realistic samples
        samples = {
            "customer_id": conn.execute(text(
                "SELECT customer_id FROM invoices GROUP BY customer_id ORDER BY COUNT(*) DESC, customer_id LIMIT 1")).scalar(),
            "invoice_id": conn.execute(text(
                "SELECT id FROM invoices ORDER BY id DESC OFFSET (SELECT COUNT(*)/2 FROM invoices) LIMIT 1")).scalar(),
        }
    print("rows: " + ", ".join(f"{k}={v:,}" for k, v in counts.items()))
    if not counts["invoices"]:
        print("No invoices found. Run scripts/seed_database.py first.")
        return 2

    results = {}
    for name, (sql, needs) in QUERIES.items():
        params = {k: samples[k] for k in needs}
        with engine.connect() as conn:
            conn.execute(text(sql), params).fetchall()                       # warm-up
            times = []
            for _ in range(args.runs):
                t0 = time.perf_counter()
                rows = conn.execute(text(sql), params).fetchall()
                times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        results[name] = dict(rows=len(rows), min=times[0], med=statistics.median(times),
                             p95=pct(times, .95), max=times[-1])

    budget_ms = args.budget * 1000
    print(f"\n{'query':<34}{'rows':>6}{'min':>9}{'median':>9}{'p95':>9}{'max':>9}   (ms)   budget {budget_ms:,.0f} ms")
    failed = []
    for name, r in results.items():
        ok = r["p95"] <= budget_ms
        if not ok:
            failed.append(name)
        print(f"{name:<34}{r['rows']:>6}{r['min']:>9.1f}{r['med']:>9.1f}{r['p95']:>9.1f}{r['max']:>9.1f}   "
              f"{'ok' if ok else 'SLOW'}")
    worst = max(results, key=lambda k: results[k]["p95"])
    print(f"\nslowest: {worst} (p95 {results[worst]['p95']:.1f} ms)  ->  "
          + ("ALL WITHIN BUDGET" if not failed else "OVER BUDGET: " + ", ".join(failed)))

    if args.explain:
        sql, needs = QUERIES[worst]
        with engine.connect() as conn:
            for (line,) in conn.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + sql), {k: samples[k] for k in needs}):
                print("   " + line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

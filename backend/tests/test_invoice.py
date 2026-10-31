import threading
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.repositories import billing_repository as repo
from app.services.errors import SubscriptionNotFoundError
from app.services.invoice_service import InvoiceService, run_billing
from tests.conftest import q

# Seed (anchored to Oct 2026): sub 1 monthly Net15 due 2026-11-01 (lines: 5 x 2000 + 2 x 300, GST18)
# sub 2 monthly Net30 due 2026-11-01 | sub 3 yearly next 2027-02-01 expiry 2027-01-31 | sub 4 quarterly next 2027-01-01
# sub 5 paused | sub 6 closed.   LOYAL5 (5%, product 1, qty>=5, auto_apply) would hit sub 1's first line.
NOV1 = date(2026, 11, 1)


def gen(conn, sid, as_of=NOV1, **opts):
    return InvoiceService(conn, **opts).generate_for_subscription(sid, as_of)


def invoice(conn, invoice_id):
    return q(conn, "SELECT * FROM invoices WHERE id = :i", i=invoice_id).mappings().one()


def lines(conn, invoice_id):
    return q(conn, "SELECT * FROM invoice_lines WHERE invoice_id = :i ORDER BY id", i=invoice_id).mappings().all()


def assert_consistent(conn, invoice_id):
    inv, ls = invoice(conn, invoice_id), lines(conn, invoice_id)
    assert inv["subtotal"] == sum(l["quantity"] * l["unit_price"] for l in ls)
    assert inv["discount_total"] == sum(l["discount_amount"] for l in ls)
    assert inv["tax_total"] == sum(l["tax_amount"] for l in ls)
    assert inv["total"] == sum(l["line_total"] for l in ls) == inv["subtotal"] - inv["discount_total"] + inv["tax_total"]


def test_successful_generation_matches_historical_pricing(conn):
    r = gen(conn, 1, apply_auto_discounts=False)
    assert r.outcome == "created" and r.invoice_number.startswith("INV-")
    inv = invoice(conn, r.invoice_id)
    assert (inv["subtotal"], inv["discount_total"], inv["tax_total"], inv["total"]) == \
        (D("10600.00"), D("0.00"), D("1908.00"), D("12508.00"))          # same as seed invoices 5..29
    assert (inv["status"], inv["billing_period_start"], inv["billing_period_end"]) == \
        ("confirmed", date(2026, 11, 1), date(2026, 11, 30))
    assert (inv["issue_date"], inv["due_date"], inv["currency"]) == (NOV1, date(2026, 11, 16), "INR")  # Net 15
    assert_consistent(conn, r.invoice_id)


def test_subscription_dates_advance(conn):
    gen(conn, 1)
    s = q(conn, "SELECT next_billing_date, last_billed_through FROM subscriptions WHERE id = 1").one()
    assert (s[0], s[1]) == (date(2026, 12, 1), date(2026, 11, 30))


def test_net30_due_date_and_multiple_lines(conn):
    r = gen(conn, 2)
    inv, ls = invoice(conn, r.invoice_id), lines(conn, r.invoice_id)
    assert inv["due_date"] == date(2026, 12, 1) and len(ls) == 2
    assert inv["total"] == D("6608.00")
    assert_consistent(conn, r.invoice_id)


def test_tax_and_discount_integration_auto_discount(conn):
    r = gen(conn, 1)    # LOYAL5 auto-applies to the 5 x 2000 CRM line: 5% of 10000 = 500
    ls = lines(conn, r.invoice_id)
    assert (ls[0]["discount_id"], ls[0]["discount_amount"], ls[0]["tax_rate"], ls[0]["tax_amount"]) == \
        (3, D("500.00"), D("18.00"), D("1710.00"))                       # 18% of (10000 - 500)
    assert ls[1]["discount_amount"] == D("0.00") and ls[1]["tax_amount"] == D("108.00")
    inv = invoice(conn, r.invoice_id)
    assert (inv["discount_total"], inv["tax_total"], inv["total"]) == (D("500.00"), D("1818.00"), D("11918.00"))
    assert_consistent(conn, r.invoice_id)
    red = q(conn, "SELECT discount_id, customer_id, amount FROM discount_redemptions WHERE invoice_id = :i",
            i=r.invoice_id).all()
    assert [tuple(x) for x in red] == [(3, 1, D("500.00"))]


def test_pinned_discount_on_quarterly_subscription(conn):
    q(conn, "UPDATE discounts SET valid_until = '2027-12-31' WHERE id = 3")   # seed LOYAL5 ends 2026-12-31
    r = gen(conn, 4, as_of=date(2027, 1, 1))
    inv = invoice(conn, r.invoice_id)
    assert (inv["billing_period_start"], inv["billing_period_end"]) == (date(2027, 1, 1), date(2027, 3, 31))
    assert (inv["subtotal"], inv["discount_total"], inv["total"]) == (D("15000.00"), D("750.00"), D("16815.00"))
    assert_consistent(conn, r.invoice_id)


def test_expired_discount_stops_appearing_on_invoices(conn):
    r = gen(conn, 4, as_of=date(2027, 1, 1))                  # LOYAL5 expired 2026-12-31
    inv = invoice(conn, r.invoice_id)
    assert (inv["discount_total"], inv["total"]) == (D("0.00"), D("17700.00"))   # 15000 + 18% tax
    assert r.discounts_rejected and "discount has expired" in r.discounts_rejected[0][2]
    assert_consistent(conn, r.invoice_id)


def test_duplicate_invoice_prevention(conn):
    first = gen(conn, 1)
    again = gen(conn, 1)
    assert first.outcome == "created" and (again.outcome, again.reason) == ("skipped", "not_due")
    # even if next_billing_date is rewound, the period is detected as already billed
    q(conn, "UPDATE subscriptions SET next_billing_date = '2026-11-01', last_billed_through = '2026-10-31' WHERE id = 1")
    third = gen(conn, 1)
    assert (third.outcome, third.reason) == ("skipped", "already_billed")
    assert q(conn, "SELECT COUNT(*) FROM invoices WHERE subscription_id = 1 AND billing_period_start = '2026-11-01'").scalar() == 1


def test_database_unique_index_is_the_backstop(conn):
    gen(conn, 1)
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            q(conn, "INSERT INTO invoices (subscription_id, customer_id, billing_period_start, billing_period_end, due_date) "
                    "VALUES (1, 1, '2026-11-01', '2026-11-30', '2026-11-16')")


def test_subscription_not_due(conn):
    r = gen(conn, 1, as_of=date(2026, 10, 31))
    assert (r.outcome, r.reason) == ("skipped", "not_due")


@pytest.mark.parametrize("sid,reason", [(5, "subscription_paused"), (6, "subscription_closed")])
def test_paused_and_closed_not_billed(conn, sid, reason):
    before = q(conn, "SELECT COUNT(*) FROM invoices WHERE subscription_id = :s", s=sid).scalar()
    r = gen(conn, sid, as_of=date(2027, 1, 1))
    assert (r.outcome, r.reason) == ("skipped", reason)
    assert q(conn, "SELECT COUNT(*) FROM invoices WHERE subscription_id = :s", s=sid).scalar() == before


def test_draft_subscription_not_billed(conn):
    q(conn, "UPDATE subscriptions SET status = 'draft' WHERE id = 1")
    assert gen(conn, 1).reason == "subscription_draft"


def test_expired_subscription_not_billed(conn):
    r = gen(conn, 3, as_of=date(2027, 2, 1))      # expiry 2027-01-31 < next billing 2027-02-01
    assert (r.outcome, r.reason) == ("skipped", "expired")


def test_unknown_subscription(conn):
    with pytest.raises(SubscriptionNotFoundError):
        gen(conn, 9999)


def test_inactive_tax_is_an_error_and_writes_nothing(conn):
    q(conn, "UPDATE taxes SET is_active = FALSE WHERE id = 4")
    n = q(conn, "SELECT COUNT(*) FROM invoices").scalar()
    r = gen(conn, 1)
    assert (r.outcome, r.reason) == ("error", "tax_configuration")
    assert q(conn, "SELECT COUNT(*) FROM invoices").scalar() == n
    assert q(conn, "SELECT next_billing_date FROM subscriptions WHERE id = 1").scalar() == NOV1


def test_inactive_product_blocks_billing_unless_allowed(conn):
    q(conn, "UPDATE products SET is_active = FALSE WHERE id = 4")
    assert gen(conn, 1).reason == "inactive_product"
    assert gen(conn, 1, allow_inactive_products=True).outcome == "created"


def test_inactive_customer_skipped_and_missing_lines_error(conn):
    q(conn, "UPDATE customers SET is_active = FALSE WHERE id = 1")
    assert gen(conn, 1).reason == "customer_inactive"
    q(conn, "DELETE FROM subscription_lines WHERE subscription_id = 2")
    assert (gen(conn, 2).outcome, gen(conn, 2).reason) == ("error", "invoice_data")


def test_failed_transaction_rolls_back_everything(conn, monkeypatch):
    calls = {"n": 0}
    real = repo.insert_invoice_line

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:                      # fail on the second line, after invoice + line 1 exist
            raise RuntimeError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(repo, "insert_invoice_line", boom)
    n_inv = q(conn, "SELECT COUNT(*) FROM invoices").scalar()
    n_red = q(conn, "SELECT COUNT(*) FROM discount_redemptions").scalar()
    with pytest.raises(RuntimeError):
        gen(conn, 1)
    assert q(conn, "SELECT COUNT(*) FROM invoices").scalar() == n_inv
    assert q(conn, "SELECT COUNT(*) FROM discount_redemptions").scalar() == n_red
    assert q(conn, "SELECT next_billing_date FROM subscriptions WHERE id = 1").scalar() == NOV1


def test_zero_total_invoice_is_created_paid(conn):
    q(conn, "UPDATE subscription_lines SET unit_price = 0 WHERE subscription_id = 2")
    r = gen(conn, 2)
    assert invoice(conn, r.invoice_id)["status"] == "paid" and r.totals.total == D("0.00")


def test_draft_mode(conn):
    r = gen(conn, 1, auto_confirm=False)
    assert invoice(conn, r.invoice_id)["status"] == "draft"


# ---- payments against a generated invoice (DB triggers own amount_paid / status) ----
def _pay(conn, customer_id, invoice_id, amount):
    pid = q(conn, "INSERT INTO payments (customer_id, amount, method) VALUES (:c, :a, 'upi') RETURNING id",
            c=customer_id, a=amount).scalar()
    q(conn, "INSERT INTO payment_allocations (payment_id, invoice_id, amount) VALUES (:p, :i, :a)",
      p=pid, i=invoice_id, a=amount)


def test_partial_payment(conn):
    r = gen(conn, 1, apply_auto_discounts=False)
    _pay(conn, 1, r.invoice_id, D("5000.00"))
    inv = invoice(conn, r.invoice_id)
    assert (inv["amount_paid"], inv["amount_due"]) == (D("5000.00"), D("7508.00"))
    assert inv["status"] in ("confirmed", "overdue") and inv["paid_at"] is None


def test_fully_paid_invoice(conn):
    r = gen(conn, 1, apply_auto_discounts=False)
    _pay(conn, 1, r.invoice_id, D("12508.00"))
    inv = invoice(conn, r.invoice_id)
    assert (inv["status"], inv["amount_due"]) == ("paid", D("0.00")) and inv["paid_at"] is not None


def test_cannot_overpay_or_pay_draft(conn):
    d = gen(conn, 2, auto_confirm=False)
    with pytest.raises(Exception):
        with conn.begin_nested():
            _pay(conn, 2, d.invoice_id, D("10.00"))        # draft invoices cannot be paid


# ---- batch run ----
def test_billing_run_creates_due_invoices_and_records_run(conn, scope):
    s = run_billing(scope, as_of=NOV1, apply_auto_discounts=False)
    assert (s.checked, s.created, s.skipped, s.status) == (2, 2, 0, "completed")
    run = q(conn, "SELECT status::text, subscriptions_checked, invoices_created, error_count FROM billing_runs WHERE id = :i",
            i=s.run_id).one()
    assert tuple(run) == ("completed", 2, 2, 0)
    assert q(conn, "SELECT COUNT(*) FROM invoices WHERE billing_run_id = :r", r=s.run_id).scalar() == 2
    again = run_billing(scope, as_of=NOV1)                        # nothing left to bill
    assert (again.checked, again.created) == (0, 0)


def test_billing_run_isolates_failures(conn, scope):
    q(conn, "UPDATE subscription_lines SET tax_id = 3 WHERE subscription_id = 1")
    q(conn, "UPDATE taxes SET is_active = FALSE WHERE id = 3")
    s = run_billing(scope, as_of=NOV1)
    assert (s.created, len(s.errors), s.status) == (1, 1, "completed_with_errors")
    assert s.errors[0]["subscription_id"] == 1 and s.errors[0]["code"] == "tax_configuration"
    stored = q(conn, "SELECT error_count, errors FROM billing_runs WHERE id = :i", i=s.run_id).one()
    assert stored[0] == 1 and stored[1][0]["code"] == "tax_configuration"


# ---- concurrency (real commits, cleaned up afterwards) ----
def test_concurrent_billing_creates_exactly_one_invoice(engine):
    results = []

    def worker():
        with engine.begin() as c:
            results.append(InvoiceService(c, apply_auto_discounts=False).generate_for_subscription(1, NOV1))

    try:
        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        outcomes = sorted(r.outcome for r in results)
        assert outcomes == ["created", "skipped", "skipped", "skipped"]
        with engine.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM invoices WHERE subscription_id = 1 "
                                  "AND billing_period_start = '2026-11-01'")).scalar() == 1
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM invoices WHERE subscription_id = 1 AND billing_period_start = '2026-11-01'"))
            c.execute(text("UPDATE subscriptions SET next_billing_date = '2026-11-01', "
                           "last_billed_through = '2026-10-31' WHERE id = 1"))

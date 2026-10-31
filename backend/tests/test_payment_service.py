"""PostgreSQL integration tests for payment_service.record_payment.

NOT YET RUN: written without a database available. Run with TEST_DATABASE_URL set (see conftest.py);
without it these tests skip. Seed anchors: customer 1 owns subscription 1 (12,508.00 per month
without the auto discount).
"""
from datetime import date
from decimal import Decimal as D

import pytest

from app.services import errors as e
from app.services.invoice_service import InvoiceService
from app.services.payment_service import record_payment
from tests.conftest import q

NOV1 = date(2026, 11, 1)


def new_invoice(conn, sid=1, **opts):
    opts.setdefault("apply_auto_discounts", False)
    r = InvoiceService(conn, **opts).generate_for_subscription(sid, NOV1)
    assert r.outcome == "created"
    return r.invoice_id


def inv(conn, invoice_id):
    return q(conn, "SELECT status::text, amount_paid, amount_due FROM invoices WHERE id = :i", i=invoice_id).one()


def pay(conn, invoice_id, amount, customer_id=1, **kw):
    return record_payment(conn, customer_id=customer_id, amount=D(amount), method="upi",
                          allocations=[(invoice_id, D(amount))], **kw)


def test_partial_then_full_payment_updates_the_invoice_through_triggers(conn):
    i = new_invoice(conn)
    pay(conn, i, "5000.00")
    assert tuple(inv(conn, i))[1:] == (D("5000.00"), D("7508.00")) and inv(conn, i)[0] in ("confirmed", "overdue")
    pay(conn, i, "7508.00")
    assert tuple(inv(conn, i)) == ("paid", D("12508.00"), D("0.00"))


def test_overpaying_an_invoice_gives_a_friendly_error_and_writes_nothing(conn):
    i = new_invoice(conn)
    n = q(conn, "SELECT COUNT(*) FROM payments").scalar()
    with pytest.raises(e.OverAllocationError):
        record_payment(conn, customer_id=1, amount=D("20000"), method="card", allocations=[(i, D("12508.01"))])
    assert q(conn, "SELECT COUNT(*) FROM payments").scalar() == n


def test_draft_invoice_cannot_be_paid(conn):
    i = new_invoice(conn, auto_confirm=False)
    with pytest.raises(e.InvoiceNotPayableError):
        pay(conn, i, "10.00")


def test_paid_invoice_cannot_be_paid_again(conn):
    i = new_invoice(conn)
    pay(conn, i, "12508.00")
    with pytest.raises(e.InvoiceNotPayableError):
        pay(conn, i, "1.00")


def test_other_customers_invoice_is_refused(conn):
    i = new_invoice(conn)                                   # belongs to customer 1
    with pytest.raises(e.InvoiceCustomerMismatchError):
        pay(conn, i, "10.00", customer_id=2)


def test_gateway_reference_can_only_be_used_once(conn):
    i = new_invoice(conn)
    pay(conn, i, "100.00", gateway_reference="pay_TEST_001")
    with pytest.raises(e.DuplicatePaymentReferenceError):
        pay(conn, i, "100.00", gateway_reference="pay_TEST_001")


def test_payment_without_allocations_goes_to_the_oldest_open_invoice(conn):
    new_invoice(conn)
    oldest = q(conn, "SELECT id FROM invoices WHERE customer_id = 1 AND status IN ('confirmed','overdue') "
                     "AND amount_due > 0 ORDER BY due_date, id LIMIT 1").scalar()
    res = record_payment(conn, customer_id=1, amount=D("1.00"), method="cash")
    assert res.allocations == [(oldest, D("1.00"))] and res.unallocated == D("0.00")


def test_leftover_stays_unallocated_instead_of_being_forced(conn):
    res = record_payment(conn, customer_id=1, amount=D("9999999.00"), method="bank_transfer")
    assert res.unallocated > 0 and sum(p for _, p in res.allocations) + res.unallocated == D("9999999.00")


def test_failed_payment_is_recorded_but_cannot_be_allocated(conn):
    i = new_invoice(conn)
    with pytest.raises(e.InvalidPaymentError):
        pay(conn, i, "10.00", status="failed")
    res = record_payment(conn, customer_id=1, amount=D("10.00"), method="card", status="failed")
    assert res.allocations == []
    assert tuple(inv(conn, i))[1] == D("0.00")


def test_pending_payment_reserves_the_amount(conn):
    i = new_invoice(conn)
    pay(conn, i, "12508.00", status="pending")              # not counted as paid yet ...
    assert inv(conn, i)[1] == D("0.00")
    with pytest.raises(e.OverAllocationError):              # ... but nobody else can take the same money
        pay(conn, i, "1.00")


def test_validation_errors(conn):
    for kw in (dict(amount=D("0")), dict(amount=D("-5")), dict(amount=10.5), dict(method="bitcoin"),
               dict(customer_id=9999)):
        args = dict(customer_id=1, amount=D("10"), method="cash")
        args.update(kw)
        with pytest.raises(e.InvalidPaymentError):
            record_payment(conn, **args)

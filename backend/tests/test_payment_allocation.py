"""Pure unit tests for the payment allocation rules (no database)."""
import unittest
from decimal import Decimal as D

from app.services import errors as e
from app.services.payment_service import PayableInvoice as Inv, plan_allocations


def inv(i, payable, status="confirmed", customer=1):
    return Inv(i, customer, status, D(payable))


class AutoAllocation(unittest.TestCase):
    def test_oldest_first_and_remainder_stays_unallocated(self):
        out = plan_allocations(D("1000"), 1, [inv(1, "300"), inv(2, "500")])
        self.assertEqual(out, [(1, D("300")), (2, D("500"))])             # 200 stays unallocated

    def test_partial_on_last_invoice(self):
        self.assertEqual(plan_allocations(D("400"), 1, [inv(1, "300"), inv(2, "500")]),
                         [(1, D("300")), (2, D("100"))])

    def test_skips_paid_other_customer_and_empty(self):
        invoices = [inv(1, "100", "paid"), inv(2, "100", customer=2), inv(3, "0"), inv(4, "50", "overdue")]
        self.assertEqual(plan_allocations(D("500"), 1, invoices), [(4, D("50"))])

    def test_no_open_invoices(self):
        self.assertEqual(plan_allocations(D("500"), 1, []), [])


class ExplicitAllocation(unittest.TestCase):
    def test_valid(self):
        out = plan_allocations(D("1000"), 1, [inv(1, "300"), inv(2, "500", "overdue")], [(2, D("500")), (1, D("200"))])
        self.assertEqual(out, [(2, D("500.00")), (1, D("200.00"))])

    def test_exact_payment_of_two_invoices(self):
        out = plan_allocations(D("800"), 1, [inv(1, "300"), inv(2, "500")], [(1, D("300")), (2, D("500"))])
        self.assertEqual(sum(p for _, p in out), D("800"))

    def test_more_than_the_invoice_still_owes(self):
        with self.assertRaises(e.OverAllocationError):
            plan_allocations(D("1000"), 1, [inv(1, "300")], [(1, D("300.01"))])

    def test_more_than_the_payment(self):
        with self.assertRaises(e.OverAllocationError):
            plan_allocations(D("500"), 1, [inv(1, "300"), inv(2, "500")], [(1, D("300")), (2, D("300"))])

    def test_draft_cancelled_and_paid_are_not_payable(self):
        for status in ("draft", "cancelled", "paid"):
            with self.assertRaises(e.InvoiceNotPayableError, msg=status):
                plan_allocations(D("100"), 1, [inv(1, "100", status)], [(1, D("10"))])

    def test_unknown_invoice_wrong_customer_duplicate_and_zero(self):
        with self.assertRaises(e.InvoiceNotFoundError):
            plan_allocations(D("100"), 1, [], [(9, D("10"))])
        with self.assertRaises(e.InvoiceCustomerMismatchError):
            plan_allocations(D("100"), 1, [inv(1, "100", customer=2)], [(1, D("10"))])
        with self.assertRaises(e.DuplicateAllocationError):
            plan_allocations(D("100"), 1, [inv(1, "100")], [(1, D("10")), (1, D("10"))])
        with self.assertRaises(e.InvalidPaymentError):
            plan_allocations(D("100"), 1, [inv(1, "100")], [(1, D("0"))])

    def test_error_codes_are_stable(self):
        self.assertEqual(e.OverAllocationError.code, "over_allocation")
        self.assertTrue(issubclass(e.OverAllocationError, e.BillingError))


if __name__ == "__main__":
    unittest.main()

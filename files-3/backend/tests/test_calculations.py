"""Pure unit tests for app/utils/calculations.py (no database). unittest style so they run with
either `python -m unittest` or pytest."""
import unittest
from datetime import date
from decimal import Decimal as D

from app.utils import calculations as c


class Money(unittest.TestCase):
    def test_floats_are_rejected(self):
        with self.assertRaises(c.CalculationError):
            c.round_money(10.5)

    def test_half_up_rounding(self):
        self.assertEqual(c.round_money(D("2.675")), D("2.68"))
        self.assertEqual(c.round_money(D("2.674")), D("2.67"))

    def test_quantity_rules(self):
        self.assertEqual(c.validate_quantity(3), 3)
        for bad in (0, -1, 1.5, True):
            with self.assertRaises(c.CalculationError):
                c.validate_quantity(bad)
        with self.assertRaises(c.CalculationError):
            c.validate_min_quantity(2, 5)
        c.validate_min_quantity(5, 5)

    def test_unit_price_adds_variant_extra(self):
        self.assertEqual(c.final_unit_price(D("1000"), D("560")), D("1560.00"))   # the brief's Odoo example
        self.assertEqual(c.final_unit_price(D("1000"), None), D("1000.00"))
        self.assertEqual(c.line_subtotal(D("2000.00"), 5), D("10000.00"))


class Tax(unittest.TestCase):
    def test_tax_on_amount_after_discount(self):
        line = c.compute_line(D("10000.00"), D("500.00"), D("18"))
        self.assertEqual((line.tax_amount, line.gross_amount), (D("1710.00"), D("11210.00")))

    def test_rate_bounds(self):
        for bad in (D("-1"), D("100.01")):
            with self.assertRaises(c.InvalidTaxRateError):
                c.validate_tax_rate(bad)
        self.assertEqual(c.validate_tax_rate(D("0")), D("0.00"))

    def test_zero_tax(self):
        self.assertEqual(c.calculate_tax(D("999.99"), D("0")), D("0.00"))


class Discounts(unittest.TestCase):
    def test_percentage_and_fixed(self):
        self.assertEqual(c.calculate_discount(D("10000"), c.PERCENTAGE, D("5")), D("500.00"))
        self.assertEqual(c.calculate_discount(D("10000"), c.FIXED, D("500")), D("500.00"))

    def test_fixed_is_capped_at_the_base(self):
        self.assertEqual(c.calculate_discount(D("300"), c.FIXED, D("500")), D("300.00"))

    def test_invalid_discounts(self):
        for args in ((D("100"), c.PERCENTAGE, D("101")), (D("100"), c.FIXED, D("0")), (D("100"), "bogus", D("5"))):
            with self.assertRaises(c.CalculationError):
                c.calculate_discount(*args)

    def test_split_sums_exactly(self):
        parts = c.allocate_proportionally(D("100.00"), [D("1"), D("1"), D("1")])
        self.assertEqual(sum(parts), D("100.00"))
        self.assertEqual(sorted(parts), [D("33.33"), D("33.33"), D("33.34")])
        self.assertEqual(c.allocate_proportionally(D("500.00"), [D("10000"), D("600")]),
                         [D("471.70"), D("28.30")])
        self.assertEqual(c.allocate_proportionally(D("0"), [D("5"), D("0")]), [D("0.00"), D("0.00")])

    def rule(self, **kw):
        base = dict(discount_type="percentage", value=D("5"))
        base.update(kw)
        return c.DiscountRule(**base)

    def test_eligible(self):
        v = c.check_discount_eligibility(self.rule(min_quantity=5), D("10000"), 5, date(2026, 11, 1))
        self.assertTrue(v.eligible)
        self.assertEqual(v.reasons, ())

    def test_expired_reason_is_an_exact_string(self):
        v = c.check_discount_eligibility(self.rule(valid_until=date(2026, 12, 31)), D("100"), 1, date(2027, 1, 1))
        self.assertFalse(v.eligible)
        self.assertIn("discount has expired", v.reasons)       # the uploaded invoice test relies on this

    def test_every_rule_can_reject(self):
        r = self.rule(min_purchase_amount=D("1000"), min_quantity=5, valid_from=date(2026, 6, 1),
                      usage_limit=2, redemption_count=2, per_customer_limit=1, customer_redemption_count=1,
                      is_active=False)
        v = c.check_discount_eligibility(r, D("10"), 1, date(2026, 1, 1))
        self.assertEqual(len(v.reasons), 6)      # 'not valid yet' and 'expired' cannot both apply
        self.assertIn("usage limit reached", v.reasons)
        self.assertIn("per-customer limit reached", v.reasons)

    def test_boundary_dates_are_inclusive(self):
        r = self.rule(valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31))
        for d in (date(2026, 1, 1), date(2026, 12, 31)):
            self.assertTrue(c.check_discount_eligibility(r, D("1"), 1, d).eligible)


class Totals(unittest.TestCase):
    def test_invoice_totals_match_the_seed_invoice(self):
        # sub 1 in the seed: 5 x 2000 + 2 x 300 at GST 18% -> 10600 + 1908 = 12508
        lines = [c.compute_line(D("10000.00"), D("0"), D("18")), c.compute_line(D("600.00"), D("0"), D("18"))]
        t = c.compute_invoice_totals(lines)
        self.assertEqual((t.subtotal, t.discount_total, t.tax_total, t.total),
                         (D("10600.00"), D("0.00"), D("1908.00"), D("12508.00")))

    def test_discounted_invoice_matches_the_loyal5_case(self):
        lines = [c.compute_line(D("10000.00"), D("500.00"), D("18")), c.compute_line(D("600.00"), D("0"), D("18"))]
        self.assertEqual(c.compute_invoice_totals(lines).total, D("11918.00"))

    def test_discount_larger_than_line_is_rejected(self):
        with self.assertRaises(c.CalculationError):
            c.compute_line(D("100"), D("101"), D("18"))


class BillingDates(unittest.TestCase):
    def end(self, start, period, interval=1, anchor=None):
        return c.billing_period_end(start, period, interval, anchor)

    def test_monthly(self):
        self.assertEqual(self.end(date(2026, 11, 1), "monthly", 1, date(2026, 3, 1)), date(2026, 11, 30))

    def test_quarterly_is_monthly_times_three(self):
        self.assertEqual(self.end(date(2027, 1, 1), "monthly", 3, date(2026, 1, 1)), date(2027, 3, 31))

    def test_yearly_and_weekly_and_daily(self):
        self.assertEqual(self.end(date(2026, 2, 1), "yearly"), date(2027, 1, 31))
        self.assertEqual(self.end(date(2026, 11, 2), "weekly"), date(2026, 11, 8))
        self.assertEqual(self.end(date(2026, 11, 2), "daily", 3), date(2026, 11, 4))

    def test_month_end_anchor_is_kept(self):
        self.assertEqual(c.next_period_start(date(2026, 1, 31), "monthly", 1), date(2026, 2, 28))
        self.assertEqual(c.next_period_start(date(2026, 2, 28), "monthly", 1, date(2026, 1, 31)), date(2026, 3, 31))

    def test_leap_year_anchor(self):
        self.assertEqual(c.next_period_start(date(2027, 2, 28), "yearly", 1, date(2024, 2, 29)), date(2028, 2, 29))

    def test_bad_inputs(self):
        with self.assertRaises(c.CalculationError):
            self.end(date(2026, 1, 1), "fortnightly")
        with self.assertRaises(c.CalculationError):
            self.end(date(2026, 1, 1), "monthly", 0)


if __name__ == "__main__":
    unittest.main()

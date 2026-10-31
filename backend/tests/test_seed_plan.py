"""Pure tests for scripts/seed_database.py planning (no database needed)."""
import sys
import unittest
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_database as sd  # noqa: E402

AS_OF = date(2026, 10, 31)


def catalog():
    """Mirrors db/02_seed.sql: 5 products, 7 variants, 4 plans, 3 payment terms."""
    products = [
        sd.ProductRow(1, "Brightloop CRM", "service", D("1500.00"), 4),
        sd.ProductRow(2, "Brightloop Helpdesk", "service", D("1200.00"), 4),
        sd.ProductRow(3, "Brightloop Analytics", "service", D("2500.00"), 4),
        sd.ProductRow(4, "Extra storage (100 GB)", "addon", D("300.00"), 4),
        sd.ProductRow(5, "Priority support", "addon", D("800.00"), 4),
    ]
    variants = {1: [sd.VariantRow(1, 1, "Starter", D("0")), sd.VariantRow(2, 1, "Pro", D("500")),
                    sd.VariantRow(3, 1, "Enterprise", D("1500"))],
                2: [sd.VariantRow(4, 2, "Standard", D("0")), sd.VariantRow(5, 2, "Pro", D("400"))],
                3: [sd.VariantRow(6, 3, "Standard", D("0")), sd.VariantRow(7, 3, "Premium", D("1000"))]}
    plans = [sd.PlanRow(1, "Monthly Standard", "monthly", 1, None, 1, date(2026, 1, 1), None),
             sd.PlanRow(2, "Quarterly Saver", "monthly", 3, None, 1, date(2026, 1, 1), None),
             sd.PlanRow(3, "Yearly Annual", "yearly", 1, 1, 1, date(2026, 1, 1), None),
             sd.PlanRow(4, "Weekly Trial", "weekly", 1, 4, 1, date(2026, 1, 1), date(2026, 12, 31))]
    return sd.Catalog(products, variants, plans, {"Immediate": 1, "Net 15": 2, "Net 30": 3}, admin_id=1)


class Customers(unittest.TestCase):
    def test_emails_are_unique_and_tagged(self):
        plans = [sd.plan_customer(i) for i in range(1, 3001)]
        self.assertEqual(len({p.email for p in plans}), 3000)
        self.assertEqual(len({p.tax_id for p in plans}), 3000)
        self.assertTrue(all(p.email.endswith("@seed.brightloop.test") for p in plans))


class Subscriptions(unittest.TestCase):
    def setUp(self):
        self.cat = catalog()
        self.subs = [sd.plan_subscription(i, AS_OF, 42, self.cat, 60) for i in range(1, 301)]

    def test_deterministic(self):
        again = [sd.plan_subscription(i, AS_OF, 42, self.cat, 60) for i in range(1, 301)]
        self.assertEqual(self.subs, again)
        other = [sd.plan_subscription(i, AS_OF, 43, self.cat, 60) for i in range(1, 301)]
        self.assertNotEqual(self.subs, other)

    def test_numbers_unique_and_customers_covered(self):
        self.assertEqual(len({s.number for s in self.subs}), 300)
        self.assertEqual({s.customer_index for s in self.subs}, set(range(1, 61)))

    def test_dates_and_plans(self):
        plans = {p.id: p for p in self.cat.plans}
        for s in self.subs:
            self.assertLess(s.start_date, AS_OF)
            self.assertGreaterEqual(s.start_date, date(2026, 1, 1))     # plan available_from
            self.assertNotEqual(s.plan_id, 4)                            # weekly trial excluded
            if s.expiry_date:
                self.assertGreater(s.expiry_date, s.start_date)
            self.assertIn(s.start_date.day, sd.ANCHOR_DAYS)
        self.assertEqual({plans[s.plan_id].billing_period for s in self.subs}, {"monthly", "yearly"})

    def test_lines_use_catalog_prices(self):
        prods = {p.id: p for p in self.cat.products}
        for s in self.subs:
            self.assertTrue(1 <= len(s.lines) <= 3)
            self.assertEqual(len({l.product_id for l in s.lines}), len(s.lines))
            for l in s.lines:
                extra = D("0")
                if l.variant_id:
                    extra = next(v.extra_price for v in self.cat.variants[l.product_id] if v.id == l.variant_id)
                self.assertEqual(l.unit_price, prods[l.product_id].sales_price + extra)
                self.assertGreaterEqual(l.quantity, 1)
                self.assertEqual(l.tax_id, 4)

    def test_final_states(self):
        st = sd.plan_final_states(120)
        self.assertEqual(Counter(st.values()), {"paused": 4, "closed": 4})
        self.assertTrue(all(i > 120 for i in st))
        self.assertEqual(len(sd.plan_final_states(5)), 2)

    def test_no_usable_plan_is_an_error(self):
        cat = sd.Catalog(self.cat.products, {}, [self.cat.plans[3]], self.cat.terms)
        with self.assertRaises(ValueError):
            sd.plan_subscription(1, AS_OF, 42, cat, 5)


class Payments(unittest.TestCase):
    def invoices(self, n=4000):
        out = []
        for i in range(n):
            issue = AS_OF - timedelta(days=(i * 7) % 230)
            due = issue + timedelta(days=(0, 15, 30)[i % 3])
            period = issue.replace(day=1) + timedelta(days=i % 5)
            total = D(1000 + (i * 137) % 40000) + D(i % 100) / 100
            out.append((i % 150 + 1, period, total, issue, due))
        return out

    def test_deterministic(self):
        a = [sd.plan_payments(42, s, p, t, i, d, AS_OF) for s, p, t, i, d in self.invoices(300)]
        b = [sd.plan_payments(42, s, p, t, i, d, AS_OF) for s, p, t, i, d in self.invoices(300)]
        self.assertEqual(a, b)

    def test_invariants(self):
        for s, p, total, issue, due in self.invoices():
            plans = sd.plan_payments(42, s, p, total, issue, due, AS_OF)
            allocated = sum((x.amount for x in plans if x.allocate), D("0"))
            self.assertLessEqual(allocated, total)                       # DB forbids overpayment
            self.assertEqual([x.seq for x in plans], list(range(1, len(plans) + 1)))
            refs = [x.gateway_reference for x in plans if x.gateway_reference]
            self.assertEqual(len(refs), len(set(refs)))
            for x in plans:
                self.assertGreater(x.amount, 0)
                self.assertLessEqual(x.transaction_date, AS_OF)
                self.assertGreaterEqual(x.transaction_date, issue)
                if x.status != "succeeded":
                    self.assertFalse(x.allocate)                         # failed/pending never settle
                self.assertEqual(x.allocate, x.status == "succeeded")
            outcome = plans[0].outcome if plans else None
            if outcome in ("paid_on_time", "paid_late", "paid"):
                self.assertEqual(allocated, total)                       # fully paid -> trigger => 'paid'
            if outcome == "part_paid":
                self.assertTrue(0 < allocated < total)

    def test_zero_total_has_no_payments(self):
        self.assertEqual(sd.plan_payments(42, 1, AS_OF, D("0"), AS_OF, AS_OF, AS_OF), [])

    def test_mix_gives_every_invoice_state(self):
        paid = part = unpaid = past_due_open = past_due = 0
        for s, p, total, issue, due in self.invoices():
            plans = sd.plan_payments(42, s, p, total, issue, due, AS_OF)
            allocated = sum((x.amount for x in plans if x.allocate), D("0"))
            if due < AS_OF:
                past_due += 1
                if allocated < total:
                    past_due_open += 1                                   # becomes 'overdue'
            if allocated == total:
                paid += 1
            elif allocated > 0:
                part += 1
            else:
                unpaid += 1
        n = 4000
        self.assertGreater(paid / n, 0.5)
        self.assertGreater(part / n, 0.03)
        self.assertGreater(unpaid / n, 0.03)
        share_overdue = past_due_open / past_due
        self.assertTrue(0.10 < share_overdue < 0.30, share_overdue)      # visible but not dominant

    def test_split_and_failed_attempts_occur(self):
        kinds = Counter()
        for s, p, total, issue, due in self.invoices():
            plans = sd.plan_payments(42, s, p, total, issue, due, AS_OF)
            kinds["split"] += sum(1 for x in plans if x.allocate) == 2
            kinds["failed"] += any(x.status == "failed" for x in plans)
            kinds["pending"] += any(x.status == "pending" for x in plans)
        for k in ("split", "failed", "pending"):
            self.assertGreater(kinds[k], 0, k)


if __name__ == "__main__":
    unittest.main()

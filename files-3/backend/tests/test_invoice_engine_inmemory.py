"""Billing engine tests that need NO database.

The repository functions are replaced by an in-memory fake loaded with the seed's subscriptions
1 and 2 (Oct 2026 anchor), so the real InvoiceService / DiscountService / TaxService /
calculations code runs end to end. Useful for teammates without Docker, and for CI speed.
The PostgreSQL-backed tests in test_invoice.py remain the source of truth for SQL and triggers.
"""
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal as D

from app.repositories import billing_repository as repo
from app.services.invoice_service import InvoiceService, ReferenceCache, run_billing

NOV1 = date(2026, 11, 1)
GST18 = {"id": 4, "name": "GST 18%", "rate_percent": D("18.00"), "is_active": True}
LOYAL5 = dict(id=3, code="LOYAL5", name="Loyalty 5%", discount_type="percentage", value=D("5.00"),
              min_purchase_amount=D("0.00"), min_quantity=5, valid_from=date(2026, 1, 1),
              valid_until=date(2026, 12, 31), usage_limit=None, per_customer_limit=None,
              auto_apply=True, is_active=True)
ANNUAL500 = dict(id=2, code="ANNUAL500", name="Annual 500 off", discount_type="fixed", value=D("500.00"),
                 min_purchase_amount=D("5000.00"), min_quantity=0, valid_from=date(2026, 1, 1),
                 valid_until=date(2026, 12, 31), usage_limit=50, per_customer_limit=1,
                 auto_apply=True, is_active=True)


def line(i, sid, product, variant, vproduct, qty, price, desc):
    return dict(id=i, subscription_id=sid, product_id=product, variant_id=variant, description=desc,
                quantity=qty, unit_price=D(price), discount_id=None, tax_id=4, product_active=True,
                default_tax_id=4, variant_product_id=vproduct, variant_active=True if variant else None)


class FakeConn:
    @contextmanager
    def begin_nested(self):
        yield self


class FakeDb:
    """Patches the repository module for the duration of a test and records every call."""

    def __init__(self):
        self.calls = {}
        self.invoices, self.invoice_lines, self.redemptions = [], [], []
        self.subs = {
            1: dict(id=1, customer_id=1, plan_id=1, payment_term_id=2, status="active",
                    start_date=date(2026, 3, 1), expiry_date=None, next_billing_date=NOV1,
                    last_billed_through=date(2026, 10, 31)),
            2: dict(id=2, customer_id=2, plan_id=1, payment_term_id=3, status="active",
                    start_date=date(2026, 5, 1), expiry_date=None, next_billing_date=NOV1,
                    last_billed_through=date(2026, 10, 31)),
        }
        self.lines = {
            1: [line(1, 1, 1, 2, 1, 5, "2000.00", "Brightloop CRM - Pro"),
                line(2, 1, 4, None, None, 2, "300.00", "Extra storage (100 GB)")],
            2: [line(3, 2, 2, 5, 2, 3, "1600.00", "Brightloop Helpdesk - Pro"),
                line(4, 2, 5, None, None, 1, "800.00", "Priority support")],
        }
        self.discount_rows = {3: LOYAL5, 2: ANNUAL500}
        self.discount_products = {3: {1}, 2: {3}}

    def count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def install(self):
        r, me = repo, self
        self._orig = {n: getattr(r, n) for n in dir(r) if not n.startswith("_") and callable(getattr(r, n))}

        def lock_subscription(conn, sid, skip_locked):
            me.count("lock_subscription")
            return dict(me.subs[sid]) if sid in me.subs else None

        def subscription_exists(conn, sid):
            return sid in me.subs

        def invoice_exists_for_period(conn, sid, start):
            return any(i["subscription_id"] == sid and i["period_start"] == start for i in me.invoices)

        def get_customer(conn, cid):
            me.count("get_customer")
            return dict(id=cid, name=f"Customer {cid}", email=f"c{cid}@x.test", currency="INR", is_active=True)

        def get_plan(conn, pid):
            me.count("get_plan")
            return dict(id=pid, name="Monthly Standard", billing_period="monthly", billing_interval=1,
                        min_quantity=1, is_active=True)

        def get_payment_term(conn, tid):
            me.count("get_payment_term")
            return dict(id=tid, name="term", due_days={2: 15, 3: 30}[tid])

        def get_taxes(conn, ids):
            me.count("get_taxes")
            return {4: GST18} if 4 in ids else {}

        def get_auto_apply_discounts(conn, on_date):
            me.count("get_auto_apply_discounts")
            return [ANNUAL500, LOYAL5]

        def get_discounts(conn, ids):
            return {i: me.discount_rows[i] for i in ids}

        def get_discount_products(conn, ids):
            return {i: set(me.discount_products.get(i, ())) for i in ids}

        def insert_invoice(conn, **v):
            n = len(me.invoices) + 1
            v["id"], v["invoice_number"] = n, f"INV-2026-{n:06d}"
            me.invoices.append(v)
            return {"id": n, "invoice_number": v["invoice_number"]}

        def insert_redemption(conn, did, iid, cid, amount):
            me.redemptions.append((did, iid, cid, amount))

        def update_subscription_billing(conn, sid, nxt, through):
            me.subs[sid]["next_billing_date"], me.subs[sid]["last_billed_through"] = nxt, through

        def due_subscription_ids(conn, as_of, ids=None, limit=None):
            return [s["id"] for s in me.subs.values()
                    if s["status"] == "active" and s["next_billing_date"] <= as_of and (not ids or s["id"] in ids)]

        fakes = dict(
            lock_subscription=lock_subscription, subscription_exists=subscription_exists,
            invoice_exists_for_period=invoice_exists_for_period, get_customer=get_customer,
            get_plan=get_plan, get_payment_term=get_payment_term, get_taxes=get_taxes,
            get_subscription_lines=lambda conn, sid: me.lines[sid],
            get_auto_apply_discounts=get_auto_apply_discounts, lock_limited_discounts=lambda *a, **k: None,
            get_discounts=get_discounts, get_discount_products=get_discount_products,
            count_redemptions=lambda conn, did, cid: (0, 0), insert_redemption=insert_redemption,
            insert_invoice=insert_invoice,
            insert_invoice_line=lambda conn, **v: me.invoice_lines.append(v),
            update_subscription_billing=update_subscription_billing,
            due_subscription_ids=due_subscription_ids,
            create_billing_run=lambda conn, d, u: 1, finish_billing_run=lambda *a, **k: None)
        for name, fn in fakes.items():
            setattr(r, name, fn)

    def restore(self):
        for name, fn in self._orig.items():
            setattr(repo, name, fn)


class InMemoryEngine(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.db.install()
        self.addCleanup(self.db.restore)
        self.conn = FakeConn()

        @contextmanager
        def scope():
            yield self.conn
        self.scope = scope

    def test_matches_historical_invoice_without_auto_discount(self):
        r = InvoiceService(self.conn, apply_auto_discounts=False).generate_for_subscription(1, NOV1)
        t = r.totals
        self.assertEqual((r.outcome, t.subtotal, t.discount_total, t.tax_total, t.total),
                         ("created", D("10600.00"), D("0.00"), D("1908.00"), D("12508.00")))
        inv = self.db.invoices[0]
        self.assertEqual((inv["status"], inv["period_start"], inv["period_end"], inv["due_date"]),
                         ("confirmed", NOV1, date(2026, 11, 30), date(2026, 11, 16)))      # Net 15
        self.assertEqual((self.db.subs[1]["next_billing_date"], self.db.subs[1]["last_billed_through"]),
                         (date(2026, 12, 1), date(2026, 11, 30)))

    def test_auto_discount_appears_on_the_invoice_by_itself(self):
        r = InvoiceService(self.conn).generate_for_subscription(1, NOV1)
        self.assertEqual((r.totals.discount_total, r.totals.tax_total, r.totals.total),
                         (D("500.00"), D("1818.00"), D("11918.00")))
        first = self.db.invoice_lines[0]
        self.assertEqual((first["discount_id"], first["discount_amount"], first["tax_amount"], first["line_total"]),
                         (3, D("500.00"), D("1710.00"), D("11210.00")))
        self.assertEqual(self.db.redemptions, [(3, 1, 1, D("500.00"))])

    def test_header_equals_sum_of_lines(self):
        InvoiceService(self.conn).generate_for_subscription(1, NOV1)
        inv, ls = self.db.invoices[0], self.db.invoice_lines
        self.assertEqual(inv["subtotal"], sum(l["quantity"] * l["unit_price"] for l in ls))
        self.assertEqual(inv["total"], sum(l["line_total"] for l in ls))
        self.assertEqual(inv["total"], inv["subtotal"] - inv["discount_total"] + inv["tax_total"])

    def test_nothing_is_billed_twice(self):
        svc = InvoiceService(self.conn)
        first, again = svc.generate_for_subscription(1, NOV1), svc.generate_for_subscription(1, NOV1)
        self.assertEqual((first.outcome, again.outcome, again.reason), ("created", "skipped", "not_due"))
        self.db.subs[1].update(next_billing_date=NOV1, last_billed_through=date(2026, 10, 31))   # rewind
        third = svc.generate_for_subscription(1, NOV1)
        self.assertEqual((third.outcome, third.reason), ("skipped", "already_billed"))
        self.assertEqual(len(self.db.invoices), 1)

    def test_not_due_paused_and_expired_are_skipped(self):
        svc = InvoiceService(self.conn)
        self.assertEqual(svc.generate_for_subscription(1, date(2026, 10, 31)).reason, "not_due")
        self.db.subs[2]["status"] = "paused"
        self.assertEqual(svc.generate_for_subscription(2, NOV1).reason, "subscription_paused")
        self.db.subs[2].update(status="active", expiry_date=date(2026, 10, 31))
        self.assertEqual(svc.generate_for_subscription(2, NOV1).reason, "expired")

    def test_billing_run_bills_everything_due_and_shares_reference_data(self):
        s = run_billing(self.scope, as_of=NOV1, apply_auto_discounts=True)
        self.assertEqual((s.checked, s.created, s.skipped, s.status), (2, 2, 0, "completed"))
        totals = {i["subscription_id"]: i["total"] for i in self.db.invoices}
        self.assertEqual(totals, {1: D("11918.00"), 2: D("6608.00")})
        # the point of ReferenceCache: one read per run instead of one per subscription
        c = self.db.calls
        self.assertEqual((c["get_plan"], c["get_auto_apply_discounts"], c["get_taxes"]), (1, 1, 1))
        self.assertEqual(c["get_payment_term"], 2)             # two different payment terms (Net 15, Net 30)
        self.assertEqual(c["get_customer"], 2)                 # customers stay live, one per invoice
        again = run_billing(self.scope, as_of=NOV1)
        self.assertEqual((again.checked, again.created), (0, 0))

    def test_without_a_shared_cache_every_invoice_rereads(self):
        for sid in (1, 2):
            InvoiceService(self.conn).generate_for_subscription(sid, NOV1)
        self.assertEqual(self.db.calls["get_plan"], 2)          # what the old code did for every subscription

    def test_reference_cache_does_not_cache_misses(self):
        cache = ReferenceCache()
        repo.get_plan = lambda conn, pid: None
        self.assertIsNone(cache.plan(self.conn, 99))
        repo.get_plan = lambda conn, pid: {"id": pid}
        self.assertEqual(cache.plan(self.conn, 99), {"id": 99})

    def test_one_bad_subscription_does_not_block_the_run(self):
        self.db.lines[1][0]["tax_id"] = 7                        # a tax that does not exist
        s = run_billing(self.scope, as_of=NOV1)
        self.assertEqual((s.created, len(s.errors), s.status), (1, 1, "completed_with_errors"))
        self.assertEqual((s.errors[0]["subscription_id"], s.errors[0]["code"]), (1, "tax_configuration"))


if __name__ == "__main__":
    unittest.main()

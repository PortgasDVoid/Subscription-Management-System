"""Automated invoice generation (Developer 3, task D).

Transaction model
-----------------
* ``InvoiceService.generate_for_subscription(conn, ...)`` does all its writes inside a
  SAVEPOINT on the caller's connection. If anything fails the savepoint rolls back, so
  there is never a half-written invoice. The caller owns the outer transaction/commit.
* ``run_billing(scope, ...)`` processes each due subscription in its OWN transaction
  (``scope()`` must be a context manager yielding a Connection, e.g. ``engine.begin``),
  so one bad subscription never blocks the others and row locks are short.

Duplicate / concurrency protection (three layers)
-------------------------------------------------
1. ``SELECT ... FOR UPDATE`` on the subscription row (batch uses SKIP LOCKED).
2. State check after the lock: next_billing_date / last_billed_through / existing invoice.
3. The database unique index ``uq_invoice_period`` (subscription_id, billing_period_start).

Performance: a ``ReferenceCache`` is shared by every subscription in one ``run_billing`` call, so
plans, payment terms, tax rows and auto-apply discount definitions are read once per run instead of
once per subscription. Anything that must be live (subscription row lock, redemption counts, discount
row locks, customer) is still read per invoice.

What is NOT done here (not in this schema/scope): sending e-mail, PDF, proration, and flipping
invoices to ``overdue`` (the nightly ``mark_overdue_invoices()`` does that). Renewing / closing
expired subscriptions lives in ``subscription_lifecycle_service.py``.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from sqlalchemy.exc import IntegrityError

from app.repositories import billing_repository as repo
from app.services.discount_service import DiscountLine, DiscountService
from app.services.errors import BillingError, InvoiceDataError, SubscriptionNotFoundError
from app.services.pricing_service import PricingService
from app.services.tax_service import TaxService
from app.utils import calculations as calc

CREATED, SKIPPED, ERROR = "created", "skipped", "error"


@dataclass
class InvoiceResult:
    subscription_id: int
    outcome: str                      # created | skipped | error
    reason: Optional[str] = None      # machine-readable code
    detail: Optional[str] = None
    invoice_id: Optional[int] = None
    invoice_number: Optional[str] = None
    totals: Optional[calc.InvoiceTotals] = None
    discounts_rejected: list = field(default_factory=list)


@dataclass
class BillingRunSummary:
    run_id: int
    run_date: date
    checked: int = 0
    created: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    results: list = field(default_factory=list)
    status: str = "completed"


class ReferenceCache:
    """Read-mostly reference rows shared across one billing run (never across runs)."""

    def __init__(self):
        self.plans: dict = {}
        self.terms: dict = {}
        self.taxes: dict = {}          # handed to TaxService, which fills it
        self._auto: dict = {}          # on_date -> auto_apply discount rows

    def plan(self, conn, plan_id):
        if plan_id not in self.plans:
            row = repo.get_plan(conn, plan_id)
            if row is None:
                return None            # do not cache misses
            self.plans[plan_id] = row
        return self.plans[plan_id]

    def term(self, conn, term_id):
        if term_id not in self.terms:
            row = repo.get_payment_term(conn, term_id)
            if row is None:
                return None
            self.terms[term_id] = row
        return self.terms[term_id]

    def auto_discounts(self, conn, on_date):
        if on_date not in self._auto:
            self._auto[on_date] = repo.get_auto_apply_discounts(conn, on_date)
        return self._auto[on_date]


class InvoiceService:
    def __init__(self, conn, *, auto_confirm: bool = True, apply_auto_discounts: bool = True,
                 allow_inactive_products: bool = False, cache: Optional[ReferenceCache] = None):
        self.conn = conn
        self.cache = cache if cache is not None else ReferenceCache()
        self.auto_confirm = auto_confirm
        self.apply_auto_discounts = apply_auto_discounts
        self.allow_inactive_products = allow_inactive_products
        self.pricing = PricingService(conn)
        self.taxes = TaxService(conn, self.cache.taxes)
        self.discounts = DiscountService(conn)

    # ------------------------------------------------------------------ #
    def generate_for_subscription(self, subscription_id: int, as_of: date,
                                  billing_run_id: Optional[int] = None, created_by: Optional[int] = None,
                                  skip_locked: bool = False) -> InvoiceResult:
        try:
            with self.conn.begin_nested():       # SAVEPOINT: all-or-nothing
                return self._generate(subscription_id, as_of, billing_run_id, created_by, skip_locked)
        except SubscriptionNotFoundError:
            raise
        except IntegrityError as exc:
            if "uq_invoice_period" in str(exc.orig):
                return InvoiceResult(subscription_id, SKIPPED, "already_billed",
                                     "another run created this invoice first")
            return InvoiceResult(subscription_id, ERROR, "database_error", str(exc.orig).splitlines()[0])
        except BillingError as exc:
            return InvoiceResult(subscription_id, ERROR, exc.code, str(exc))
        except calc.CalculationError as exc:
            return InvoiceResult(subscription_id, ERROR, "calculation_error", str(exc))

    # ------------------------------------------------------------------ #
    def _skip(self, sid, reason, detail=None) -> InvoiceResult:
        return InvoiceResult(sid, SKIPPED, reason, detail)

    def _generate(self, sid, as_of, run_id, created_by, skip_locked) -> InvoiceResult:
        sub = repo.lock_subscription(self.conn, sid, skip_locked)
        if sub is None:
            if not repo.subscription_exists(self.conn, sid):
                raise SubscriptionNotFoundError(f"subscription {sid} does not exist")
            return self._skip(sid, "locked_by_another_run")

        if sub["status"] != "active":
            return self._skip(sid, f"subscription_{sub['status']}")
        period_start = sub["next_billing_date"]
        if period_start is None:
            raise InvoiceDataError("active subscription has no next_billing_date")
        if period_start > as_of:
            return self._skip(sid, "not_due", f"next billing date is {period_start}")
        if sub["expiry_date"] and period_start > sub["expiry_date"]:
            return self._skip(sid, "expired", f"expired on {sub['expiry_date']}")
        if (sub["last_billed_through"] and period_start <= sub["last_billed_through"]) \
                or repo.invoice_exists_for_period(self.conn, sid, period_start):
            return self._skip(sid, "already_billed", f"period starting {period_start} already invoiced")

        customer = repo.get_customer(self.conn, sub["customer_id"])
        if customer is None or not customer["name"] or not customer["email"]:
            raise InvoiceDataError("customer information is missing")
        if not customer["is_active"]:
            return self._skip(sid, "customer_inactive")
        plan = self.cache.plan(self.conn, sub["plan_id"])
        term = self.cache.term(self.conn, sub["payment_term_id"])
        if plan is None or term is None:
            raise InvoiceDataError("plan or payment term is missing")
        rows = repo.get_subscription_lines(self.conn, sid)
        if not rows:
            raise InvoiceDataError("subscription has no lines")

        period_end = calc.billing_period_end(period_start, plan["billing_period"],
                                             plan["billing_interval"], anchor=sub["start_date"])

        # 1. validate + price lines (locked unit_price), 2. taxes, 3. discounts
        self.taxes.preload([r["tax_id"] for r in rows] + [r["default_tax_id"] for r in rows])
        subtotals, resolved = {}, {}
        for r in rows:
            self.pricing.validate_subscription_line(r, self.allow_inactive_products)
            subtotals[r["id"]] = calc.line_subtotal(r["unit_price"], r["quantity"])
            resolved[r["id"]] = self.taxes.resolve(r["tax_id"], r["default_tax_id"])
        plan_d = self.discounts.plan(
            customer["id"],
            [DiscountLine(r["id"], r["product_id"], r["quantity"], subtotals[r["id"]], r["discount_id"])
             for r in rows],
            on_date=as_of, apply_auto=self.apply_auto_discounts,
            auto_rows=self.cache.auto_discounts(self.conn, as_of) if self.apply_auto_discounts else [])

        amounts = {}
        for r in rows:
            _, disc = plan_d.for_line(r["id"])
            amounts[r["id"]] = calc.compute_line(subtotals[r["id"]], disc, resolved[r["id"]].rate_percent)
        totals = calc.compute_invoice_totals([amounts[r["id"]] for r in rows])

        status = "draft"
        if self.auto_confirm:
            status = "paid" if totals.total == 0 else "confirmed"   # nothing to collect on a 0 invoice
        inv = repo.insert_invoice(
            self.conn, subscription_id=sid, customer_id=customer["id"], billing_run_id=run_id,
            status=status, period_start=period_start, period_end=period_end, issue_date=as_of,
            due_date=as_of + timedelta(days=term["due_days"]), currency=customer["currency"],
            subtotal=totals.subtotal, discount_total=totals.discount_total, tax_total=totals.tax_total,
            total=totals.total, created_by=created_by)
        for r in rows:
            a = amounts[r["id"]]
            did, _ = plan_d.for_line(r["id"])
            repo.insert_invoice_line(
                self.conn, invoice_id=inv["id"], subscription_line_id=r["id"], product_id=r["product_id"],
                variant_id=r["variant_id"], description=r["description"], quantity=r["quantity"],
                unit_price=calc.round_money(r["unit_price"]), discount_id=did, discount_amount=a.discount,
                tax_id=resolved[r["id"]].tax_id, tax_rate=a.tax_rate, tax_amount=a.tax_amount,
                line_total=a.gross_amount)
        self.discounts.record_redemptions(inv["id"], customer["id"], plan_d)
        repo.update_subscription_billing(self.conn, sid, period_end + timedelta(days=1), period_end)
        return InvoiceResult(sid, CREATED, invoice_id=inv["id"], invoice_number=inv["invoice_number"],
                             totals=totals, discounts_rejected=plan_d.rejected)


# ---------------------------------------------------------------------- #
def run_billing(scope: Callable[[], AbstractContextManager], as_of: Optional[date] = None,
                triggered_by: Optional[int] = None, subscription_ids: Optional[list] = None,
                limit: Optional[int] = None, **service_options) -> BillingRunSummary:
    """Bill every due active subscription. ``scope()`` yields a Connection in its own transaction."""
    as_of = as_of or date.today()
    with scope() as conn:
        due = repo.due_subscription_ids(conn, as_of, subscription_ids, limit)
        run_id = repo.create_billing_run(conn, as_of, triggered_by)
    summary = BillingRunSummary(run_id=run_id, run_date=as_of, checked=len(due))
    cache = ReferenceCache()               # one cache per run, shared by every subscription
    try:
        for sid in due:
            with scope() as conn:
                res = InvoiceService(conn, cache=cache, **service_options).generate_for_subscription(
                    sid, as_of, billing_run_id=run_id, created_by=triggered_by, skip_locked=True)
            summary.results.append(res)
            if res.outcome == CREATED:
                summary.created += 1
            elif res.outcome == SKIPPED:
                summary.skipped += 1
            else:
                summary.errors.append({"subscription_id": sid, "code": res.reason, "detail": res.detail})
        summary.status = "completed_with_errors" if summary.errors else "completed"
    except Exception:
        summary.status = "failed"
        raise
    finally:
        with scope() as conn:
            repo.finish_billing_run(conn, run_id, summary.status, summary.checked, summary.created,
                                    summary.skipped, summary.errors)
    return summary

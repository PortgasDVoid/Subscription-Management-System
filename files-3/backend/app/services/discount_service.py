"""Discount selection and allocation for one invoice.

Rules (see DATABASE_MAPPING.md):
* Candidates = discounts pinned on subscription lines (subscription_lines.discount_id)
  plus active ``auto_apply`` discounts inside their validity window.
* Scope: a discount with rows in ``discount_products`` only touches lines of those
  products; with no rows it covers every line it is allowed to claim.
  A pinned discount covers only the lines pinned to it. An auto discount covers
  lines that have no pinned discount. A line carries at most one discount.
* Eligibility is evaluated on the scope lines: minimum purchase (sum of line
  subtotals), minimum quantity (sum of quantities), validity dates, total usage
  limit and per-customer limit (counted from discount_redemptions, ignoring
  cancelled invoices).
* Fixed discounts are capped at the eligible amount and split across lines in
  whole cents; percentage discounts are computed per line.
* Among competing auto discounts the biggest saving wins (ties: lowest id).
* Discounts with limits are row-locked (FOR UPDATE, id order) so two concurrent
  invoices cannot both take the last redemption.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.repositories import billing_repository as repo
from app.services.errors import DiscountConfigurationError
from app.utils import calculations as calc


@dataclass(frozen=True)
class DiscountLine:
    line_id: int
    product_id: int
    quantity: int
    subtotal: Decimal
    pinned_discount_id: Optional[int] = None


@dataclass(frozen=True)
class AppliedDiscount:
    discount_id: int
    code: str
    total_amount: Decimal
    line_amounts: dict  # line_id -> Decimal


@dataclass
class DiscountPlan:
    applied: list = field(default_factory=list)    # AppliedDiscount
    rejected: list = field(default_factory=list)   # (discount_id, code, reasons)

    def for_line(self, line_id: int):
        """(discount_id, amount) for the line, or (None, 0.00)."""
        for a in self.applied:
            if line_id in a.line_amounts:
                return a.discount_id, a.line_amounts[line_id]
        return None, calc.ZERO


class DiscountService:
    def __init__(self, conn):
        self.conn = conn

    # -- public ------------------------------------------------------------
    def plan(self, customer_id: int, lines: list, on_date: date, apply_auto: bool = True,
             lock: bool = True, auto_rows: Optional[list] = None) -> DiscountPlan:
        """``auto_rows``: pre-fetched auto_apply discounts for ``on_date`` (a billing run shares one
        query across all subscriptions). Redemption counts and row locks stay live per invoice."""
        pinned_ids = {l.pinned_discount_id for l in lines if l.pinned_discount_id is not None}
        if not apply_auto:
            auto_rows = []
        elif auto_rows is None:
            auto_rows = repo.get_auto_apply_discounts(self.conn, on_date)
        all_ids = sorted(pinned_ids | {d["id"] for d in auto_rows})
        if not all_ids:
            return DiscountPlan()
        if lock:
            repo.lock_limited_discounts(self.conn, all_ids)
        discounts = repo.get_discounts(self.conn, all_ids)
        products = repo.get_discount_products(self.conn, all_ids)
        result = DiscountPlan()
        claimed: set = set()

        for did in sorted(pinned_ids):
            d = discounts.get(did)
            if d is None:
                raise DiscountConfigurationError(f"discount {did} does not exist")
            scope = [l for l in lines if l.pinned_discount_id == did and self._in_scope(l, products[did])]
            outcome = self._evaluate(d, scope, customer_id, on_date)
            if isinstance(outcome, AppliedDiscount):
                result.applied.append(outcome)
                claimed.update(outcome.line_amounts)
            else:
                result.rejected.append((did, d["code"], outcome))

        candidates = [d for d in auto_rows if d["id"] not in pinned_ids]
        while candidates:
            free = [l for l in lines if l.line_id not in claimed and l.pinned_discount_id is None]
            best = None
            for d in candidates:
                scope = [l for l in free if self._in_scope(l, products[d["id"]])]
                outcome = self._evaluate(d, scope, customer_id, on_date)
                if isinstance(outcome, AppliedDiscount) and (
                        best is None or outcome.total_amount > best.total_amount):
                    best = outcome
            if best is None:
                break
            result.applied.append(best)
            claimed.update(best.line_amounts)
            candidates = [d for d in candidates if d["id"] != best.discount_id]
        return result

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _in_scope(line: DiscountLine, product_ids: set) -> bool:
        return not product_ids or line.product_id in product_ids

    def _evaluate(self, d: dict, scope: list, customer_id: int, on_date: date):
        """AppliedDiscount, or a tuple of rejection reasons."""
        if not scope:
            return ("no eligible lines",)
        eligible_amount = calc.round_money(sum((l.subtotal for l in scope), calc.ZERO))
        quantity = sum(l.quantity for l in scope)
        total_used, customer_used = repo.count_redemptions(self.conn, d["id"], customer_id)
        rule = calc.DiscountRule(
            discount_type=d["discount_type"], value=d["value"],
            min_purchase_amount=d["min_purchase_amount"], min_quantity=d["min_quantity"],
            valid_from=d["valid_from"], valid_until=d["valid_until"],
            usage_limit=d["usage_limit"], redemption_count=total_used,
            per_customer_limit=d["per_customer_limit"], customer_redemption_count=customer_used,
            is_active=d["is_active"])
        verdict = calc.check_discount_eligibility(rule, eligible_amount, quantity, on_date)
        if not verdict.eligible:
            return verdict.reasons
        try:
            if d["discount_type"] == calc.PERCENTAGE:
                amounts = [calc.calculate_discount(l.subtotal, calc.PERCENTAGE, d["value"]) for l in scope]
            else:
                total = calc.calculate_discount(eligible_amount, calc.FIXED, d["value"])
                amounts = calc.allocate_proportionally(total, [l.subtotal for l in scope])
        except calc.CalculationError as exc:
            raise DiscountConfigurationError(f"discount {d['code']}: {exc}") from None
        line_amounts = {l.line_id: a for l, a in zip(scope, amounts) if a > 0}
        if not line_amounts:
            return ("discount amount is zero",)
        return AppliedDiscount(d["id"], d["code"], calc.round_money(sum(line_amounts.values(), calc.ZERO)),
                               line_amounts)

    def record_redemptions(self, invoice_id: int, customer_id: int, plan: DiscountPlan) -> None:
        for a in plan.applied:
            repo.insert_redemption(self.conn, a.discount_id, invoice_id, customer_id, a.total_amount)

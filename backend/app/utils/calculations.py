"""Money, tax, discount and billing-period maths. Pure functions, no database.

RECONSTRUCTED STAND-IN: this module was not in the uploaded zips, so it was rebuilt from how
the pricing/tax/discount/invoice services and tests call it. If you still have the original
(32 unit tests), keep the original and only check the names the services import.

Rules: Decimal only (floats are rejected), cents rounded half-up, header totals are sums of
line values so every DB CHECK (total = subtotal - discount + tax) holds.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Optional, Sequence

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PERCENTAGE = "percentage"
FIXED = "fixed"


class CalculationError(ValueError):
    """Any invalid input to a calculation."""


class InvalidTaxRateError(CalculationError):
    pass


# ------------------------------------------------------------------ helpers
def to_decimal(value, name: str = "value") -> Decimal:
    if isinstance(value, (bool, float)):
        raise CalculationError(f"{name}: floats/bools are not allowed for money, use Decimal")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, str)):
        try:
            d = Decimal(value)
        except Exception:
            raise CalculationError(f"{name}: '{value}' is not a number") from None
    else:
        raise CalculationError(f"{name}: unsupported type {type(value).__name__}")
    if not d.is_finite():
        raise CalculationError(f"{name}: must be a finite number")
    return d


def round_money(value) -> Decimal:
    return to_decimal(value, "amount").quantize(CENT, rounding=ROUND_HALF_UP)


def non_negative_money(value, name: str = "amount") -> Decimal:
    d = round_money(to_decimal(value, name))
    if d < 0:
        raise CalculationError(f"{name} cannot be negative")
    return d


def validate_quantity(quantity) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise CalculationError("quantity must be a whole number")
    if quantity < 1:
        raise CalculationError("quantity must be at least 1")
    return quantity


def validate_min_quantity(quantity: int, min_quantity: int) -> None:
    if quantity < min_quantity:
        raise CalculationError(f"quantity {quantity} is below the plan minimum of {min_quantity}")


# ------------------------------------------------------------------ pricing
def final_unit_price(sales_price, extra_price=None) -> Decimal:
    """Final Unit Price = sales_price + variant extra_price."""
    base = non_negative_money(sales_price, "sales price")
    extra = round_money(to_decimal(extra_price, "extra price")) if extra_price is not None else ZERO
    price = base + extra
    if price < 0:
        raise CalculationError("final unit price cannot be negative")
    return price


def line_subtotal(unit_price, quantity) -> Decimal:
    return round_money(non_negative_money(unit_price, "unit price") * validate_quantity(quantity))


# ---------------------------------------------------------------------- tax
def validate_tax_rate(rate) -> Decimal:
    try:
        d = to_decimal(rate, "tax rate")
    except CalculationError as exc:
        raise InvalidTaxRateError(str(exc)) from None
    if d < 0 or d > 100:
        raise InvalidTaxRateError(f"tax rate {d} must be between 0 and 100")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_tax(taxable_amount, rate_percent) -> Decimal:
    """Tax = taxable (AFTER discount) x rate / 100, rounded to cents."""
    taxable = non_negative_money(taxable_amount, "taxable amount")
    return round_money(taxable * validate_tax_rate(rate_percent) / Decimal(100))


# ---------------------------------------------------------------- discounts
def calculate_discount(base_amount, discount_type: str, value) -> Decimal:
    base = non_negative_money(base_amount, "discount base")
    v = to_decimal(value, "discount value")
    if v <= 0:
        raise CalculationError("discount value must be greater than 0")
    if discount_type == PERCENTAGE:
        if v > 100:
            raise CalculationError("percentage discount cannot exceed 100")
        return round_money(base * v / Decimal(100))
    if discount_type == FIXED:
        return min(round_money(v), base)           # a fixed discount is capped at what it can claim
    raise CalculationError(f"unknown discount type '{discount_type}'")


def allocate_proportionally(total, weights: Sequence) -> list:
    """Split ``total`` across ``weights`` in whole cents (largest remainder); parts sum to total."""
    total_c = int((round_money(total) / CENT).to_integral_value())
    ws = [non_negative_money(w, "weight") for w in weights]
    wsum = sum(ws, ZERO)
    if not ws:
        if total_c:
            raise CalculationError("nothing to allocate to")
        return []
    if wsum == 0:
        if total_c:
            raise CalculationError("cannot split an amount across zero weights")
        return [ZERO for _ in ws]
    exact = [Decimal(total_c) * w / wsum for w in ws]
    parts = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    order = sorted(range(len(ws)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in order[: total_c - sum(parts)]:
        parts[i] += 1
    return [Decimal(p) * CENT for p in parts]


@dataclass(frozen=True)
class DiscountRule:
    discount_type: str
    value: Decimal
    min_purchase_amount: Decimal = ZERO
    min_quantity: int = 0
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    usage_limit: Optional[int] = None
    redemption_count: int = 0
    per_customer_limit: Optional[int] = None
    customer_redemption_count: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class EligibilityVerdict:
    eligible: bool
    reasons: tuple = ()


def check_discount_eligibility(rule: DiscountRule, eligible_amount, quantity: int,
                               on_date: date) -> EligibilityVerdict:
    """Reasons are exact, stable strings (the uploaded test matches 'discount has expired')."""
    reasons = []
    amount = round_money(eligible_amount)
    if not rule.is_active:
        reasons.append("discount is inactive")
    if rule.valid_from is not None and on_date < rule.valid_from:
        reasons.append("discount is not valid yet")
    if rule.valid_until is not None and on_date > rule.valid_until:
        reasons.append("discount has expired")
    if amount < round_money(rule.min_purchase_amount or ZERO):
        reasons.append(f"minimum purchase of {round_money(rule.min_purchase_amount)} not met")
    if quantity < (rule.min_quantity or 0):
        reasons.append(f"minimum quantity of {rule.min_quantity} not met")
    if rule.usage_limit is not None and rule.redemption_count >= rule.usage_limit:
        reasons.append("usage limit reached")
    if rule.per_customer_limit is not None and rule.customer_redemption_count >= rule.per_customer_limit:
        reasons.append("per-customer limit reached")
    return EligibilityVerdict(not reasons, tuple(reasons))


# ----------------------------------------------------------- line / invoice
@dataclass(frozen=True)
class LineAmounts:
    subtotal: Decimal
    discount: Decimal
    taxable: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    gross_amount: Decimal          # invoice_lines.line_total = subtotal - discount + tax


@dataclass(frozen=True)
class InvoiceTotals:
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


def compute_line(subtotal, discount, tax_rate) -> LineAmounts:
    sub = non_negative_money(subtotal, "line subtotal")
    disc = non_negative_money(discount, "line discount")
    if disc > sub:
        raise CalculationError("discount cannot exceed the line subtotal")
    rate = validate_tax_rate(tax_rate)
    taxable = sub - disc
    tax = calculate_tax(taxable, rate)
    return LineAmounts(sub, disc, taxable, rate, tax, taxable + tax)


def compute_invoice_totals(lines: Sequence[LineAmounts]) -> InvoiceTotals:
    sub = sum((l.subtotal for l in lines), ZERO)
    disc = sum((l.discount for l in lines), ZERO)
    tax = sum((l.tax_amount for l in lines), ZERO)
    total = sum((l.gross_amount for l in lines), ZERO)
    if total != sub - disc + tax:                      # defensive: mirrors the DB CHECK
        raise CalculationError("invoice totals are inconsistent")
    return InvoiceTotals(sub, disc, tax, total)


# ------------------------------------------------------------ billing dates
def add_months(d: date, months: int, day: Optional[int] = None) -> date:
    """Add whole months, keeping the anchor day-of-month (clamped to the month's length)."""
    year, month0 = divmod(d.year * 12 + (d.month - 1) + months, 12)
    month = month0 + 1
    want = day if day is not None else d.day
    return date(year, month, min(want, calendar.monthrange(year, month)[1]))


def next_period_start(period_start: date, billing_period: str, interval: int,
                      anchor: Optional[date] = None) -> date:
    if interval < 1:
        raise CalculationError("billing interval must be at least 1")
    day = (anchor or period_start).day
    if billing_period == "daily":
        return period_start + timedelta(days=interval)
    if billing_period == "weekly":
        return period_start + timedelta(weeks=interval)
    if billing_period == "monthly":
        return add_months(period_start, interval, day)
    if billing_period == "yearly":
        return add_months(period_start, 12 * interval, day)
    raise CalculationError(f"unknown billing period '{billing_period}'")


def billing_period_end(period_start: date, billing_period: str, interval: int = 1,
                       anchor: Optional[date] = None) -> date:
    """Last day covered by the period that starts on ``period_start``."""
    return next_period_start(period_start, billing_period, interval, anchor) - timedelta(days=1)

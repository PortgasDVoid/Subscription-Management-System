"""Deterministic Decimal-based pricing, discount and tax calculations."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

def money(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise ValueError("Invalid monetary value") from exc
    if not result.is_finite():
        raise ValueError("Monetary value must be finite")
    return result

def variant_unit_price(base_price, extra_price=0) -> Decimal:
    base, extra = money(base_price), money(extra_price)
    if base < 0 or extra < 0:
        raise ValueError("Prices cannot be negative")
    return money(base + extra)

def discount_amount(subtotal, *, kind: str, value, min_purchase=0, quantity=1,
                    min_quantity=0, valid_from: Optional[date]=None,
                    valid_until: Optional[date]=None, today: Optional[date]=None,
                    active=True, remaining_uses: Optional[int]=None,
                    already_used_by_customer: Optional[int]=0,
                    per_customer_limit: Optional[int]=None) -> Decimal:
    subtotal = money(subtotal); value = money(value)
    today = today or date.today()
    if subtotal < 0 or quantity < 1 or value <= 0:
        raise ValueError("Invalid subtotal, quantity or discount value")
    if not active or (valid_from and today < valid_from) or (valid_until and today > valid_until):
        return ZERO
    if subtotal < money(min_purchase) or quantity < int(min_quantity or 0):
        return ZERO
    if remaining_uses is not None and remaining_uses <= 0:
        return ZERO
    if per_customer_limit is not None and (already_used_by_customer or 0) >= per_customer_limit:
        return ZERO
    if kind == "fixed":
        amount = value
    elif kind == "percentage":
        if value > 100:
            raise ValueError("Percentage discount cannot exceed 100")
        amount = money(subtotal * value / Decimal("100"))
    else:
        raise ValueError("Discount kind must be fixed or percentage")
    return min(subtotal, amount)

def calculate_line(*, unit_price, quantity, tax_rate=0, discount=0):
    unit = money(unit_price); qty = int(quantity); rate = Decimal(str(tax_rate)); disc = money(discount)
    if qty < 1 or unit < 0 or disc < 0 or rate < 0 or rate > 100:
        raise ValueError("Invalid line inputs")
    subtotal = money(unit * qty)
    if disc > subtotal:
        raise ValueError("Discount cannot exceed line subtotal")
    taxable = money(subtotal - disc)
    tax = money(taxable * rate / Decimal("100"))
    return {"subtotal": subtotal, "discount": disc, "taxable": taxable,
            "tax": tax, "total": money(taxable + tax)}

def calculate_invoice(lines):
    subtotal = sum((money(x["subtotal"]) for x in lines), ZERO)
    discount = sum((money(x["discount"]) for x in lines), ZERO)
    tax = sum((money(x["tax"]) for x in lines), ZERO)
    return {"subtotal": money(subtotal), "discount_total": money(discount),
            "tax_total": money(tax), "total": money(subtotal-discount+tax)}

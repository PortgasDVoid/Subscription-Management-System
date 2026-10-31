"""Pricing: base price + variant extra price, quantity, plan minimum.

Billing uses the LOCKED ``subscription_lines.unit_price`` (the schema says it is
fixed at conversion time), so this service is used when a price is being set
(quotes / new subscription lines) and to validate lines before they are billed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.repositories import billing_repository as repo
from app.services.errors import (
    InactiveProductError, InactiveVariantError, PlanNotFoundError,
    ProductNotFoundError, VariantMismatchError, VariantNotFoundError,
)
from app.utils import calculations as calc


@dataclass(frozen=True)
class PricedLine:
    product_id: int
    variant_id: Optional[int]
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class PricingService:
    def __init__(self, conn):
        self.conn = conn

    def validate_product_variant(self, product_id: int, variant_id: Optional[int] = None,
                                 allow_inactive: bool = False) -> tuple:
        """Return (product_row, variant_row_or_None); raise a specific error otherwise."""
        product = repo.get_product(self.conn, product_id)
        if product is None:
            raise ProductNotFoundError(f"product {product_id} does not exist")
        if not product["is_active"] and not allow_inactive:
            raise InactiveProductError(f"product {product['sku']} is inactive")
        variant = None
        if variant_id is not None:
            variant = repo.get_variant(self.conn, variant_id)
            if variant is None:
                raise VariantNotFoundError(f"variant {variant_id} does not exist")
            if variant["product_id"] != product_id:
                raise VariantMismatchError(
                    f"variant {variant_id} belongs to product {variant['product_id']}, not {product_id}")
            if not variant["is_active"] and not allow_inactive:
                raise InactiveVariantError(f"variant {variant_id} is inactive")
        return product, variant

    def unit_price(self, product_id: int, variant_id: Optional[int] = None) -> Decimal:
        """Final Unit Price = products.sales_price + product_variants.extra_price."""
        product, variant = self.validate_product_variant(product_id, variant_id)
        return calc.final_unit_price(product["sales_price"], variant["extra_price"] if variant else None)

    def price_line(self, product_id: int, variant_id: Optional[int], quantity: int,
                   plan_id: Optional[int] = None) -> PricedLine:
        qty = calc.validate_quantity(quantity)
        if plan_id is not None:
            plan = repo.get_plan(self.conn, plan_id)
            if plan is None:
                raise PlanNotFoundError(f"plan {plan_id} does not exist")
            calc.validate_min_quantity(qty, plan["min_quantity"])
        price = self.unit_price(product_id, variant_id)
        return PricedLine(product_id, variant_id, qty, price, calc.line_subtotal(price, qty))

    def validate_subscription_line(self, line: dict, allow_inactive_products: bool = False) -> None:
        """Checks a joined subscription_lines row (see repository.get_subscription_lines)."""
        if not line["product_active"] and not allow_inactive_products:
            raise InactiveProductError(f"product {line['product_id']} is inactive")
        if line["variant_id"] is not None:
            if line["variant_product_id"] != line["product_id"]:
                raise VariantMismatchError(
                    f"line {line['id']}: variant {line['variant_id']} does not belong to "
                    f"product {line['product_id']}")
            if not line["variant_active"] and not allow_inactive_products:
                raise InactiveVariantError(f"variant {line['variant_id']} is inactive")
        calc.non_negative_money(line["unit_price"], "unit price")
        calc.validate_quantity(line["quantity"])

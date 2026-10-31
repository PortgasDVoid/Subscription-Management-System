"""Tax rates come from ``taxes``; nothing is hardcoded.

Resolution order for a subscription line: line.tax_id, else the product's
default_tax_id, else no tax (0%, tax_id NULL). Inactive / unknown taxes are a
configuration error (the invoice is not created). The rate used is returned so
the invoice line can snapshot it in ``tax_rate`` / ``tax_amount``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from app.repositories import billing_repository as repo
from app.services.errors import TaxConfigurationError
from app.utils import calculations as calc


@dataclass(frozen=True)
class ResolvedTax:
    tax_id: Optional[int]
    name: str
    rate_percent: Decimal


NO_TAX = ResolvedTax(None, "No tax", Decimal("0.00"))


class TaxService:
    def __init__(self, conn, cache: Optional[dict] = None):
        self.conn = conn
        # a dict shared across a billing run avoids re-reading the same tax rows per subscription
        self._cache: dict = cache if cache is not None else {}

    def preload(self, tax_ids: Iterable[Optional[int]]) -> None:
        missing = [i for i in tax_ids if i is not None and i not in self._cache]
        if missing:
            self._cache.update(repo.get_taxes(self.conn, missing))

    def get(self, tax_id: int) -> ResolvedTax:
        self.preload([tax_id])
        row = self._cache.get(tax_id)
        if row is None:
            raise TaxConfigurationError(f"tax {tax_id} does not exist")
        if not row["is_active"]:
            raise TaxConfigurationError(f"tax '{row['name']}' is inactive")
        try:
            rate = calc.validate_tax_rate(row["rate_percent"])
        except calc.InvalidTaxRateError as exc:
            raise TaxConfigurationError(f"tax '{row['name']}': {exc}") from None
        return ResolvedTax(row["id"], row["name"], rate)

    def resolve(self, line_tax_id: Optional[int], product_default_tax_id: Optional[int]) -> ResolvedTax:
        tax_id = line_tax_id if line_tax_id is not None else product_default_tax_id
        return NO_TAX if tax_id is None else self.get(tax_id)

    @staticmethod
    def tax_amount(taxable_amount, tax: ResolvedTax) -> Decimal:
        """Tax Amount = Taxable Amount x rate_percent / 100 (taxable is AFTER discount)."""
        return calc.calculate_tax(taxable_amount, tax.rate_percent)

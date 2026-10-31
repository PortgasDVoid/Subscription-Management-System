"""Record a payment and allocate it to invoices, with friendly errors.

Why this exists: the database already refuses over-payment (CHECK amount_paid <= total, the
allocation trigger), but it does so with raw errors. This service checks the same rules first and
raises ``PaymentError`` subclasses with stable ``code`` values the API can turn into clear messages.
The DB rules stay in place as the backstop; the triggers still own ``amount_paid`` and invoice status.

Rules
-----
* amount > 0, method must be a known payment_method, a gateway_reference can be used only once.
* Allocations (optional): list of (invoice_id, amount). Each invoice must exist, belong to the paying
  customer and be ``confirmed`` or ``overdue``; amount > 0 and <= what is still payable on it
  (amount_due minus money already promised by pending payments); no invoice twice; sum <= payment.
* No allocations given: the payment is applied oldest-due-first to the customer's open invoices.
  Whatever is left over stays unallocated on the payment (an advance), it is never forced onto an invoice.
* ``failed`` / ``refunded`` payments cannot be allocated.
* Invoices are row-locked in id order so two concurrent payments cannot both take the last rupee.

``plan_allocations`` is pure (no database) so the rules are unit-tested without PostgreSQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.exc import IntegrityError

from app.repositories import payment_repository as repo
from app.services.errors import (
    DuplicateAllocationError, DuplicatePaymentReferenceError, InvalidPaymentError,
    InvoiceCustomerMismatchError, InvoiceNotFoundError, InvoiceNotPayableError, OverAllocationError,
)
from app.utils import calculations as calc

PAYMENT_METHODS = {"cash", "bank_transfer", "card", "upi", "cheque", "online_gateway"}
PAYMENT_STATUSES = {"pending", "succeeded", "failed", "refunded"}
PAYABLE_INVOICE_STATUSES = {"confirmed", "overdue"}


@dataclass(frozen=True)
class PayableInvoice:
    """What the planner needs to know about an invoice (``payable`` already excludes pending money)."""
    id: int
    customer_id: int
    status: str
    payable: Decimal


@dataclass(frozen=True)
class PaymentResult:
    payment_id: int
    payment_number: str
    amount: Decimal
    allocations: list = field(default_factory=list)      # [(invoice_id, Decimal)]
    unallocated: Decimal = calc.ZERO


def _payable(row: dict) -> PayableInvoice:
    amount_due = calc.round_money(row["amount_due"])
    pending = calc.round_money(row["pending_allocated"])
    return PayableInvoice(row["id"], row["customer_id"], row["status"], max(amount_due - pending, calc.ZERO))


def plan_allocations(amount: Decimal, customer_id: int, invoices: Sequence[PayableInvoice],
                     requested: Optional[Sequence[tuple]] = None) -> list:
    """Return [(invoice_id, Decimal)] or raise a PaymentError. Pure: no database."""
    by_id = {i.id: i for i in invoices}

    if requested is None:                                    # oldest-first, as the caller ordered them
        remaining, out = amount, []
        for inv in invoices:
            if remaining <= 0:
                break
            if inv.customer_id != customer_id or inv.status not in PAYABLE_INVOICE_STATUSES or inv.payable <= 0:
                continue
            take = min(remaining, inv.payable)
            out.append((inv.id, take))
            remaining -= take
        return out

    seen, out, total = set(), [], calc.ZERO
    for invoice_id, raw in requested:
        part = calc.round_money(raw)
        if part <= 0:
            raise InvalidPaymentError(f"allocation to invoice {invoice_id} must be greater than 0")
        if invoice_id in seen:
            raise DuplicateAllocationError(f"invoice {invoice_id} appears more than once")
        seen.add(invoice_id)
        inv = by_id.get(invoice_id)
        if inv is None:
            raise InvoiceNotFoundError(f"invoice {invoice_id} does not exist")
        if inv.customer_id != customer_id:
            raise InvoiceCustomerMismatchError(f"invoice {invoice_id} belongs to a different customer")
        if inv.status == "paid":
            raise InvoiceNotPayableError(f"invoice {invoice_id} is already paid")
        if inv.status not in PAYABLE_INVOICE_STATUSES:
            raise InvoiceNotPayableError(f"invoice {invoice_id} is {inv.status}; only confirmed or overdue "
                                         "invoices can be paid")
        if part > inv.payable:
            raise OverAllocationError(f"invoice {invoice_id} has only {inv.payable} left to pay, "
                                      f"cannot allocate {part}")
        total += part
        out.append((invoice_id, part))
    if total > amount:
        raise OverAllocationError(f"allocations total {total}, more than the payment of {amount}")
    return out


def record_payment(conn, *, customer_id: int, amount, method: str, transaction_date: Optional[date] = None,
                   notes: Optional[str] = None, gateway_reference: Optional[str] = None,
                   recorded_by: Optional[int] = None, status: str = "succeeded",
                   allocations: Optional[Sequence[tuple]] = None) -> PaymentResult:
    """Create the payment and its allocations in one savepoint (all or nothing). Caller commits."""
    try:
        amt = calc.round_money(amount)
    except calc.CalculationError as exc:
        raise InvalidPaymentError(str(exc)) from None
    if amt <= 0:
        raise InvalidPaymentError("payment amount must be greater than 0")
    if method not in PAYMENT_METHODS:
        raise InvalidPaymentError(f"unknown payment method '{method}'")
    if status not in PAYMENT_STATUSES:
        raise InvalidPaymentError(f"unknown payment status '{status}'")
    if allocations and status in ("failed", "refunded"):
        raise InvalidPaymentError(f"a {status} payment cannot be allocated to invoices")
    if not repo.customer_exists(conn, customer_id):
        raise InvalidPaymentError(f"customer {customer_id} does not exist")
    if gateway_reference and repo.payment_id_by_gateway_reference(conn, gateway_reference) is not None:
        raise DuplicatePaymentReferenceError(f"payment reference '{gateway_reference}' was already recorded")

    try:
        with conn.begin_nested():
            if status in ("failed", "refunded"):
                planned, rows = [], []
            elif allocations is None:
                rows = repo.lock_open_invoices_for_customer(conn, customer_id)
                planned = plan_allocations(amt, customer_id, [_payable(r) for r in rows])
            else:
                rows = list(repo.lock_invoices(conn, [i for i, _ in allocations]).values())
                planned = plan_allocations(amt, customer_id, [_payable(r) for r in rows], allocations)

            pay = repo.insert_payment(
                conn, customer_id=customer_id, amount=amt, method=method, status=status,
                transaction_date=transaction_date or date.today(), gateway_reference=gateway_reference or None,
                notes=notes, recorded_by=recorded_by)
            for invoice_id, part in planned:
                repo.insert_allocation(conn, pay["id"], invoice_id, part)   # triggers update the invoice
    except IntegrityError as exc:
        if "uq_payment_gateway_ref" in str(exc.orig):
            raise DuplicatePaymentReferenceError(f"payment reference '{gateway_reference}' was already recorded") from None
        raise
    allocated = sum((p for _, p in planned), calc.ZERO)
    return PaymentResult(pay["id"], pay["payment_number"], amt, planned, amt - allocated)

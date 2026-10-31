"""All SQL for recording payments and allocating them to invoices (no business rules)."""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import text


def _one(result):
    row = result.mappings().first()
    return dict(row) if row else None


def _all(result):
    return [dict(r) for r in result.mappings().all()]


# Money already promised by PENDING payments does not reduce invoices.amount_due (only succeeded
# payments do), so it is reported separately and subtracted by the service.
_INVOICE_COLS = (
    "i.id, i.customer_id, i.status::text AS status, i.total, i.amount_paid, i.amount_due, i.due_date, "
    "COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id = pa.payment_id "
    "WHERE pa.invoice_id = i.id AND p.status = 'pending'), 0) AS pending_allocated"
)


def customer_exists(conn, customer_id: int) -> bool:
    return conn.execute(text("SELECT 1 FROM customers WHERE id = :id"), {"id": customer_id}).first() is not None


def lock_invoices(conn, invoice_ids: Iterable[int]) -> dict:
    """Row-lock the invoices (id order, so concurrent payments cannot deadlock) and return them by id."""
    ids = sorted(set(invoice_ids))
    if not ids:
        return {}
    rows = _all(conn.execute(text(
        f"SELECT {_INVOICE_COLS} FROM invoices i WHERE i.id = ANY(:ids) ORDER BY i.id FOR UPDATE OF i"
    ), {"ids": ids}))
    return {r["id"]: r for r in rows}


def lock_open_invoices_for_customer(conn, customer_id: int) -> list:
    """Payable invoices, oldest due date first (used when the caller does not pick invoices)."""
    return _all(conn.execute(text(
        f"SELECT {_INVOICE_COLS} FROM invoices i WHERE i.customer_id = :c "
        "AND i.status IN ('confirmed', 'overdue') AND i.amount_due > 0 "
        "ORDER BY i.due_date, i.id FOR UPDATE OF i"), {"c": customer_id}))


def payment_id_by_gateway_reference(conn, reference: str) -> Optional[int]:
    return conn.execute(text("SELECT id FROM payments WHERE gateway_reference = :r"),
                        {"r": reference}).scalar()


def insert_payment(conn, **v) -> dict:
    return _one(conn.execute(text(
        "INSERT INTO payments (customer_id, amount, method, status, transaction_date, gateway_reference, "
        "notes, recorded_by) VALUES (:customer_id, :amount, CAST(:method AS payment_method), "
        "CAST(:status AS payment_status), :transaction_date, :gateway_reference, :notes, :recorded_by) "
        "RETURNING id, payment_number"), v))


def insert_allocation(conn, payment_id: int, invoice_id: int, amount) -> None:
    conn.execute(text(
        "INSERT INTO payment_allocations (payment_id, invoice_id, amount) VALUES (:p, :i, :a)"),
        {"p": payment_id, "i": invoice_id, "a": amount})

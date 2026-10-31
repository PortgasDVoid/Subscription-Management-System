"""All SQL for pricing / tax / discount / invoicing lives here (no business rules).

Written against 01_schema.sql with plain SQL on a SQLAlchemy ``Connection`` so it
does not depend on anyone's ORM models. Every function takes the connection.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import text


def _one(result):
    row = result.mappings().first()
    return dict(row) if row else None


def _all(result):
    return [dict(r) for r in result.mappings().all()]


# ------------------------------ catalog ----------------------------------- #
def get_product(conn, product_id: int):
    return _one(conn.execute(text(
        "SELECT id, sku, name, sales_price, default_tax_id, is_active FROM products WHERE id = :id"
    ), {"id": product_id}))


def get_variant(conn, variant_id: int):
    return _one(conn.execute(text(
        "SELECT id, product_id, attribute, value, extra_price, is_active FROM product_variants WHERE id = :id"
    ), {"id": variant_id}))


def get_plan(conn, plan_id: int):
    return _one(conn.execute(text(
        "SELECT id, name, billing_period::text AS billing_period, billing_interval, min_quantity, "
        "is_active FROM plans WHERE id = :id"
    ), {"id": plan_id}))


def get_taxes(conn, tax_ids: Iterable[int]) -> dict:
    ids = sorted({i for i in tax_ids if i is not None})
    if not ids:
        return {}
    rows = _all(conn.execute(text(
        "SELECT id, name, rate_percent, is_active FROM taxes WHERE id = ANY(:ids)"
    ), {"ids": ids}))
    return {r["id"]: r for r in rows}


# ---------------------------- subscriptions ------------------------------- #
def due_subscription_ids(conn, as_of: date, subscription_ids: Optional[list] = None,
                         limit: Optional[int] = None) -> list:
    sql = ("SELECT id FROM subscriptions WHERE status = 'active' AND next_billing_date <= :as_of "
           + ("AND id = ANY(:ids) " if subscription_ids else "")
           + "ORDER BY next_billing_date, id" + (" LIMIT :limit" if limit else ""))
    params = {"as_of": as_of}
    if subscription_ids:
        params["ids"] = list(subscription_ids)
    if limit:
        params["limit"] = limit
    return [r[0] for r in conn.execute(text(sql), params).all()]


def subscription_exists(conn, subscription_id: int) -> bool:
    return conn.execute(text("SELECT 1 FROM subscriptions WHERE id = :id"),
                        {"id": subscription_id}).first() is not None


def lock_subscription(conn, subscription_id: int, skip_locked: bool):
    """Row lock = the concurrency guard. skip_locked=True returns None if another run holds it."""
    return _one(conn.execute(text(
        "SELECT id, customer_id, plan_id, payment_term_id, status::text AS status, start_date, "
        "expiry_date, next_billing_date, last_billed_through FROM subscriptions WHERE id = :id "
        "FOR UPDATE" + (" SKIP LOCKED" if skip_locked else "")
    ), {"id": subscription_id}))


def get_customer(conn, customer_id: int):
    return _one(conn.execute(text(
        "SELECT id, name, email, currency, is_active FROM customers WHERE id = :id"
    ), {"id": customer_id}))


def get_payment_term(conn, term_id: int):
    return _one(conn.execute(text(
        "SELECT id, name, due_days FROM payment_terms WHERE id = :id"), {"id": term_id}))


def get_subscription_lines(conn, subscription_id: int) -> list:
    return _all(conn.execute(text(
        "SELECT sl.id, sl.product_id, sl.variant_id, sl.description, sl.quantity, sl.unit_price, "
        "sl.discount_id, sl.tax_id, p.is_active AS product_active, p.default_tax_id, "
        "v.product_id AS variant_product_id, v.is_active AS variant_active "
        "FROM subscription_lines sl JOIN products p ON p.id = sl.product_id "
        "LEFT JOIN product_variants v ON v.id = sl.variant_id "
        "WHERE sl.subscription_id = :sid ORDER BY sl.id"), {"sid": subscription_id}))


def update_subscription_billing(conn, subscription_id: int, next_billing_date: date,
                                last_billed_through: date) -> None:
    conn.execute(text(
        "UPDATE subscriptions SET next_billing_date = :n, last_billed_through = :l WHERE id = :id"
    ), {"n": next_billing_date, "l": last_billed_through, "id": subscription_id})


# ------------------------------ discounts --------------------------------- #
_DISCOUNT_COLS = ("id, code, name, discount_type::text AS discount_type, value, min_purchase_amount, "
                  "min_quantity, valid_from, valid_until, usage_limit, per_customer_limit, "
                  "auto_apply, is_active")


def get_auto_apply_discounts(conn, on_date: date) -> list:
    return _all(conn.execute(text(
        f"SELECT {_DISCOUNT_COLS} FROM discounts WHERE auto_apply AND is_active "
        "AND (valid_from IS NULL OR valid_from <= :d) AND (valid_until IS NULL OR valid_until >= :d) "
        "ORDER BY id"), {"d": on_date}))


def lock_limited_discounts(conn, discount_ids: list) -> None:
    """Serialise redemption counting for discounts that have limits (taken in id order)."""
    if discount_ids:
        conn.execute(text(
            "SELECT id FROM discounts WHERE id = ANY(:ids) AND "
            "(usage_limit IS NOT NULL OR per_customer_limit IS NOT NULL) ORDER BY id FOR UPDATE"
        ), {"ids": sorted(discount_ids)})


def get_discounts(conn, discount_ids: list) -> dict:
    if not discount_ids:
        return {}
    rows = _all(conn.execute(text(
        f"SELECT {_DISCOUNT_COLS} FROM discounts WHERE id = ANY(:ids)"), {"ids": sorted(discount_ids)}))
    return {r["id"]: r for r in rows}


def get_discount_products(conn, discount_ids: list) -> dict:
    out = {i: set() for i in discount_ids}
    if discount_ids:
        for did, pid in conn.execute(text(
                "SELECT discount_id, product_id FROM discount_products WHERE discount_id = ANY(:ids)"),
                {"ids": sorted(discount_ids)}).all():
            out[did].add(pid)
    return out


def count_redemptions(conn, discount_id: int, customer_id: int) -> tuple:
    """(total, for this customer). Redemptions on cancelled invoices do not count."""
    row = conn.execute(text(
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE dr.customer_id = :c) FROM discount_redemptions dr "
        "JOIN invoices i ON i.id = dr.invoice_id WHERE dr.discount_id = :d AND i.status <> 'cancelled'"
    ), {"d": discount_id, "c": customer_id}).one()
    return int(row[0]), int(row[1])


def insert_redemption(conn, discount_id: int, invoice_id: int, customer_id: int, amount) -> None:
    conn.execute(text(
        "INSERT INTO discount_redemptions (discount_id, invoice_id, customer_id, amount) "
        "VALUES (:d, :i, :c, :a)"), {"d": discount_id, "i": invoice_id, "c": customer_id, "a": amount})


# ------------------------------- invoices --------------------------------- #
def invoice_exists_for_period(conn, subscription_id: int, period_start: date) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM invoices WHERE subscription_id = :s AND billing_period_start = :p "
        "AND status <> 'cancelled'"), {"s": subscription_id, "p": period_start}).first() is not None


def insert_invoice(conn, **v) -> dict:
    return _one(conn.execute(text(
        "INSERT INTO invoices (subscription_id, customer_id, billing_run_id, status, billing_period_start, "
        "billing_period_end, issue_date, due_date, currency, subtotal, discount_total, tax_total, total, "
        "confirmed_at, paid_at, created_by) VALUES (:subscription_id, :customer_id, :billing_run_id, "
        "CAST(:status AS invoice_status), :period_start, :period_end, :issue_date, :due_date, :currency, "
        ":subtotal, :discount_total, :tax_total, :total, "
        "CASE WHEN :status IN ('confirmed','paid') THEN now() END, "
        "CASE WHEN :status = 'paid' THEN now() END, :created_by) "
        "RETURNING id, invoice_number"), v))


def insert_invoice_line(conn, **v) -> None:
    conn.execute(text(
        "INSERT INTO invoice_lines (invoice_id, subscription_line_id, product_id, variant_id, description, "
        "quantity, unit_price, discount_id, discount_amount, tax_id, tax_rate, tax_amount, line_total) "
        "VALUES (:invoice_id, :subscription_line_id, :product_id, :variant_id, :description, :quantity, "
        ":unit_price, :discount_id, :discount_amount, :tax_id, :tax_rate, :tax_amount, :line_total)"), v)


# ----------------------------- billing runs ------------------------------- #
def create_billing_run(conn, run_date: date, triggered_by: Optional[int]) -> int:
    return conn.execute(text(
        "INSERT INTO billing_runs (run_date, triggered_by) VALUES (:d, :u) RETURNING id"),
        {"d": run_date, "u": triggered_by}).scalar_one()


def finish_billing_run(conn, run_id: int, status: str, checked: int, created: int, skipped: int,
                       errors: list) -> None:
    conn.execute(text(
        "UPDATE billing_runs SET status = CAST(:s AS billing_run_status), subscriptions_checked = :c, "
        "invoices_created = :n, invoices_skipped = :k, error_count = :e, "
        "errors = CAST(:j AS jsonb), finished_at = now() WHERE id = :id"),
        {"s": status, "c": checked, "n": created, "k": skipped, "e": len(errors),
         "j": json.dumps(errors) if errors else None, "id": run_id})

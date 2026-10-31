"""Seed a Brightloop database with demo-scale data (Developer 3).

What it creates (all rows are tagged so they can be found, re-run and removed):
  * customers  : users(role=customer) + customers   email  custNNNN@seed.brightloop.test
  * subscriptions : number SUB-SEED-NNNNN, 1-3 lines each, a mix of monthly / quarterly / yearly plans
  * invoices   : produced by the REAL billing engine (app.services.invoice_service.run_billing),
                 one billing run per due date, so history is made of confirmed invoices exactly as
                 production would make them (taxes, auto-discounts, redemptions included)
  * payments   : SEED-PAY-... inserted with payment_allocations; the database TRIGGERS then move each
                 invoice to paid / (part-paid) confirmed / overdue. Nothing sets those statuses by hand.
  * end states : a few subscriptions are paused / closed (terminated early) after their history is billed

Order:  customers -> subscriptions -> billing history -> payments -> pause/close -> mark_overdue_invoices()

Idempotent: every row has a fixed key (email, subscription_number, payment_number) and uses
ON CONFLICT DO NOTHING; child rows are only written for parents that were newly inserted, and invoices
are only paid once. Re-running with the same --seed and --as-of changes nothing. (A later --as-of can
bill new periods and settle invoices that were not yet due; it never duplicates existing ones.)

Usage (from backend/):
    python scripts/seed_database.py                         # 120 active subs, 60 customers
    python scripts/seed_database.py --subscriptions 5000 --customers 2500   # "thousands" scale
    python scripts/seed_database.py --reset                 # delete ONLY seed rows, then seed again
    DATABASE_URL=postgresql+psycopg2://... python scripts/seed_database.py

Prerequisite: db/01_schema.sql and db/02_seed.sql are loaded (catalog, plans, taxes, payment terms).
Note: the database's own CURRENT_DATE decides 'overdue' in the triggers, so keep --as-of at today
(the default) unless you are testing.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]          # backend/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils import calculations as calc            # pure, no database  # noqa: E402

SEED_EMAIL_DOMAIN = "seed.brightloop.test"
SUB_PREFIX = "SUB-SEED-"
PAY_PREFIX = "SEED-PAY-"
DEMO_PASSWORD_HASH = "$2b$12$Cl9dlTRCOMGNSBhRMGZ/3.1w/6uns7Cdnhmse09KCtmZM7.gzNLzm"   # Password@123
ANCHOR_DAYS = (1, 5, 10, 15, 20, 25)     # few billing days => few distinct billing runs
METHODS = ("cash", "bank_transfer", "card", "upi", "cheque", "online_gateway")
METHOD_WEIGHTS = (4, 34, 24, 28, 3, 7)
GATEWAY_METHODS = ("card", "upi", "online_gateway")
CENT = Decimal("0.01")

FIRST = ["Anjali", "Suresh", "Meera", "Vivek", "Divya", "Arjun", "Lakshmi", "Rahul", "Nisha", "Kiran",
         "Fathima", "George", "Sreeja", "Anil", "Deepa", "Joseph", "Reshma", "Manoj", "Asha", "Sandeep"]
LAST = ["Varma", "Kumar", "Iyer", "Pillai", "Menon", "Nair", "Thomas", "George", "Das", "Krishnan",
        "Joseph", "Mathew", "Warrier", "Panicker", "Rao", "Shetty"]
STEMS = ["Nila", "Kerali", "Blue Wave", "Green Field", "Sahyadri", "Malabar", "Backwater", "Spice Route",
         "Lotus", "Coastal", "Periyar", "Western Ghats", "Cardamom", "Monsoon", "Kovalam", "Munnar"]
SUFFIXES = ["Tech", "Digital", "Retail", "Logistics", "Foods", "Studios", "Labs", "Traders", "Health", "Systems"]
CITIES = [("Thiruvananthapuram", "Kerala", "695001"), ("Kochi", "Kerala", "682001"),
          ("Kozhikode", "Kerala", "673001"), ("Thrissur", "Kerala", "680001"),
          ("Bengaluru", "Karnataka", "560001"), ("Chennai", "Tamil Nadu", "600001")]
QTY_CHOICES = (1, 1, 2, 3, 5, 5, 8, 10, 12, 15, 25)


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ====================================================================== #
#  PURE PLANNING (no database; unit-tested in tests/test_seed_plan.py)    #
# ====================================================================== #
@dataclass(frozen=True)
class ProductRow:
    id: int
    name: str
    product_type: str
    sales_price: Decimal
    default_tax_id: Optional[int]


@dataclass(frozen=True)
class VariantRow:
    id: int
    product_id: int
    value: str
    extra_price: Decimal


@dataclass(frozen=True)
class PlanRow:
    id: int
    name: str
    billing_period: str
    billing_interval: int
    term_periods: Optional[int]
    min_quantity: int
    available_from: Optional[date]
    available_to: Optional[date]


@dataclass(frozen=True)
class Catalog:
    products: list
    variants: dict            # product_id -> [VariantRow]
    plans: list
    terms: dict               # payment term name -> id
    admin_id: Optional[int] = None

    def term_id(self, name: str) -> int:
        return self.terms[name] if name in self.terms else next(iter(self.terms.values()))


@dataclass(frozen=True)
class CustomerPlan:
    index: int
    email: str
    full_name: str
    company: str
    phone: str
    tax_id: str
    city: str
    state: str
    postal: str


@dataclass(frozen=True)
class LinePlan:
    product_id: int
    variant_id: Optional[int]
    description: str
    quantity: int
    unit_price: Decimal
    tax_id: Optional[int]


@dataclass(frozen=True)
class SubscriptionPlan:
    index: int
    number: str
    customer_index: int
    plan_id: int
    term_id: int
    start_date: date
    expiry_date: Optional[date]
    lines: tuple


@dataclass(frozen=True)
class PaymentPlan:
    seq: int                      # 1-based position within the invoice (part of the payment_number)
    amount: Decimal
    method: str
    status: str                   # succeeded | failed | pending
    transaction_date: date
    gateway_reference: Optional[str]
    notes: str
    allocate: bool                # only succeeded payments are allocated to the invoice
    outcome: str                  # paid_on_time | paid_late | paid | part_paid | unpaid


def plan_customer(index: int) -> CustomerPlan:
    first, last = FIRST[(index - 1) % len(FIRST)], LAST[(index * 7) % len(LAST)]
    stem = STEMS[(index - 1) % len(STEMS)]
    suffix = SUFFIXES[((index - 1) // len(STEMS)) % len(SUFFIXES)]
    city, state, postal = CITIES[index % len(CITIES)]
    return CustomerPlan(
        index=index, email=f"cust{index:04d}@{SEED_EMAIL_DOMAIN}", full_name=f"{first} {last}",
        company=f"{stem} {suffix}", phone=f"+91 98950 {20000 + index:05d}",
        tax_id=f"32AABCS{index:04d}A1Z5", city=city, state=state, postal=postal)


def _plan_weight(p: PlanRow) -> int:
    if p.billing_period == "monthly" and p.billing_interval == 1:
        return 70
    if p.billing_period == "monthly":
        return 20                      # quarterly etc.
    if p.billing_period == "yearly":
        return 10
    return 0                           # daily / weekly plans are not part of the demo mix


def plan_subscription(index: int, as_of: date, seed: int, catalog: Catalog,
                      n_customers: int, history_months: int = 8) -> SubscriptionPlan:
    rng = random.Random(f"{seed}:sub:{index}")
    usable = [p for p in catalog.plans
              if _plan_weight(p) > 0
              and (p.available_from is None or p.available_from <= as_of)
              and (p.available_to is None or p.available_to >= as_of)]
    if not usable:
        raise ValueError("no usable monthly/quarterly/yearly plan is available at the --as-of date")
    plan = rng.choices(usable, weights=[_plan_weight(p) for p in usable])[0]
    term = rng.choices(["Net 15", "Net 30", "Immediate"], weights=[40, 40, 20])[0]

    months_back = rng.randint(1, history_months)
    start = calc.add_months(as_of.replace(day=1), -months_back, rng.choice(ANCHOR_DAYS))
    if plan.available_from and start < plan.available_from:
        start = plan.available_from
    expiry = None
    if plan.term_periods:
        expiry = calc.next_period_start(start, plan.billing_period, plan.term_periods) - timedelta(days=1)

    services = [p for p in catalog.products if p.product_type != "addon"] or list(catalog.products)
    addons = [p for p in catalog.products if p.product_type == "addon"]
    chosen = [(rng.choice(services), rng.choice(QTY_CHOICES))]
    if addons:
        for p in rng.sample(addons, min(rng.choice([0, 0, 1, 1, 2]), len(addons))):
            chosen.append((p, rng.randint(1, 5)))
    lines = []
    for product, qty in chosen:
        variants = catalog.variants.get(product.id, [])
        variant = rng.choice(variants) if variants and rng.random() < 0.6 else None
        unit = calc.final_unit_price(product.sales_price, variant.extra_price if variant else None)
        lines.append(LinePlan(
            product_id=product.id, variant_id=variant.id if variant else None,
            description=f"{product.name} - {variant.value}" if variant else product.name,
            quantity=max(qty, plan.min_quantity), unit_price=unit, tax_id=product.default_tax_id))
    return SubscriptionPlan(index=index, number=f"{SUB_PREFIX}{index:05d}",
                            customer_index=(index - 1) % n_customers + 1, plan_id=plan.id,
                            term_id=catalog.term_id(term), start_date=start, expiry_date=expiry,
                            lines=tuple(lines))


def plan_final_states(n_active: int) -> dict:
    """Extra subscriptions (index n_active+1 ...) that end up paused or closed after billing."""
    each = max(1, n_active // 25)
    states = {}
    for k in range(each):
        states[n_active + 1 + k] = "paused"
        states[n_active + 1 + each + k] = "closed"
    return states


def plan_payments(seed: int, sub_index: int, period_start: date, total, issue_date: date,
                  due_date: date, as_of: date) -> list:
    """Deterministic payment story for one confirmed invoice. Pure: same inputs, same output."""
    total = money(total)
    if total <= 0:
        return []
    rng = random.Random(f"{seed}:pay:{sub_index}:{period_start.isoformat()}")
    past_due = due_date < as_of
    roll = rng.random()
    if past_due:
        outcome = ("paid_on_time" if roll < .76 else "paid_late" if roll < .85
                   else "part_paid" if roll < .92 else "unpaid")
    else:
        outcome = "paid" if roll < .45 else "part_paid" if roll < .55 else "unpaid"

    def pick_day(lo: date, hi: date) -> date:
        lo, hi = max(lo, issue_date), min(hi, as_of)
        return min(lo, as_of) if hi < lo else lo + timedelta(days=rng.randint(0, (hi - lo).days))

    pays: list = []

    def add(amount, day, status="succeeded", allocate=True, note="", method=None):
        method = method or rng.choices(METHODS, weights=METHOD_WEIGHTS)[0]
        seq = len(pays) + 1
        ref = (f"SEEDTXN-{sub_index:05d}-{period_start:%Y%m%d}-{seq}"
               if method in GATEWAY_METHODS else None)
        pays.append(PaymentPlan(seq, money(amount), method, status, day, ref, note, allocate, outcome))

    if rng.random() < 0.05:            # a declined attempt before the real payment (or instead of one)
        add(total, pick_day(issue_date, due_date), "failed", False, "Card declined (seed)", "card")

    if outcome in ("paid_on_time", "paid_late", "paid"):
        day = (pick_day(issue_date, due_date) if outcome == "paid_on_time"
               else pick_day(due_date + timedelta(days=1), due_date + timedelta(days=30))
               if outcome == "paid_late" else pick_day(issue_date, as_of))
        if total >= Decimal("0.02") and rng.random() < 0.10:      # paid in two instalments
            first = min(max(money(total * rng.randint(50, 70) / 100), CENT), total - CENT)
            add(first, day, note="Instalment 1 of 2 (seed)")
            add(total - first, min(as_of, day + timedelta(days=rng.randint(1, 20))),
                note="Instalment 2 of 2 (seed)")
        else:
            add(total, day, note=f"Seed payment ({outcome})")
    elif outcome == "part_paid":
        part = min(max(money(total * rng.randint(25, 75) / 100), CENT), total - CENT) \
            if total >= Decimal("0.02") else total
        add(part, pick_day(issue_date, as_of), note="Part payment (seed)")
    elif not past_due and rng.random() < 0.05:                    # unpaid, gateway still processing
        add(total, pick_day(issue_date, as_of), "pending", False, "Gateway pending (seed)", "online_gateway")
    return pays


# ====================================================================== #
#  DATABASE LAYER                                                         #
# ====================================================================== #
def _text(sql: str):
    from sqlalchemy import text
    return text(sql)


def _run(conn, sql: str, params: Optional[dict] = None):
    """Execute, passing only the bind parameters this statement mentions."""
    used = {k: v for k, v in (params or {}).items() if f":{k}" in sql}
    return conn.execute(_text(sql), used)


def load_catalog(conn) -> Catalog:
    def rows(sql):
        return conn.execute(_text(sql)).mappings().all()

    products = [ProductRow(r["id"], r["name"], r["product_type"], r["sales_price"], r["default_tax_id"])
                for r in rows("SELECT id, name, product_type, sales_price, default_tax_id FROM products "
                              "WHERE is_active ORDER BY id")]
    variants: dict = {}
    for r in rows("SELECT id, product_id, value, extra_price FROM product_variants WHERE is_active ORDER BY id"):
        variants.setdefault(r["product_id"], []).append(
            VariantRow(r["id"], r["product_id"], r["value"], r["extra_price"]))
    plans = [PlanRow(r["id"], r["name"], str(r["billing_period"]), r["billing_interval"], r["term_periods"],
                     r["min_quantity"], r["available_from"], r["available_to"])
             for r in rows("SELECT id, name, billing_period, billing_interval, term_periods, min_quantity, "
                           "available_from, available_to FROM plans WHERE is_active ORDER BY id")]
    terms = {r["name"]: r["id"] for r in rows("SELECT id, name FROM payment_terms WHERE is_active ORDER BY id")}
    admin = conn.execute(_text("SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1")).scalar()
    if not products or not plans or not terms:
        raise SystemExit("Catalog is empty. Load db/01_schema.sql and db/02_seed.sql first.")
    return Catalog(products, variants, plans, terms, admin)


def reset_seed_rows(conn) -> dict:
    """Delete ONLY rows created by this script. Order respects the foreign keys."""
    p = {"sub": SUB_PREFIX + "%", "pay": PAY_PREFIX + "%", "mail": "%@" + SEED_EMAIL_DOMAIN}
    out = {}
    for label, sql in [
        ("payment_allocations",
         "DELETE FROM payment_allocations WHERE payment_id IN (SELECT id FROM payments WHERE payment_number LIKE :pay)"),
        ("payments", "DELETE FROM payments WHERE payment_number LIKE :pay"),
        ("invoices",      # invoice_lines and discount_redemptions cascade
         "DELETE FROM invoices WHERE subscription_id IN (SELECT id FROM subscriptions WHERE subscription_number LIKE :sub)"),
        ("subscriptions",  # subscription_lines and subscription_events cascade
         "DELETE FROM subscriptions WHERE subscription_number LIKE :sub"),
        ("customers", "DELETE FROM customers WHERE email LIKE :mail"),
        ("users", "DELETE FROM users WHERE email LIKE :mail"),
    ]:
        out[label] = _run(conn, sql, p).rowcount
    return out


def ensure_customers(scope, n: int, admin_id) -> dict:
    ids = {}
    with scope() as conn:
        for i in range(1, n + 1):
            c = plan_customer(i)
            conn.execute(_text(
                "INSERT INTO users (email, password_hash, role, full_name, phone, email_verified_at, created_by) "
                "VALUES (:email, :hash, CAST('customer' AS user_role), :name, :phone, now(), :by) "
                "ON CONFLICT (email) DO NOTHING"),
                {"email": c.email, "hash": DEMO_PASSWORD_HASH, "name": c.full_name, "phone": c.phone, "by": admin_id})
            uid = conn.execute(_text("SELECT id FROM users WHERE email = :e"), {"e": c.email}).scalar_one()
            conn.execute(_text(
                "INSERT INTO customers (user_id, name, company_name, email, phone, tax_id, billing_line1, "
                "billing_city, billing_state, billing_postal) "
                "VALUES (:uid, :name, :company, :email, :phone, :tax, :line1, :city, :state, :postal) "
                "ON CONFLICT (user_id) DO NOTHING"),
                {"uid": uid, "name": c.full_name, "company": c.company, "email": c.email, "phone": c.phone,
                 "tax": c.tax_id, "line1": f"{10 + c.index} Tech Park Road", "city": c.city,
                 "state": c.state, "postal": c.postal})
            ids[i] = conn.execute(_text("SELECT id FROM customers WHERE user_id = :u"), {"u": uid}).scalar_one()
    return ids


def ensure_subscription(conn, sp: SubscriptionPlan, customer_id: int, admin_id) -> tuple:
    """Returns (subscription_id, created_now). Lines and the 'activated' event only for new rows."""
    row = conn.execute(_text(
        "INSERT INTO subscriptions (subscription_number, customer_id, plan_id, payment_term_id, status, "
        "start_date, expiry_date, next_billing_date, auto_renew, created_by, created_at) "
        "VALUES (:num, :cid, :plan, :term, CAST('active' AS subscription_status), :start, :expiry, :start, "
        "TRUE, :by, CAST(:start AS timestamptz)) "
        "ON CONFLICT (subscription_number) DO NOTHING RETURNING id"),
        {"num": sp.number, "cid": customer_id, "plan": sp.plan_id, "term": sp.term_id,
         "start": sp.start_date, "expiry": sp.expiry_date, "by": admin_id}).first()
    if row is None:
        sid = conn.execute(_text("SELECT id FROM subscriptions WHERE subscription_number = :n"),
                           {"n": sp.number}).scalar_one()
        return sid, False
    sid = row[0]
    for ln in sp.lines:
        conn.execute(_text(
            "INSERT INTO subscription_lines (subscription_id, product_id, variant_id, description, quantity, "
            "unit_price, tax_id) VALUES (:sid, :pid, :vid, :desc, :qty, :price, :tax)"),
            {"sid": sid, "pid": ln.product_id, "vid": ln.variant_id, "desc": ln.description,
             "qty": ln.quantity, "price": ln.unit_price, "tax": ln.tax_id})
    conn.execute(_text(
        "INSERT INTO subscription_events (subscription_id, from_status, to_status, event_type, reason, "
        "actor_user_id, created_at) VALUES (:sid, CAST('draft' AS subscription_status), "
        "CAST('active' AS subscription_status), 'activated', 'Seed data', :by, CAST(:start AS timestamptz))"),
        {"sid": sid, "by": admin_id, "start": sp.start_date})
    return sid, True


def bill_history(scope, sub_ids: list, as_of: date, log) -> dict:
    """Run the real billing engine once per distinct due date, oldest first, until nothing is due.

    run_billing creates ONE period per subscription per call, so a subscription that is several
    periods behind is caught up by successive runs. Subscriptions that do not progress (error or
    skip) are set aside and reported instead of looping forever."""
    from app.services.invoice_service import run_billing, CREATED
    stats = {"runs": 0, "created": 0, "set_aside": {}}
    remaining = set(sub_ids)
    while remaining:
        with scope() as conn:
            due_on = conn.execute(_text(
                "SELECT MIN(next_billing_date) FROM subscriptions WHERE status = 'active' "
                "AND next_billing_date <= :as_of AND id = ANY(:ids)"),
                {"as_of": as_of, "ids": sorted(remaining)}).scalar()
        if due_on is None:
            break
        summary = run_billing(scope, as_of=due_on, subscription_ids=sorted(remaining))
        stats["runs"] += 1
        stats["created"] += summary.created
        for res in summary.results:
            if res.outcome != CREATED:
                remaining.discard(res.subscription_id)
                if res.outcome != "skipped" or res.reason not in ("already_billed",):
                    stats["set_aside"][res.subscription_id] = f"{res.outcome}:{res.reason}"
        if summary.created == 0 and not summary.results:
            break
    return stats


def pay_invoices(scope, seed: int, as_of: date, admin_id) -> dict:
    stats = {"invoices": 0, "payments": 0, "allocations": 0}
    with scope() as conn:
        invoices = conn.execute(_text(
            "SELECT i.id, i.customer_id, i.total, i.issue_date, i.due_date, i.billing_period_start, "
            "s.subscription_number FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id "
            "WHERE s.subscription_number LIKE :pat AND i.status IN ('confirmed', 'overdue') AND i.total > 0 "
            "AND NOT EXISTS (SELECT 1 FROM payment_allocations pa WHERE pa.invoice_id = i.id) "
            "ORDER BY i.id"), {"pat": SUB_PREFIX + "%"}).mappings().all()
    for inv in invoices:
        sub_index = int(inv["subscription_number"].rsplit("-", 1)[1])
        plans = plan_payments(seed, sub_index, inv["billing_period_start"], inv["total"],
                              inv["issue_date"], inv["due_date"], as_of)
        if not plans:
            continue
        stats["invoices"] += 1
        with scope() as conn:                       # one short transaction per invoice
            for pp in plans:
                number = f"{PAY_PREFIX}{sub_index:05d}-{inv['billing_period_start']:%Y%m%d}-{pp.seq}"
                row = conn.execute(_text(
                    "INSERT INTO payments (payment_number, customer_id, amount, method, status, "
                    "transaction_date, gateway_reference, notes, recorded_by) "
                    "VALUES (:num, :cid, :amt, CAST(:method AS payment_method), CAST(:status AS payment_status), "
                    ":day, :ref, :notes, :by) ON CONFLICT DO NOTHING RETURNING id"),
                    {"num": number, "cid": inv["customer_id"], "amt": pp.amount, "method": pp.method,
                     "status": pp.status, "day": pp.transaction_date, "ref": pp.gateway_reference,
                     "notes": pp.notes, "by": admin_id}).first()
                if row is None:
                    continue
                stats["payments"] += 1
                if pp.allocate:
                    # the AFTER INSERT trigger recomputes amount_paid and the invoice status
                    conn.execute(_text("INSERT INTO payment_allocations (payment_id, invoice_id, amount) "
                                       "VALUES (:p, :i, :a)"), {"p": row[0], "i": inv["id"], "a": pp.amount})
                    stats["allocations"] += 1
    return stats


def apply_final_states(scope, states: dict, by_index: dict, as_of: date, admin_id) -> dict:
    out = {"paused": 0, "closed": 0}
    ts = f"{as_of.isoformat()} 10:00+00"
    with scope() as conn:
        for index, state in states.items():
            sid = by_index.get(index)
            if sid is None:
                continue
            if state == "paused":
                sql = ("UPDATE subscriptions SET status = 'paused', paused_at = CAST(:ts AS timestamptz) "
                       "WHERE id = :id AND status = 'active' RETURNING id")
                reason, event = "Customer requested pause (seed)", "paused"
            else:
                sql = ("UPDATE subscriptions SET status = 'closed', closed_at = CAST(:ts AS timestamptz), "
                       "closure_reason = 'terminated_early', closure_note = 'Closed early (seed)' "
                       "WHERE id = :id AND status = 'active' RETURNING id")
                reason, event = "Terminated early (seed)", "closed"
            if conn.execute(_text(sql), {"id": sid, "ts": ts}).first() is not None:
                out[state] += 1
                conn.execute(_text(
                    "INSERT INTO subscription_events (subscription_id, from_status, to_status, event_type, "
                    "reason, actor_user_id, created_at) VALUES (:id, CAST('active' AS subscription_status), "
                    "CAST(:to AS subscription_status), :ev, :reason, :by, CAST(:ts AS timestamptz))"),
                    {"id": sid, "to": state, "ev": event, "reason": reason, "by": admin_id, "ts": ts})
    return out


def finish_up(scope) -> dict:
    """Overdue flip (the nightly job) + cosmetic back-dating so time-based reports look real."""
    pat = {"sub": SUB_PREFIX + "%", "pay": PAY_PREFIX + "%"}
    with scope() as conn:
        flipped = _run(conn, "SELECT mark_overdue_invoices()").scalar()
        _run(conn, (
            "UPDATE invoices SET created_at = CAST(issue_date AS timestamptz) + interval '9 hours', "
            "confirmed_at = CAST(issue_date AS timestamptz) + interval '9 hours' "
            "WHERE subscription_id IN (SELECT id FROM subscriptions WHERE subscription_number LIKE :sub) "
            "AND created_at > CAST(issue_date AS timestamptz) + interval '1 day'"), pat)
        _run(conn, (
            "UPDATE invoices i SET paid_at = x.last_pay FROM ("
            "  SELECT pa.invoice_id, MAX(p.transaction_date)::timestamptz + interval '10 hours' AS last_pay "
            "  FROM payment_allocations pa JOIN payments p ON p.id = pa.payment_id "
            "  WHERE p.status = 'succeeded' AND p.payment_number LIKE :pay GROUP BY pa.invoice_id) x "
            "WHERE x.invoice_id = i.id AND i.status = 'paid' AND i.paid_at IS DISTINCT FROM x.last_pay"), pat)
        _run(conn, (
            "UPDATE payments SET created_at = CAST(transaction_date AS timestamptz) + interval '11 hours' "
            "WHERE payment_number LIKE :pay AND created_at > CAST(transaction_date AS timestamptz) + interval '1 day'"), pat)
    return {"marked_overdue": flipped}


def report(scope) -> None:
    pat = {"sub": SUB_PREFIX + "%", "pay": PAY_PREFIX + "%"}
    with scope() as conn:
        subs = _run(conn, (
            "SELECT status::text, COUNT(*) FROM subscriptions WHERE subscription_number LIKE :sub "
            "GROUP BY 1 ORDER BY 1"), pat).all()
        invs = _run(conn, (
            "SELECT i.status::text, COUNT(*), COALESCE(SUM(i.total),0), COALESCE(SUM(i.amount_due),0) "
            "FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id "
            "WHERE s.subscription_number LIKE :sub GROUP BY 1 ORDER BY 1"), pat).all()
        pays = _run(conn, (
            "SELECT status::text, COUNT(*), COALESCE(SUM(amount),0) FROM payments "
            "WHERE payment_number LIKE :pay GROUP BY 1 ORDER BY 1"), pat).all()
    print("\n  subscriptions : " + ", ".join(f"{s}={n}" for s, n in subs))
    print("  invoices      :")
    for status, n, total, due in invs:
        print(f"      {status:<10} {n:>6}   total {total:>14,.2f}   still due {due:>14,.2f}")
    print("  payments      : " + ", ".join(f"{s}={n} ({a:,.2f})" for s, n, a in pays))


# ====================================================================== #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--subscriptions", type=int, default=120, help="number of ACTIVE subscriptions (default 120)")
    ap.add_argument("--customers", type=int, default=60)
    ap.add_argument("--history-months", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42, help="same seed + as-of => same data")
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--database-url", help="overrides DATABASE_URL")
    ap.add_argument("--reset", action="store_true", help="delete previously seeded rows first")
    args = ap.parse_args(argv)
    if args.subscriptions < 1 or args.customers < 1:
        ap.error("--subscriptions and --customers must be at least 1")
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.db import scope                                   # after DATABASE_URL is settled
    t0 = time.perf_counter()

    def log(msg):
        print(f"[{time.perf_counter() - t0:7.1f}s] {msg}", flush=True)

    with scope() as conn:
        catalog = load_catalog(conn)
        if args.reset:
            log(f"reset: removed {reset_seed_rows(conn)}")
    states = plan_final_states(args.subscriptions)
    total_subs = args.subscriptions + len(states)

    cust_ids = ensure_customers(scope, args.customers, catalog.admin_id)
    log(f"customers ready: {len(cust_ids)}")

    by_index, new_subs = {}, 0
    for i in range(1, total_subs + 1):
        sp = plan_subscription(i, args.as_of, args.seed, catalog, args.customers, args.history_months)
        with scope() as conn:
            sid, created = ensure_subscription(conn, sp, cust_ids[sp.customer_index], catalog.admin_id)
        by_index[i] = sid
        new_subs += created
    log(f"subscriptions ready: {total_subs} ({new_subs} new)")

    stats = bill_history(scope, list(by_index.values()), args.as_of, log)
    log(f"billing history: {stats['runs']} runs, {stats['created']} invoices created")
    for sid, why in stats["set_aside"].items():
        log(f"   NOT billed: subscription {sid} -> {why}")

    pay = pay_invoices(scope, args.seed, args.as_of, catalog.admin_id)
    log(f"payments: {pay['payments']} inserted, {pay['allocations']} allocated, across {pay['invoices']} invoices")

    log(f"end states: {apply_final_states(scope, states, by_index, args.as_of, catalog.admin_id)}")
    log(f"finish: {finish_up(scope)}")
    report(scope)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

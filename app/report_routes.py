"""Finance dashboard / reports (staff) and the customer self-service portal."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from .deps import db, require, STAFF, customer_id_for

router = APIRouter(prefix="/api", tags=["reports"])
staff = require(*STAFF)
customer = require("customer")
OVERDUE_SQL = "(i.status='overdue' OR (i.status='confirmed' AND i.due_date < CURRENT_DATE))"


def _page(limit, offset):
    return max(1, min(limit, 200)), max(0, offset)


@router.get("/dashboard/summary")
@router.get("/reports/summary")
def summary(date_from: date | None = None, date_to: date | None = None, user=Depends(staff)):
    p = {"f": date_from, "t": date_to}
    with db().connect() as c:
        r = c.execute(text("""SELECT
          (SELECT count(*) FROM subscriptions WHERE status='active') active_subscriptions,
          (SELECT COALESCE(sum(mrr),0) FROM v_subscription_mrr) mrr,
          (SELECT COALESCE(sum(total),0) FROM invoices i WHERE i.status<>'cancelled'
              AND (CAST(:f AS date) IS NULL OR i.issue_date>=:f) AND (CAST(:t AS date) IS NULL OR i.issue_date<=:t)) billed_total,
          (SELECT COALESCE(sum(amount),0) FROM payments pm WHERE pm.status='succeeded'
              AND (CAST(:f AS date) IS NULL OR pm.transaction_date>=:f) AND (CAST(:t AS date) IS NULL OR pm.transaction_date<=:t)) collected_total,
          (SELECT COALESCE(sum(amount_due),0) FROM invoices WHERE status IN ('confirmed','overdue')) outstanding_total,
          (SELECT count(*) FROM invoices i WHERE """ + OVERDUE_SQL + """ AND i.amount_due>0) overdue_count,
          (SELECT COALESCE(sum(amount_due),0) FROM invoices i WHERE """ + OVERDUE_SQL + """) overdue_amount"""), p).mappings().one()
        by_status = c.execute(text("SELECT status::text s, count(*) n FROM subscriptions GROUP BY 1")).mappings().all()
        monthly = c.execute(text("""SELECT to_char(month,'Mon YY') label, billed_amount, collected_amount FROM v_monthly_financials
            ORDER BY month DESC LIMIT 12""")).mappings().all()
    out = {k: (int(v) if k in ("active_subscriptions", "overdue_count") else str(v)) for k, v in r.items()}
    out["subscriptions_by_status"] = {x["s"]: x["n"] for x in by_status}
    out["monthly"] = [{"label": m["label"], "billed": float(m["billed_amount"]), "collected": float(m["collected_amount"])} for m in reversed(monthly)]
    return out


@router.get("/reports/invoices")
def report_invoices(status: str | None = None, overdue_only: bool = False, customer_id: int | None = None,
                    date_from: date | None = None, date_to: date | None = None, q: str | None = None,
                    limit: int = 50, offset: int = 0, user=Depends(staff)):
    limit, offset = _page(limit, offset)
    where, p = ["1=1"], {"lim": limit, "off": offset}
    if status: where.append("i.status::text=:st"); p["st"] = status
    if overdue_only: where.append(OVERDUE_SQL + " AND i.amount_due>0")
    if customer_id: where.append("i.customer_id=:cid"); p["cid"] = customer_id
    if date_from: where.append("i.issue_date>=:df"); p["df"] = date_from
    if date_to: where.append("i.issue_date<=:dt"); p["dt"] = date_to
    if q: where.append("(i.invoice_number ILIKE :q OR c.name ILIKE :q)"); p["q"] = f"%{q}%"
    w = " AND ".join(where)
    with db().connect() as c:
        rows = c.execute(text(f"""SELECT i.id,i.invoice_number,c.name customer_name,i.status,i.issue_date,i.due_date,i.total,i.amount_paid,i.amount_due,
            GREATEST(CURRENT_DATE-i.due_date,0) days_overdue FROM invoices i JOIN customers c ON c.id=i.customer_id
            WHERE {w} ORDER BY i.due_date DESC, i.id DESC LIMIT :lim OFFSET :off"""), p).mappings().all()
        total = c.execute(text(f"SELECT count(*) FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE {w}"), p).scalar()
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/reports/subscriptions")
def report_subscriptions(status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0, user=Depends(staff)):
    limit, offset = _page(limit, offset)
    where, p = ["1=1"], {"lim": limit, "off": offset}
    if status: where.append("s.status::text=:st"); p["st"] = status
    if q: where.append("(s.subscription_number ILIKE :q OR c.name ILIKE :q)"); p["q"] = f"%{q}%"
    w = " AND ".join(where)
    with db().connect() as c:
        rows = c.execute(text(f"""SELECT s.id,s.subscription_number,c.name customer_name,pl.name plan_name,s.status,s.start_date,s.expiry_date,
            s.next_billing_date FROM subscriptions s JOIN customers c ON c.id=s.customer_id JOIN plans pl ON pl.id=s.plan_id
            WHERE {w} ORDER BY s.id DESC LIMIT :lim OFFSET :off"""), p).mappings().all()
        total = c.execute(text(f"SELECT count(*) FROM subscriptions s JOIN customers c ON c.id=s.customer_id WHERE {w}"), p).scalar()
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/reports/payments")
def report_payments(method: str | None = None, date_from: date | None = None, date_to: date | None = None,
                    limit: int = 50, offset: int = 0, user=Depends(staff)):
    limit, offset = _page(limit, offset)
    where, p = ["1=1"], {"lim": limit, "off": offset}
    if method: where.append("pm.method::text=:m"); p["m"] = method
    if date_from: where.append("pm.transaction_date>=:df"); p["df"] = date_from
    if date_to: where.append("pm.transaction_date<=:dt"); p["dt"] = date_to
    w = " AND ".join(where)
    with db().connect() as c:
        rows = c.execute(text(f"""SELECT pm.id,pm.payment_number,c.name customer_name,pm.method,pm.status,pm.amount,pm.transaction_date,pm.notes,
            (SELECT string_agg(i.invoice_number, ', ') FROM payment_allocations pa JOIN invoices i ON i.id=pa.invoice_id WHERE pa.payment_id=pm.id) invoices
            FROM payments pm JOIN customers c ON c.id=pm.customer_id WHERE {w} ORDER BY pm.transaction_date DESC, pm.id DESC LIMIT :lim OFFSET :off"""), p).mappings().all()
        total = c.execute(text(f"SELECT count(*) FROM payments pm WHERE {w}"), p).scalar()
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


# ------------------------------------------------------------------ customer portal
@router.get("/portal/subscriptions")
def portal_subscriptions(user=Depends(customer)):
    with db().connect() as c:
        cid = customer_id_for(c, user)
        rows = c.execute(text("""SELECT s.id,s.subscription_number,pl.name plan_name,pl.billing_period,s.status,s.start_date,s.expiry_date,
            s.next_billing_date,(SELECT COALESCE(sum(quantity*unit_price),0) FROM subscription_lines WHERE subscription_id=s.id) amount_per_period
            FROM subscriptions s JOIN plans pl ON pl.id=s.plan_id WHERE s.customer_id=:c ORDER BY s.id DESC"""), {"c": cid}).mappings().all()
    return {"items": [dict(r) for r in rows], "total": len(rows)}


@router.get("/portal/invoices")
def portal_invoices(limit: int = 50, offset: int = 0, user=Depends(customer)):
    limit, offset = _page(limit, offset)
    with db().connect() as c:
        cid = customer_id_for(c, user)
        rows = c.execute(text("""SELECT id,invoice_number,status,issue_date,due_date,total,amount_paid,amount_due FROM invoices
            WHERE customer_id=:c AND status<>'draft' ORDER BY issue_date DESC,id DESC LIMIT :l OFFSET :o"""), {"c": cid, "l": limit, "o": offset}).mappings().all()
        total = c.execute(text("SELECT count(*) FROM invoices WHERE customer_id=:c AND status<>'draft'"), {"c": cid}).scalar()
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/portal/subscriptions/{sid}/pause")
@router.post("/portal/subscriptions/{sid}/close")
def portal_blocked(sid: int, user=Depends(customer)):
    raise HTTPException(403, "Please contact the Brightloop team to change a subscription")

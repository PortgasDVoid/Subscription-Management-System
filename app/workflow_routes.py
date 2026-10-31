"""Business workflows: quotation -> subscription, subscription lifecycle, invoice actions, payments."""
from datetime import date, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from .billing import add_period
from .calculations import money, calculate_line, calculate_invoice
from .deps import db, require, STAFF, audit
from .emailer import send_email

router = APIRouter(prefix="/api", tags=["workflows"])
staff = require(*STAFF)


def _one(c, sql, params, msg="Record not found"):
    row = c.execute(text(sql), params).mappings().first()
    if not row: raise HTTPException(404, msg)
    return row


def _event(c, sid, frm, to, event, reason, actor):
    c.execute(text("""INSERT INTO subscription_events(subscription_id,from_status,to_status,event_type,reason,actor_user_id)
        VALUES (:s,CAST(:f AS subscription_status),CAST(:t AS subscription_status),:e,:r,:a)"""),
        {"s": sid, "f": frm, "t": to, "e": event, "r": reason, "a": actor})


# ---------------------------------------------------------------- quotations
class FromTemplate(BaseModel):
    customer_id: int; template_id: int
    plan_id: int | None = None; payment_term_id: int | None = None; notes: str | None = None


@router.post("/quotations/from-template", status_code=201)
def quotation_from_template(x: FromTemplate, user=Depends(staff)):
    """A sales rep starts from a template: plan, lines and validity come pre-filled."""
    with db().begin() as c:
        t = _one(c, "SELECT * FROM quotation_templates WHERE id=:i AND is_active", {"i": x.template_id}, "Template not found")
        _one(c, "SELECT id FROM customers WHERE id=:i", {"i": x.customer_id}, "Customer not found")
        plan_id = x.plan_id or t["plan_id"]; term_id = x.payment_term_id or t["payment_term_id"]
        if not plan_id or not term_id:
            raise HTTPException(422, "Template has no plan / payment term - supply plan_id and payment_term_id")
        tlines = c.execute(text("""SELECT l.*, p.name pname, p.sales_price, p.default_tax_id, v.value vvalue, COALESCE(v.extra_price,0) extra,
            COALESCE(tx.rate_percent,0) rate FROM quotation_template_lines l JOIN products p ON p.id=l.product_id
            LEFT JOIN product_variants v ON v.id=l.variant_id LEFT JOIN taxes tx ON tx.id=p.default_tax_id
            WHERE l.template_id=:t ORDER BY l.id"""), {"t": x.template_id}).mappings().all()
        if not tlines: raise HTTPException(422, "Template has no lines")
        today = date.today()
        qid = c.execute(text("""INSERT INTO quotations(customer_id,template_id,plan_id,payment_term_id,status,issue_date,valid_until,notes,created_by)
            VALUES (:c,:t,:p,:pt,'draft',:d,:v,:n,:u) RETURNING id"""),
            {"c": x.customer_id, "t": x.template_id, "p": plan_id, "pt": term_id, "d": today,
             "v": today + timedelta(days=t["validity_days"]), "n": x.notes, "u": user["id"]}).scalar_one()
        calcs = []
        for l in tlines:
            unit = money(l["sales_price"] + l["extra"])
            calc = calculate_line(unit_price=unit, quantity=l["quantity"], tax_rate=l["rate"])
            desc = l["pname"] + (f" - {l['vvalue']}" if l["vvalue"] else "")
            c.execute(text("""INSERT INTO quotation_lines(quotation_id,product_id,variant_id,description,quantity,unit_price,
                discount_amount,tax_id,tax_rate,tax_amount,line_total) VALUES (:q,:p,:v,:d,:qty,:u,0,:tx,:r,:ta,:lt)"""),
                {"q": qid, "p": l["product_id"], "v": l["variant_id"], "d": desc, "qty": l["quantity"], "u": unit,
                 "tx": l["default_tax_id"], "r": l["rate"], "ta": calc["tax"], "lt": calc["total"]})
            calcs.append(calc)
        tot = calculate_invoice(calcs)
        c.execute(text("UPDATE quotations SET subtotal=:s,discount_total=:d,tax_total=:t,total=:tt WHERE id=:i"),
                  {"s": tot["subtotal"], "d": tot["discount_total"], "t": tot["tax_total"], "tt": tot["total"], "i": qid})
        audit(c, user["id"], "quotation.create", "quotations", qid, None, {"template_id": x.template_id})
        return {"id": qid, **{k: str(v) for k, v in tot.items()}}


class QStatus(BaseModel):
    status: str


QUOTE_FLOW = {"draft": {"sent"}, "sent": {"approved", "rejected"}}


@router.post("/quotations/{qid}/status")
def quotation_status(qid: int, x: QStatus, user=Depends(staff)):
    with db().begin() as c:
        q = _one(c, "SELECT * FROM quotations WHERE id=:i FOR UPDATE", {"i": qid})
        if x.status not in QUOTE_FLOW.get(q["status"], set()):
            raise HTTPException(409, f"A {q['status']} quotation cannot become {x.status}")
        if q["valid_until"] < date.today() and x.status == "approved":
            raise HTTPException(409, "Quotation validity has passed")
        c.execute(text("UPDATE quotations SET status=CAST(:s AS quotation_status),approved_at=CASE WHEN :s='approved' THEN now() ELSE approved_at END WHERE id=:i"),
                  {"s": x.status, "i": qid})
        audit(c, user["id"], f"quotation.{x.status}", "quotations", qid, {"status": q["status"]}, {"status": x.status})
    return {"id": qid, "status": x.status}


class Convert(BaseModel):
    start_date: date | None = None


@router.post("/quotations/{qid}/convert", status_code=201)
def quotation_convert(qid: int, x: Convert, user=Depends(staff)):
    with db().begin() as c:
        q = _one(c, "SELECT * FROM quotations WHERE id=:i FOR UPDATE", {"i": qid})
        if q["status"] != "approved":
            raise HTTPException(409, "Only an approved quotation can be converted")
        plan = _one(c, "SELECT * FROM plans WHERE id=:i", {"i": q["plan_id"]})
        start = x.start_date or date.today()
        expiry = None
        if plan["term_periods"]:
            expiry = add_period(start, plan["billing_period"], plan["term_periods"]) - timedelta(days=1)
        sid = c.execute(text("""INSERT INTO subscriptions(customer_id,quotation_id,plan_id,payment_term_id,status,start_date,expiry_date,
            auto_renew,created_by) VALUES (:c,:q,:p,:pt,'confirmed',:s,:e,:ar,:u) RETURNING id"""),
            {"c": q["customer_id"], "q": qid, "p": q["plan_id"], "pt": q["payment_term_id"], "s": start, "e": expiry,
             "ar": plan["auto_renew"], "u": user["id"]}).scalar_one()
        c.execute(text("""INSERT INTO subscription_lines(subscription_id,product_id,variant_id,description,quantity,unit_price,discount_id,tax_id)
            SELECT :s,product_id,variant_id,description,quantity,unit_price,discount_id,tax_id FROM quotation_lines WHERE quotation_id=:q"""),
            {"s": sid, "q": qid})
        c.execute(text("UPDATE quotations SET status='converted' WHERE id=:i"), {"i": qid})
        _event(c, sid, None, "confirmed", "created_from_quotation", f"Converted from quotation {q['quotation_number']}", user["id"])
        audit(c, user["id"], "quotation.convert", "quotations", qid, None, {"subscription_id": sid})
        return {"subscription_id": sid, "status": "confirmed"}


# ---------------------------------------------------------------- subscriptions
class AddLine(BaseModel):
    product_id: int; variant_id: int | None = None; quantity: int = Field(ge=1); discount_id: int | None = None


@router.post("/subscriptions/{sid}/lines", status_code=201)
def subscription_add_line(sid: int, x: AddLine, user=Depends(staff)):
    with db().begin() as c:
        s = _one(c, "SELECT status FROM subscriptions WHERE id=:i FOR UPDATE", {"i": sid})
        if s["status"] not in ("draft", "quotation", "confirmed"):
            raise HTTPException(409, "Lines can only be edited before the subscription is active")
        p = _one(c, "SELECT * FROM products WHERE id=:i AND is_active", {"i": x.product_id}, "Product not found")
        extra, label = Decimal("0"), p["name"]
        if x.variant_id:
            v = _one(c, "SELECT * FROM product_variants WHERE id=:i AND product_id=:p AND is_active", {"i": x.variant_id, "p": x.product_id}, "Variant not found for this product")
            extra, label = v["extra_price"], f"{p['name']} - {v['value']}"
        lid = c.execute(text("""INSERT INTO subscription_lines(subscription_id,product_id,variant_id,description,quantity,unit_price,discount_id,tax_id)
            VALUES (:s,:p,:v,:d,:q,:u,:di,:t) RETURNING id"""),
            {"s": sid, "p": x.product_id, "v": x.variant_id, "d": label, "q": x.quantity, "u": money(p["sales_price"] + extra),
             "di": x.discount_id, "t": p["default_tax_id"]}).scalar_one()
        return {"id": lid, "description": label, "unit_price": str(money(p["sales_price"] + extra))}


class Transition(BaseModel):
    action: str; reason: str | None = None; start_date: date | None = None


@router.post("/subscriptions/{sid}/transition")
def subscription_transition(sid: int, x: Transition, user=Depends(staff)):
    """Draft -> Quotation -> Confirmed -> Active -> Closed, plus pause / resume / renew."""
    a = x.action
    with db().begin() as c:
        s = _one(c, "SELECT * FROM subscriptions WHERE id=:i FOR UPDATE", {"i": sid})
        plan = _one(c, "SELECT * FROM plans WHERE id=:i", {"i": s["plan_id"]})
        cur = s["status"]; today = date.today(); sets = {}; new = None; ev = a; reason = x.reason

        def need(*states):
            if cur not in states: raise HTTPException(409, f"Cannot {a} a subscription that is {cur}")

        if a == "send_quotation": need("draft"); new = "quotation"
        elif a == "confirm": need("quotation"); new = "confirmed"
        elif a == "activate":
            need("confirmed")
            start = x.start_date or s["start_date"]
            if plan["available_from"] and start < plan["available_from"] or plan["available_to"] and start > plan["available_to"]:
                raise HTTPException(409, "Plan is not available on the chosen start date")
            lines = c.execute(text("SELECT quantity FROM subscription_lines WHERE subscription_id=:i"), {"i": sid}).scalars().all()
            if not lines: raise HTTPException(409, "Add at least one line before activating")
            if any(q < plan["min_quantity"] for q in lines):
                raise HTTPException(409, f"Plan requires a minimum quantity of {plan['min_quantity']} per line")
            sets = {"start_date": start, "next_billing_date": start}
            new = "active"; ev = "activated"
        elif a == "pause":
            need("active")
            if not plan["pause_allowed"]: raise HTTPException(409, "This plan does not allow pausing")
            sets = {"paused_at": "now()"}; new = "paused"; ev = "paused"
        elif a == "resume":
            need("paused")
            sets = {"resumed_at": "now()", "next_billing_date": max(s["next_billing_date"] or today, today)}
            new = "active"; ev = "resumed"   # paused time is not back-billed
        elif a == "close":
            need("confirmed", "active", "paused", "quotation", "draft")
            if cur in ("active", "paused") and not plan["early_termination_allowed"] and user["role"] != "admin":
                raise HTTPException(403, "This plan cannot be closed early (admin override required)")
            sets = {"closed_at": "now()", "closure_reason": "terminated_early" if cur in ("active", "paused") else "cancelled",
                    "closure_note": reason}
            new = "closed"; ev = "closed"
        elif a == "renew":
            need("active", "paused")
            base = s["expiry_date"] or today
            span = plan["term_periods"] or 1
            sets = {"expiry_date": add_period(base + timedelta(days=1), plan["billing_period"], span) - timedelta(days=1),
                    "renewal_count": s["renewal_count"] + 1}
            new = cur; ev = "renewed"
        else:
            raise HTTPException(422, "Unknown action")

        assign, params = [], {"i": sid}
        if new != cur: assign.append("status=CAST(:status AS subscription_status)"); params["status"] = new
        for k, v in sets.items():
            if v == "now()": assign.append(f"{k}=now()")
            else: assign.append(f"{k}=:{k}"); params[k] = v
        if assign:
            c.execute(text(f"UPDATE subscriptions SET {','.join(assign)} WHERE id=:i"), params)
        _event(c, sid, cur, new, ev, reason, user["id"])
        audit(c, user["id"], f"subscription.{ev}", "subscriptions", sid, {"status": cur}, {"status": new})
        return {"id": sid, "status": new}


# ---------------------------------------------------------------- invoices
class Reason(BaseModel):
    reason: str | None = None


@router.post("/invoices/mark-overdue")
def mark_overdue(user=Depends(staff)):
    with db().begin() as c:
        return {"marked_overdue": c.execute(text("SELECT mark_overdue_invoices()")).scalar()}


@router.post("/invoices/{iid}/confirm")
def invoice_confirm(iid: int, user=Depends(staff)):
    with db().begin() as c:
        i = _one(c, "SELECT status,total FROM invoices WHERE id=:i FOR UPDATE", {"i": iid})
        if i["status"] != "draft": raise HTTPException(409, f"Only a draft invoice can be confirmed (this one is {i['status']})")
        c.execute(text("UPDATE invoices SET status='confirmed',confirmed_at=now() WHERE id=:i"), {"i": iid})
        audit(c, user["id"], "invoice.confirm", "invoices", iid, {"status": "draft"}, {"status": "confirmed"})
    return {"id": iid, "status": "confirmed"}


@router.post("/invoices/{iid}/cancel")
def invoice_cancel(iid: int, x: Reason, user=Depends(staff)):
    with db().begin() as c:
        i = _one(c, "SELECT status,amount_paid FROM invoices WHERE id=:i FOR UPDATE", {"i": iid})
        if i["status"] in ("cancelled", "paid") or i["amount_paid"] > 0:
            raise HTTPException(409, "Paid or part-paid invoices cannot be cancelled - refund the payment first")
        c.execute(text("UPDATE invoices SET status='cancelled',cancelled_at=now(),cancel_reason=:r WHERE id=:i"), {"i": iid, "r": x.reason})
        audit(c, user["id"], "invoice.cancel", "invoices", iid, {"status": i["status"]}, {"status": "cancelled"})
    return {"id": iid, "status": "cancelled"}


@router.post("/invoices/{iid}/send")
def invoice_send(iid: int, user=Depends(staff)):
    with db().begin() as c:
        i = _one(c, """SELECT i.invoice_number,i.status,i.total,i.due_date,c.email FROM invoices i JOIN customers c ON c.id=i.customer_id
            WHERE i.id=:i FOR UPDATE OF i""", {"i": iid})
        if i["status"] in ("draft", "cancelled"): raise HTTPException(409, "Confirm the invoice before sending it")
        res = send_email(c, i["email"], "invoice_sent", f"Invoice {i['invoice_number']} from Brightloop",
                         f"Your invoice {i['invoice_number']} for {i['total']} is due on {i['due_date']}. Sign in to the portal to view or download it.",
                         related_type="invoice", related_id=iid)
        if res["status"] != "failed":
            c.execute(text("UPDATE invoices SET sent_at=now() WHERE id=:i"), {"i": iid})
        audit(c, user["id"], "invoice.send", "invoices", iid, None, res)
    return res


# ---------------------------------------------------------------- payments
class Allocation(BaseModel):
    invoice_id: int; amount: Decimal | None = Field(default=None, gt=0)


class PaymentIn(BaseModel):
    customer_id: int; amount: Decimal = Field(gt=0); method: str
    transaction_date: date | None = None; notes: str | None = None; gateway_reference: str | None = None
    status: str = "succeeded"; allocations: list[Allocation] = []


@router.post("/payments", status_code=201)
def record_payment(x: PaymentIn, user=Depends(staff)):
    """Record a payment against one or more invoices (method, amount, date, note)."""
    if x.status not in ("succeeded", "pending"): raise HTTPException(422, "Record payments as succeeded or pending")
    amount = money(x.amount)
    with db().begin() as c:
        _one(c, "SELECT id FROM customers WHERE id=:i", {"i": x.customer_id}, "Customer not found")
        pid = c.execute(text("""INSERT INTO payments(customer_id,amount,method,status,transaction_date,gateway_reference,notes,recorded_by)
            VALUES (:c,:a,CAST(:m AS payment_method),CAST(:st AS payment_status),COALESCE(:d,CURRENT_DATE),:g,:n,:u) RETURNING id"""),
            {"c": x.customer_id, "a": amount, "m": x.method, "st": x.status, "d": x.transaction_date, "g": x.gateway_reference,
             "n": x.notes, "u": user["id"]}).scalar_one()
        left, applied = amount, []
        for al in x.allocations:
            inv = _one(c, "SELECT id,customer_id,status,total,amount_paid FROM invoices WHERE id=:i FOR UPDATE", {"i": al.invoice_id}, f"Invoice {al.invoice_id} not found")
            if inv["customer_id"] != x.customer_id: raise HTTPException(422, f"Invoice {inv['id']} belongs to another customer")
            if inv["status"] not in ("confirmed", "overdue"): raise HTTPException(409, f"Invoice {inv['id']} is {inv['status']} and cannot take a payment")
            due = inv["total"] - inv["amount_paid"]
            part = money(al.amount if al.amount is not None else min(left, due))
            if part > due: raise HTTPException(422, f"Invoice {inv['id']} only has {due} outstanding")
            if part > left: raise HTTPException(422, "Allocations exceed the payment amount")
            if part > 0:
                c.execute(text("INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES (:p,:i,:a)"), {"p": pid, "i": inv["id"], "a": part})
                left -= part; applied.append({"invoice_id": inv["id"], "amount": str(part)})
        audit(c, user["id"], "payment.record", "payments", pid, None, {"amount": str(amount), "applied": applied})
        return {"id": pid, "amount": str(amount), "unallocated": str(left), "allocations": applied}

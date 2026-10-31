"""Brightloop Subscription Management API."""
import os, threading, time
from datetime import date
from decimal import Decimal
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from .billing import run_billing
from .calculations import variant_unit_price, calculate_line, discount_amount
from .deps import db, require, STAFF, current_user, customer_id_for
from .invoices import render_invoice_pdf
from . import auth_routes, workflow_routes, report_routes, resources

app = FastAPI(title="Brightloop Subscription Management API", version="2.0.0",
              description="Auth, catalog, quotations, subscriptions, billing, payments, reporting")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# workflow routes first so dedicated endpoints (e.g. POST /api/payments) are matched before generic CRUD
for r in (auth_routes.router, workflow_routes.router, report_routes.router, resources.router):
    app.include_router(r)
staff = require(*STAFF)


class LineRequest(BaseModel):
    unit_price: Decimal = Field(ge=0); quantity: int = Field(ge=1); tax_rate: Decimal = Field(default=0, ge=0, le=100); discount: Decimal = Field(default=0, ge=0)
class VariantRequest(BaseModel):
    base_price: Decimal = Field(ge=0); extra_price: Decimal = Field(default=0, ge=0)
class DiscountRequest(BaseModel):
    subtotal: Decimal = Field(ge=0); kind: str; value: Decimal = Field(gt=0); min_purchase: Decimal = Decimal("0"); quantity: int = 1; min_quantity: int = 0
    valid_from: date | None = None; valid_until: date | None = None; active: bool = True; remaining_uses: int | None = None
    already_used_by_customer: int = 0; per_customer_limit: int | None = None


@app.get("/")
def root(): return {"name": "Brightloop Subscription Management API", "version": app.version, "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    try:
        with db().connect() as c: c.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(503, f"Database unavailable: {e}")


# pure calculators (no data access) - handy for demos and used by the UI
@app.post("/api/calculations/variant-price")
def variant_price(x: VariantRequest): return {"unit_price": str(variant_unit_price(x.base_price, x.extra_price))}

@app.post("/api/calculations/line")
def line_calc(x: LineRequest):
    try: return {k: str(v) for k, v in calculate_line(unit_price=x.unit_price, quantity=x.quantity, tax_rate=x.tax_rate, discount=x.discount).items()}
    except ValueError as e: raise HTTPException(422, str(e))

@app.post("/api/calculations/discount")
def discount_calc(x: DiscountRequest):
    try:
        return {"discount_amount": str(discount_amount(x.subtotal, kind=x.kind, value=x.value, min_purchase=x.min_purchase, quantity=x.quantity,
                min_quantity=x.min_quantity, valid_from=x.valid_from, valid_until=x.valid_until, active=x.active, remaining_uses=x.remaining_uses,
                already_used_by_customer=x.already_used_by_customer, per_customer_limit=x.per_customer_limit))}
    except ValueError as e: raise HTTPException(422, str(e))


@app.post("/api/billing/run")
def billing_run(run_date: date | None = None, auto_confirm: bool = True, user=Depends(staff)):
    try: return run_billing(db(), run_date=run_date, triggered_by=user["id"], auto_confirm=auto_confirm)
    except Exception as e: raise HTTPException(500, f"Billing run failed: {e}")


@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, user=Depends(current_user)):
    with db().connect() as c:
        inv = c.execute(text("""SELECT i.*,c.name customer_name,c.email customer_email,c.billing_line1,c.billing_city,c.billing_state,c.billing_postal
            FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.id=:id"""), {"id": invoice_id}).mappings().first()
        if not inv: raise HTTPException(404, "Invoice not found")
        if user["role"] == "customer" and (inv["customer_id"] != customer_id_for(c, user) or inv["status"] == "draft"):
            raise HTTPException(404, "Invoice not found")   # customers only ever see their own invoices
        lines = c.execute(text("""SELECT description,quantity,unit_price,discount_amount,tax_rate,tax_amount,line_total FROM invoice_lines
            WHERE invoice_id=:id ORDER BY id"""), {"id": invoice_id}).mappings().all()
    pdf = render_invoice_pdf(dict(inv), [dict(x) for x in lines])
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{inv["invoice_number"]}.pdf"'})


@app.get("/api/performance/benchmark")
def benchmark(user=Depends(staff)):
    """Times the queries behind every dashboard / list page on the connected database."""
    checks = {
        "dashboard_summary": "SELECT (SELECT count(*) FROM subscriptions WHERE status='active'),(SELECT COALESCE(sum(mrr),0) FROM v_subscription_mrr),"
                             "(SELECT COALESCE(sum(amount_due),0) FROM invoices WHERE status IN ('confirmed','overdue')),(SELECT count(*) FROM invoices WHERE status='overdue')",
        "monthly_financials": "SELECT * FROM v_monthly_financials",
        "active_subscriptions_page": "SELECT s.id FROM subscriptions s JOIN customers c ON c.id=s.customer_id WHERE s.status='active' ORDER BY s.id DESC LIMIT 50",
        "overdue_invoices_page": "SELECT i.id FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.status IN ('confirmed','overdue') AND i.due_date<CURRENT_DATE ORDER BY i.due_date DESC LIMIT 50",
        "invoice_search": "SELECT i.id FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE c.name ILIKE '%a%' ORDER BY i.id DESC LIMIT 50",
        "payments_page": "SELECT id FROM payments ORDER BY transaction_date DESC LIMIT 50"}
    counts_sql = {"subscriptions": "SELECT count(*) FROM subscriptions", "invoices": "SELECT count(*) FROM invoices", "payments": "SELECT count(*) FROM payments"}
    results = {}
    with db().connect() as c:
        dataset = {k: c.execute(text(v)).scalar() for k, v in counts_sql.items()}
        for name, sql in checks.items():
            t0 = time.perf_counter(); n = len(c.execute(text(sql)).all()); ms = (time.perf_counter() - t0) * 1000
            results[name] = {"rows": n, "elapsed_ms": round(ms, 2), "under_2000ms": ms < 2000}
    return {"dataset": dataset, "threshold_ms": 2000, "results": results,
            "all_under_threshold": all(r["under_2000ms"] for r in results.values()),
            "note": "Measured on this database instance; record dataset size and hardware with the result."}


def _scheduler():
    """Optional (ENABLE_SCHEDULER=1): hourly overdue sweep, daily billing run once per calendar day."""
    last_billed = None
    while True:
        try:
            with db().begin() as c: c.execute(text("SELECT mark_overdue_invoices()"))
            if date.today() != last_billed:
                run_billing(db()); last_billed = date.today()
        except Exception as e:
            print("scheduler error:", e)
        time.sleep(3600)


@app.on_event("startup")
def start_scheduler():
    if os.getenv("ENABLE_SCHEDULER") == "1":
        threading.Thread(target=_scheduler, daemon=True).start()

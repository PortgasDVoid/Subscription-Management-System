"""Brightloop Subscription Management API."""
import os
from datetime import date
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from .calculations import variant_unit_price, calculate_line, discount_amount, calculate_invoice
from .billing import run_billing
from .invoices import render_invoice_pdf

DATABASE_URL=os.getenv("DATABASE_URL","postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db")
engine=create_engine(DATABASE_URL,pool_pre_ping=True,**({"pool_size":5,"max_overflow":10} if DATABASE_URL.startswith("postgresql") else {})) if DATABASE_URL else None
app=FastAPI(title="Brightloop Subscription Management API",version="1.0.0",description="Developer 3 pricing, discounts, tax, billing, PDF and QA services")

class LineRequest(BaseModel):
    unit_price: Decimal=Field(ge=0); quantity:int=Field(ge=1); tax_rate:Decimal=Field(default=0,ge=0,le=100); discount:Decimal=Field(default=0,ge=0)
class VariantRequest(BaseModel):
    base_price:Decimal=Field(ge=0); extra_price:Decimal=Field(default=0,ge=0)
class DiscountRequest(BaseModel):
    subtotal:Decimal=Field(ge=0); kind:str; value:Decimal=Field(gt=0); min_purchase:Decimal=Decimal("0"); quantity:int=1; min_quantity:int=0
    valid_from:date|None=None; valid_until:date|None=None; active:bool=True; remaining_uses:int|None=None; already_used_by_customer:int=0; per_customer_limit:int|None=None

def db():
    if engine is None: raise HTTPException(503,"DATABASE_URL is not configured")
    return engine

@app.get("/")
def root(): return {"name":"Brightloop Subscription Management API","version":"1.0.0","docs":"/docs","health":"/health"}
@app.get("/health")
def health():
    try:
        with db().connect() as c: c.execute(text("SELECT 1"))
        return {"status":"ok","database":"connected"}
    except Exception as e: raise HTTPException(503,f"Database unavailable: {e}")
@app.post("/api/calculations/variant-price")
def variant_price(x:VariantRequest): return {"unit_price":str(variant_unit_price(x.base_price,x.extra_price))}
@app.post("/api/calculations/line")
def line_calc(x:LineRequest):
    try: return {k:str(v) for k,v in calculate_line(unit_price=x.unit_price,quantity=x.quantity,tax_rate=x.tax_rate,discount=x.discount).items()}
    except ValueError as e: raise HTTPException(422,str(e))
@app.post("/api/calculations/discount")
def discount_calc(x:DiscountRequest):
    try:
        v=discount_amount(x.subtotal,kind=x.kind,value=x.value,min_purchase=x.min_purchase,quantity=x.quantity,min_quantity=x.min_quantity,valid_from=x.valid_from,valid_until=x.valid_until,active=x.active,remaining_uses=x.remaining_uses,already_used_by_customer=x.already_used_by_customer,per_customer_limit=x.per_customer_limit)
        return {"discount_amount":str(v)}
    except ValueError as e: raise HTTPException(422,str(e))
@app.post("/api/billing/run")
def billing_run(run_date:date|None=None):
    try: return run_billing(db(),run_date=run_date)
    except Exception as e: raise HTTPException(500,f"Billing run failed: {e}")
@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id:int):
    try:
        with db().connect() as c:
            inv=c.execute(text("""SELECT i.*,c.name customer_name,c.email customer_email,c.billing_line1,c.billing_city,c.billing_state,c.billing_postal
              FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.id=:id"""),{"id":invoice_id}).mappings().first()
            if not inv: raise HTTPException(404,"Invoice not found")
            lines=c.execute(text("SELECT description,quantity,unit_price,discount_amount,tax_rate,tax_amount,line_total FROM invoice_lines WHERE invoice_id=:id ORDER BY id"),{"id":invoice_id}).mappings().all()
        pdf=render_invoice_pdf(dict(inv),[dict(x) for x in lines])
        return Response(pdf,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="{inv["invoice_number"]}.pdf"'})
    except HTTPException: raise
    except Exception as e: raise HTTPException(500,f"Could not render invoice: {e}")
@app.get("/api/dashboard/summary")
def dashboard():
    try:
        with db().connect() as c:
            row=c.execute(text("""SELECT (SELECT count(*) FROM subscriptions WHERE status='active') active_subscriptions,
              (SELECT COALESCE(sum(total),0) FROM invoices WHERE status<>'cancelled') billed_total,
              (SELECT COALESCE(sum(amount_paid),0) FROM invoices WHERE status<>'cancelled') collected_total,
              (SELECT COALESCE(sum(amount_due),0) FROM invoices WHERE status IN ('confirmed','overdue')) outstanding_total,
              (SELECT count(*) FROM invoices WHERE status='overdue' OR (status='confirmed' AND due_date<CURRENT_DATE)) overdue_count,
              (SELECT COALESCE(sum(amount_due),0) FROM invoices WHERE status='overdue' OR (status='confirmed' AND due_date<CURRENT_DATE)) overdue_amount""")).mappings().one()
            return {k:(int(v) if k in ('active_subscriptions','overdue_count') else str(v)) for k,v in row.items()}
    except Exception as e: raise HTTPException(500,str(e))
@app.get("/api/performance/benchmark")
def benchmark():
    """Measures core indexed dashboard queries on the connected database; run after scaling seed."""
    import time
    checks={"active_subscriptions":"SELECT id FROM subscriptions WHERE status='active' ORDER BY next_billing_date LIMIT 100",
            "overdue_invoices":"SELECT id FROM invoices WHERE status IN ('confirmed','overdue') AND due_date<CURRENT_DATE ORDER BY due_date LIMIT 100",
            "mrr_view":"SELECT * FROM v_subscription_mrr"}
    results={}
    try:
        with db().connect() as c:
            for name,sql in checks.items():
                start=time.perf_counter(); count=len(c.execute(text(sql)).all()); elapsed=(time.perf_counter()-start)*1000
                results[name]={"rows":count,"elapsed_ms":round(elapsed,2),"under_2000ms":elapsed<2000}
        return {"threshold_ms":2000,"results":results,"all_under_threshold":all(x['under_2000ms'] for x in results.values()),"note":"Measured on this database instance; not a guarantee for every deployment."}
    except Exception as e: raise HTTPException(500,str(e))

# Resource API used by the Brightloop web client. Table names are strictly allow-listed;
# incoming fields are checked against PostgreSQL metadata before any statement is built.
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','), allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
RESOURCE_TABLES={
 'customers':'customers','users':'users','products':'products','product_variants':'product_variants','plans':'plans',
 'discounts':'discounts','quotations':'quotations','subscriptions':'subscriptions','invoices':'invoices','payments':'payments',
 'taxes':'taxes','payment_terms':'payment_terms','quotation_templates':'quotation_templates'
}
@app.get('/api/resources/{resource}')
def list_resource(resource:str, limit:int=200, offset:int=0):
    if resource not in RESOURCE_TABLES: raise HTTPException(404,'Unknown resource')
    table=RESOURCE_TABLES[resource]; limit=max(1,min(limit,500)); offset=max(0,offset)
    try:
        with db().connect() as c:
            select_sql='SELECT id,email,role,full_name,phone,is_active,created_at,updated_at FROM users' if table == 'users' else f'SELECT * FROM {table}'
            rows=c.execute(text(select_sql+ ' ORDER BY id DESC LIMIT :lim OFFSET :off'),{'lim':limit,'off':offset}).mappings().all()
            return {'items':[dict(x) for x in rows], 'limit':limit,'offset':offset}
    except Exception as e: raise HTTPException(500,str(e))
@app.post('/api/resources/{resource}')
def create_resource(resource:str, payload:dict):
    if resource not in RESOURCE_TABLES: raise HTTPException(404,'Unknown resource')
    table=RESOURCE_TABLES[resource]
    try:
        with db().begin() as c:
            cols={x['name'] for x in inspect(c).get_columns(table)}
            data={k:v for k,v in payload.items() if k in cols and k not in ('id','created_at','updated_at') and v not in ('',None)}
            if table == 'users':
                import hashlib, os as _os
                raw=payload.get('password')
                if not raw or len(raw) <= 8 or not any(x.isupper() for x in raw) or not any(x.islower() for x in raw) or not any(not x.isalnum() for x in raw): raise HTTPException(422,'Password must be >8 characters and include uppercase, lowercase and a special character')
                salt=_os.urandom(16); data['password_hash']='scrypt$'+salt.hex()+'$'+hashlib.scrypt(raw.encode(),salt=salt,n=2**14,r=8,p=1).hex()
                data.pop('password',None)
            if not data: raise HTTPException(422,'No valid fields supplied')
            names=list(data); sql=f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(':'+k for k in names)}) RETURNING *"
            row=c.execute(text(sql),data).mappings().one(); result=dict(row); result.pop('password_hash',None); return result
    except HTTPException: raise
    except Exception as e: raise HTTPException(422,str(e))
@app.patch('/api/resources/{resource}/{record_id}')
def update_resource(resource:str,record_id:int,payload:dict):
    if resource not in RESOURCE_TABLES: raise HTTPException(404,'Unknown resource')
    table=RESOURCE_TABLES[resource]
    try:
        with db().begin() as c:
            cols={x['name'] for x in inspect(c).get_columns(table)}
            data={k:v for k,v in payload.items() if k in cols and k not in ('id','created_at')}
            if not data: raise HTTPException(422,'No valid fields supplied')
            sets=','.join(f'{k}=:{k}' for k in data); data['rid']=record_id
            row=c.execute(text(f'UPDATE {table} SET {sets} WHERE id=:rid RETURNING *'),data).mappings().first()
            if not row: raise HTTPException(404,'Record not found')
            return dict(row)
    except HTTPException: raise
    except Exception as e: raise HTTPException(422,str(e))
@app.delete('/api/resources/{resource}/{record_id}')
def delete_resource(resource:str,record_id:int):
    if resource not in RESOURCE_TABLES: raise HTTPException(404,'Unknown resource')
    try:
        with db().begin() as c:
            result=c.execute(text(f'DELETE FROM {RESOURCE_TABLES[resource]} WHERE id=:id'),{'id':record_id})
            if not result.rowcount: raise HTTPException(404,'Record not found')
            return {'deleted':True,'id':record_id}
    except HTTPException: raise
    except Exception as e: raise HTTPException(409,str(e))
@app.get('/api/reports/summary')
def report_summary(): return dashboard()

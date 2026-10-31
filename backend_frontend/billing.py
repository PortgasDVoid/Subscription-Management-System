"""PostgreSQL billing runner. Each subscription is processed atomically and idempotently."""
from datetime import date, timedelta
from decimal import Decimal
from calendar import monthrange
from sqlalchemy import text
from .calculations import money, discount_amount, calculate_line, calculate_invoice

def add_period(start: date, period: str, interval: int=1) -> date:
    if interval < 1: raise ValueError("Billing interval must be >= 1")
    if period == "daily": return start + timedelta(days=interval)
    if period == "weekly": return start + timedelta(weeks=interval)
    months = interval * (12 if period == "yearly" else 1)
    if period not in ("monthly", "yearly"): raise ValueError("Unsupported billing period")
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12); month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))

def run_billing(engine, run_date=None, triggered_by=None):
    run_date = run_date or date.today()
    created = skipped = checked = errors = 0
    error_items = []
    with engine.begin() as conn:
        run_id = conn.execute(text("""INSERT INTO billing_runs(run_date,status,triggered_by)
          VALUES (:d,'running',:actor) RETURNING id"""), {"d":run_date,"actor":triggered_by}).scalar_one()
        due = conn.execute(text("""SELECT s.id FROM subscriptions s
          WHERE s.status='active' AND s.next_billing_date <= :d
          ORDER BY s.next_billing_date, s.id"""), {"d":run_date}).scalars().all()
        checked = len(due)
        for sid in due:
            try:
                # A savepoint ensures one bad subscription does not abort the run.
                with conn.begin_nested():
                    sub = conn.execute(text("""SELECT s.*, p.billing_period, p.billing_interval,
                      p.min_quantity, pt.due_days, c.currency
                      FROM subscriptions s JOIN plans p ON p.id=s.plan_id
                      JOIN payment_terms pt ON pt.id=s.payment_term_id
                      JOIN customers c ON c.id=s.customer_id
                      WHERE s.id=:id FOR UPDATE OF s"""), {"id":sid}).mappings().one()
                    if sub["status"] != "active" or sub["next_billing_date"] > run_date:
                        skipped += 1; continue
                    period_start = sub["next_billing_date"]
                    period_end = add_period(period_start, sub["billing_period"], sub["billing_interval"]) - timedelta(days=1)
                    duplicate = conn.execute(text("""SELECT id FROM invoices WHERE subscription_id=:s
                      AND billing_period_start=:b AND status <> 'cancelled'"""), {"s":sid,"b":period_start}).scalar()
                    if duplicate:
                        conn.execute(text("UPDATE subscriptions SET next_billing_date=:n,last_billed_through=:e WHERE id=:s"),
                                     {"n":period_end+timedelta(days=1),"e":period_end,"s":sid})
                        skipped += 1; continue
                    lines = conn.execute(text("""SELECT sl.*, p.name product_name, p.default_tax_id,
                      COALESCE(t.rate_percent,0) tax_rate
                      FROM subscription_lines sl JOIN products p ON p.id=sl.product_id
                      LEFT JOIN taxes t ON t.id=COALESCE(sl.tax_id,p.default_tax_id)
                      WHERE sl.subscription_id=:s ORDER BY sl.id"""), {"s":sid}).mappings().all()
                    if not lines: raise ValueError("Subscription has no billable lines")
                    invoice_id = conn.execute(text("""INSERT INTO invoices(subscription_id,customer_id,billing_run_id,
                      status,billing_period_start,billing_period_end,issue_date,due_date,currency,created_by)
                      VALUES (:s,:c,:r,'draft',:bs,:be,:d,:due,:currency,:actor) RETURNING id"""),
                      {"s":sid,"c":sub["customer_id"],"r":run_id,"bs":period_start,"be":period_end,
                       "d":run_date,"due":run_date+timedelta(days=sub["due_days"]),"currency":sub["currency"],"actor":triggered_by}).scalar_one()
                    calc_lines=[]
                    applied_discount_ids=set()
                    for line in lines:
                        base = money(line["unit_price"]); qty = line["quantity"]
                        raw_subtotal = money(base*qty); disc = Decimal("0.00"); discount_id = None
                        # Explicit line discount wins; otherwise use first eligible auto-apply discount.
                        discount_rows = conn.execute(text("""SELECT d.*,
                          (SELECT COUNT(*) FROM discount_redemptions r WHERE r.discount_id=d.id) used_total,
                          (SELECT COUNT(*) FROM discount_redemptions r WHERE r.discount_id=d.id AND r.customer_id=:c) used_customer,
                          (SELECT COUNT(*) FROM discount_products dp WHERE dp.discount_id=d.id) product_scope,
                          EXISTS(SELECT 1 FROM discount_products dp WHERE dp.discount_id=d.id AND dp.product_id=:p) product_match
                          FROM discounts d WHERE d.is_active AND (d.id=:did OR (:did IS NULL AND d.auto_apply))
                          ORDER BY CASE WHEN d.id=:did THEN 0 ELSE 1 END, d.id FOR UPDATE OF d"""),
                          {"c":sub["customer_id"],"p":line["product_id"],"did":line["discount_id"]}).mappings().all()
                        for d in discount_rows:
                            if d["id"] in applied_discount_ids: continue
                            if d["product_scope"] and not d["product_match"]: continue
                            remaining = None if d["usage_limit"] is None else d["usage_limit"]-d["used_total"]
                            try:
                                candidate = discount_amount(raw_subtotal, kind=d["discount_type"], value=d["value"],
                                  min_purchase=d["min_purchase_amount"], quantity=qty,min_quantity=d["min_quantity"],
                                  valid_from=d["valid_from"],valid_until=d["valid_until"],today=run_date,
                                  active=d["is_active"],remaining_uses=remaining,
                                  already_used_by_customer=d["used_customer"],per_customer_limit=d["per_customer_limit"])
                            except ValueError: continue
                            if candidate > 0: disc=candidate; discount_id=d["id"]; break
                        calc=calculate_line(unit_price=base,quantity=qty,tax_rate=line["tax_rate"],discount=disc)
                        conn.execute(text("""INSERT INTO invoice_lines(invoice_id,subscription_line_id,product_id,variant_id,
                          description,quantity,unit_price,discount_id,discount_amount,tax_id,tax_rate,tax_amount,line_total)
                          VALUES (:i,:sl,:p,:v,:desc,:q,:u,:did,:disc,:taxid,:rate,:tax,:total)"""),
                          {"i":invoice_id,"sl":line["id"],"p":line["product_id"],"v":line["variant_id"],
                           "desc":line["description"] or line["product_name"],"q":qty,"u":base,"did":discount_id,
                           "disc":calc["discount"],"taxid":line["tax_id"] or line["default_tax_id"],
                           "rate":line["tax_rate"],"tax":calc["tax"],"total":calc["total"]})
                        calc_lines.append(calc)
                        if discount_id:
                            applied_discount_ids.add(discount_id)
                            conn.execute(text("""INSERT INTO discount_redemptions(discount_id,invoice_id,customer_id,amount)
                              VALUES (:d,:i,:c,:a) ON CONFLICT (discount_id,invoice_id) DO NOTHING"""),
                              {"d":discount_id,"i":invoice_id,"c":sub["customer_id"],"a":disc})
                    totals=calculate_invoice(calc_lines)
                    conn.execute(text("""UPDATE invoices SET subtotal=:s,discount_total=:d,tax_total=:t,total=:total,
                      status='confirmed',confirmed_at=now() WHERE id=:i"""),
                      {"s":totals["subtotal"],"d":totals["discount_total"],"t":totals["tax_total"],"total":totals["total"],"i":invoice_id})
                    next_date=period_end+timedelta(days=1)
                    if sub["expiry_date"] and next_date > sub["expiry_date"] and not sub["auto_renew"]:
                        conn.execute(text("""UPDATE subscriptions SET status='closed',closure_reason='expired',closed_at=now(),
                          last_billed_through=:e WHERE id=:s"""), {"e":period_end,"s":sid})
                    else:
                        conn.execute(text("""UPDATE subscriptions SET next_billing_date=:n,last_billed_through=:e,
                          renewal_count=renewal_count+1 WHERE id=:s"""), {"n":next_date,"e":period_end,"s":sid})
                    created += 1
            except Exception as exc:
                errors += 1; error_items.append({"subscription_id":sid,"error":str(exc)[:500]})
        status = "completed_with_errors" if errors else "completed"
        conn.execute(text("""UPDATE billing_runs SET status=:st,subscriptions_checked=:c,invoices_created=:i,
          invoices_skipped=:sk,error_count=:e,errors=CAST(:errors AS jsonb),finished_at=now() WHERE id=:id"""),
          {"st":status,"c":checked,"i":created,"sk":skipped,"e":errors,
           "errors":__import__('json').dumps(error_items),"id":run_id})
    return {"billing_run_id":run_id,"subscriptions_checked":checked,"invoices_created":created,
            "invoices_skipped":skipped,"error_count":errors,"errors":error_items}

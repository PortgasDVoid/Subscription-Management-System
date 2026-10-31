"""PostgreSQL billing runner. Each subscription is processed atomically and idempotently."""
import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from .calculations import money, calculate_line, calculate_invoice
from .discounting import plan_line_discounts

MAX_CATCHUP_PERIODS = 12   # a run bills at most this many missed periods per subscription


def add_period(start: date, period: str, interval: int = 1) -> date:
    """Simple step used for contract lengths. For recurring dates use next_period_start (anchored)."""
    if interval < 1: raise ValueError("Billing interval must be >= 1")
    if period == "daily": return start + timedelta(days=interval)
    if period == "weekly": return start + timedelta(weeks=interval)
    months = interval * (12 if period == "yearly" else 1)
    if period not in ("monthly", "yearly"): raise ValueError("Unsupported billing period")
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12); month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def next_period_start(anchor: date, current: date, period: str, interval: int = 1) -> date:
    """Next billing date measured from the ORIGINAL start date, so Jan 31 -> Feb 28 -> Mar 31 (no drift)."""
    if interval < 1: raise ValueError("Billing interval must be >= 1")
    if period == "daily": return current + timedelta(days=interval)
    if period == "weekly": return current + timedelta(weeks=interval)
    if period not in ("monthly", "yearly"): raise ValueError("Unsupported billing period")
    step = interval * (12 if period == "yearly" else 1)
    elapsed = (current.year - anchor.year) * 12 + current.month - anchor.month
    index = anchor.year * 12 + anchor.month - 1 + elapsed + step
    year, month = divmod(index, 12); month += 1
    return date(year, month, min(anchor.day, monthrange(year, month)[1]))


def _log_event(conn, sid, frm, to, event, reason, actor=None):
    conn.execute(text("""INSERT INTO subscription_events(subscription_id,from_status,to_status,event_type,reason,actor_user_id)
        VALUES (:s,CAST(:f AS subscription_status),CAST(:t AS subscription_status),:e,:r,:a)"""),
        {"s": sid, "f": frm, "t": to, "e": event, "r": reason, "a": actor})


def _bill_one(conn, sid, run_date, run_id, actor, auto_confirm):
    """Bill the oldest due period of one subscription. Returns 'created', 'skipped' or None (nothing due)."""
    sub = conn.execute(text("""SELECT s.*, p.billing_period, p.billing_interval, p.term_periods, pt.due_days, c.currency
        FROM subscriptions s JOIN plans p ON p.id=s.plan_id JOIN payment_terms pt ON pt.id=s.payment_term_id
        JOIN customers c ON c.id=s.customer_id WHERE s.id=:id FOR UPDATE OF s"""), {"id": sid}).mappings().one()
    if sub["status"] != "active" or sub["next_billing_date"] is None or sub["next_billing_date"] > run_date:
        return None
    period_start = sub["next_billing_date"]
    next_start = next_period_start(sub["start_date"], period_start, sub["billing_period"], sub["billing_interval"])
    period_end = next_start - timedelta(days=1)

    dup = conn.execute(text("""SELECT id FROM invoices WHERE subscription_id=:s AND billing_period_start=:b
        AND status <> 'cancelled'"""), {"s": sid, "b": period_start}).scalar()
    if dup:   # already billed: just move the pointer forward, never bill twice
        conn.execute(text("UPDATE subscriptions SET next_billing_date=:n,last_billed_through=:e WHERE id=:s"),
                     {"n": next_start, "e": period_end, "s": sid})
        return "skipped"

    lines = conn.execute(text("""SELECT sl.*, p.name product_name, p.default_tax_id, COALESCE(t.rate_percent,0) tax_rate
        FROM subscription_lines sl JOIN products p ON p.id=sl.product_id
        LEFT JOIN taxes t ON t.id=COALESCE(sl.tax_id,p.default_tax_id)
        WHERE sl.subscription_id=:s ORDER BY sl.id"""), {"s": sid}).mappings().all()
    if not lines:
        raise ValueError("Subscription has no billable lines")

    cust = sub["customer_id"]
    explicit_ids = [l["discount_id"] for l in lines if l["discount_id"]]
    disc_rows = conn.execute(text("""SELECT d.*,
        (SELECT COUNT(*) FROM discount_redemptions r JOIN invoices i ON i.id=r.invoice_id
          WHERE r.discount_id=d.id AND i.status<>'cancelled') used_total,
        (SELECT COUNT(*) FROM discount_redemptions r JOIN invoices i ON i.id=r.invoice_id
          WHERE r.discount_id=d.id AND r.customer_id=:c AND i.status<>'cancelled') used_customer
        FROM discounts d WHERE d.is_active AND (d.auto_apply OR d.id = ANY(CAST(:ids AS bigint[])))
        ORDER BY d.id FOR UPDATE OF d"""), {"c": cust, "ids": explicit_ids}).mappings().all()
    scopes = {}
    if disc_rows:
        for r in conn.execute(text("SELECT discount_id, product_id FROM discount_products WHERE discount_id = ANY(CAST(:ids AS bigint[]))"),
                              {"ids": [d["id"] for d in disc_rows]}).mappings():
            scopes.setdefault(r["discount_id"], set()).add(r["product_id"])
    discounts = [{**dict(d), "product_ids": scopes.get(d["id"], set())} for d in disc_rows]

    plan_in = [{"product_id": l["product_id"], "quantity": l["quantity"], "subtotal": money(money(l["unit_price"]) * l["quantity"]),
                "explicit_discount_id": l["discount_id"]} for l in lines]
    per_line, redemptions = plan_line_discounts(plan_in, discounts, run_date)

    invoice_id = conn.execute(text("""INSERT INTO invoices(subscription_id,customer_id,billing_run_id,status,billing_period_start,
        billing_period_end,issue_date,due_date,currency,created_by) VALUES (:s,:c,:r,'draft',:bs,:be,:d,:due,:cur,:a) RETURNING id"""),
        {"s": sid, "c": cust, "r": run_id, "bs": period_start, "be": period_end, "d": run_date,
         "due": run_date + timedelta(days=sub["due_days"]), "cur": sub["currency"], "a": actor}).scalar_one()

    calc_lines = []
    for line, (did, disc) in zip(lines, per_line):
        base = money(line["unit_price"])
        calc = calculate_line(unit_price=base, quantity=line["quantity"], tax_rate=line["tax_rate"], discount=disc)
        conn.execute(text("""INSERT INTO invoice_lines(invoice_id,subscription_line_id,product_id,variant_id,description,quantity,
            unit_price,discount_id,discount_amount,tax_id,tax_rate,tax_amount,line_total)
            VALUES (:i,:sl,:p,:v,:desc,:q,:u,:did,:disc,:taxid,:rate,:tax,:total)"""),
            {"i": invoice_id, "sl": line["id"], "p": line["product_id"], "v": line["variant_id"],
             "desc": line["description"] or line["product_name"], "q": line["quantity"], "u": base, "did": did,
             "disc": calc["discount"], "taxid": line["tax_id"] or line["default_tax_id"], "rate": line["tax_rate"],
             "tax": calc["tax"], "total": calc["total"]})
        calc_lines.append(calc)
    for did, amount in redemptions.items():   # one redemption (= one use) per discount per invoice
        conn.execute(text("""INSERT INTO discount_redemptions(discount_id,invoice_id,customer_id,amount) VALUES (:d,:i,:c,:a)
            ON CONFLICT (discount_id,invoice_id) DO UPDATE SET amount=EXCLUDED.amount"""),
            {"d": did, "i": invoice_id, "c": cust, "a": amount})

    t = calculate_invoice(calc_lines)
    conn.execute(text("""UPDATE invoices SET subtotal=:s,discount_total=:d,tax_total=:t,total=:total,
        status=CAST(:st AS invoice_status),confirmed_at=CASE WHEN :st='confirmed' THEN now() END WHERE id=:i"""),
        {"s": t["subtotal"], "d": t["discount_total"], "t": t["tax_total"], "total": t["total"],
         "st": "confirmed" if auto_confirm else "draft", "i": invoice_id})

    # advance the schedule; handle end of contract
    if sub["expiry_date"] and next_start > sub["expiry_date"]:
        if sub["auto_renew"]:
            span = sub["term_periods"] or 1
            new_expiry = add_period(sub["expiry_date"] + timedelta(days=1), sub["billing_period"], span) - timedelta(days=1)
            conn.execute(text("""UPDATE subscriptions SET next_billing_date=:n,last_billed_through=:e,expiry_date=:x,
                renewal_count=renewal_count+1 WHERE id=:s"""), {"n": next_start, "e": period_end, "x": new_expiry, "s": sid})
            _log_event(conn, sid, "active", "active", "renewed", f"Auto-renewed until {new_expiry}")
        else:
            conn.execute(text("""UPDATE subscriptions SET status='closed',closure_reason='expired',closed_at=now(),
                last_billed_through=:e WHERE id=:s"""), {"e": period_end, "s": sid})
            _log_event(conn, sid, "active", "closed", "closed", "Contract ended (no auto-renew)")
    else:
        conn.execute(text("UPDATE subscriptions SET next_billing_date=:n,last_billed_through=:e WHERE id=:s"),
                     {"n": next_start, "e": period_end, "s": sid})
    return "created"


def run_billing(engine, run_date=None, triggered_by=None, auto_confirm=True):
    run_date = run_date or date.today()
    created = skipped = checked = errors = 0
    error_items = []
    with engine.begin() as conn:
        run_id = conn.execute(text("INSERT INTO billing_runs(run_date,status,triggered_by) VALUES (:d,'running',:a) RETURNING id"),
                              {"d": run_date, "a": triggered_by}).scalar_one()
        due = conn.execute(text("""SELECT id FROM subscriptions WHERE status='active' AND next_billing_date <= :d
            ORDER BY next_billing_date, id"""), {"d": run_date}).scalars().all()
        checked = len(due)
        for sid in due:
            try:
                for _ in range(MAX_CATCHUP_PERIODS):
                    with conn.begin_nested():   # savepoint: one bad subscription never aborts the run
                        outcome = _bill_one(conn, sid, run_date, run_id, triggered_by, auto_confirm)
                    if outcome is None: break
                    if outcome == "created": created += 1
                    else: skipped += 1
            except Exception as exc:
                errors += 1; error_items.append({"subscription_id": sid, "error": str(exc)[:500]})
        conn.execute(text("SELECT mark_overdue_invoices()"))
        conn.execute(text("""UPDATE billing_runs SET status=CAST(:st AS billing_run_status),subscriptions_checked=:c,invoices_created=:i,
            invoices_skipped=:sk,error_count=:e,errors=CAST(:errors AS jsonb),finished_at=now() WHERE id=:id"""),
            {"st": "completed_with_errors" if errors else "completed", "c": checked, "i": created, "sk": skipped,
             "e": errors, "errors": json.dumps(error_items), "id": run_id})
    return {"billing_run_id": run_id, "subscriptions_checked": checked, "invoices_created": created,
            "invoices_skipped": skipped, "error_count": errors, "errors": error_items}

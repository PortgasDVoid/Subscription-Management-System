"""Pure discount allocation (no DB) so it can be unit-tested.

Rules implemented:
* A discount with no product restriction applies to the WHOLE subscription; otherwise only to its products.
* min purchase / min quantity are checked on the discount's eligible lines together, not line by line.
* Dates, total usage limit and per-customer limit are honoured.
* Percentage discounts apply per line; a fixed amount is spent across eligible lines once (capped at their subtotal).
* One discount per invoice line: an explicit line discount wins, otherwise the most valuable auto-apply one.
"""
from datetime import date
from decimal import Decimal
from .calculations import money, discount_amount, ZERO


def plan_line_discounts(lines, discounts, today: date):
    """lines: [{product_id, quantity, subtotal, explicit_discount_id}]
    discounts: [{id, discount_type, value, min_purchase_amount, min_quantity, valid_from, valid_until, is_active,
                 usage_limit, used_total, per_customer_limit, used_customer, auto_apply, product_ids:set}]
    Returns (per_line [(discount_id|None, Decimal)], redemptions {discount_id: Decimal})."""
    pool = {}
    for d in sorted(discounts, key=lambda x: x["id"]):
        scope = [i for i, l in enumerate(lines) if not d["product_ids"] or l["product_id"] in d["product_ids"]]
        if not scope:
            continue
        group_subtotal = sum((money(lines[i]["subtotal"]) for i in scope), ZERO)
        group_qty = sum(int(lines[i]["quantity"]) for i in scope)
        remaining = None if d["usage_limit"] is None else d["usage_limit"] - d["used_total"]
        try:
            total = discount_amount(group_subtotal, kind=d["discount_type"], value=d["value"],
                                    min_purchase=d["min_purchase_amount"], quantity=max(group_qty, 1),
                                    min_quantity=d["min_quantity"], valid_from=d["valid_from"], valid_until=d["valid_until"],
                                    today=today, active=d["is_active"], remaining_uses=remaining,
                                    already_used_by_customer=d["used_customer"], per_customer_limit=d["per_customer_limit"])
        except ValueError:
            continue
        if total > 0:
            pool[d["id"]] = {"d": d, "scope": set(scope), "fixed_left": total if d["discount_type"] == "fixed" else None}

    per_line, redemptions = [], {}
    for i, line in enumerate(lines):
        sub = money(line["subtotal"])
        explicit = line.get("explicit_discount_id")
        best_id, best_amt = None, ZERO
        for did, p in pool.items():
            if i not in p["scope"]:
                continue
            if explicit is not None:
                if did != explicit: continue
            elif not p["d"]["auto_apply"]:
                continue
            if p["d"]["discount_type"] == "percentage":
                amt = min(sub, money(sub * Decimal(str(p["d"]["value"])) / Decimal("100")))
            else:
                amt = min(sub, p["fixed_left"])
            if amt > best_amt:
                best_id, best_amt = did, amt
        if best_id is not None:
            if pool[best_id]["fixed_left"] is not None:
                pool[best_id]["fixed_left"] -= best_amt
            redemptions[best_id] = redemptions.get(best_id, ZERO) + best_amt
        per_line.append((best_id, best_amt))
    return per_line, redemptions

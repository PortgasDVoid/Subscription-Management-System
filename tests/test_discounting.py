from datetime import date
from decimal import Decimal as D
from app.discounting import plan_line_discounts
from app.billing import next_period_start

TODAY = date(2026, 11, 1)
BASE = dict(discount_type="fixed", value=500, min_purchase_amount=0, min_quantity=0, valid_from=None, valid_until=None, is_active=True,
            usage_limit=None, used_total=0, per_customer_limit=None, used_customer=0, auto_apply=True, product_ids=set())
def disc(i, **kw): return {**BASE, "id": i, **kw}
def line(pid, qty, sub, explicit=None): return {"product_id": pid, "quantity": qty, "subtotal": D(sub), "explicit_discount_id": explicit}


def test_min_purchase_is_checked_across_the_whole_subscription():
    lines = [line(1, 1, 3000), line(2, 1, 3000)]
    out, red = plan_line_discounts(lines, [disc(1, min_purchase_amount=5000)], TODAY)
    assert sum(a for _, a in out) == D("500.00") and red == {1: D("500.00")}


def test_fixed_discount_is_spent_once_not_per_line():
    out, _ = plan_line_discounts([line(1, 1, 300), line(1, 1, 300)], [disc(1, value=500)], TODAY)
    assert [a for _, a in out] == [D("300.00"), D("200.00")]


def test_percentage_applies_to_every_eligible_line():
    out, red = plan_line_discounts([line(1, 5, 1000), line(1, 5, 2000)], [disc(1, discount_type="percentage", value=10)], TODAY)
    assert [a for _, a in out] == [D("100.00"), D("200.00")] and red[1] == D("300.00")


def test_product_scope_and_min_quantity():
    d = disc(1, discount_type="percentage", value=5, min_quantity=5, product_ids={1})
    out, _ = plan_line_discounts([line(1, 5, 1000), line(2, 5, 1000)], [d], TODAY)
    assert out[0][1] == D("50.00") and out[1] == (None, D("0.00"))
    out, _ = plan_line_discounts([line(1, 4, 1000)], [d], TODAY)
    assert out == [(None, D("0.00"))]


def test_expired_exhausted_and_customer_limit_are_ignored():
    for kw in ({"valid_until": date(2026, 10, 1)}, {"usage_limit": 3, "used_total": 3}, {"per_customer_limit": 1, "used_customer": 1}, {"is_active": False}):
        out, red = plan_line_discounts([line(1, 1, 1000)], [disc(1, **kw)], TODAY)
        assert out == [(None, D("0.00"))] and red == {}


def test_explicit_line_discount_wins_and_non_auto_needs_explicit():
    manual = disc(2, discount_type="percentage", value=50, auto_apply=False)
    auto = disc(1, value=100)
    out, _ = plan_line_discounts([line(1, 1, 1000, explicit=2), line(1, 1, 1000)], [auto, manual], TODAY)
    assert out[0] == (2, D("500.00")) and out[1] == (1, D("100.00"))


def test_best_auto_discount_is_chosen():
    out, _ = plan_line_discounts([line(1, 1, 1000)], [disc(1, value=50), disc(2, discount_type="percentage", value=10)], TODAY)
    assert out == [(2, D("100.00"))]


def test_billing_dates_do_not_drift_from_month_end():
    a = d = date(2026, 1, 31); seen = []
    for _ in range(4):
        d = next_period_start(a, d, "monthly"); seen.append(d)
    assert seen == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]


def test_quarterly_and_yearly_anchoring():
    assert next_period_start(date(2026, 1, 1), date(2026, 1, 1), "monthly", 3) == date(2026, 4, 1)
    assert next_period_start(date(2024, 2, 29), date(2025, 2, 28), "yearly") == date(2026, 2, 28)
    assert next_period_start(date(2024, 2, 29), date(2027, 2, 28), "yearly") == date(2028, 2, 29)

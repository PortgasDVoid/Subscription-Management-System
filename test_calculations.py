from datetime import date, timedelta
from decimal import Decimal
import pytest
from app.calculations import variant_unit_price, calculate_line, discount_amount, calculate_invoice, money
from app.billing import add_period

def test_variant_price(): assert variant_unit_price('1000','560') == Decimal('1560.00')
def test_variant_rejects_negative():
    with pytest.raises(ValueError): variant_unit_price(10,-1)
def test_expected_discount_tax_example():
    x=calculate_line(unit_price=1000,quantity=2,tax_rate=18,discount=100)
    assert x == {'subtotal':Decimal('2000.00'),'discount':Decimal('100.00'),'taxable':Decimal('1900.00'),'tax':Decimal('342.00'),'total':Decimal('2242.00')}
def test_discount_fixed_capped(): assert discount_amount(100,kind='fixed',value=150)==Decimal('100.00')
def test_percentage_discount(): assert discount_amount(2000,kind='percentage',value=10)==Decimal('200.00')
def test_discount_minimum_purchase(): assert discount_amount(99,kind='fixed',value=10,min_purchase=100)==Decimal('0.00')
def test_discount_minimum_quantity(): assert discount_amount(200,kind='fixed',value=10,quantity=1,min_quantity=2)==Decimal('0.00')
def test_discount_expired(): assert discount_amount(200,kind='fixed',value=10,valid_until=date.today()-timedelta(days=1))==Decimal('0.00')
def test_discount_not_started(): assert discount_amount(200,kind='fixed',value=10,valid_from=date.today()+timedelta(days=1))==Decimal('0.00')
def test_discount_usage_exhausted(): assert discount_amount(200,kind='fixed',value=10,remaining_uses=0)==Decimal('0.00')
def test_discount_customer_limit(): assert discount_amount(200,kind='fixed',value=10,already_used_by_customer=2,per_customer_limit=2)==Decimal('0.00')
def test_invalid_discount_percentage():
    with pytest.raises(ValueError): discount_amount(200,kind='percentage',value=101)
def test_negative_discount_rejected():
    with pytest.raises(ValueError): calculate_line(unit_price=10,quantity=1,discount=-1)
def test_invoice_totals():
    a=calculate_line(unit_price=100,quantity=2,tax_rate=5,discount=10)
    assert calculate_invoice([a])['total']==Decimal('199.50')
def test_month_end_period_clamps(): assert add_period(date(2026,1,31),'monthly')==date(2026,2,28)
def test_leap_year_month_end(): assert add_period(date(2028,1,31),'monthly')==date(2028,2,29)
def test_yearly_period(): assert add_period(date(2024,2,29),'yearly')==date(2025,2,28)
def test_weekly_period(): assert add_period(date(2026,1,1),'weekly',2)==date(2026,1,15)
def test_invalid_period():
    with pytest.raises(ValueError): add_period(date.today(),'hourly')
def test_decimal_rounding(): assert money('1.005')==Decimal('1.01')

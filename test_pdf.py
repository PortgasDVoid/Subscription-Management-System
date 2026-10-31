from decimal import Decimal
from app.invoices import render_invoice_pdf

def test_pdf_is_generated():
    invoice={"invoice_number":"INV-TEST-000001","status":"confirmed","issue_date":"2026-10-31","due_date":"2026-11-15",
      "customer_name":"Demo Customer","customer_email":"demo@example.test","billing_line1":"Main Road","billing_city":"Kochi",
      "billing_state":"Kerala","billing_postal":"682001","currency":"INR","subtotal":Decimal('2000.00'),
      "discount_total":Decimal('100.00'),"tax_total":Decimal('342.00'),"total":Decimal('2242.00'),
      "amount_paid":Decimal('0.00'),"amount_due":Decimal('2242.00')}
    lines=[{"description":"Brightloop CRM","quantity":2,"unit_price":Decimal('1000.00'),"discount_amount":Decimal('100.00'),
      "tax_rate":Decimal('18.00'),"tax_amount":Decimal('342.00'),"line_total":Decimal('2242.00')}]
    result=render_invoice_pdf(invoice,lines)
    assert result.startswith(b'%PDF-')
    assert len(result)>1000

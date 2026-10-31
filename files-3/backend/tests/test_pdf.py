"""Tests for app/services/pdf_service.py. The rendering tests need no database; the last one
(pytest only) reads a seeded invoice from PostgreSQL and is skipped without TEST_DATABASE_URL."""
import io
import unittest
from datetime import date
from decimal import Decimal as D

from app.services import pdf_service as ps

try:
    from pypdf import PdfReader
except ImportError:                                  # pragma: no cover
    PdfReader = None


def make_doc(n_lines=3, **over):
    base = ps.DocLine("Brightloop CRM - Pro", 5, D("2000.00"), D("500.00"), D("18.00"), D("1710.00"),
                      D("11210.00"), "LOYAL5")
    other = ps.DocLine("Priority support", 1, D("800.00"), D("0.00"), D("18.00"), D("144.00"), D("944.00"))
    exempt = ps.DocLine("Extra storage", 2, D("300.00"), D("0.00"), D("0"), D("0.00"), D("600.00"))
    lines = tuple([base, other, exempt] + [other] * max(0, n_lines - 3))[:max(n_lines, 3)]   # ties to the header totals
    fields = dict(
        invoice_number="INV-2026-000123", status="overdue", issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 16), period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
        currency="INR", subtotal=D("12400.00"), discount_total=D("500.00"), tax_total=D("1854.00"),
        total=D("13754.00"), amount_paid=D("5000.00"), amount_due=D("8754.00"),
        customer_name="Kerali Digital & Sons", customer_company="Kerali <Digital> Pvt Ltd",
        customer_email="suresh@keralidigital.test", customer_phone=None, customer_tax_id="32AABCS0001A1Z5",
        customer_address=("12 Tech Park Road", "Kochi, Kerala, 682001"), subscription_number="SUB-2026-000004",
        payment_term="Net 15", notes="Thank you.", lines=lines,
        payments=(ps.DocPayment("PAY-2026-000010", date(2026, 10, 9), "bank_transfer", D("5000.00")),))
    fields.update(over)
    return ps.InvoiceDoc(**fields)


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


class Rendering(unittest.TestCase):
    def test_is_a_pdf(self):
        pdf = ps.render_invoice_pdf(make_doc())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_contains_the_persisted_numbers(self):
        t = text_of(ps.render_invoice_pdf(make_doc()))
        for expected in ("INV-2026-000123", "OVERDUE", "Kerali Digital & Sons", "Kerali <Digital> Pvt Ltd",
                         "INR 12,400.00", "-INR 500.00", "INR 1,854.00", "INR 13,754.00", "INR 8,754.00",
                         "SUB-2026-000004", "Net 15", "PAY-2026-000010", "LOYAL5", "Page 1 of 1"):
            self.assertIn(expected, t)

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_many_lines_paginate_with_repeated_header_and_page_count(self):
        pdf = ps.render_invoice_pdf(make_doc(n_lines=80))
        reader = PdfReader(io.BytesIO(pdf))
        self.assertGreater(len(reader.pages), 1)
        n = len(reader.pages)
        for i, page in enumerate(reader.pages, 1):
            txt = page.extract_text()
            self.assertIn(f"Page {i} of {n}", txt)
            self.assertIn("Unit price", txt)               # table header repeats on every page

    def test_markup_in_user_text_cannot_break_rendering(self):
        doc = make_doc(customer_name="<b>A & B</b> </para>", notes="x < y & z > w <unclosed")
        self.assertTrue(ps.render_invoice_pdf(doc).startswith(b"%PDF"))

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_paid_invoice_without_discount_or_payments_optional_blocks(self):
        doc = make_doc(status="paid", discount_total=D("0.00"), amount_paid=D("13754.00"),
                       amount_due=D("0.00"), payments=(), notes=None, customer_email=None, subscription_number=None,
                       payment_term=None)
        t = text_of(ps.render_invoice_pdf(doc))
        self.assertIn("PAID", t)
        self.assertNotIn("PAYMENTS RECEIVED", t)
        self.assertNotIn("NOTES", t)

    def test_tax_summary_groups_by_rate(self):
        summary = ps.tax_summary(make_doc())
        self.assertEqual(summary, [(D("0"), D("600.00"), D("0.00")), (D("18.00"), D("10300.00"), D("1854.00"))])
        self.assertEqual(sum(a for _, _, a in summary), make_doc().tax_total)

    def test_filename_is_safe(self):
        self.assertEqual(ps.invoice_filename(make_doc(invoice_number="INV/2026 #1")), "INV_2026__1.pdf")


def test_fetch_and_render_seeded_invoice(conn):        # pytest + PostgreSQL only (NOT RUN where written)
    from sqlalchemy import text
    inv_id = conn.execute(text("SELECT id FROM invoices WHERE status = 'paid' ORDER BY id LIMIT 1")).scalar_one()
    doc = ps.fetch_invoice_document(conn, inv_id)
    row = conn.execute(text("SELECT invoice_number, total, amount_paid FROM invoices WHERE id = :i"),
                       {"i": inv_id}).one()
    assert (doc.invoice_number, doc.total, doc.amount_paid) == tuple(row)
    assert sum(l.line_total for l in doc.lines) == doc.total                # DB CHECK, seen from the PDF side
    assert ps.generate_invoice_pdf(conn, inv_id).startswith(b"%PDF")
    import pytest
    from app.services.errors import InvoiceNotFoundError
    with pytest.raises(InvoiceNotFoundError):
        ps.fetch_invoice_document(conn, -1)


if __name__ == "__main__":
    unittest.main()

"""Printable invoice PDF (Developer 3).

Reads PERSISTED values only (invoices, invoice_lines, customers, allocations); nothing is recalculated,
so the PDF always matches what the database holds. Layout: company + invoice header, bill-to, line
table (repeats its header on every page), tax summary by rate, totals, payments received, notes,
and "Page X of Y" in the footer.

    pdf_bytes = generate_invoice_pdf(conn, invoice_id)        # needs a Connection
    pdf_bytes = render_invoice_pdf(doc)                        # pure: no database

Amounts are printed as "INR 1,234.00" (the currency code stored on the invoice): the built-in PDF
fonts have no rupee glyph, and a code works for any currency.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from app.services.errors import InvoiceNotFoundError

ZERO = Decimal("0.00")
STATUS_COLOURS = {"paid": "#1b7f3b", "overdue": "#b42318", "confirmed": "#175cd3",
                  "draft": "#667085", "cancelled": "#667085"}
INK, MUTED, RULE, HEAD_BG = colors.HexColor("#101828"), colors.HexColor("#667085"), \
    colors.HexColor("#d0d5dd"), colors.HexColor("#f2f4f7")


# ------------------------------------------------------------------ data
@dataclass(frozen=True)
class CompanyInfo:
    name: str = "Brightloop Software"
    lines: tuple = ("billing@brightloop.test",)


@dataclass(frozen=True)
class DocLine:
    description: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    discount_code: Optional[str] = None


@dataclass(frozen=True)
class DocPayment:
    number: str
    paid_on: date
    method: str
    amount: Decimal


@dataclass(frozen=True)
class InvoiceDoc:
    invoice_number: str
    status: str
    issue_date: date
    due_date: date
    period_start: date
    period_end: date
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    customer_name: str
    customer_company: Optional[str]
    customer_email: Optional[str]
    customer_phone: Optional[str]
    customer_tax_id: Optional[str]
    customer_address: tuple                      # non-empty address lines
    subscription_number: Optional[str]
    payment_term: Optional[str]
    notes: Optional[str]
    lines: tuple
    payments: tuple = field(default_factory=tuple)


# ------------------------------------------------------------------ database read
_HEADER_SQL = (
    "SELECT i.invoice_number, i.status::text AS status, i.issue_date, i.due_date, i.billing_period_start, "
    "i.billing_period_end, i.currency, i.subtotal, i.discount_total, i.tax_total, i.total, i.amount_paid, "
    "i.amount_due, i.notes, c.name AS c_name, c.company_name, c.email AS c_email, c.phone AS c_phone, "
    "c.tax_id AS c_tax_id, c.billing_line1, c.billing_line2, c.billing_city, c.billing_state, "
    "c.billing_postal, c.billing_country, s.subscription_number, pt.name AS payment_term "
    "FROM invoices i JOIN customers c ON c.id = i.customer_id "
    "LEFT JOIN subscriptions s ON s.id = i.subscription_id "
    "LEFT JOIN payment_terms pt ON pt.id = s.payment_term_id WHERE i.id = :id")
_LINES_SQL = (
    "SELECT l.description, l.quantity, l.unit_price, l.discount_amount, l.tax_rate, l.tax_amount, "
    "l.line_total, d.code AS discount_code FROM invoice_lines l "
    "LEFT JOIN discounts d ON d.id = l.discount_id WHERE l.invoice_id = :id ORDER BY l.id")
_PAYMENTS_SQL = (
    "SELECT p.payment_number, p.transaction_date, p.method::text AS method, pa.amount "
    "FROM payment_allocations pa JOIN payments p ON p.id = pa.payment_id "
    "WHERE pa.invoice_id = :id AND p.status = 'succeeded' ORDER BY p.transaction_date, p.id")


def fetch_invoice_document(conn, invoice_id: int) -> InvoiceDoc:
    from sqlalchemy import text
    h = conn.execute(text(_HEADER_SQL), {"id": invoice_id}).mappings().first()
    if h is None:
        raise InvoiceNotFoundError(f"invoice {invoice_id} does not exist")
    lines = tuple(DocLine(r["description"], r["quantity"], r["unit_price"], r["discount_amount"],
                          r["tax_rate"], r["tax_amount"], r["line_total"], r["discount_code"])
                  for r in conn.execute(text(_LINES_SQL), {"id": invoice_id}).mappings().all())
    payments = tuple(DocPayment(r["payment_number"], r["transaction_date"], r["method"], r["amount"])
                     for r in conn.execute(text(_PAYMENTS_SQL), {"id": invoice_id}).mappings().all())
    city_line = ", ".join(x for x in (h["billing_city"], h["billing_state"], h["billing_postal"]) if x)
    address = tuple(x for x in (h["billing_line1"], h["billing_line2"], city_line, h["billing_country"]) if x)
    return InvoiceDoc(
        invoice_number=h["invoice_number"], status=h["status"], issue_date=h["issue_date"],
        due_date=h["due_date"], period_start=h["billing_period_start"], period_end=h["billing_period_end"],
        currency=(h["currency"] or "").strip(), subtotal=h["subtotal"], discount_total=h["discount_total"],
        tax_total=h["tax_total"], total=h["total"], amount_paid=h["amount_paid"], amount_due=h["amount_due"],
        customer_name=h["c_name"], customer_company=h["company_name"], customer_email=h["c_email"],
        customer_phone=h["c_phone"], customer_tax_id=h["c_tax_id"], customer_address=address,
        subscription_number=h["subscription_number"], payment_term=h["payment_term"], notes=h["notes"],
        lines=lines, payments=payments)


def generate_invoice_pdf(conn, invoice_id: int, company: CompanyInfo = CompanyInfo()) -> bytes:
    return render_invoice_pdf(fetch_invoice_document(conn, invoice_id), company)


def invoice_filename(doc: InvoiceDoc) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in doc.invoice_number)
    return f"{safe}.pdf"


# ------------------------------------------------------------------ rendering
def _fmt(value, currency: str = "") -> str:
    value = Decimal(value)
    text = f"{abs(value):,.2f}"
    return f"{'-' if value < 0 else ''}{currency} {text}".strip()


def _d(value: date) -> str:
    return value.strftime("%d %b %Y")


def tax_summary(doc: InvoiceDoc) -> list:
    """[(rate, taxable_amount, tax_amount)] grouped by rate, from the persisted lines."""
    groups: dict = {}
    for l in doc.lines:
        taxable = Decimal(l.quantity) * l.unit_price - l.discount_amount
        t, a = groups.get(l.tax_rate, (ZERO, ZERO))
        groups[l.tax_rate] = (t + taxable, a + l.tax_amount)
    return [(rate, t, a) for rate, (t, a) in sorted(groups.items())]


class _NumberedCanvas(rl_canvas.Canvas):
    """Two-pass canvas so the footer can say 'Page X of Y'."""

    def __init__(self, *args, footer: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved, self._footer = [], footer

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawString(18 * mm, 10 * mm, self._footer)
            self.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def render_invoice_pdf(doc: InvoiceDoc, company: CompanyInfo = CompanyInfo()) -> bytes:
    cur = doc.currency
    base = getSampleStyleSheet()["Normal"]
    P = lambda size=9, **kw: ParagraphStyle("x", parent=base, fontName=kw.pop("font", "Helvetica"),
                                            fontSize=size, leading=size + 3, textColor=kw.pop("color", INK), **kw)
    small, body, bold = P(8, color=MUTED), P(9), P(9, font="Helvetica-Bold")
    right, right_bold = P(9, alignment=TA_RIGHT), P(9, font="Helvetica-Bold", alignment=TA_RIGHT)
    cell, cell_r = P(8.5), P(8.5, alignment=TA_RIGHT)

    def para(text, style=body):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=20 * mm, title=f"Invoice {doc.invoice_number}", author=company.name)
    width = A4[0] - 36 * mm
    story = []

    # header: company | INVOICE + number
    status_colour = STATUS_COLOURS.get(doc.status, "#667085")
    left = [Paragraph(f"<b>{escape(company.name)}</b>", P(14))] + [para(x, small) for x in company.lines]
    rightcol = [Paragraph("INVOICE", P(18, font="Helvetica-Bold", alignment=TA_RIGHT)),
                para(doc.invoice_number, right_bold),
                Paragraph(f'<font color="{status_colour}"><b>{escape(doc.status.upper())}</b></font>', right)]
    story.append(Table([[left, rightcol]], colWidths=[width * .55, width * .45],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), .8, RULE),
                              ("BOTTOMPADDING", (0, 0), (-1, 0), 8)]))
    story.append(Spacer(1, 8))

    # bill to | dates
    bill = [Paragraph("BILL TO", small), para(doc.customer_name, bold)]
    if doc.customer_company:
        bill.append(para(doc.customer_company))
    bill += [para(x) for x in doc.customer_address]
    if doc.customer_email:
        bill.append(para(doc.customer_email, small))
    if doc.customer_phone:
        bill.append(para(doc.customer_phone, small))
    if doc.customer_tax_id:
        bill.append(para(f"Tax ID: {doc.customer_tax_id}", small))
    meta = [("Issue date", _d(doc.issue_date)), ("Due date", _d(doc.due_date)),
            ("Billing period", f"{_d(doc.period_start)} to {_d(doc.period_end)}")]
    if doc.subscription_number:
        meta.append(("Subscription", doc.subscription_number))
    if doc.payment_term:
        meta.append(("Payment terms", doc.payment_term))
    meta_t = Table([[para(k, small), para(v, right)] for k, v in meta], colWidths=[width * .17, width * .28],
                   style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])
    story.append(Table([[bill, meta_t]], colWidths=[width * .55, width * .45],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 12))

    # lines
    head = [para(h, P(8, font="Helvetica-Bold", color=MUTED, alignment=a)) for h, a in
            (("Description", 0), ("Qty", 2), ("Unit price", 2), ("Discount", 2), ("Tax %", 2), ("Tax", 2), ("Amount", 2))]
    rows = [head]
    for l in doc.lines:
        desc = escape(l.description) + (f'<br/><font size="7" color="#667085">Discount {escape(l.discount_code)}</font>'
                                        if l.discount_code and l.discount_amount > 0 else "")
        rows.append([Paragraph(desc, cell), para(l.quantity, cell_r), para(_fmt(l.unit_price), cell_r),
                     para(_fmt(l.discount_amount) if l.discount_amount else "-", cell_r),
                     para(f"{l.tax_rate.normalize():f}" if l.tax_rate else "0", cell_r),
                     para(_fmt(l.tax_amount), cell_r), para(_fmt(l.line_total), cell_r)])
    cw = [width * f for f in (.32, .06, .14, .12, .09, .12, .15)]
    story.append(Table(rows, colWidths=cw, repeatRows=1, style=[
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), .4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(Spacer(1, 10))

    # tax summary (left) | totals (right)
    ts = [[para(h, P(8, font="Helvetica-Bold", color=MUTED, alignment=a)) for h, a in
           (("Tax rate", 0), ("Taxable", 2), ("Tax", 2))]]
    for rate, taxable, tax in tax_summary(doc):
        ts.append([para(f"{rate.normalize():f}%" if rate else "No tax", cell), para(_fmt(taxable), cell_r),
                   para(_fmt(tax), cell_r)])
    tax_t = Table(ts, colWidths=[width * .12, width * .15, width * .13],
                  style=[("LINEBELOW", (0, 0), (-1, -1), .4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 2),
                         ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    tot = [("Subtotal", doc.subtotal, False), ("Discount", -doc.discount_total if doc.discount_total else ZERO, False),
           ("Tax", doc.tax_total, False), ("Total", doc.total, True),
           ("Paid", doc.amount_paid, False), ("Amount due", doc.amount_due, True)]
    tot_rows = [[para(k, right_bold if strong else right), para(_fmt(v, cur), right_bold if strong else right)]
                for k, v, strong in tot]
    tot_t = Table(tot_rows, colWidths=[width * .17, width * .26], style=[
        ("LINEABOVE", (0, 3), (-1, 3), .8, INK), ("LINEABOVE", (0, 5), (-1, 5), .8, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    story.append(Table([[tax_t, tot_t]], colWidths=[width * .40, width * .60],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))

    if doc.payments:
        story += [Spacer(1, 12), Paragraph("PAYMENTS RECEIVED", small)]
        prow = [[para(p.number, cell), para(_d(p.paid_on), cell), para(p.method.replace("_", " "), cell),
                 para(_fmt(p.amount, cur), cell_r)] for p in doc.payments]
        story.append(Table(prow, colWidths=[width * .30, width * .22, width * .22, width * .26],
                           style=[("LINEBELOW", (0, 0), (-1, -1), .4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    if doc.notes:
        story += [Spacer(1, 12), Paragraph("NOTES", small), para(doc.notes)]

    footer = f"{company.name}  |  {doc.invoice_number}  |  computer-generated invoice"
    pdf.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, **k))
    return buf.getvalue()

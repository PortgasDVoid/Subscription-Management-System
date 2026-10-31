"""Invoice PDF renderer (ReportLab)."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

def render_invoice_pdf(invoice, lines):
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm)
    styles=getSampleStyleSheet(); story=[]
    story += [Paragraph("BRIGHTLOOP SOFTWARE",styles["Title"]),Paragraph("SUBSCRIPTION INVOICE",styles["Heading2"]),Spacer(1,8)]
    story.append(Paragraph(f"<b>Invoice:</b> {invoice['invoice_number']} &nbsp;&nbsp; <b>Status:</b> {invoice['status']}",styles['Normal']))
    story.append(Paragraph(f"<b>Issued:</b> {invoice['issue_date']} &nbsp;&nbsp; <b>Due:</b> {invoice['due_date']}",styles['Normal']))
    story.append(Paragraph(f"<b>Customer:</b> {invoice['customer_name']} ({invoice['customer_email']})",styles['Normal']))
    story.append(Paragraph(f"<b>Billing address:</b> {invoice.get('billing_line1') or ''}, {invoice.get('billing_city') or ''}, {invoice.get('billing_state') or ''} {invoice.get('billing_postal') or ''}",styles['Normal']))
    story.append(Spacer(1,12))
    data=[["Description","Qty","Unit price","Discount","Tax %","Tax","Line total"]]
    for x in lines:
        data.append([x['description'],str(x['quantity']),f"{x['unit_price']:.2f}",f"{x['discount_amount']:.2f}",f"{x['tax_rate']:.2f}",f"{x['tax_amount']:.2f}",f"{x['line_total']:.2f}"])
    table=Table(data,repeatRows=1,colWidths=[57*mm,12*mm,23*mm,20*mm,15*mm,20*mm,23*mm])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#23395B')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.4,colors.grey),('ALIGN',(1,1),(-1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('FONTSIZE',(0,0),(-1,-1),8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F3F6FA')]),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.append(table); story.append(Spacer(1,14))
    summary=[["Subtotal",f"{invoice['currency']} {invoice['subtotal']:.2f}"],["Discount",f"- {invoice['discount_total']:.2f}"],["Tax",f"{invoice['tax_total']:.2f}"],["TOTAL",f"{invoice['currency']} {invoice['total']:.2f}"],["Amount paid",f"{invoice['amount_paid']:.2f}"],["Outstanding",f"{invoice['amount_due']:.2f}"]]
    t=Table(summary,colWidths=[45*mm,45*mm],hAlign='RIGHT'); t.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('FONTNAME',(0,-3),(-1,-3),'Helvetica-Bold'),('LINEABOVE',(0,-3),(-1,-3),1,colors.black),('FONTSIZE',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),5)])); story.append(t)
    story.append(Spacer(1,18)); story.append(Paragraph("Thank you for your business. This is a computer-generated invoice.",styles['Italic']))
    doc.build(story); return buf.getvalue()

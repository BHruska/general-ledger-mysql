"""
General Ledger v0.5.1
File: utils/invoice_pdf.py
Description: The invoice PDF (docs/DESIGN.md section 8.2), drawn with fpdf2: pure Python,
             so the image needs no system libraries. One layout: company, invoice number
             and dates, bill-to, lines, total and balance, memo, and "How to pay" by Zelle.

Zelle has no payment-request link a third party can make, so the box prints the enrolled
address and the name the customer's bank app will show, and asks for the invoice number
in the memo -- which is what lets the review queue match the payment to the invoice.
"""

import unicodedata
from decimal import Decimal

from fpdf import FPDF

from models import Invoice, Payee, Settings

BLUE = (0, 123, 255)
TEXT = (51, 51, 51)
MUTED = (102, 102, 102)
LIGHT = (233, 236, 239)
TINT = (231, 243, 255)


def _t(text) -> str:
    """fpdf2's built-in Helvetica is Latin-1 only. Map what customers type (curly quotes,
    dashes) to plain equivalents rather than print a replacement box on an invoice."""
    text = str(text or "")
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("…", "..."), (" ", " ")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKC", text)
    return text.encode("latin-1", "replace").decode("latin-1")


def _money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _qty(value: Decimal) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"


def render(session, inv: Invoice) -> bytes:
    settings = session.get(Settings, 1)
    customer = session.get(Payee, inv.customer_id)
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    # Header: company on the left, INVOICE and number on the right.
    top = pdf.get_y()
    pdf.set_text_color(*TEXT)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(width * 0.6, 20, _t(settings.company_name or "Invoice"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    for line in (settings.company_address or "").splitlines():
        pdf.cell(width * 0.6, 14, _t(line), new_x="LMARGIN", new_y="NEXT")
    left_bottom = pdf.get_y()

    pdf.set_xy(pdf.l_margin + width * 0.6, top)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*BLUE)
    title = "INVOICE" if inv.status != "DRAFT" else "DRAFT INVOICE"
    pdf.cell(width * 0.4, 26, title, align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(*TEXT)
    pdf.set_font("Helvetica", "", 10)
    rows = [("Invoice #", inv.number or "(not yet issued)"), ("Date", inv.issue_date.strftime("%B %d, %Y")),
            ("Due", inv.due_date.strftime("%B %d, %Y") + (f" ({inv.terms})" if inv.terms else ""))]
    if inv.status == "VOID":
        rows.append(("Status", "VOID"))
    for label, value in rows:
        pdf.set_x(pdf.l_margin + width * 0.6)
        pdf.cell(width * 0.4, 14, _t(f"{label}:  {value}"), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 18)

    # Bill to.
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(width, 12, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*TEXT)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(width, 15, _t(customer.name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in (customer.address or "").splitlines():
        pdf.cell(width, 13, _t(line), new_x="LMARGIN", new_y="NEXT")
    if customer.email:
        pdf.cell(width, 13, _t(customer.email), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(14)

    # Lines.
    cols = (width * 0.58, width * 0.12, width * 0.15, width * 0.15)
    pdf.set_fill_color(*LIGHT)
    pdf.set_font("Helvetica", "B", 9)
    for text, w, align in zip(("DESCRIPTION", "QTY", "RATE", "AMOUNT"), cols, ("L", "R", "R", "R")):
        pdf.cell(w, 20, text, align=align, fill=True)
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 10)
    for line in inv.lines:
        y = pdf.get_y()
        pdf.multi_cell(cols[0], 15, _t(line.description), new_x="RIGHT", new_y="TOP")
        height = max(pdf.get_y() - y, 15)
        pdf.set_xy(pdf.l_margin + cols[0], y)
        pdf.cell(cols[1], 15, _qty(line.quantity), align="R")
        pdf.cell(cols[2], 15, _money(line.rate), align="R")
        pdf.cell(cols[3], 15, _money(line.amount), align="R")
        pdf.set_y(y + height + 4)
        pdf.set_draw_color(*LIGHT)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
        pdf.ln(4)

    # Totals.
    label_w, value_w = width * 0.25, width * 0.15
    x = pdf.l_margin + width - label_w - value_w
    totals = [("Total", inv.total)]
    if inv.amount_paid:
        totals += [("Paid", -inv.amount_paid), ("Balance due", inv.balance)]
    for n, (label, value) in enumerate(totals):
        pdf.set_x(x)
        pdf.set_font("Helvetica", "B" if n == len(totals) - 1 else "", 11)
        pdf.cell(label_w, 18, label, align="R")
        pdf.cell(value_w, 18, _money(value), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    if inv.memo:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(width, 14, _t(inv.memo), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*TEXT)
        pdf.ln(8)

    # How to pay.
    if settings.zelle_recipient and inv.status not in ("VOID", "PAID"):
        pdf.set_fill_color(*TINT)
        pdf.set_draw_color(182, 212, 254)
        y = pdf.get_y()
        shown_as = f" (shows as {settings.zelle_display_name})" if settings.zelle_display_name else ""
        text = (f"Pay by Zelle to {settings.zelle_recipient}{shown_as}.\n"
                f"Please put invoice {inv.number or ''} in the Zelle memo.")
        pdf.set_xy(pdf.l_margin + 10, y + 10)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(width - 20, 16, "How to pay", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(pdf.l_margin + 10)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(width - 20, 14, _t(text), new_x="LMARGIN", new_y="NEXT")
        box_h = pdf.get_y() - y + 10
        pdf.rect(pdf.l_margin, y, width, box_h, style="D")
        pdf.set_y(y + box_h + 10)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(width, 14, "Thank you for your business.", align="C")
    return bytes(pdf.output())

""" EOF - invoice_pdf.py """

"""
General Ledger v0.5.1
File: routes/invoice_routes.py
Description: Invoices and Customers pages and their JSON API (drafts, issue, void, PDF),
             and the A/R aging report.
"""

import csv
import io
from datetime import date

from flask import Blueprint, Response, render_template, request

from routes.api import body, envelope
from utils import invoices
from utils.errors import LedgerError, NotFound
from utils.money import parse_optional_date

invoice_bp = Blueprint("invoices", __name__)


@invoice_bp.route("/invoices")
def invoices_page():
    return render_template("invoices.html")


@invoice_bp.route("/invoices/new")
def new_invoice_page():
    return render_template("invoice_edit.html", invoice_id=None)


@invoice_bp.route("/invoices/<int:invoice_id>/edit")
def edit_invoice_page(invoice_id):
    return render_template("invoice_edit.html", invoice_id=invoice_id)


@invoice_bp.route("/invoices/<int:invoice_id>/pdf")
def invoice_pdf(invoice_id):
    try:
        data, name = invoices.pdf_bytes(invoice_id)
    except NotFound:
        return Response("No such invoice.\n", status=404, mimetype="text/plain")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "private, no-store",
                             "X-Content-Type-Options": "nosniff"})


@invoice_bp.route("/invoices/<int:invoice_id>")
def invoice_page(invoice_id):
    return render_template("invoice_view.html", invoice_id=invoice_id)


@invoice_bp.route("/invoices/customers")
def customers_page():
    return render_template("customers.html")


@invoice_bp.route("/reports/ar-aging")
def ar_aging_page():
    return render_template("reports_ar_aging.html")


@invoice_bp.route("/api/invoices", methods=["GET"])
@envelope
def list_invoices():
    return invoices.list_invoices(request.args.get("status") or None,
                                  request.args.get("customer_id", type=int))


@invoice_bp.route("/api/invoices/<int:invoice_id>", methods=["GET"])
@envelope
def get_invoice(invoice_id):
    return {"invoice": invoices.get_invoice(invoice_id)}


@invoice_bp.route("/api/invoices", methods=["POST"])
@envelope
def create_invoice():
    return {"invoice": invoices.save_draft(body())}


@invoice_bp.route("/api/invoices/check", methods=["POST"])
@envelope
def check_invoice():
    return {"check": invoices.check_draft(body())}


@invoice_bp.route("/api/invoices/open", methods=["GET"])
@envelope
def open_invoices():
    return {"invoices": invoices.open_invoices()}


@invoice_bp.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
@envelope
def update_invoice(invoice_id):
    return {"invoice": invoices.save_draft(body(), invoice_id)}


@invoice_bp.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
@envelope
def delete_invoice(invoice_id):
    invoices.delete_draft(invoice_id)
    return {}


@invoice_bp.route("/api/invoices/<int:invoice_id>/issue", methods=["POST"])
@envelope
def issue_invoice(invoice_id):
    return {"invoice": invoices.issue(invoice_id)}


@invoice_bp.route("/api/invoices/<int:invoice_id>/void", methods=["POST"])
@envelope
def void_invoice(invoice_id):
    return {"invoice": invoices.void(invoice_id)}


@invoice_bp.route("/api/customers", methods=["POST"])
@envelope
def create_customer():
    return {"customer": invoices.create_customer(body())}


@invoice_bp.route("/api/customers", methods=["GET"])
@envelope
def list_customers():
    return invoices.list_customers()


def _as_of() -> date:
    return parse_optional_date(request.args.get("as_of"), "As-of date") or date.today()


@invoice_bp.route("/api/reports/ar-aging", methods=["GET"])
@envelope
def ar_aging():
    return {"report": invoices.ar_aging(_as_of())}


@invoice_bp.route("/api/reports/ar-aging.csv", methods=["GET"])
def ar_aging_csv():
    try:
        r = invoices.ar_aging(_as_of())
    except LedgerError as e:
        return Response(f"Report failed: {e}\n", status=400, mimetype="text/plain")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Customer"] + [b["label"] for b in r["buckets"]] + ["Total"])
    for row in r["rows"]:
        w.writerow([row["customer"]] + [row[b["key"]] for b in r["buckets"]] + [row["total"]])
    w.writerow(["Total"] + [r["totals"][b["key"]] for b in r["buckets"]] + [r["totals"]["total"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ar-aging-{r["as_of"]}.csv"'})

""" EOF - invoice_routes.py """

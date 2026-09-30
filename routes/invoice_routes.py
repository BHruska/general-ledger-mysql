"""
General Ledger v0.5.0
File: routes/invoice_routes.py
Description: Invoices and Customers pages and their JSON API, and the A/R aging report.
"""

import csv
import io
from datetime import date

from flask import Blueprint, Response, render_template, request

from routes.api import envelope
from utils import invoices
from utils.errors import LedgerError
from utils.money import parse_optional_date

invoice_bp = Blueprint("invoices", __name__)


@invoice_bp.route("/invoices")
def invoices_page():
    return render_template("invoices.html")


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

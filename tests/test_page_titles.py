"""
General Ledger v0.1.0
File: tests/test_page_titles.py
Description: Every browser tab reads "Ledger - <Page Name>" (docs/STYLING.md section 3).
             base.html applies the prefix; this renders every page template, so a new
             page that bypasses base.html or hand-types a title fails here.
"""

import re
from pathlib import Path

import pytest
from flask import render_template

import config

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PAGES = sorted(p.name for p in TEMPLATES.glob("*.html") if p.name != "base.html")


@pytest.mark.parametrize("page", PAGES)
def test_title_leads_with_the_app_prefix(app, page):
    with app.test_request_context("/"):
        html = render_template(page)
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    assert title.startswith(f"{config.APP_TITLE_PREFIX} - "), title
    assert title.count(config.APP_TITLE_PREFIX) == 1, title
    assert title != f"{config.APP_TITLE_PREFIX} - ", "page_title is empty"

""" EOF - test_page_titles.py """

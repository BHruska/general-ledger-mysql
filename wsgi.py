"""
General Ledger v0.1.0
File: wsgi.py
Description: Gunicorn entry point. `gunicorn wsgi:app`.
"""

from app import app

__all__ = ["app"]

""" EOF - wsgi.py """

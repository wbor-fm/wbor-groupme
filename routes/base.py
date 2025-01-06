"""
Base routes for the Flask app.
"""

from flask import Blueprint

base = Blueprint("base", __name__)


@base.route("/")
def is_online():
    """
    Health check endpoint.
    """
    return "OK", 200

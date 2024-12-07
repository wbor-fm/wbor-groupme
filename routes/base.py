"""
Base routes for the Flask app.
"""

from flask import Blueprint

base = Blueprint("base", __name__)


@base.route("/")
def hello_world():
    """Serve a simple static Hello World page at the root"""
    return "<h1>wbor-groupme is online!</h1>"

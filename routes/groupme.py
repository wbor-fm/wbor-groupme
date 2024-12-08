"""
Module for GroupMe API endpoints.
"""

from flask import Blueprint, request
from utils.logging import configure_logging
from utils.command_parser import CommandParser
from rabbitmq.publisher import publish_log_pg

logger = configure_logging(__name__)

groupme = Blueprint("groupme", __name__)


@groupme.route("/callback", methods=["POST"])
def groupme_callback():
    """
    Callback endpoint for GroupMe API upon messages being sent to the group chat.
    """
    body = request.json
    sender_type = body.get("sender_type")
    if sender_type != "bot":
        logger.info("GroupMe callback received: %s", body)
        text = body.get("text")
        CommandParser.parse_message(text)
        publish_log_pg(
            body,
            source="groupme.callback",
            statuscode=200,
            uid=body.get("source_guid"),
            routing_key="groupme.callback",
        )
    return "OK"

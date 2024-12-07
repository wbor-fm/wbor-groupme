"""
Module for GroupMe API endpoints.
"""

from flask import Blueprint, request
from utils.logging import configure_logging
from utils.groupme import GroupMe
from utils.command_parser import CommandParser

logger = configure_logging(__name__)

groupme = Blueprint("groupme", __name__)


def parse_message(text):
    """
    Parse a GroupMe message sent by a group member.

    Parameters:
    - text (str): The message text to parse

    Returns:
    - None
    """
    if not text.startswith("!"):
        return

    command_parser = CommandParser(GroupMe)
    command_parser.execute_command(text)


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
        parse_message(text)
    return "OK"

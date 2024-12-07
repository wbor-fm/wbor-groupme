"""
Module for GroupMe API endpoints.
"""

from flask import Blueprint, request
from utils.logging import configure_logging
from utils.groupme import GroupMe
from handlers.admin import ban, unban, get_stats

logger = configure_logging(__name__)

groupme = Blueprint("groupme", __name__)


def parse_message(text):
    """
    Parse a GroupMe message sent by a group member.

    TODO: Put actual functionality in a separate class.

    Parameters:
    - text (str): The message text to parse

    Returns:
    - None
    """
    if text.startswith("!"):
        command = text.split(" ")[0].lower()
        uid_arg = text.split(" ")[1] if len(text.split(" ")) > 1 else "NO_UID"
        if command == "!help":
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "Available commands:\n"
                        "!help - Display this help message\n"
                        "!ping - Check if the bot is online\n"
                        "!ban <UID> - Ban a phone number from sending messages\n"
                        "!unban <UID> - Unban a phone number from sending messages\n"
                        "!stats <UID> - Display message statistics for a phone number"
                    )
                }
            )
        elif command == "!ping":
            GroupMe.send_to_groupme({"text": f"Pong! UID: {uid_arg}"})
        elif command == "!ban":
            if ban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has been "
                        "banned from sending messages."
                    }
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Ban functionality is not yet implemented. "
                            "This will block a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    }
                )
        elif command == "!unban":
            if unban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has "
                        "been UNBANNED from sending messages."
                    }
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Unban functionality is not yet implemented. "
                            "This will unblock a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    }
                )
        elif command == "!stats":
            stats = get_stats(uid_arg)
            if stats:
                # send_stats(stats)
                pass
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Stats functionality is not yet implemented. "
                            "This will include information such as the # of messages sent by a #. "
                            f"UID: {uid_arg}"
                        )
                    }
                )
        else:
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "Unknown command.\n\n"
                        "Type `!help` to see a list of available commands."
                    )
                }
            )


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

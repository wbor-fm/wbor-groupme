"""
A class to parse and execute GroupMe admin commands.
"""

from utils.groupme import GroupMe
from utils.admin import ban, unban, get_stats


class CommandParser:
    """
    A class to parse and execute GroupMe commands.
    """

    def execute_command(self, text):
        """
        Parse and execute a GroupMe command.

        Parameters:
        - text (str): The message text to parse.

        Returns:
        - None
        """
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
                },
                source="command_parser",
            )
        elif command == "!ping":
            GroupMe.send_to_groupme(
                {"text": f"Pong! UID: {uid_arg}"}, source="command_parser"
            )
        elif command == "!ban":
            if ban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has been "
                        "banned from sending messages."
                    },
                    source="command_parser",
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Ban functionality is not yet implemented. "
                            "This will block a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    },
                    source="command_parser",
                )
        elif command == "!unban":
            if unban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has "
                        "been UNBANNED from sending messages."
                    },
                    source="command_parser",
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Unban functionality is not yet implemented. "
                            "This will unblock a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    },
                    source="command_parser",
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
                    },
                    source="command_parser",
                )
        else:
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "Unknown command.\n\n"
                        "Type `!help` to see a list of available commands."
                    )
                },
                source="command_parser",
            )

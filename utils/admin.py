"""
MGMT admin functions.
"""

from utils.logging import configure_logging

logger = configure_logging(__name__)


def ban(uid, ban):
    """
    Ban or unban a phone number from sending messages to the station.

    Parameters:
    - uid (str): The message UID of the person to ban/unban
    - ban (bool): True to ban the phone number, False to unban

    Returns:
    - bool: True if the phone number was successfully banned/unbanned, False otherwise
    """
    # 1. Get the phone number associated with the UID by searching the received messages logs
    # - Fetch record & extract phone number
    # - If there are more than one match for the provided UID, choose the most recent one
    # 2. Add the phone number to the ban list table
    # - Insert record
    # 3. Eventually, clear all messages from the sender in the current message queue
    # (that is shown on the dashboard)
    logger.info("Banning phone number associated with UID: %s", uid)
    return False


def get_stats(uid):
    """
    Retrieve message statistics for a phone number. Includes:
    - Number of messages sent
    - Number of images sent
    - Last message sent
    """
    # 1. Get the phone number associated with the UID by searching the received messages logs
    # - Fetch record & extract phone number
    # 2. Fetch message statistics from the database
    # - Query the message logs table
    logger.info(
        "Retrieving message statistics for phone number associated with UID: %s", uid
    )
    return False

"""
MGMT admin functions.
"""

from utils.logging import configure_logging

logger = configure_logging(__name__)


def ban(uid):
    """
    Ban a phone number from sending messages to the station.

    Parameters:
    - uid (str): The message UID of the person to ban

    Returns:
    - bool: True if the phone number was successfully banned, False otherwise
    """
    # 1. Get the phone number associated with the UID by searching the received messages logs
    # - Fetch record & extract phone number
    # 2. Add the phone number to the ban list table
    # - Insert record
    # 3. Eventually, clear all messages from the sender in the current message queue
    # (that is shown on the dashboard)
    logger.info("Banning phone number associated with UID: %s", uid)
    return False


def unban(uid):
    """
    Unban a phone number from sending messages to the station.

    Parameters:
    - uid (str): The message UID of the person to ban

    Returns:
    - bool: True if the phone number was successfully banned, False otherwise
    """
    # 1. Get the phone number associated with the UID by searching the received messages logs
    # - Fetch record & extract phone number
    # 2. Remove the phone number from the ban list table
    # - Delete record
    logger.info("Unbanning phone number associated with UID: %s", uid)
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

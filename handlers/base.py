"""
Module for base classes for handlers.
"""

from utils.logging import configure_logging
from utils.groupme import GroupMe

logger = configure_logging(__name__)


class MessageSourceHandler:
    """
    Base class for message source handlers.
    """

    def process_message(self, message, subkey, alreadysent):
        """
        Logic to process a message from the source.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

    @staticmethod
    def send_message_to_groupme(message, extract_images, source):
        """
        Generalized method to send messages and images to GroupMe.

        Parameters:
        - message (dict): The message data.
        - uid (str): The unique message ID.
        - extract_images (callable): The handler-specific function to extract images.
        - source (str): The source of the message.

        Returns:
        - None
        """
        # Normalize field names due to differences between sources
        # Twilio capitalizes `Body`, while other sources use `body`
        body = message.get("body") or message.get("Body")
        uid = message.get("wbor_message_id")
        if not body:
            logger.warning("Message body is missing for UID: %s", uid)
            return

        logger.debug("Preparing to send message: %s: %s", uid, body)

        # Split and send text segments
        segments = GroupMe.split_message(body)
        GroupMe.send_text_segments(segments, source, uid)

        # Extract images using the handler's method
        groupme_images, unsupported_type = extract_images(message, source, uid)

        if groupme_images:
            GroupMe.send_images(groupme_images, source, uid)
            logger.info("Images sent for: %s", uid)

        if unsupported_type:
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "A media item was sent with an unsupported format.\n\n"
                        "Check the message in Twilio logs for details.\n"
                        "---------\n"
                        "%s\n"
                        "---------",
                        uid,
                    )
                },
                source,
                uid=uid,
            )

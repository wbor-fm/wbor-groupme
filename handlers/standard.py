"""
Standard message processing and forwarding, e.g. for the UPS/AzuraCast/etc. sources.
"""

from utils.logging import configure_logging
from utils.groupme import GroupMe
from .base import MessageSourceHandler

logger = configure_logging(__name__)


class StandardHandler(MessageSourceHandler):
    """
    Catch-all message processing and forwarding, e.g. for the UPS/AzuraCast/etc. sources.

    The request body is expected to include the following fields:
    - body (str): The message text
    - wbor_message_id (str): The unique message ID
    - images (list): A list of image URLs (optional)

    Returns:
    - bool: True if the message was successfully processed, False otherwise
    """

    def process_message(self, body):
        logger.debug(
            "Standard `process_message` called for: %s",
            body.get("wbor_message_id"),
        )
        self.send_message_to_groupme(body)
        return True
        # Ack (to other container) not needed, unlike Twilio

    @staticmethod
    def send_message_to_groupme(message):
        """
        Send a message to GroupMe.

        Parameters:
        - message (dict): The message to send

        Returns:
        - None
        """
        body = message.get("body")
        uid = message.get("wbor_message_id")
        logger.debug("Sending message: %s: %s", uid, body)

        # Split the message into segments if it exceeds GroupMe's character limit
        if body:
            segments = GroupMe.split_message(body)
            GroupMe.send_text_segments(segments, uid)
        else:
            logger.error("Message body is missing, message not sent.")

        # Extract image URLs from the message and upload them to GroupMe
        groupme_images, unsupported_type = StandardHandler.extract_images(message, uid)

        if groupme_images:
            GroupMe.send_images(groupme_images)
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
                uid=uid,
            )

    @staticmethod
    def extract_images(message, uid):
        """
        Extract image URLs from the message response body and upload them to GroupMe's image
        service.

        Parameters:
        - message (dict): The standard message response body
        - uid (str): The unique message ID

        Returns:
        - groupme_images (list): A list of image URLs from GroupMe's image service
        - unsupported_type (bool): True if an unsupported media type was found, False otherwise
        """
        unsupported_type = False

        images = message.get("images")
        groupme_images = []
        if images:
            for image_url in images:
                upload_response = GroupMe.upload_image(image_url, uid)
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        groupme_images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", image_url)
                    unsupported_type = True
        return groupme_images, unsupported_type

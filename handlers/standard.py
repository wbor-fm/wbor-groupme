"""
Standard message processing and forwarding, e.g. for the UPS/AzuraCast/etc. sources.
"""

from utils.logging import configure_logging
from utils.groupme import GroupMe
from rabbitmq.publisher import publish_log_pg
from .base import MessageSourceHandler

logger = configure_logging(__name__)


class StandardHandler(MessageSourceHandler):
    """
    Bound to key `source.standard`.

    The request body is expected to include the following fields:
    - body (str): The message text
    - wbor_message_id (str): The unique message ID
    - images (list): A list of image URLs (optional)

    Returns:
    - bool: True if the message was successfully processed, False otherwise
    """

    def process_message(self, body, subkey, alreadysent=False):
        subkey = subkey or None

        logger.debug(
            "Standard `process_message` called for: %s",
            body.get("wbor_message_id"),
        )
        logger.debug("Subkey: %s", subkey)
        logger.debug("Type: %s", body.get("type"))
        # TODO: decide on keeping type field embedded in the message body versus using the subkey

        # If the message was already sent, skip sending and just log the API interaction
        # TODO: there's a chance the downstream producer had image API interactions as well
        if alreadysent:
            logger.info("Message already sent: %s", body.get("wbor_message_id"))
            publish_log_pg(
                body,
                source=body.get("source"),
                statuscode=body.get("statuscode"),
                uid=body.get("wbor_message_id"),
                routing_key="groupme.msg",
            )
            return True

        self.send_message_to_groupme(
            body,
            body.get("wbor_message_id"),
            self.extract_images,
            source=body.get("source"),
        )
        return True  # Ack (to other container) not needed, unlike Twilio

    @staticmethod
    def extract_images(message, source, uid):
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
                upload_response = GroupMe.upload_image(image_url, source, uid)
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        groupme_images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", image_url)
                    unsupported_type = True
        return groupme_images, unsupported_type

"""
Module for handling Twilio-specific message processing and forwarding.
"""

import requests
from config import ACK_URL
from utils.logging import configure_logging
from utils.groupme import GroupMe
from .base import MessageSourceHandler

logger = configure_logging(__name__)


class TwilioHandler(MessageSourceHandler):
    """
    Handles Twilio-specific message processing and forwarding.
    """

    def process_message(self, body):
        """
        Process a text message from Twilio.

        Returns:
        - bool: True if the message was successfully processed, False otherwise
        """
        logger.debug(
            "Twilio `process_message` called for: %s",
            body.get("wbor_message_id"),
        )
        self.send_message_to_groupme(body)

        # Send acknowledgment back to wbor-twilio (the sender)
        logger.debug("Sending acknowledgment for: %s", body["wbor_message_id"])
        ack_response = requests.post(
            ACK_URL,
            json={"wbor_message_id": body["wbor_message_id"]},
            timeout=3,
        )
        if ack_response.status_code == 200:
            logger.debug("Acknowledgment sent for: %s", body["wbor_message_id"])
            return True
        logger.error(
            "Acknowledgment failed for: %s. Status: %s",
            body["wbor_message_id"],
            ack_response.status_code,
        )
        return False

    @staticmethod
    def send_message_to_groupme(message):
        """
        Primary handler!

        Send a text message with optional images to GroupMe.

        This entire process should take no longer than 5 seconds to complete.

        Parameters:
        - message (dict): The message response body from Twilio

        Returns:
        - None

        Throws:
        - requests.exceptions.RequestException: If the HTTP request fails
        - KeyError: If the message body is missing
        """
        try:
            body = message.get("Body")
            uid = message.get("wbor_message_id")
            logger.debug("Sending message: %s: %s", uid, body)

            # Extract images from the message and upload them to GroupMe
            images, unsupported_type = TwilioHandler.extract_images(message)

            # Split the message into segments if it exceeds GroupMe's character limit
            if body:
                segments = GroupMe.split_message(body)
                GroupMe.send_text_segments(segments, uid)

            if images:
                GroupMe.send_images(images)

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

        except (requests.exceptions.RequestException, KeyError) as e:
            logger.error("Failed to send message: %s", e)

    @staticmethod
    def extract_images(message):
        """
        Extract image URLs from Twilio's message response body and upload them to GroupMe's image
        service.

        Assumes that only up to 10 images are present in the original message.
        (which is what Twilio supports)

        Parameters:
        - message (dict): The message response body from Twilio

        Returns:
        - images (list): A list of image URLs from GroupMe's image service
        - unsupported_type (bool): True if an unsupported media type was found, False otherwise
        """
        unsupported_type = False

        images = []
        for i in range(10):
            media_url_key = f"MediaUrl{i}"
            if media_url_key in message:
                upload_response = GroupMe.upload_image(message[media_url_key])
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", message[media_url_key])
                    unsupported_type = True
        return images, unsupported_type

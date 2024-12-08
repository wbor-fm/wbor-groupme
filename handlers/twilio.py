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

    def process_message(self, body, subkey):
        """
        Process a text message from Twilio.

        Twilio bodies have a `type` field.

        source.twilio.# is consumed by this handler.

        Possible types / subkeys:
        - sms.incoming

        Returns:
        - bool: True if the message was successfully processed, False otherwise
        """
        logger.debug(
            "Twilio `process_message` called for: %s",
            body.get("wbor_message_id"),
        )
        logger.debug("Subkey: %s", subkey)
        logger.debug("Type: %s", body.get("type"))
        self.send_message_to_groupme(
            body, body.get("wbor_message_id"), self.extract_images, source="twilio"
        )

        # Send ack back to wbor-twilio (the sender)
        logger.debug("Sending acknowledgment for: %s", body["wbor_message_id"])
        try:
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
        except requests.exceptions.RequestException as e:
            # Handle issues with the HTTP request to the acknowledgment URL
            logger.error(
                "Failed to send acknowledgment for: %s. Exception: %s",
                body["wbor_message_id"],
                e,
            )
            return False
        except KeyError as e:
            # Handle issues with the message body
            logger.error("Failed to send acknowledgment: %s", e)
            return False

    @staticmethod
    def extract_images(message, source, uid):
        """
        Extract image URLs from Twilio's message response body and upload them to GroupMe's image
        service.

        Assumes that only up to 10 images are present in the original message.
        (which is what Twilio supports)

        Parameters:
        - message (dict): The message response body from Twilio
        - uid (str): The unique ID for the message

        Returns:
        - images (list): A list of image URLs from GroupMe's image service
        - unsupported_type (bool): True if an unsupported media type was found, False otherwise
        """
        unsupported_type = False
        groupme_images = []
        for i in range(10):
            media_url_key = f"MediaUrl{i}"
            if media_url_key in message:
                upload_response = GroupMe.upload_image(
                    message[media_url_key], source, uid
                )
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        groupme_images.append(image_url)
                        logger.info("Image uploaded for: %s: %s", uid, image_url)
                else:
                    logger.warning("Failed to upload media: %s", message[media_url_key])
                    unsupported_type = True
        return groupme_images, unsupported_type

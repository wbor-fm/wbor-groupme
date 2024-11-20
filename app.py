"""
GroupMe Handler.
- Consumes messages from the RabbitMQ queue to forward to a GroupMe group chat.

TO-DO:
- Generalize to support other incoming message sources (not just Twilio)
- Log GroupMe API calls in Postgres, including origination source (Twilio, etc.)
    - Assign a unique ID to each message to prevent duplicates
- Store and retry failed messages - use RabbitMQ dead-letter exchange
- Queue messages to prevent rate limiting or unordered sending by GroupMe
- Assign Twilio related functions to a separate module
- Write class for GroupMe API calls
- Callback actions - block sender based on the message's UID
"""

import os
import logging
import json
from datetime import datetime, timezone
import sys
import time
import requests
import pika
import pika.exceptions
import pytz
from flask import Flask
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
APP_PORT = os.getenv("APP_PORT", "2000")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "wbor-rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
GROUPME_QUEUE = os.getenv("GROUPME_QUEUE", "groupme")
GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
GROUPME_ACCESS_TOKEN = os.getenv("GROUPME_ACCESS_TOKEN")
GROUPME_CHARACTER_LIMIT = abs(int(os.getenv("GROUPME_CHARACTER_LIMIT", "900")))

GROUPME_API = "https://api.groupme.com/v3/bots/post"
GROUPME_IMAGE_API = "https://image.groupme.com/pictures"

ACK_URL = "http://wbor-twilio:5000/acknowledge"

# Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Define a handler to output to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)


class EasternTimeFormatter(logging.Formatter):
    """Custom log formatter to display timestamps in Eastern Time"""

    def formatTime(self, record, datefmt=None):
        # Convert UTC to Eastern Time
        eastern = pytz.timezone("America/New_York")
        utc_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        eastern_dt = utc_dt.astimezone(eastern)
        # Use ISO 8601 format
        return eastern_dt.isoformat()


formatter = EasternTimeFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logging.getLogger("werkzeug").setLevel(logging.INFO)

app = Flask(__name__)

if not GROUPME_BOT_ID or not GROUPME_ACCESS_TOKEN:
    logger.critical(
        "GROUPME_BOT_ID or GROUPME_ACCESS_TOKEN is missing. Exiting application."
    )
    sys.exit(1)


def sanitize_text(string, replacement="\uFFFD"):
    """
    Remove or replace unprintable characters from a string.

    Parameters:
    - text (str): The input string to sanitize.
    - replacement (str): The character to use for replacement.
        Default is the Unicode replacement character.

    Returns:
    - str: Sanitized text with unprintable characters replaced.
    """
    if not isinstance(string, str):
        return string

    string.replace("\xa0", " ")  # Replace non-breaking space with regular spaces
    sanitized = "".join(char if char.isprintable() else replacement for char in string)
    return sanitized


class TwilioHandler:
    """
    Handles Twilio-specific message processing and forwarding.
    """

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
            logger.debug("Sending message %s: %s", uid, body)

            # Extract images from the message and upload them to GroupMe
            images, unsupported_type = TwilioHandler.extract_images(message)

            # Split the message into segments if it exceeds GroupMe's character limit
            if body:
                segments = GroupMeHandler.split_message(body)
                GroupMeHandler.send_text_segments(segments, uid)

            if images:
                GroupMeHandler.send_images(images)

            if unsupported_type:
                GroupMeHandler.send_to_groupme(
                    {
                        "text": (
                            "A media item was sent with an unsupported format.\n\n"
                            "Check the message in Twilio logs for details.\n"
                            "---------\n"
                            "%s\n"
                            "---------",
                            uid,
                        )
                    }
                )

        except (requests.exceptions.RequestException, KeyError) as e:
            logger.error("Failed to send message: %s", e)

    @staticmethod
    def extract_images(message):
        """
        Extract image URLs from the message response body and upload them to GroupMe's image service

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
                upload_response = GroupMeHandler.upload_image(message[media_url_key])
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", message[media_url_key])
                    unsupported_type = True
        return images, unsupported_type


class GroupMeHandler:
    """
    Handles GroupMe-specific message sending and processing.
    """

    @staticmethod
    def upload_image(image_url):
        """
        Upload an image to GroupMe's image service.

        Parameters:
        - image_url (str): The URL of the image to upload

        Returns:
        - dict: The JSON response from the GroupMe API, including the GroupMe image URL
        - None: If the upload fails

        Throws:
        - ValueError: If the image file type is unsupported
        - Exception: If the image fails to download from Twilio
        """
        mime_types = {
            "image/gif": ".gif",
            "image/jpeg": ".jpeg",
            "image/png": ".png",
        }

        # Download the image from a URL (in this case, Twilio's MediaUrl)
        image_response = requests.get(image_url, stream=True, timeout=10)
        if image_response.status_code != 200:
            raise requests.exceptions.RequestException(
                f"Failed to download image from {image_url}: \
                {image_response.status_code}"
            )

        content_type = image_response.headers.get("Content-Type", "").lower()
        file_extension = mime_types.get(content_type)

        if not file_extension:
            logger.warning(
                "Unsupported content type `%s`. Must be one of: image/gif, image/jpeg, image/png",
                content_type,
            )
            return None

        headers = {
            "X-Access-Token": GROUPME_ACCESS_TOKEN,
            "Content-Type": content_type,
        }

        # Upload the downloaded image to GroupMe
        response = requests.post(
            GROUPME_IMAGE_API, headers=headers, data=image_response.content, timeout=10
        )

        if response.status_code == 200:
            logger.debug("Upload successful: %s", response.json())
            return response.json()
        logger.warning("Upload failed: %s - %s", response.status_code, response.text)
        return None

    @staticmethod
    def split_message(body):
        """
        Split a message body string if it exceeds GroupMe's character limit.

        Parameters:
        - body (str): The message string

        Returns:
        - list: A list of message segment strings
        """
        segments = [
            body[i : i + GROUPME_CHARACTER_LIMIT]
            for i in range(0, len(body), GROUPME_CHARACTER_LIMIT)
        ]
        return segments

    @staticmethod
    def send_text_segments(segments, uid):
        """
        Send each text segment to GroupMe.
        Pre-process the text to include segment labels (if applicable) and an end marker.

        Parameters:
        - segments (list): A list of message segment strings
        - uid (str): The unique message ID (generated by message originator)

        Returns:
        - None
        """
        before_dash_split = uid.split("-", 1)[0]  # Get the first part of the UID

        total_segments = len(segments)
        for index, segment in enumerate(segments, start=1):
            segment_label = (
                f"({index}/{total_segments}):\n" if total_segments > 1 else ""
            )
            end_marker = (
                f"\n---UID---\n{before_dash_split}\n---------"
                if index == total_segments
                else ""
            )
            data = {
                "text": f'{segment_label}"{segment}"{end_marker}',
            }
            GroupMeHandler.send_to_groupme(data)
            time.sleep(0.1)  # Rate limit to prevent GroupMe API rate limiting

    @staticmethod
    def send_images(images):
        """
        Send images to GroupMe if any are present.

        Parameters:
        - images (list): A list of image URLs from GroupMe's image service

        Returns:
        - None
        """
        for image_url in images:
            # Construct body for image sending
            image_data = {
                "picture_url": image_url,
                "text": "",
            }
            GroupMeHandler.send_to_groupme(image_data)
            time.sleep(0.1)

    @staticmethod
    def send_to_groupme(body, bot_id=GROUPME_BOT_ID):
        """
        Make the actual HTTP POST request to GroupMe API and log the response.

        Parameters:
        - body (dict): The message body to send.
            Assumes it is constructed, only needs the bot ID.
        - bot_id (str): The GroupMe bot ID from the group to send the message to

        Returns:
        - None

        Throws:
        - requests.exceptions.RequestException: If the HTTP POST request fails
        """
        body["bot_id"] = bot_id

        response = requests.post(GROUPME_API, json=body, timeout=10)

        if response.status_code in {200, 202}:
            logger.debug("Message Sent: %s", body.get("text", "Image"))
        else:
            logger.error(
                "Failed to send message: %s - %s", response.status_code, response.text
            )


def callback(ch, method, _properties, body):
    """
    Callback function to process messages from the RabbitMQ queue.

    Parameters:
    - body: The message body

    Returns:
    - None

    Throws:
    - json.JSONDecodeError: If the message body is not valid JSON
    - KeyError: If the message body is missing required keys
    """
    logger.info("Callback triggered.")

    try:
        message = json.loads(body)
        logger.debug("Received message: %s", message)

        if "Body" in message:
            original_body = message["Body"]
            sanitized_body = sanitize_text(original_body)
            if original_body != sanitized_body:
                logger.warning(
                    "Sanitized unprintable characters in message body: %s -> %s",
                    original_body,
                    sanitized_body,
                )
            message["Body"] = sanitized_body

        sender_number = message.get("From")
        logger.debug("Processing message from %s", sender_number)

        # As of now, only Twilio messages are supported.
        # The follow logic will be generalized later to other originators.

        TwilioHandler.send_message_to_groupme(message)

        # Now need to acknowledge the message both to the queue and to the sender
        # Rabbit Queue
        ch.basic_ack(delivery_tag=method.delivery_tag)

        # Send acknowledgment back to wbor-twilio (the sender)
        ack_response = requests.post(
            ACK_URL,
            json={"wbor_message_id": message["wbor_message_id"]},
            timeout=3,
        )
        if ack_response.status_code == 200:
            logger.info(
                "Acknowledgment sent for message ID: %s", message["wbor_message_id"]
            )
        else:
            logger.error(
                "Acknowledgment failed for message ID: %s. Status: %s",
                message["wbor_message_id"],
                ack_response.status_code,
            )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to execute callback: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    except requests.exceptions.ReadTimeout as e:
        logger.error("Failed to send acknowledgment: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def consume_messages():
    """Consume messages from the RabbitMQ queue."""
    while True:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": "GroupMeConsumerConnection"},
        )
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue=GROUPME_QUEUE, durable=True)
            channel.basic_consume(
                queue=GROUPME_QUEUE, on_message_callback=callback, auto_ack=False
            )
            logger.info("Now ready to consume messages.")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            logger.error("Failed to connect to RabbitMQ: %s", e)
            logger.info("Retrying in 5 seconds...")
            time.sleep(5)


@app.route("/")
def hello_world():
    """Serve a simple static Hello World page at the root"""
    return "<h1>wbor-groupme is online!</h1>"


if __name__ == "__main__":
    logger.info("Starting Flask app and RabbitMQ consumer...")
    consume_messages()
    app.run(host="0.0.0.0", port=APP_PORT)

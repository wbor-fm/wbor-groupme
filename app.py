"""
GroupMe Handler.
- Consumes messages from the RabbitMQ queue to forward to a GroupMe group chat.

TO-DO:
- Log GroupMe API calls in Postgres, including origination source (Twilio, etc.)
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
import emoji
from flask import Flask, request
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


class MessageUtils:
    """
    Common utility functions for message processing.
    """

    @staticmethod
    def sanitize_string(string, replacement="\uFFFD"):
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
        sanitized = "".join(
            char if char.isprintable() or MessageUtils.is_emoji(char) else replacement
            for char in string
        )
        return sanitized

    @staticmethod
    def is_emoji(char):
        """Check if a character is an emoji."""
        # Emojis are generally in the Unicode ranges:
        # - U+1F600 to U+1F64F (emoticons)
        # - U+1F300 to U+1F5FF (symbols & pictographs)
        # - U+1F680 to U+1F6FF (transport & map symbols)
        # - U+2600 to U+26FF (miscellaneous symbols)
        # - U+2700 to U+27BF (dingbats)
        # - Additional ranges may exist
        return emoji.is_emoji(char)


class MessageSourceHandler:
    """
    Base class for message source handlers.
    """

    def process_message(self, message):
        """
        Logic to process a message from the source.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")


class TwilioHandler(MessageSourceHandler):
    """
    Handles Twilio-specific message processing and forwarding.
    """

    def process_message(self, message):
        """
        Process a text message from Twilio.
        """
        logger.debug("Processing Twilio message: %s", message)
        self.send_message_to_groupme(message)

        logger.debug(
            "Sending acknowledgment for message ID: %s", message["wbor_message_id"]
        )
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
                upload_response = GroupMe.upload_image(message[media_url_key])
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", message[media_url_key])
                    unsupported_type = True
        return images, unsupported_type


class GroupMe:
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
            GroupMe.send_to_groupme(data)
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
            GroupMe.send_to_groupme(image_data)
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


# Define message handlers for each source
# Each handler should implement the `process_message` method
# These handlers are used to process messages from the RabbitMQ queue based on the routing key
MESSAGE_HANDLERS = {"twilio": TwilioHandler()}

# These are defined automatically based on the keys in MESSAGE_HANDLERS
SOURCES = {key: f"source.{key}" for key in MESSAGE_HANDLERS}


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
        sender_number = message.get("From")
        logger.debug("Processing message from %s: %s", sender_number, message)

        if "Body" in message:
            original_body = message["Body"]
            sanitized_body = MessageUtils.sanitize_string(original_body)
            if original_body != sanitized_body:
                logger.warning(
                    "Sanitized unprintable characters in message body: %s -> %s",
                    original_body,
                    sanitized_body,
                )
            message["Body"] = sanitized_body

        handler = MESSAGE_HANDLERS[method.routing_key.split(".")[1]]
        handler.process_message(message)
        ch.basic_ack(delivery_tag=method.delivery_tag)
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

            # Assert the exchange exists
            channel.exchange_declare(
                exchange="source_exchange", exchange_type="topic", durable=True
            )

            # Declare and bind queues dynamically
            for source, routing_key in SOURCES.items():
                queue_name = f"{source}"
                channel.queue_declare(queue=queue_name, durable=True)
                logger.debug("Queue declared: %s", queue_name)
                channel.queue_bind(
                    exchange="source_exchange",
                    queue=queue_name,
                    routing_key=routing_key,
                )
                logger.debug(
                    'Queue %s bound to "source_exchange" with routing key %s',
                    queue_name,
                    routing_key,
                )
                channel.basic_consume(
                    queue=queue_name,
                    on_message_callback=callback,
                    auto_ack=False,
                    consumer_tag=f"{source}_consumer",
                )

            logger.info("Connected! Now ready to consume messages...")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            logger.error("Failed to connect to RabbitMQ: %s", e)
            logger.info("Retrying in 5 seconds...")
            time.sleep(5)


def parse_command(text):
    """
    Parse a command from a GroupMe message.

    Parameters:
    - text (str): The message text to parse

    Returns:
    - None
    """
    if text.startswith("!"):
        command = text.split(" ")[0].lower()
        if command == "!help":
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "Available commands:\n"
                        "!help - Display this help message\n"
                        "!ping - Check if the bot is online\n"
                        "!ban <UID> - Ban a phone number from sending messages\n"
                        "!stats <UID> - Display message statistics for a phone number"
                    )
                }
            )
        elif command == "!ping":
            GroupMe.send_to_groupme({"text": "Pong!"})
        elif command == "!ban":
            # TO-DO: Implement ban functionality
            GroupMe.send_to_groupme(
                {"text": "Ban functionality is not yet implemented."}
            )
        elif command == "!stats":
            # TO-DO: Implement stats functionality
            GroupMe.send_to_groupme(
                {
                    "text": "Stats functionality is not yet implemented. This will include information such as the number of messages sent by a phone number."
                }
            )


@app.route("/callback", methods=["POST"])
def groupme_callback():
    """Callback endpoint for GroupMe API."""
    body = request.json
    logger.info("GroupMe callback received: %s", body)
    text = body.get("text")
    parse_command(text)
    return "OK"


@app.route("/")
def hello_world():
    """Serve a simple static Hello World page at the root"""
    return "<h1>wbor-groupme is online!</h1>"


if __name__ == "__main__":
    consume_messages()
    app.run(host="0.0.0.0", port=APP_PORT)

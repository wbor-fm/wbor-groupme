"""
GroupMe Handler.

We have a group chat on GroupMe that includes all members of station management.
This chat is used to monitor messages from various sources, including incoming Twilio SMS messages,
our UPS backups, our Sage Digital ENDEC, and our online AzuraCast streams.

This application serves as a message handler for the GroupMe chat. Various sources submit messages
to RabbitMQ, which are then consumed by this application. The messages are then forwarded to the
GroupMe chat.

Additionally, this application can receive messages directly via an HTTP POST request to /send,
which is meant for sources that do not use RabbitMQ or is impractical to use.

The application also includes a callback endpoint for the GroupMe API, which is triggered when
messages are sent to the group chat. This allows for various commands to be parsed and executed.
Twilio commands include:
- Banning a phone number from sending messages
- Unbanning a phone number from sending messages
- Displaying message statistics for a phone number

Finally, all interactions with the GroupMe API are logged in Postgres for auditing purposes.

Message handling:
- Messages are received from RabbitMQ and processed by the appropriate handler based on the 
  routing key.
- For all messages:
    - The message body is sanitized to remove unprintable characters.
    - The message is processed by the appropriate handler.

Source keys:
- `source.twilio.sms.incoming`: TwilioHandler()
- `source.standard.*`: StandardHandler()
- `source.endec.*`: 
- `source.apcupsd.*`: 
- `source.azuracast.*`:

TODO:
- Log GroupMe API calls in Postgres, including origination source (Twilio, etc.)
- Callback actions
    - Block sender based on the message's UID
    - Implement message statistics tracking and retrieval
    - Implement message banning/unbanning
    - Remotely clear the dashboard screen?
"""

import os
import logging
import json
from datetime import datetime, timezone
import sys
import time
import uuid
import requests
import pika
import pika.exceptions
import pytz
import emoji
from colorlog import ColoredFormatter
from flask import Flask, request
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
APP_PORT = os.getenv("APP_PORT", "2000")
APP_PASSWORD = os.getenv("APP_PASSWORD")
GROUPCHAT_NAME = os.getenv("GROUPCHAT_NAME", "WBOR MGMT")

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

EXCHANGE = "source_exchange"


# Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Define a handler to output to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)


class EasternTimeFormatter(ColoredFormatter):
    """Custom log formatter to display timestamps in Eastern Time with colorized output"""

    def formatTime(self, record, datefmt=None):
        # Convert UTC to Eastern Time
        eastern = pytz.timezone("America/New_York")
        utc_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        eastern_dt = utc_dt.astimezone(eastern)
        # Use ISO 8601 format
        return eastern_dt.isoformat()


# Define the formatter with color
formatter = EasternTimeFormatter(
    "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    log_colors={
        "DEBUG": "white",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    },
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Configure werkzeug logging to match
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("werkzeug").addHandler(console_handler)

app = Flask(__name__)

if not GROUPME_BOT_ID or not GROUPME_ACCESS_TOKEN:
    logger.critical(
        "GROUPME_BOT_ID or GROUPME_ACCESS_TOKEN is missing. Exiting application."
    )
    sys.exit(1)


class MessageUtils:
    """
    Common utility functions for messages.
    """

    @staticmethod
    def sanitize_string(string, replacement="\uFFFD"):
        """
        Remove or replace unprintable characters from a string.
        Allows for newlines and tabs.

        Parameters:
        - text (str): The input string to sanitize.
        - replacement (str): The character to use for replacement.
            Default is the Unicode replacement character.

        Returns:
        - str: Sanitized text with unprintable characters replaced.
        """
        if not isinstance(string, str):
            return string

        string = string.replace(
            "\xa0", " "
        )  # Replace non-breaking space with regular spaces

        # Replace unprintable characters with the replacement character
        sanitized = []
        for char in string:
            if char.isprintable() or MessageUtils.is_emoji(char) or char in "\n\t":
                sanitized.append(char)
            else:
                sanitized.append(replacement)
        sanitized = "".join(sanitized)
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

    @staticmethod
    def gen_uuid():
        """Generate a UUID for a message."""
        return str(uuid.uuid4())


class MessageSourceHandler:
    """
    Base class for message source handlers.
    """

    def process_message(self, body):
        """
        Logic to process a message from the source.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")


class StandardHandler(MessageSourceHandler):
    """
    Catch-all message processing and forwarding, e.g. for the UPS/AzuraCast/etc. sources.

    The request body is expected to include the following fields:
    - body (str): The message text
    - wbor_message_id (str): The unique message ID
    - images (list): A list of image URLs (optional)
    """

    def process_message(self, body):
        logger.debug(
            "Standard `process_message` called for: %s",
            body.get("wbor_message_id"),
        )
        self.send_message_to_groupme(body)
        # Ack not needed

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
        groupme_images, unsupported_type = StandardHandler.extract_images(message)

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
    def extract_images(message):
        """
        Extract image URLs from the message response body and upload them to GroupMe's image
        service.

        Parameters:
        - message (dict): The standard message response body

        Returns:
        - groupme_images (list): A list of image URLs from GroupMe's image service
        - unsupported_type (bool): True if an unsupported media type was found, False otherwise
        """
        unsupported_type = False

        images = message.get("images")
        groupme_images = []
        if images:
            for image_url in images:
                upload_response = GroupMe.upload_image(image_url)
                if upload_response is not None:
                    image_url = upload_response.get("payload", {}).get("url")
                    if image_url:
                        groupme_images.append(image_url)
                else:
                    logger.warning("Failed to upload media: %s", image_url)
                    unsupported_type = True
        return groupme_images, unsupported_type


class TwilioHandler(MessageSourceHandler):
    """
    Handles Twilio-specific message processing and forwarding.
    """

    def process_message(self, body):
        """
        Process a text message from Twilio.
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
        else:
            logger.error(
                "Acknowledgment failed for: %s. Status: %s",
                body["wbor_message_id"],
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

        try:
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
                    "Unsupported content type `%s`. "
                    "Must be one of: image/gif, image/jpeg, image/png",
                    content_type,
                )
                return None

            headers = {
                "X-Access-Token": GROUPME_ACCESS_TOKEN,
                "Content-Type": content_type,
            }

            # Upload the downloaded image to GroupMe
            response = requests.post(
                GROUPME_IMAGE_API,
                headers=headers,
                data=image_response.content,
                timeout=10,
            )

            if response.status_code == 200:
                logger.debug("Upload successful: %s", response.json())
                return response.json()
            logger.warning(
                "Upload failed: %s - %s", response.status_code, response.text
            )
            return None
        except requests.exceptions.RequestException as e:
            logger.error(
                "Exception occurred while processing image %s: %s", image_url, e
            )
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
        A delay is added between each segment to prevent rate limiting.

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
            GroupMe.send_to_groupme(data, uid=uid)
            time.sleep(0.1)  # Rate limit to prevent GroupMe API rate limiting

    @staticmethod
    def send_images(images):
        """
        Send images to GroupMe if any are present.
        A delay is added between each image to prevent rate limiting.

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
    def send_to_groupme(body, uid=MessageUtils.gen_uuid(), bot_id=GROUPME_BOT_ID):
        """
        Make the actual HTTP POST request to GroupMe API. Logs the request in Postgres.

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
            if body.get("text"):
                logger.info(
                    "Message sent successfully to %s:\n\n%s\n",
                    GROUPCHAT_NAME,
                    body.get("text"),
                )
            elif body.get("picture_url"):
                logger.info("Image sent successfully: %s", body.get("picture_url"))
        else:
            logger.error(
                "Failed to send message: %s - %s", response.status_code, response.text
            )
        # TODO: Log the GroupMe API call in Postgres


# Define message handlers for each source
# Each handler should implement the `process_message` method
# These handlers are used to process messages from the RabbitMQ queue based on the routing key
# e.g. "source.twilio.*" -> TwilioHandler(), "source.standard.*" -> StandardHandler()
MESSAGE_HANDLERS = {"twilio": TwilioHandler(), "standard": StandardHandler()}

# These are defined automatically based on the keys in MESSAGE_HANDLERS
# e.g. "twilio" -> "source.twilio.#", "standard" -> "source.standard.#"
# Used for binding the relevant queues to the exchange
SOURCES = {key: f"source.{key}.#" for key in MESSAGE_HANDLERS}


def callback(ch, method, _properties, body):
    """
    Callback function to process messages from the RabbitMQ queue.

    Treatment for all messages:
    - Sanitize the message body
    - Process the message using the appropriate handler

    TODO:
    - Logic based on key - currently just checking for "sms.incoming" but other sources
      will need different keys

    Parameters:
    - body: The message body

    Returns:
    - None

    Throws:
    - json.JSONDecodeError: If the message body is not valid JSON
    - KeyError: If the message body is missing required keys
    """
    logger.debug("Callback triggered.")

    try:
        message = json.loads(body)
        logger.debug("Received message: %s", message)
        sender = message.get("From") or message.get("source")

        if not sender and (not message.get("body") or not message.get("Body")):
            logger.warning("Not for us: %s", message)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        original_body = message.get("Body") or message.get("body")
        logger.info("Processing message from `%s`: %s", sender, original_body)

        if (
            not message.get("type") == "sms.incoming"
            and not message.get("source") == "standard"
        ):
            logger.debug("message.type: %s", message.get("type"))
            logger.debug("message.source: %s", message.get("source"))
            logger.warning(
                "Wrong key for us: %s, delivery_tag: %s", message, method.delivery_tag
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        # Handle differences in message body key capitalization due to Twilio API
        if "Body" in message or "body" in message:
            original_body = message.get("Body") or message.get("body")
            sanitized_body = MessageUtils.sanitize_string(original_body)
            if original_body != sanitized_body:
                logger.info(
                    "Sanitized unprintable characters in message body: %s -> %s",
                    original_body,
                    sanitized_body,
                )
            if message.get("Body"):
                message["Body"] = sanitized_body
            else:
                message["body"] = sanitized_body

        # Check for UID
        if not message.get("wbor_message_id"):
            message["wbor_message_id"] = MessageUtils.gen_uuid()

        logger.debug("Handler query provided: `%s`", method.routing_key.split(".")[1])
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
    """
    Consume messages from the RabbitMQ queue. Sets up the connection and channel for each source.
    Binds the queue to the exchange and starts consuming messages, calling callback().

    The callback function processes the message and acknowledges it if successful.
    """
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

            # Assert that the primary exchange exists
            channel.exchange_declare(
                exchange=EXCHANGE, exchange_type="topic", durable=True
            )

            # Declare and bind queues dynamically
            for source, routing_key in SOURCES.items():
                queue_name = f"{source}"
                channel.queue_declare(queue=queue_name, durable=True)
                logger.debug("Queue declared: %s", queue_name)
                channel.queue_bind(
                    exchange=EXCHANGE,
                    queue=queue_name,
                    routing_key=routing_key,
                )
                logger.debug(
                    "Queue `%s` bound to `%s` with routing key %s",
                    queue_name,
                    EXCHANGE,
                    routing_key,
                )
                channel.basic_consume(
                    queue=queue_name,
                    on_message_callback=callback,
                    auto_ack=False,
                    consumer_tag=f"{source}_consumer",
                )

            logger.info("Connected to RabbitMQ! Ready to consume...")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            logger.error("(Retrying in 5 seconds) Failed to connect to RabbitMQ: %s", e)
            time.sleep(5)


def publish_to_queue(request_body, key):
    """
    Publish a message to the RabbitMQ queue.

    Parameters:
    - request_body (dict): The message request body to publish
        - body (str): The message text
        - wbor_message_id (str): The unique message ID
        - images (list): A list of image URLs (optional)
    - key (str): The routing key for the message
        - e.g. "source.twilio", "source.standard"
            - In this case, `twilio` is published in the wbor-twilio service

    Returns:
    - None
    """
    try:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": "GroupMePublisherConnection"},
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        logger.debug("RabbitMQ connected!")

        channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=key,
            body=json.dumps(request_body).encode(),
            properties=pika.BasicProperties(
                headers={
                    "x-retry-count": 0
                },  # Initialize retry count for other consumers
                delivery_mode=2,  # Make the message persistent
            ),
        )
        logger.info("Message published: %s", request_body)
        connection.close()
    except pika.exceptions.AMQPConnectionError as e:
        logger.error(
            'Connection error when publishing to exchange with routing key "source.%s": %s',
            key,
            e,
        )
    except pika.exceptions.AMQPChannelError as e:
        logger.error(
            'Channel error when publishing to exchange with routing key "source.%s": %s',
            key,
            e,
        )
    except json.JSONDecodeError as e:
        logger.error("JSON encoding error for message %s: %s", request_body, e)


def publish_log_pg(message, statuscode, key="source.groupme", sub_key="log"):
    """
    Log message actions in Postgres by publishing to the RabbitMQ exchange.

    Parameters:
    - message (dict): The message to publish
    - routing_key (str): The routing key for the message
    """
    try:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": "GroupMePublisherConnection"},
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        logger.debug("RabbitMQ connected!")

        channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=key,
            body=json.dumps(
                {
                    **message,
                    "code": statuscode,
                    "type": sub_key,
                }
            ).encode(),
            properties=pika.BasicProperties(
                headers={
                    "x-retry-count": 0
                },  # Initialize retry count for other consumers
                delivery_mode=2,  # Make the message persistent
            ),
        )
        logger.info("Message published: %s", message)
        connection.close()
    except pika.exceptions.AMQPConnectionError as conn_error:
        logger.error(
            'Connection error when publishing to exchange with routing key "source.%s.%s": %s',
            key,
            sub_key,
            conn_error,
        )
    except pika.exceptions.AMQPChannelError as chan_error:
        logger.error(
            'Channel error when publishing to exchange with routing key "source.%s.%s": %s',
            key,
            sub_key,
            chan_error,
        )
    except json.JSONDecodeError as json_error:
        logger.error("JSON encoding error for message %s: %s", message, json_error)


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


def parse_message(text):
    """
    Parse a GroupMe message sent by a group member.

    TODO: Put actual functionality in a separate class.

    Parameters:
    - text (str): The message text to parse

    Returns:
    - None
    """
    if text.startswith("!"):
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
                }
            )
        elif command == "!ping":
            GroupMe.send_to_groupme({"text": f"Pong! UID: {uid_arg}"})
        elif command == "!ban":
            if ban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has been "
                        "banned from sending messages."
                    }
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Ban functionality is not yet implemented. "
                            "This will block a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    }
                )
        elif command == "!unban":
            if unban(uid_arg):
                GroupMe.send_to_groupme(
                    {
                        "text": f"Phone # associated with message UID {uid_arg} has "
                        "been UNBANNED from sending messages."
                    }
                )
            else:
                GroupMe.send_to_groupme(
                    {
                        "text": (
                            "Unban functionality is not yet implemented. "
                            "This will unblock a phone # from sending messages to the station. "
                            f"UID: {uid_arg}"
                        )
                    }
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
                    }
                )
        else:
            GroupMe.send_to_groupme(
                {
                    "text": (
                        "Unknown command.\n\n"
                        "Type `!help` to see a list of available commands."
                    )
                }
            )


@app.route("/callback", methods=["POST"])
def groupme_callback():
    """
    Callback endpoint for GroupMe API upon messages being sent to the group chat.
    """
    body = request.json
    sender_type = body.get("sender_type")
    if sender_type != "bot":
        logger.info("GroupMe callback received: %s", body)
        text = body.get("text")
        parse_message(text)
    return "OK"


@app.route("/send", methods=["POST"])
def send_message():
    """
    Send a message via a bot. Meant for sources that do not use RabbitMQ or is impractical to use.

    Logs the message in Postgres with:
    - Source (e.g. Twilio)
    - UID (unique message ID)
    - Timestamp
    - Text
    - Images (if any)

    Request body includes the following fields:
    - body (str): The message text to send
    - password (str): The password to authenticate the request
    - source (str): The source of the message (e.g. "Twilio")
    - wbor_message_id (str): The unique message ID (generated by message originator) (optional)
        - If not provided (the case for non-RabbitMQ messages), a UID will be generated
    - images (list): A list of image URLs to send (optional)

    Returns:
    - str: "OK" if the message was sent successfully
    - str: "Unauthorized" if the password is incorrect
    - str: "Bad Request" if the request body is missing required fields
    - str: "Internal Server Error" if the message failed to send
    """
    body = request.json
    logger.info("Send callback received: %s", body)

    # Check for password
    if body.get("password") != APP_PASSWORD:
        logger.warning(
            "Unauthorized access attempt with password: %s", body.get("password")
        )
        return "Unauthorized"

    # Check for required fields
    required_fields = ["body", "password", "source"]
    missing_fields = [field for field in required_fields if field not in body]
    if missing_fields:
        logger.error("Bad Request: Missing required fields: %s", missing_fields)
        return "Bad Request"

    # Generate or use the provided UID
    sender_uid = body.get("wbor_message_id")
    if sender_uid is None:
        sender_uid = MessageUtils.gen_uuid()
        logger.debug("Generated new UID: %s", sender_uid)
    else:
        logger.debug("Using provided UID: %s", sender_uid)

    logger.info("Publishing message to RabbitMQ: %s", sender_uid)
    publish_to_queue(body, "source.standard")
    return "OK"


@app.route("/")
def hello_world():
    """Serve a simple static Hello World page at the root"""
    return "<h1>wbor-groupme is online!</h1>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)

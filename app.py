"""
GroupMe Handler.
- Consumes messages from the RabbitMQ queue to forward to a GroupMe group chat.
"""

import os
import logging
import json
from datetime import datetime, timezone
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
GROUPME_CHARACTER_LIMIT = abs(int(os.getenv("GROUPME_CHARACTER_LIMIT", "970")))

GROUPME_API = "https://api.groupme.com/v3/bots/post"
GROUPME_IMAGE_API = "https://image.groupme.com/pictures"

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
    logger.critical("GROUPME_BOT_ID or GROUPME_ACCESS_TOKEN is missing. Exiting application.")
    exit(1)


def upload_image(image_url):
    """
    Upload a Twilio image to GroupMe's image service.

    Parameters:
    - image_url (str): The URL of the image to upload

    Returns:
    - dict: The JSON response from the GroupMe API, including the GroupMe image URL

    Throws:
    - ValueError: If the image file type is unsupported
    - Exception: If the image fails to download from Twilio
    """
    mime_types = {
        "image/gif": ".gif",
        "image/jpeg": ".jpeg",
        "image/png": ".png",
    }

    # Download the image from Twilio
    image_response = requests.get(image_url, stream=True, timeout=10)
    if image_response.status_code != 200:
        raise requests.exceptions.RequestException(
            f"Failed to download image from Twilio: \
            {image_response.status_code}"
        )

    content_type = image_response.headers.get("Content-Type", "").lower()
    file_extension = mime_types.get(content_type)

    if not file_extension:
        logger.warning(
            "Unsupported file type `%s`. Please use a .gif, .jpeg, .jpg, or .png file.",
            file_extension,
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
        return response.json()  # Return the JSON response if needed
    logger.warning("Upload failed: %s - %s", response.status_code, response.text)
    return None  # Return None if the upload failed


def send_message(message):
    """
    Send a message to the GroupMe group chat.

    Parameters:
    - body (str): The message to send

    Throws:
    - requests.exceptions.RequestException: If the message fails to send
    """
    try:
        body = message.get("Body")
        logger.debug("Sending message: %s", body)

        # Check for Media
        images = []
        for i in range(10):
            media_url_key = f"MediaUrl{i}"
            if media_url_key in message:
                upload_response = upload_image(message[media_url_key])
                image_url = upload_response.get("payload", {}).get("url")
                if image_url is not None:
                    images.append(image_url)

        # GroupMe has a character limit. Split the message into segments if it exceeds the limit.
        segments = []
        for i in range(0, len(body), GROUPME_CHARACTER_LIMIT):
            segments.append(body[i : i + GROUPME_CHARACTER_LIMIT])

        total_segments = len(segments)

        for index, segment in enumerate(segments, start=1):
            # Add segment label and end marker if there are multiple segments
            segment_label = (
                f"({index}/{total_segments}):\n" if total_segments > 1 else ""
            )  # Max 17 chars.
            end_marker = "\n---------" if index == total_segments else ""  # 10 chars.

            data = {
                "text": f"{segment_label}{segment}{end_marker}",
                "bot_id": GROUPME_BOT_ID,
            }
            headers = {"Content-Type": "application/json"}

            # Send the message
            response = requests.post(
                GROUPME_API, data=json.dumps(data), headers=headers, timeout=10
            )
            if response.status_code == 200:
                try:
                    response_json = response.json()
                    logger.debug("Sent: %s", segment_label + segment)
                    logger.debug("Response JSON: %s", response_json)
                except json.JSONDecodeError:
                    logger.debug("Response was not JSON-formatted, but message sent successfully.")
            else:
                logger.error("Failed to send message: %s - %s", response.status_code, response.text)

        # Send images if they exist
        for image_url in images:
            image_data = {"bot_id": GROUPME_BOT_ID, "picture_url": image_url, "text": ""}
            headers = {"Content-Type": "application/json"}

            image_response = requests.post(
                GROUPME_API,
                data=json.dumps(image_data),
                headers=headers,
                timeout=10,
            )
            if image_response.status_code == 200:
                try:
                    image_response_json = image_response.json()
                    logger.debug("Image Sent: %s", image_url)
                    logger.debug("Response JSON: %s", image_response_json)
                except json.JSONDecodeError:
                    logger.debug("Response was not JSON-formatted, but message sent successfully.")
            else:
                logger.error("Failed to send message: %s - %s", image_response.status_code, image_response.text)
    except requests.exceptions.RequestException as e:
        logger.error("Failed to send message: %s", e)


def callback(_ch, _method, _properties, body):
    """Callback function to process messages from the RabbitMQ queue."""
    logger.info("Callback triggered.")

    try:
        message = json.loads(body)
        logger.debug("Received message: %s", message)

        sender_number = message.get("From")
        logger.debug("Processing message from %s", sender_number)

        send_message(message)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to execute callback: %s", e)


def consume_messages():
    """Consume messages from the RabbitMQ queue."""
    while True:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST, credentials=credentials
        )
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue=GROUPME_QUEUE, durable=True)
            channel.basic_consume(
                queue=GROUPME_QUEUE, on_message_callback=callback, auto_ack=True
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

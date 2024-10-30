"""
Postgres Handler.
- Consumes messages from the RabbitMQ queue to insert SMS data into a Postgres database.
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

GROUPME_API = "https://api.groupme.com/v3/bots/post"

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


def callback(_ch, _method, _properties, body):
    """Callback function to process messages from the RabbitMQ queue."""
    logger.info("Callback triggered.")
    try:
        message = json.loads(body)
        logger.debug("Received message: %s", message)

        sender_number = message.get("From")
        message_body = message.get("Body")
        logger.debug("Processing message from %s", sender_number)

        # Send message to GroupMe
        data = {
            'text': f"\"{message_body}\"\n---------",
            'bot_id': GROUPME_BOT_ID
        }

        headers = {'Content-Type': 'application/json'}

        requests.post(GROUPME_API, data=json.dumps(data), headers=headers, timeout=10)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to process message: %s", e)


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

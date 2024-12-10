"""
RabbitMQ utility functions.
"""

import json
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from utils.logging import configure_logging
from utils.message import MessageUtils
from config import (
    RABBITMQ_EXCHANGE,
    RABBITMQ_HOST,
    RABBITMQ_PASS,
    RABBITMQ_USER,
    GLOBAL_BLOCKLIST,
)

logger = configure_logging(__name__)


def process_message_body(body):
    """
    Load the raw message body as JSON.
    """
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON message body: %s", e)
        raise


def sanitize_message(message, alreadysent):
    """
    Strip unprintable characters from the message body.

    Preserve capitalization of the `Body` field for Twilio message logging downstream.
    """
    # Sanitize the message body only if it hasn't been sent yet
    if alreadysent:
        return

    original_body = message.get("Body") or message.get("body")
    sanitized_body = MessageUtils.sanitize_string(original_body)
    if original_body != sanitized_body:
        logger.debug("Sanitized message body: %s -> %s", original_body, sanitized_body)
    if "Body" in message:
        message["Body"] = sanitized_body
    else:
        message["body"] = sanitized_body


def parse_routing_key(routing_key):
    """
    Parse the routing key into its components and check the blocklist.

    Assumes:
    - The routing key is in the format `source.<handler>.<subkey.#>`

    Parameters:
    - routing_key (str): The routing key from RabbitMQ.

    Returns:
    - handler_key (str): The key for determining the handler (e.g., "twilio").
    - subkey (str): The subkey used for further message processing.
    - is_blocked (bool): Whether the routing key is in the blocklist.
    """
    # Example incoming routing key: "source.twilio.sms.incoming"
    parts = routing_key.split(".")
    handler_key = parts[1]  # e.g., "twilio" or "standard"
    subkey = ".".join(parts[2:])  # e.g., "sms.incoming"
    is_blocked = routing_key in GLOBAL_BLOCKLIST
    return handler_key, subkey, is_blocked


def generate_message_id(message):
    """
    If a message ID is not provided, generate a local UUID for it.
    """
    if not message.get("wbor_message_id"):
        message["wbor_message_id"] = MessageUtils.gen_uuid()


def assert_exchange(channel, exchange_name=RABBITMQ_EXCHANGE):
    """
    Assert the existence of a RabbitMQ exchange.

    Parameters:
    - channel: The channel to use
    - exchange_name: The name of the exchange to assert
    """
    channel.exchange_declare(
        exchange=exchange_name, exchange_type="topic", durable=True
    )


def send_acknowledgment(message, reply_to, correlation_id):
    """
    Send an acknowledgment message to the reply_to queue.
    """
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        channel.basic_publish(
            exchange="",  # No exchange, direct queue routing
            routing_key=reply_to,
            body=json.dumps(
                {"status": "success", "message_id": message["wbor_message_id"]}
            ).encode(),
            properties=pika.BasicProperties(correlation_id=correlation_id),
        )

        connection.close()
        logger.info(
            "Acknowledgment sent for message ID: %s", message["wbor_message_id"]
        )
    except AMQPConnectionError as e:
        logger.error("Failed to connect to RabbitMQ: %s", str(e))
    except AMQPChannelError as e:
        logger.error("Failed to open a channel: %s", str(e))


def handle_acknowledgment(message, properties):
    """
    Handle acknowledgment of a message by sending an acknowledgment message to the reply_to queue
    if the message has a reply_to and correlation_id.
    """
    reply_to = properties.reply_to
    correlation_id = properties.correlation_id
    if reply_to and correlation_id:
        logger.debug("Sending acknowledgment for: %s", message.get("wbor_message_id"))
        send_acknowledgment(message, reply_to, correlation_id)

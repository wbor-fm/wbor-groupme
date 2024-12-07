"""
Consumer module for RabbitMQ.
"""

import json
import time
import sys
import pika
import pika.exceptions
import requests
from utils.logging import configure_logging
from utils.message import MessageUtils
from config import (
    RABBITMQ_HOST,
    RABBITMQ_USER,
    RABBITMQ_PASS,
    RABBITMQ_EXCHANGE,
)
from .handlers import MESSAGE_HANDLERS, SOURCES

logger = configure_logging(__name__)


def callback(ch, method, _properties, body):
    """
    Callback function to process messages from the RabbitMQ queue.

    Treatment for all messages:
    - Sanitize the message body
    - Process the message using the appropriate handler

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

        # "From" if from Twilio, "source" otherwise
        sender = message.get("From") or message.get("source")

        # Verify required fields
        # If both the sender and the message body (body or Body) are missing,
        # the message is rejected using basic_nack with requeue=False (it won't be requeued).
        # Twilio capitalizes `Body`, while other sources use `body`
        if not sender and (not message.get("body") or not message.get("Body")):
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        original_body = message.get("Body") or message.get("body")
        logger.info("Processing message from `%s`: %s", sender, original_body)

        # Verify the message source
        # Check for the correct message type and source
        # Must be either an incoming SMS or a standard message
        # Twilio messages don't have a source key, so we check for the type key instead
        # (We only process incoming SMS messages from Twilio)
        # Add other sources as needed in the future (e.g. AzuraCast)
        if (
            not message.get("type") == "sms.incoming"
            and not message.get("source") == "standard"
        ):
            logger.debug("message.type: %s", message.get("type"))
            logger.debug("message.source: %s", message.get("source"))
            logger.warning(
                "Matching condition not met: %s, delivery_tag: %s",
                message,
                method.delivery_tag,
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        # Sanitize the message body
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

        # Generate a UUID if one is not provided
        if not message.get("wbor_message_id"):
            message["wbor_message_id"] = MessageUtils.gen_uuid()

        # Determine and invoke the appropriate handler
        logger.debug("Handler query provided: `%s`", method.routing_key.split(".")[1])
        handler = MESSAGE_HANDLERS[method.routing_key.split(".")[1]]

        # Validate success of handler.process_message
        result = handler.process_message(message)
        if result:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info("Message processed and acknowledged.")
        else:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            logger.warning("Message processing failed. Message requeued.")
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
                exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
            )

            # Declare and bind queues dynamically
            for source, routing_key in SOURCES.items():
                queue_name = f"{source}"
                channel.queue_declare(queue=queue_name, durable=True)
                logger.debug("Queue declared: %s", queue_name)
                channel.queue_bind(
                    exchange=RABBITMQ_EXCHANGE,
                    queue=queue_name,
                    routing_key=routing_key,
                )
                logger.debug(
                    "Queue `%s` bound to `%s` with routing key %s",
                    queue_name,
                    RABBITMQ_EXCHANGE,
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
        except pika.exceptions.AMQPConnectionError as conn_error:
            error_message = str(conn_error)
            logger.error(
                "(Retrying in 5 seconds) Failed to connect to RabbitMQ: %s",
                error_message,
            )
            if "CONNECTION_FORCED" in error_message and "shutdown" in error_message:
                logger.critical(
                    "Broker shut down the connection. Shutting down consumer."
                )
                sys.exit(1)  # Exit the process to avoid infinite retries
            time.sleep(5)

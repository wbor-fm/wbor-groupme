"""
Consumer module for RabbitMQ. Takes messages from the RabbitMQ queues and handles them
accordingly as defined in the message handlers within the callback function.
"""

import time
import sys
import pika
from pika.exceptions import AMQPConnectionError
from utils.logging import configure_logging
from config import (
    RABBITMQ_HOST,
    RABBITMQ_USER,
    RABBITMQ_PASS,
    RABBITMQ_EXCHANGE,
)
from .util import (
    assert_exchange,
    process_message_body,
    parse_routing_key,
    generate_message_id,
    handle_acknowledgment,
    sanitize_message,
)
from .handlers import MESSAGE_HANDLERS, SOURCES

logger = configure_logging(__name__)


def validate_message_fields(message, method, ch):
    """
    Ensure that the message has the required fields and meets conditions.

    Required fields:
    - "From" or "source"
        - "From" if from Twilio, "source" otherwise
    - "body" or "Body"
        - Twilio capitalizes `Body`, while other sources use `body`

    Don't requeue the message if it's missing any.

    Conditions:
    - The message source must be either Twilio or standard.
    - The message source must be Twilio if the sender is Twilio.
    """
    sender = message.get("From") or message.get("source")
    message_body = message.get("body") or message.get("Body")
    if not sender:
        logger.debug("Missing sender field in message: %s", message)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return False
    if not message_body:
        logger.debug("Missing message body field in message: %s", message)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return False

    logger.info(
        "Received and validated message from `%s`: %s - UID: %s",
        sender,
        message_body,
        message.get("wbor_message_id"),
    )
    return True


def process_message_handler(message, handler_key, subkey, alreadysent):
    """
    Processes an incoming message by determining the appropriate handler based on the routing key.

    Parameters:
    - message (dict): The message payload to be processed.
    - method (pika.spec.Basic.Deliver): The delivery method containing the routing key.
    - alreadysent (bool): A flag indicating whether the message has already been sent.
        - e.g. the message was sent to GroupMe by the producer's API interaction

    Returns:
    - The result of the handler's process_message().
    """
    # Determine and invoke the appropriate handle
    # NOTE that the routing key[1] is the same as the body source field
    logger.debug("Handler query provided: `%s`", handler_key)

    handler = MESSAGE_HANDLERS[handler_key]
    return handler.process_message(message, subkey, alreadysent)


def callback(ch, method, properties, body):
    """
    Actually process the messages being consumed from the queue.

    Validates, sanitizes, and routes these messages to appropriate handlers based on their routing
    keys.

    If a message has the header `alreadysent`, it is assumed to have been sent
    and at this point is only logged, so we don't sanitize it since we assume the producer has done
    so in order to send it from their end.

    Parameters:
    - body: The message body

    Returns:
    - None

    Throws:
    - json.JSONDecodeError: If the message body is not valid JSON
    - KeyError: If the message body is missing required keys
    """
    try:
        message = process_message_body(body)
        logger.debug(
            "Received message (w/ routing key `%s`), JSON: %s",
            method.routing_key,
            message,
        )

        handler_key, subkey, is_blocked = parse_routing_key(method.routing_key)
        if is_blocked:
            logger.warning(
                "Routing key `%s` is in the blocklist. Message rejected (not requeueing).",
                method.routing_key,
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        # Ensure the message has the required fields
        if not validate_message_fields(message, method, ch):
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        alreadysent = properties.headers.get("alreadysent", False)
        sanitize_message(message, alreadysent)
        generate_message_id(message)  # Append a message ID if it doesn't exist already

        # Routes the message to the correct handler based on its routing key
        if process_message_handler(message, handler_key, subkey, alreadysent):
            # Send a message acknowledgment, if applicable
            handle_acknowledgment(message, properties)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(
                "Message processed, logged, and acknowledged: %s",
                message.get("wbor_message_id"),
            )
        else:
            logger.warning(
                "Message processing failed (not requeueing): %s",
                message.get("wbor_message_id"),
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except KeyError as e:
        logger.error("KeyError during message processing (not requeueing): %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def consume_messages():
    """
    Consume messages from the RabbitMQ queues.

    Sets up the connection and channel for each source, defined in SOURCES.
    Binds the queue to the EXCHANGE and starts consuming messages via callback.

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
            assert_exchange(channel)

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

            logger.info("Connected to RabbitMQ & queues bound. Now consuming...")
            channel.start_consuming()
        except AMQPConnectionError as conn_error:
            error_message = str(conn_error)
            if "CONNECTION_FORCED" in error_message and "shutdown" in error_message:
                logger.critical(
                    "Broker shut down the connection. Shutting down consumer."
                )
                sys.exit(1)  # Exit the process to avoid infinite retries
            if "ACCESS_REFUSED" in error_message:
                logger.critical(
                    "RabbitMQ access refused. Check user permissions. Shutting down consumer."
                )
                sys.exit(1)
            logger.error(
                "(Retrying in 5 seconds) Failed to connect to RabbitMQ: %s",
                error_message,
            )
            time.sleep(5)

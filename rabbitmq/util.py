"""
RabbitMQ utility functions.
"""

import json
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from utils.logging import configure_logging
from config import RABBITMQ_EXCHANGE, RABBITMQ_HOST, RABBITMQ_PASS, RABBITMQ_USER

logger = configure_logging(__name__)


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

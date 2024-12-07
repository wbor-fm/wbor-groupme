"""
RabbitMQ Publisher module.
"""

import json
import pika
from utils.logging import configure_logging
from config import RABBITMQ_HOST, RABBITMQ_USER, RABBITMQ_PASS, RABBITMQ_EXCHANGE


logger = configure_logging(__name__)


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
        logger.debug("Connecting to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": "GroupMePublisherConnection"},
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        logger.debug("RabbitMQ connected!")

        channel.exchange_declare(
            exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
        )

        logger.debug("Attempting to publish message with routing key: %s", key)
        channel.basic_publish(
            exchange=RABBITMQ_EXCHANGE,
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

        channel.exchange_declare(
            exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
        )
        channel.basic_publish(
            exchange=RABBITMQ_EXCHANGE,
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

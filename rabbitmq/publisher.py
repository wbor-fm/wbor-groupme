"""
RabbitMQ Publisher module.
"""

import json
import pika
import pika.exceptions
from utils.logging import configure_logging
from config import RABBITMQ_HOST, RABBITMQ_USER, RABBITMQ_PASS, RABBITMQ_EXCHANGE


logger = configure_logging(__name__)


def publish_message(
    request_body,
    routing_key,
    connection_name="GroupMePublisherConnection",
    extra_properties=None,
):
    """
    Publish a message to the RabbitMQ queue.

    Parameters:
    - request_body (dict): The message request body to publish
        - Example: For queue messages, it includes 'body', 'wbor_message_id',
            'images' (if applicable)
        - Example: For logs, it includes 'message', 'code', and 'type'
    - routing_key (str): The routing key for the message
        - e.g. "source.twilio", "source.standard", "source.groupme.log"
            - In this case, `twilio` is published in the wbor-twilio service
    - connection_name (str): Name for the RabbitMQ connection
    - extra_properties (dict, optional): Additional properties for the message (e.g., headers)

    Returns:
    - None
    """
    try:
        logger.debug("Connecting to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": connection_name},
            # client_properties={"connection_name": "GroupMePublisherConnection"},
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        logger.debug("RabbitMQ connected!")

        channel.exchange_declare(
            exchange=RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
        )

        logger.debug("Attempting to publish message with routing key: %s", routing_key)
        properties = pika.BasicProperties(
            headers={"x-retry-count": 0},  # Initialize retry count for other consumers
            delivery_mode=2,  # Make the message persistent
        )

        # Add extra properties if provided
        if extra_properties:
            properties.headers.update(extra_properties)

        channel.basic_publish(
            exchange=RABBITMQ_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(request_body).encode(),
            properties=properties,
        )
        logger.info("Message published: %s", request_body)
        connection.close()
    except pika.exceptions.AMQPConnectionError as e:
        logger.error(
            'Connection error when publishing to exchange with routing key "source.%s": %s',
            routing_key,
            e,
        )
    except pika.exceptions.AMQPChannelError as e:
        logger.error(
            'Channel error when publishing to exchange with routing key "source.%s": %s',
            routing_key,
            e,
        )
    except json.JSONDecodeError as e:
        logger.error("JSON encoding error for message %s: %s", request_body, e)


def publish_log_pg(message, statuscode, uid, key="source.groupme", sub_key="log"):
    """
    Log message actions in Postgres by publishing to the RabbitMQ exchange.

    Parameters:
    - message (dict): The message to publish
    - routing_key (str): The routing key for the message
    """
    publish_message(
        request_body={
            **message,
            "code": statuscode,
            "type": sub_key,
            "uid": uid,
        },
        routing_key=key,
        connection_name="GroupMeLogPublisherConnection",
    )

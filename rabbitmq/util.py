"""
RabbitMQ utility functions.
"""

from config import RABBITMQ_EXCHANGE


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

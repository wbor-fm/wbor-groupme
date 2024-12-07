"""
Handle Gunicorn worker post-fork initialization.
"""

import threading
from rabbitmq.consumer import consume_messages


def post_fork(_server, _worker):
    """
    Function to be executed after a Gunicorn worker process is forked.
    Starts a consumer thread to handle RabbitMQ messages.
    """

    consumer_thread = threading.Thread(
        target=consume_messages, daemon=True, name="ConsumerThread"
    )
    consumer_thread.start()

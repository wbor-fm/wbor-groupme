"""
Handle Gunicorn worker post-fork initialization.
"""

import threading
import logging
from app import consume_messages


def post_fork(_server, worker):
    """
    Function to be executed after a Gunicorn worker process is forked.
    Starts a consumer thread to handle RabbitMQ messages.
    """

    logger = logging.getLogger(__name__)
    logger.info("Initializing post-fork process for worker: %s", worker.pid)

    logger.info("Starting consumer thread for message processing.")
    consumer_thread = threading.Thread(
        target=consume_messages, daemon=True, name="ConsumerThread"
    )
    consumer_thread.start()
    logger.info("Consumer thread started successfully.")

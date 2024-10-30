def post_fork(server, worker):
    from app import consume_messages
    import threading
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Starting consumer in worker process.")
    consumer_thread = threading.Thread(target=consume_messages, daemon=True)
    consumer_thread.start()
"""
GroupMe Handler.
"""

import sys
import logging
from flask import Flask
from config import APP_PORT, GROUPME_BOT_ID, GROUPME_ACCESS_TOKEN
from utils.logging import configure_logging
from routes.base import base
from routes.groupme import groupme
from routes.send import send

logging.root.handlers = []
logger = configure_logging()

app = Flask(__name__)
app.register_blueprint(base)
app.register_blueprint(groupme)
app.register_blueprint(send)

if not GROUPME_BOT_ID or not GROUPME_ACCESS_TOKEN:
    logger.critical(
        "GROUPME_BOT_ID or GROUPME_ACCESS_TOKEN is missing. Exiting application."
    )
    sys.exit(1)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)

"""
GroupMe Handler.

We have a group chat on GroupMe that includes all members of station management.
This chat is used to monitor messages from various sources, including incoming Twilio SMS messages,
our UPS backups, our Sage Digital ENDEC, and our online AzuraCast streams.

This application serves as a message handler for the GroupMe chat. Various sources submit messages
to RabbitMQ, which are then consumed by this application. The messages are then forwarded to the
GroupMe chat.

Additionally, this application can receive messages directly via an HTTP POST request to /send,
which is meant for sources that do not use RabbitMQ or is impractical to use.

The application also includes a callback endpoint for the GroupMe API, which is triggered when
messages are sent to the group chat. This allows for various commands to be parsed and executed.
Twilio commands include:
- Banning a phone number from sending messages
- Unbanning a phone number from sending messages
- Displaying message statistics for a phone number

Finally, all interactions with the GroupMe API are logged in Postgres for auditing purposes.

Message handling:
- Messages are received from RabbitMQ and processed by the appropriate handler based on the 
  routing key.
- For all messages:
    - The message body is sanitized to remove unprintable characters.
    - The message is processed by the appropriate handler.

Source keys:
- `source.twilio.sms.incoming`: TwilioHandler()
- `source.standard.*`: StandardHandler()
- `source.endec.*`: 
- `source.apcupsd.*`: 
- `source.azuracast.*`:

TODO:
- Log GroupMe API calls in Postgres, including origination source (Twilio, etc.)
- Callback actions
    - Block sender based on the message's UID
    - Implement message statistics tracking and retrieval
    - Implement message banning/unbanning
    - Remotely clear the dashboard screen?
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

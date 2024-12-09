"""
Define message handlers for each source.
"""

from handlers.twilio import TwilioHandler
from handlers.standard import StandardHandler

# Define message handlers for each source
# Each handler should implement the `process_message` method
# These handlers are used to process messages from the RabbitMQ queue based on the routing key
# e.g.: "source.twilio.*" -> TwilioHandler(), 
#       "source.standard.*" -> StandardHandler()
MESSAGE_HANDLERS = {
    "twilio": TwilioHandler(), 
    "standard": StandardHandler()
}

# These are defined automatically based on the keys in MESSAGE_HANDLERS
# e.g. "twilio" -> "source.twilio.#", "standard" -> "source.standard.#"
# Used in queue bindings in setup
SOURCES = {key: f"source.{key}.#" for key in MESSAGE_HANDLERS}

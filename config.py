"""
App configuration file. Load environment variables from .env file.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
APP_PORT = os.getenv("APP_PORT", "2000")
APP_PASSWORD = os.getenv("APP_PASSWORD")
GROUPCHAT_NAME = os.getenv("GROUPCHAT_NAME", "WBOR MGMT")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "wbor-rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "source_exchange")
ACK_URL = os.getenv("ACK_URL", "http://wbor-twilio:5000/acknowledge")

GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
GROUPME_ACCESS_TOKEN = os.getenv("GROUPME_ACCESS_TOKEN")
GROUPME_CHARACTER_LIMIT = abs(int(os.getenv("GROUPME_CHARACTER_LIMIT", "900")))

GROUPME_API = "https://api.groupme.com/v3/bots/post"
GROUPME_IMAGE_API = "https://image.groupme.com/pictures"

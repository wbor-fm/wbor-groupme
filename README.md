# wbor-groupme

We have a GroupMe group that includes all members of station management. This chat is used to monitor messages from various sources, including incoming Twilio (text-the-DJ) SMS messages, our UPS backups, our Sage Digital ENDEC, and our online AzuraCast streams.

This application serves as a message handler for the GroupMe chat. Various sources submit messages to RabbitMQ, which are then consumed by this application. The messages are then forwarded to the groupchat.

Additionally, this application can receive messages directly via an HTTP POST request to /send, which is meant for sources that can't use RabbitMQ.

The application also includes a callback endpoint for the GroupMe API, which is triggered when messages are sent to the chat.

In our particular architecture, this allows station management to:

- Ban/unban a phone number from sending messages
- Displaying message statistics for a sender

Finally, all interactions with the GroupMe API are logged in Postgres (externally) for auditing purposes. If this application is down, producers should fallback to their own API interaction with GroupMe (for immediate message sending) and then queue the logs for said interactions to be sent here to be consumed upon spinning back up. This ensures Postgres gets the whole picture, even if this app is taken offline for any reason.

## Message handling

- Messages are received from RabbitMQ and processed by the appropriate handler based on the routing key. Message body sanitization takes place unless the message was already sent (as in the aforementioned fallback scenario).

### Expects incoming keys

- `source.twilio.#`: TwilioHandler()
- `source.standard.#`: StandardHandler() - could generate locally from /send
  - `sms.incoming`: Incoming SMS messages

### Emits keys

- `source.groupme.msg`: Bot message logs (includes images attached to messages)
- `source.groupme.img`: Image service API logs
- `source.groupme.callback`: Chat callback logs
- `source.#`: Using POST /send, the source is potentially wildcard

## TODO

- Rate limiting outbound message sending as to not upset GroupMe's API
- Callback action implementation
  - Block sender based on the message's UID
  - Implement message statistics tracking and retrieval
  - Implement message banning/unbanning
  - Remotely clear the [dashboard](https://github.com/WBOR-91-1-FM/wbor-studio-dashboard) screen?
    - Publish a message to the MQ exchange

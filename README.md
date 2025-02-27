# wbor-groupme

WBOR is Bowdoin College's student-run non-commercial radio station. Like any station, we rely on various audio processing equipment and data sources that need constant monitoring. To centralize relevant alerts and notifications, we use a GroupMe chat that includes station management members. Messages are sent to this chat from multiple sources, including:

- **Twilio** – SMS messages for our "text-the-DJ" service
- **UPS backup units** – Alerts for power outages
- **Sage Digital ENDEC** – [Emergency alert system](https://en.wikipedia.org/wiki/Emergency_Alert_System?useskin=vector) notifications
- **AzuraCast public streams** – Status updates for our online radio stream

This application acts as a message handler for the GroupMe chat. The aforementioned message sources (producers) submit messages to our [RabbitMQ](https://www.rabbitmq.com/) message exchange, where they are consumed by this application and forwarded to the admin chat.

## Why centralize GroupMe API interaction?

Consolidating GroupMe API interactions into a single application provides several advantages:

- **Single point of contact** – No need to distribute our API key across multiple producers or duplicate API logic
- **External message logging** – Messages are stored in a database for tracking and auditing
- **Message statistics tracking** – Enables analysis of message frequency and patterns
- **Source-specific business logic** – Includes actions such as banning/unbanning senders or callers
- **Group chat callback actions** – Automates responses and interactions based on incoming messages

Additionally, this application supports direct message submission via an HTTP `POST` request to `/send`, used by sources that cannot publish messages via RabbitMQ.

## Failure Handling

If this application goes offline, producers should fall back to [their own direct API interaction with GroupMe](https://github.com/WBOR-91-1-FM/wbor-groupme-producer) to ensure immediate message delivery. However, logs for these interactions should still be queued for later submission to this application once it is back online. This ensures that the logging database remains comprehensive, even if temporary outages occur.

## Message Handling

- Messages are received from RabbitMQ and routed to the appropriate handler based on the routing key.
- Message body sanitization occurs unless the message was previously sent via a fallback method.

### Expected Incoming Keys

| Routing Key Pattern | Handler | Description |
|---------------------|---------|-------------|
| `source.twilio.#` | `TwilioHandler()` | Handles incoming messages from Twilio (e.g., SMS) |
| `source.standard.#` | `StandardHandler()` | Handles general messages, including those sent via `/send` |
| `source.standard.sms.incoming` | `StandardHandler()` | Processes incoming SMS messages |

### Emitted Keys

| Routing Key Pattern | Purpose |
|---------------------|---------|
| `source.groupme.msg` | Logs bot messages, including attached images |
| `source.groupme.img` | Logs image service API interactions |
| `source.groupme.callback` | Logs chat callback events |
| `source.#` | Used for messages submitted via `POST /send` |

## TODO

- Implement **rate limiting** for outbound messages to comply with GroupMe's API constraints
- Implement **callback actions**, including:
  - Blocking a sender based on message UID
  - Message statistics tracking and retrieval
  - Implementing message banning/unbanning
  - Remotely clearing the [studio dashboard](https://github.com/WBOR-91-1-FM/wbor-studio-dashboard) screen by publishing a message to the RabbitMQ exchange
- Implement `!who` command to return sender information based on previous messages or a provided UID

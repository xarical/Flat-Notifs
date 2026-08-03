# Flat Notifs

Flat Notifs is a Python-based Discord bot prototype for forwarding Flat.io notifications into Discord. It uses Discord.py for the bot interface, aiohttp for asynchronous API requests, Fernet encryption for stored tokens, and Hugging Face Hub for persistent user-state storage.

### Running locally

```bash
# Create and enter a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

Create a `.env` file with the required values:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token
DATASET_ID=your_huggingface_dataset_id
HF_API_KEY=your_huggingface_api_key
FERNET_KEY=your_fernet_key
LOGGING_LEVEL=INFO
# Optional
NAMESERVERS=8.8.8.8,1.1.1.1
```

Then start the bot:

```bash
python app.py
```

Once the bot is online, register it in Discord with:

```text
%flatnotifs getstarted <your_personal_token>
```

## Technical implementation

The project is organized around a small set of Python modules that work together to poll Flat.io, filter notifications, and relay them to Discord.

- `app.py` is the main entrypoint. It creates the Discord bot, registers commands, initializes the aiohttp session, and runs a background loop that periodically checks the Flat notifications API.
- `utils/AiohttpManager.py` wraps the asynchronous HTTP client and enforces a semaphore-based request limit so the bot does not overwhelm the Flat.io API.
- `utils/config.py` centralizes the bot settings, polling intervals, notification cache size, Flat API URLs, and user-facing help/error messages.
- `utils/datasets.py` loads and updates user state from a Hugging Face dataset. This allows settings, rules, and user metadata to survive restarts.
- `utils/helpers.py` provides logging and markdown-safe formatting helpers used when sending notification messages to Discord.
- `utils/keepalive.py` provides a lightweight keepalive mechanism for hosting environments that need the process to remain active.

The runtime flow is straightforward:

1. A user registers with a Flat.io personal token in a DM.
2. The bot validates the token and stores an encrypted version of it.
3. A periodic loop fetches the latest notifications from the Flat API.
4. Each notification is checked against the user’s include/exclude rules.
5. Matching notifications are formatted and forwarded to the user’s DM or a configured server channel.
6. Preferences such as pause state, override mode, sendhere settings, and rule lists are persisted between runs.

## Features

- Multi-user support
- Registration and unregistration via personal tokens
- Persistent user preferences and encrypted token storage
- Rule-based filtering by actor username, notification type, and score ID
- Override mode to receive all notifications
- Delivery to DMs or a specific channel in a server
- Pause and resume controls
- Error handling for invalid tokens, missing channels, and transient API failures

## Commands

- `%flatnotifs getstarted <token>` - Register your account
- `%flatnotifs addrule include/exclude category value` - Add a rule
- `%flatnotifs removerule value` - Remove a rule
- `%flatnotifs override` - Toggle override mode
- `%flatnotifs pause` - Pause or resume notifications
- `%flatnotifs sendhere mention/nomention` - Send notifications to the current channel
- `%flatnotifs unregister` - Remove your saved data
- `%flatnotifs updatetoken <token>` - Replace your personal token
- `%flatnotifs rules` - Show the current rules
- `%flatnotifs version` - Show version information
- `%flatnotifs help` - Show the help menu

## Deploying

### Self-hosted

A long-running host is the most reliable way to keep the bot online. The repository is designed to run as a standalone Python process and can be deployed to a VPS, container, or other persistent environment.

### Hugging Face Spaces

The repository also includes a basic Hugging Face Spaces configuration for convenience. Add the required environment variables in the Space settings and launch the app from the configured runtime.

## Project files

- `app.py` - Main entrypoint for the Discord bot and command handlers
- `utils/config.py` - Bot settings, polling delays, API URLs, and help/error text
- `utils/datasets.py` - Loads and updates the Hugging Face-backed dataset
- `utils/AiohttpManager.py` - Shared aiohttp session and API request handling
- `utils/helpers.py` - Logging and markdown escaping helpers
- `utils/keepalive.py` - Keepalive helper for hosted environments
- `requirements.txt` - Python dependencies
- `data.json` - Local dataset cache used by the bot

## More context

For a deeper write-up on the concept and implementation, see:

https://xarical.medium.com/making-a-notifications-forwarding-discord-bot-using-python-and-discord-py-16b4ca54702e

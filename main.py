import os
import discord
from discord import app_commands
from dotenv import load_dotenv

# logger must be imported before any module that uses "logger",
# since importing it is what configures all handlers/formatters.
from utils.logger import logger, set_discord_destinations
from commands import play, leave

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID"))
ERRORS_THREAD_ID = int(os.getenv("ERRORS_THREAD_ID"))

#* Discord client setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

#* Register commands from their own files onto the shared tree
play.setup(tree)
leave.setup(tree)

@client.event
async def on_ready():
	"""Fires when the bot successfully connects to Discord and is ready."""
	# Command syncing is no longer done automatically on every startup —
	# see scripts/sync_commands_global.py and scripts/sync_commands_local.py
	# to push command changes to Discord when actually needed.

	# Wire up Discord-mirrored logging as early as possible, so the
	# "connected and ready" line below (marked channel_notify=True)
	# actually reaches the logs channel instead of being silently dropped.
	logs_channel = client.get_channel(LOGS_CHANNEL_ID) or await client.fetch_channel(LOGS_CHANNEL_ID)
	errors_thread = client.get_channel(ERRORS_THREAD_ID) or await client.fetch_channel(ERRORS_THREAD_ID)
	set_discord_destinations(client, logs_channel, errors_thread)

	logger.info(f"🟢  I'm connected and ready to receive commands! 🟢", extra={"channel_notify": True})

# --- Entry point ---
# log_handler=None disables discord.py's own default logging setup
# (which would otherwise add a second, differently-formatted handler
# to the "discord" logger, causing every line to print twice).
client.run(TOKEN, log_handler=None)
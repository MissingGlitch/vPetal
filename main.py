import os
import discord
from discord import app_commands
from dotenv import load_dotenv

# logger must be imported before any module that uses "logger",
# since importing it is what configures all handlers/formatters.
from utils.logger import logger
from commands import play, leave

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID"))

#* Discord client setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

#* Register commands from their own files onto the shared tree
play.setup(tree)
leave.setup(tree)

# Guild used for development
TEST_GUILD = discord.Object(id=DEV_GUILD_ID)

@client.event
async def on_ready():
	"""Fires when the bot successfully connects to Discord and is ready."""
	tree.copy_global_to(guild=TEST_GUILD)
	await tree.sync(guild=TEST_GUILD)
	logger.info(f"🟢  I'm connected and ready to receive commands! 🟢")

# --- Entry point ---
# log_handler=None disables discord.py's own default logging setup
# (which would otherwise add a second, differently-formatted handler
# to the "discord" logger, causing every line to print twice).
client.run(TOKEN, log_handler=None)
"""One-off script: pushes the current command tree to Discord as GLOBAL
commands (visible in every server the bot is in, can take up to 1 hour
to propagate). Run manually with `python -m scripts.sync_commands_global`
whenever a command's signature actually changes — not on every startup.
"""
import os
import asyncio
import discord
from discord import app_commands
from dotenv import load_dotenv

from commands import play, leave

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

play.setup(tree)
leave.setup(tree)


@client.event
async def on_ready():
	synced = await tree.sync()
	print(f"Synced {len(synced)} global command(s).")
	await client.close()


client.run(TOKEN, log_handler=None)
"""One-off script: pushes the current command tree to Discord as GUILD
commands for DEV_GUILD_ID only (visible instantly in that one server,
no propagation delay). Run manually with `python -m scripts.sync_commands_local`
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
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID"))
TEST_GUILD = discord.Object(id=DEV_GUILD_ID)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

play.setup(tree)
leave.setup(tree)


@client.event
async def on_ready():
	tree.copy_global_to(guild=TEST_GUILD)
	synced = await tree.sync(guild=TEST_GUILD)
	print(f"Synced {len(synced)} guild command(s) to guild {DEV_GUILD_ID}.")
	await client.close()


client.run(TOKEN, log_handler=None)
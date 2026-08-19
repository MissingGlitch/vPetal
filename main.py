import os
import sys
import platform
import logging
import asyncio
import discord
import yt_dlp
from discord import app_commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID"))

#* FFmpeg path resolution
# Resolves the correct FFmpeg executable path depending on the runtime environment.
# When running as a compiled .exe on Windows, it looks for dependencies/ffmpeg.exe
# relative to the executable. On Linux/WSL (development), it uses the system FFmpeg.
if getattr(sys, "frozen", False):
	_base = os.path.dirname(sys.executable)
	FFMPEG_PATH = os.path.join(_base, "dependencies", "ffmpeg.exe")
elif platform.system() == "Windows":
	_base = os.path.dirname(os.path.abspath(__file__))
	FFMPEG_PATH = os.path.join(_base, "dependencies", "ffmpeg.exe")
else:
	FFMPEG_PATH = "ffmpeg"

#* Deno path resolution
# Resolves the portable Deno executable, required by yt-dlp to run YouTube's
# JS challenge solver without depending on a system-wide installation.
if getattr(sys, "frozen", False):
	DENO_PATH = os.path.join(_base, "dependencies", "deno.exe")
elif platform.system() == "Windows":
	DENO_PATH = os.path.join(_base, "dependencies", "deno.exe")
else:
	DENO_PATH = "deno"

#* yt-dlp configuration:
# Extract best audio stream without downloading js_runtimes points to
# the portable Deno binary, required to solve YouTube's JS challenge and
# avoid falling back to clients that require a PO Token.
# player_client is restricted to clients that do NOT require a PO Token,
# given several are tried in order in case one is rejected for a specific video.
YDL_OPTIONS = {
	"format": "bestaudio/best",
	"noplaylist": True,
	"quiet": True,
	"js_runtimes": {"deno": {"path": DENO_PATH}},
	"extractor_args": {"youtube": {"player_client": ["tv_downgraded", "web_embedded", "tv"]}},
}

# FFmpeg options for streaming: Reconnect if the stream URL expires mid-playback
FFMPEG_OPTIONS = {
	"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

#* Discord client setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

#* Logging configuration
# Separate logger for our own bot events (command usage, playback flow),
# kept independent from discord.py's internal "discord" logger.
logger = logging.getLogger("vPetal")
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())

# Raise verbosity only on discord.player (ffmpeg spawn/read loop) and
# discord.voice_state (handshake/state machine transitions). We deliberately
# do NOT raise "discord.gateway" to DEBUG: it's shared by both the voice
# websocket and the main shard gateway, so it dumps full JSON payloads for
# every Discord event (GUILD_CREATE, INTERACTION_CREATE, heartbeats, etc.),
# drowning out the voice-specific lines we actually care about.
logging.getLogger("discord.player").setLevel(logging.DEBUG)
logging.getLogger("discord.voice_state").setLevel(logging.DEBUG)

#* Custom filter: drop the noisy raw gateway event dumps
# (GUILD_CREATE, INTERACTION_CREATE, MESSAGE_CREATE, heartbeats, etc.)
# while still allowing through the voice-specific DEBUG lines
# (MLS/DAVE negotiation, ip discovery, ffmpeg spawn command) that
# share the same "discord.gateway" logger.
class _DropRawGatewayEvents(logging.Filter):
	def filter(self, record: logging.LogRecord) -> bool:
		return "WebSocket Event" not in record.getMessage()

gateway_logger = logging.getLogger("discord.gateway")
gateway_logger.setLevel(logging.DEBUG)
gateway_logger.addFilter(_DropRawGatewayEvents())


# Guild used for development
TEST_GUILD = discord.Object(id=DEV_GUILD_ID)

@client.event
async def on_ready():
	"""Fires when the bot successfully connects to Discord and is ready."""
	tree.copy_global_to(guild=TEST_GUILD)
	await tree.sync(guild=TEST_GUILD)
	logger.info(f"Bot ready: {client.user}")

#* /play command
@tree.command(name="play", description="Plays audio from a YouTube URL in your voice channel.")
async def play(interaction: discord.Interaction, url: str):
	"""Joins the caller's voice channel and streams audio from the given URL."""
	# Log command usage: who invoked it, and with which URL
	logger.info(f"@{interaction.user} used /play with url='{url}' in guild='{interaction.guild}'")

	# Verify the user is currently in a voice channel
	if interaction.user.voice is None:
		logger.warning(f"@{interaction.user} used /play but is not in a voice channel")
		await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
		return

	voice_channel = interaction.user.voice.channel

	# Defer the response: yt-dlp extraction may take a few seconds
	await interaction.response.defer()

	# Extract the direct audio stream URL using yt-dlp (no download)
	logger.debug(f"Extracting audio info for '{url}' via yt-dlp...")
	with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
		info = ydl.extract_info(url, download=False)
		audio_url = info["url"]
		title = info.get("title", "Unknown title")
	logger.debug(f"Extraction complete: title='{title}' audio_url='{audio_url}'")

	# Connect to the voice channel, or move there if already connected elsewhere
	if interaction.guild.voice_client is None:
		logger.debug(f"Connecting to voice channel '{voice_channel}'...")
		voice_client = await voice_channel.connect()
	else:
		voice_client = interaction.guild.voice_client
		logger.debug(f"Already connected elsewhere, moving to voice channel '{voice_channel}'...")
		await voice_client.move_to(voice_channel)
	logger.debug(f"Voice client connected: {voice_client.is_connected()}")

	# Stop any currently playing audio before starting the new track
	if voice_client.is_playing():
		logger.debug("Stopping currently playing audio before starting new track")
		voice_client.stop()

	# Build the audio source and start playback
	# Debug: capture ffmpeg's stderr to a file, since it's not captured by default,
	# and log on playback error/finish regardless of logger configuration
	ffmpeg_log = open("ffmpeg_debug.log", "wb")

	def _on_playback_error(error):
		if error:
			logger.error(f"[FFMPEG ERROR] {error}")
		else:
			logger.debug(f"Playback of '{title}' finished without errors")

	# Debug: wrap send_audio_packet to count real outgoing packets and confirm
	# they are being sent continuously without silent failures, independent of
	# discord.py's own "A packet has been dropped" debug log (only shown on OSError).
	_original_send_audio_packet = voice_client.send_audio_packet
	_packet_counter = {"count": 0}

	def _counting_send_audio_packet(data, *, encode=True):
		_packet_counter["count"] += 1
		if _packet_counter["count"] % 50 == 0:
			logger.debug(f"Sent {_packet_counter['count']} audio packets so far")
		return _original_send_audio_packet(data, encode=encode)

	voice_client.send_audio_packet = _counting_send_audio_packet

	source = discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, stderr=ffmpeg_log, **FFMPEG_OPTIONS)
	logger.debug(f"Starting playback with FFmpeg executable='{FFMPEG_PATH}'")
	voice_client.play(source, after=_on_playback_error)
	logger.info(f"Now playing '{title}' (requested by @{interaction.user})")

	# Debug: inspect the internal DAVE/MLS session state a moment after playback
	# starts, to confirm directly whether the session reached "ready" without
	# relying on discord.py's own logging (accesses a private attribute,
	# for diagnostic purposes only - remove once the DAVE hypothesis is settled).
	async def _log_dave_state():
		await asyncio.sleep(2)
		connection = getattr(voice_client, "_connection", None)
		dave_session = getattr(connection, "dave_session", None)
		if dave_session is not None:
			logger.debug(f"DAVE session state 2s after play(): {dave_session!r}")
		else:
			logger.debug("No DAVE session present on this voice connection 2s after play()")

	client.loop.create_task(_log_dave_state())

	await interaction.followup.send(f"Now playing: **{title}**")

#* /leave-voice-chat command
@tree.command(name="leave-voice-chat", description="Stops playback and disconnects the bot from the voice channel.")
async def stop(interaction: discord.Interaction):
	"""Stops audio playback and disconnects the bot from the voice channel."""
	logger.info(f"@{interaction.user} used /leave-voice-chat")
	voice_client = interaction.guild.voice_client

	# Verify the bot is actually connected before attempting to stop
	if voice_client is None:
		logger.warning(f"@{interaction.user} used /leave-voice-chat but the bot is not in a voice channel")
		await interaction.response.send_message("I am not in a voice channel.", ephemeral=True)
		return

	# Stop playback and disconnect from the voice channel
	logger.debug("Stopping playback and disconnecting from voice channel")
	voice_client.stop()
	await voice_client.disconnect()
	logger.info(f"Disconnected from voice channel (requested by @{interaction.user})")
	await interaction.response.send_message("Stopped and disconnected.")

# --- Entry point ---
client.run(TOKEN)
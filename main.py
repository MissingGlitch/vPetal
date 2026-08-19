import os
import sys
import platform
import logging
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

#* yt-dlp custom logger
# Routes yt-dlp's internal debug/warning/error messages through our own
# formatted "vPetal" logger instead of letting them print raw to stderr.
# Debug messages carry a "[debug] " prefix (per yt-dlp's own convention);
# anything without that prefix is treated as informational.
class _YtDlpLogger:
	def debug(self, msg):
		if msg.startswith("[debug] "):
			logger.debug(msg)
		else:
			logger.info(msg)

	def warning(self, msg):
		logger.warning(msg)

	def error(self, msg):
		logger.error(msg)

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
	"logger": _YtDlpLogger(),
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
# Custom formatter: prepends an emoji based on the log level, and formats
# the timestamp as DD/MM/YYYY HH:MM:SS AM/PM using the system's local time.
class _EmojiFormatter(logging.Formatter):
	EMOJIS = {
		logging.DEBUG: "📄",
		logging.INFO: "ℹ️ ",
		logging.WARNING: "⚠️ ",
		logging.ERROR: "❌",
	}

	def format(self, record: logging.LogRecord) -> str:
		emoji = self.EMOJIS.get(record.levelno, "")
		return f"{emoji} {super().format(record)}"

_formatter = _EmojiFormatter(
	fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
	datefmt="%d/%m/%Y %I:%M:%S %p",
)

_handler = logging.StreamHandler()
_handler.setFormatter(_formatter)

# Separate logger for our own bot events (command usage, playback flow),
# kept independent from discord.py's internal "discord" logger.
logger = logging.getLogger("vPetal")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)

# Apply the same formatter to discord.py's own top-level logger, so every
# log line (ours and the library's) follows the same readable format.
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.INFO)
discord_logger.addHandler(_handler)
discord_logger.propagate = False

# --- Deep debugging (commented out by default) ---
# Low-level voice protocol: state machine transitions during the voice
# handshake (e.g. "Connection state changed to ..."), heartbeat keep-alives,
# and MLS/DAVE negotiation opcodes. Uncomment only when diagnosing voice
# connection/encryption issues specifically.
# logging.getLogger("discord.voice_state").setLevel(logging.DEBUG)

# Gateway: raw WebSocket traffic for both the main shard gateway (full JSON
# payloads for every Discord event: GUILD_CREATE, INTERACTION_CREATE, etc.)
# and the voice websocket (binary MLS/DAVE frames, ip discovery, keep-alives).
# Very verbose. Uncomment only when diagnosing gateway/connection issues.
# logging.getLogger("discord.gateway").setLevel(logging.DEBUG)

# ffmpeg spawn/read loop: shows the exact command used to launch ffmpeg.
# Uncomment when diagnosing ffmpeg path/argument issues.
# logging.getLogger("discord.player").setLevel(logging.DEBUG)


# Guild used for development
TEST_GUILD = discord.Object(id=DEV_GUILD_ID)

@client.event
async def on_ready():
	"""Fires when the bot successfully connects to Discord and is ready."""
	tree.copy_global_to(guild=TEST_GUILD)
	await tree.sync(guild=TEST_GUILD)
	logger.info(f"🟢  I'm connected and ready to receive commands! 🟢")

#* /play command
@tree.command(name="play", description="Plays audio from a YouTube URL in your voice channel.")
async def play(interaction: discord.Interaction, url: str):
	"""Joins the caller's voice channel and streams audio from the given URL."""
	# Log command usage: who invoked it, and with which URL
	logger.info(f"@{interaction.user} used /play with url=\"{url}\" in guild=\"{interaction.guild}\"")

	# Verify the user is currently in a voice channel
	if interaction.user.voice is None:
		logger.warning(f"@{interaction.user} used /play but is not in a voice channel")
		await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
		return

	voice_channel = interaction.user.voice.channel

	# Defer the response: yt-dlp extraction may take a few seconds
	await interaction.response.defer()

	# Extract the direct audio stream URL using yt-dlp (no download)
	logger.debug(f"Extracting audio info for \"{url}\" via yt-dlp...")
	with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
		info = ydl.extract_info(url, download=False)
		audio_url = info["url"]
		title = info.get("title", "Unknown title")
	logger.debug(f"Extraction complete: title=\"{title}\"")

	# Connect to the voice channel, or move there if already connected elsewhere
	if interaction.guild.voice_client is None:
		logger.debug(f"Connecting to voice channel \"{voice_channel}\"")
		voice_client = await voice_channel.connect()
	else:
		voice_client = interaction.guild.voice_client
		logger.debug(f"Already connected elsewhere, moving to voice channel \"{voice_channel}\"")
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
			logger.debug(f"Playback of \"{title}\" finished without errors")

	source = discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, stderr=ffmpeg_log, **FFMPEG_OPTIONS)
	logger.debug(f"Starting playback with FFmpeg")
	voice_client.play(source, after=_on_playback_error)
	logger.info(f"🎵  Now playing \"{title}\" (requested by @{interaction.user}) 🎵")

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
	logger.info(f"⏸️   Disconnected from voice channel (requested by @{interaction.user}) ⏸️")
	await interaction.response.send_message("Stopped and disconnected.")

# --- Entry point ---
# log_handler=None disables discord.py's own default logging setup
# (which would otherwise add a second, differently-formatted handler
# to the "discord" logger, causing every line to print twice).
client.run(TOKEN, log_handler=None)
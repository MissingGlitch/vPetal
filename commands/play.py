import re
import discord
from utils.logger import logger
from utils.paths import FFMPEG_PATH
from utils.youtube import YDL_OPTIONS
import yt_dlp

# FFmpeg options for streaming: Reconnect if the stream URL expires mid-playback
FFMPEG_OPTIONS = {
	"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

def setup(tree: discord.app_commands.CommandTree):
	"""Registers the /play command on the given command tree."""

	#* /play command
	@tree.command(name="play", description="Plays audio from a YouTube URL in your voice channel.")
	async def play(interaction: discord.Interaction, url: str):
		"""Joins the caller's voice channel and streams audio from the given URL."""
		# Log command usage: who invoked it, and with which URL
		logger.info(f"🕹️   @{interaction.user} used /play with url=\"{url}\" in guild=\"{interaction.guild}\" 🕹️")

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
		# Route ffmpeg's stderr through a custom writer instead of a plain file,
		# so lines are logged live (through our own formatted logger) as ffmpeg
		# emits them, instead of being silently written to disk with no visibility.
		class _FFmpegStderrLogger:
			def __init__(self):
				self._buffer = b""

			def write(self, data):
				text = data.decode(errors="ignore").strip()
				if not text:
					return
				# Truncate long googlevideo.com URLs (query strings can be 1000+ chars)
				# so a single ffmpeg error line doesn't flood the terminal/log files.
				text = re.sub(r"(https://[^\s]{30})[^\s]+", r"\1... [truncated]", text)
				for line in text.splitlines():
					logger.error(f"[FFMPEG] {line}")

		def _on_playback_error(error):
			if error:
				logger.error(f"[FFMPEG ERROR] {error}")
			else:
				logger.debug(f"Playback of \"{title}\" finished without errors")

		source = discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, stderr=_FFmpegStderrLogger(), **FFMPEG_OPTIONS)
		logger.debug(f"Starting playback with FFmpeg")
		voice_client.play(source, after=_on_playback_error)
		logger.info(f"🎵  Now playing \"{title}\" (requested by @{interaction.user}) 🎵")

		await interaction.followup.send(f"Now playing: **{title}**")
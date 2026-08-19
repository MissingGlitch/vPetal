import os
import logging
import logging.handlers

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

#* Log file handlers (rotating)
# Two categories, kept in /logs: "all.log" captures everything (DEBUG+),
# "errors.log" captures only WARNING/ERROR. Each category rotates at 2 MB
# and keeps at most 3 files total (the active file + 2 backups); once the
# 3rd fills up, the oldest is discarded and a new one takes its place.
os.makedirs("logs", exist_ok=True)

_all_file_handler = logging.handlers.RotatingFileHandler(
	filename=os.path.join("logs", "all.log"),
	encoding="utf-8",
	maxBytes=2 * 1024 * 1024,  # 2 MiB
	backupCount=2,  # active file + 2 backups = 3 files max
)
_all_file_handler.setFormatter(_formatter)

_errors_file_handler = logging.handlers.RotatingFileHandler(
	filename=os.path.join("logs", "errors.log"),
	encoding="utf-8",
	maxBytes=2 * 1024 * 1024,  # 2 MiB
	backupCount=2,  # active file + 2 backups = 3 files max
)
_errors_file_handler.setLevel(logging.WARNING)
_errors_file_handler.setFormatter(_formatter)

#* Separate logger for our own bot events (command usage, playback flow),
# kept independent from discord.py's internal "discord" logger.
logger = logging.getLogger("vPetal")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)
logger.addHandler(_all_file_handler)
logger.addHandler(_errors_file_handler)

#* Apply the same formatter to discord.py's own top-level logger, so every
# log line (ours and the library's) follows the same readable format.
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.INFO)
discord_logger.addHandler(_handler)
discord_logger.addHandler(_all_file_handler)
discord_logger.addHandler(_errors_file_handler)
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
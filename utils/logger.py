import os
import time
import asyncio
import logging
import logging.handlers
from dotenv import load_dotenv


# Loaded here (not only in main.py) so LOGS_CHANNEL_ID/ERRORS_THREAD_ID are
# available regardless of import order, since this module is imported
# before main.py's own load_dotenv() call.
load_dotenv()


#* Logging configuration
# Custom formatter: prepends an emoji based on the log level, and formats
# the timestamp as DD/MM/YYYY HH:MM:SS AM/PM using the system's local time.
class _EmojiFormatter(logging.Formatter):
	EMOJIS = {
		logging.DEBUG: "📄",
		logging.INFO: "ℹ️",
		logging.WARNING: "⚠️",
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
# "errors.log" captures only WARNING/ERROR. Each category rotates at 1 MB
# and keeps at most 3 files total (the active file + 2 backups); once the
# 3rd fills up, the oldest is discarded and a new one takes its place.
os.makedirs("logs", exist_ok=True)

_all_file_handler = logging.handlers.RotatingFileHandler(
	filename=os.path.join("logs", "all.log"),
	encoding="utf-8",
	maxBytes=1 * 1024 * 1024,  # 1 MiB
	backupCount=2,  # active file + 2 backups = 3 files max
)
_all_file_handler.setFormatter(_formatter)

_errors_file_handler = logging.handlers.RotatingFileHandler(
	filename=os.path.join("logs", "errors.log"),
	encoding="utf-8",
	maxBytes=1 * 1024 * 1024,  # 1 MiB
	backupCount=2,  # active file + 2 backups = 3 files max
)
_errors_file_handler.setLevel(logging.WARNING)
_errors_file_handler.setFormatter(_formatter)


#* Discord channel/thread log mirroring: selected records also get sent
# live to a Discord channel (LOGS_CHANNEL_ID) and its errors thread
# (ERRORS_THREAD_ID). Populated lazily via set_discord_destinations(),
# called once from main.py's on_ready once the client/loop exist; until
# then, records routed here are silently dropped instead of raising.
_discord_client = None
_logs_channel = None
_errors_thread = None


def set_discord_destinations(client, logs_channel, errors_thread):
	"""Called once from on_ready to wire up where Discord-mirrored logs go."""
	global _discord_client, _logs_channel, _errors_thread
	_discord_client = client
	_logs_channel = logs_channel
	_errors_thread = errors_thread


# Separate, undecorated logger used only to report a failure to mirror a
# log record to Discord itself (e.g. missing permissions, deleted channel).
# Deliberately has no Discord handler attached, so a mirroring failure
# can never trigger another mirroring attempt (no feedback loop).
_discord_mirror_diag_logger = logging.getLogger("vPetal.discord_mirror")
_discord_mirror_diag_logger.setLevel(logging.ERROR)
_discord_mirror_diag_logger.addHandler(_handler)
_discord_mirror_diag_logger.addHandler(_errors_file_handler)
_discord_mirror_diag_logger.propagate = False


def _on_discord_send_done(future):
	try:
		future.result()
	except Exception as exc:
		_discord_mirror_diag_logger.error(f"Failed to mirror a log record to Discord: {exc}")


class _DiscordHandler(logging.Handler):
	"""Mirrors log records into a Discord channel or thread. emit() stays
	non-blocking: the actual send() is scheduled onto the bot's asyncio
	loop via run_coroutine_threadsafe() instead of awaited directly, since
	log calls can happen from any thread (e.g. the AudioPlayer thread
	calling logger.error() for FFmpeg failures).

	Also self-throttles: at most MAX_MESSAGES_PER_WINDOW sends within any
	WINDOW_SECONDS rolling window (tracked independently per instance, so
	the channel handler and the thread handler each have their own
	budget). Anything beyond that is dropped, not queued for later, and
	counted; the next allowed message reports how many were dropped since
	the last one that actually went through."""

	MAX_MESSAGES_PER_WINDOW = 5
	WINDOW_SECONDS = 10

	def __init__(self, get_destination, level=logging.NOTSET):
		super().__init__(level)
		self._get_destination = get_destination
		self._sent_at = []
		self._suppressed_count = 0

	def emit(self, record: logging.LogRecord) -> None:
		destination = self._get_destination()
		if _discord_client is None or destination is None:
			return

		now = time.monotonic()
		self._sent_at = [t for t in self._sent_at if now - t < self.WINDOW_SECONDS]
		if len(self._sent_at) >= self.MAX_MESSAGES_PER_WINDOW:
			self._suppressed_count += 1
			return

		try:
			text = self.format(record)
		except Exception:
			return
		if self._suppressed_count:
			text = f"[+{self._suppressed_count} more message(s) suppressed to avoid flooding this channel]\n{text}"
			self._suppressed_count = 0
		# Discord's 2000-character message limit; wrapped in a code block
		# so multi-line tracebacks/log lines stay readable.
		if len(text) > 1900:
			text = text[:1900] + "… [truncated]"
		self._sent_at.append(now)
		future = asyncio.run_coroutine_threadsafe(destination.send(f"```{text}```"), _discord_client.loop)
		future.add_done_callback(_on_discord_send_done)


class _NoiseFilter(logging.Filter):
	"""Blocks specific loggers known to be noisy and not worth mirroring to
	Discord, even at WARNING/ERROR level locally (e.g. discord.py's own
	rate-limit retries, which can fire many times in a row and would
	otherwise flood the channel/thread with duplicate, low-value lines)."""

	NOISY_LOGGERS = {"discord.http"}

	def filter(self, record: logging.LogRecord) -> bool:
		return record.name not in self.NOISY_LOGGERS


class _ChannelFilter(logging.Filter):
	"""Lets WARNING/ERROR records through unconditionally (mirroring the
	errors thread), plus any record explicitly marked with
	extra={"channel_notify": True} (startup-ready and command-usage logs)."""

	def filter(self, record: logging.LogRecord) -> bool:
		return record.levelno >= logging.WARNING or getattr(record, "channel_notify", False)


_channel_handler = _DiscordHandler(lambda: _logs_channel)
_channel_handler.setFormatter(_formatter)
_channel_handler.addFilter(_ChannelFilter())
_channel_handler.addFilter(_NoiseFilter())

_thread_handler = _DiscordHandler(lambda: _errors_thread)
_thread_handler.setLevel(logging.WARNING)
_thread_handler.setFormatter(_formatter)
_thread_handler.addFilter(_NoiseFilter())


#* Separate logger for our own bot events (command usage, playback flow),
# kept independent from discord.py's internal "discord" logger.
logger = logging.getLogger("vPetal")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)
logger.addHandler(_all_file_handler)
logger.addHandler(_errors_file_handler)
logger.addHandler(_channel_handler)
logger.addHandler(_thread_handler)


#* Apply the same formatter to discord.py's own top-level logger, so every
# log line (ours and the library's) follows the same readable format.
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.INFO)
discord_logger.addHandler(_handler)
discord_logger.addHandler(_all_file_handler)
discord_logger.addHandler(_errors_file_handler)
discord_logger.addHandler(_channel_handler)
discord_logger.addHandler(_thread_handler)
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
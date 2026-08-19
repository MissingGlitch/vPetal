import yt_dlp
from utils.logger import logger
from utils.paths import DENO_PATH

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

#* Search-only configuration:
# Used when /play receives a plain search term instead of a direct URL.
# "extract_flat" skips resolving each candidate's playable audio format
# (no JS-challenge solving needed per result), so listing 20 candidates
# stays fast. The real playable stream URL is resolved separately, only
# for the single video the user ends up selecting.
SEARCH_YDL_OPTIONS = {
	"quiet": True,
	"logger": _YtDlpLogger(),
	"extract_flat": "in_playlist",
}
import re
import discord
from utils.logger import logger
from utils.paths import FFMPEG_PATH
from utils.youtube import YDL_OPTIONS, SEARCH_YDL_OPTIONS
import yt_dlp

# FFmpeg options for streaming: Reconnect if the stream URL expires mid-playback
FFMPEG_OPTIONS = {
	"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

# Matches a direct http(s) URL. Anything else typed into /play is treated
# as a search term instead.
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

# View limits to 5 rows max: 4 rows of results + 1 row of navigation buttons.
RESULTS_PER_PAGE = 4
SEARCH_TIMEOUT = 60  # seconds before the search results view disables itself


# Route ffmpeg's stderr through a custom writer instead of a plain file,
# so lines are logged live (through our own formatted logger) as ffmpeg
# emits them, instead of being silently written to disk with no visibility.
class _FFmpegStderrLogger:
	def write(self, data):
		text = data.decode(errors="ignore").strip()
		if not text:
			return
		# Truncate long googlevideo.com URLs (query strings can be 1000+ chars)
		# so a single ffmpeg error line doesn't flood the terminal/log files.
		text = re.sub(r"(https://[^\s]{30})[^\s]+", r"\1... [truncated]", text)
		for line in text.splitlines():
			logger.error(f"[FFMPEG] {line}")


def _format_duration(seconds):
	"""Formats a duration in seconds as MM:SS, e.g. 203 -> '3:23'."""
	if not seconds:
		return "?:??"
	minutes, secs = divmod(int(seconds), 60)
	return f"{minutes}:{secs:02d}"


def _truncate(text, max_len):
	if len(text) <= max_len:
		return text
	return text[: max_len - 1].rstrip() + "…"


# Reserved character budgets, sized for worst-case content so the layout
# stays consistent across all buttons/pages instead of shifting based on
# each entry's actual (usually shorter) values:
# - "#999: " -> supports up to a 3-digit result number, in case
#   RESULTS_PER_PAGE/ytsearchN is ever increased past 99 results.
# - "999:59" -> supports videos over 16 hours long (extremely unlikely,
#   but costs nothing to reserve).
NUMBER_RESERVED = len("#999: ")
DURATION_RESERVED = len("999:59")


def _build_label(index, entry):
	"""Builds a button label: '#N: 🔴 Title | 👤 Channel | ⏳ MM:SS',
	truncated to fit inside Discord's 80-character button label limit."""
	number = f"#{index}: "
	duration = _format_duration(entry.get("duration"))
	duration_part = f" | ⏳ {duration}"

	# Fixed-width parts: number, title emoji, separators, channel emoji,
	# duration emoji + reserved worst-case width (not the actual duration
	# length, so the split between title/channel doesn't shift per entry).
	fixed_len = NUMBER_RESERVED + len("🔴 ") + len(" | 👤 ") + len(" | ⏳ ") + DURATION_RESERVED
	remaining = max(80 - fixed_len, 20)
	title_budget = max(remaining * 2 // 3, 10)
	channel_budget = max(remaining - title_budget, 10)

	title = _truncate(entry.get("title") or "Unknown title", title_budget)
	channel = _truncate(entry.get("channel") or entry.get("uploader") or "Unknown", channel_budget)

	label = f"{number}🔴 {title} | 👤 {channel}{duration_part}"
	return label if len(label) <= 80 else label[:79] + "…"


async def _play_track(interaction: discord.Interaction, voice_channel: discord.VoiceChannel, audio_url: str, title: str):
	"""Shared playback logic for both direct-URL and search-selection flows:
	connects/moves to the voice channel, stops any currently playing audio,
	and starts streaming the given track."""
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

	def _on_playback_error(error):
		if error:
			logger.error(f"[FFMPEG ERROR] {error}")
		else:
			logger.debug(f"Playback of \"{title}\" finished without errors")

	source = discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, stderr=_FFmpegStderrLogger(), **FFMPEG_OPTIONS)
	logger.debug("Starting playback with FFmpeg")
	voice_client.play(source, after=_on_playback_error)
	logger.info(f"🎵  Now playing \"{title}\" (requested by @{interaction.user}) 🎵")

	await interaction.followup.send(f"Now playing: **{title}**")


class _SearchResultsView(discord.ui.View):
	"""Paginated search results: up to RESULTS_PER_PAGE buttons (one per
	video) plus a navigation row ("<" / "Page x/y" / ">"). Restricted to
	the user who ran /play, and disables itself after SEARCH_TIMEOUT
	seconds without a selection."""

	def __init__(self, author: discord.abc.User, entries: list, voice_channel: discord.VoiceChannel):
		super().__init__(timeout=SEARCH_TIMEOUT)
		self.author = author
		self.entries = entries
		self.voice_channel = voice_channel
		self.page = 0
		self.message: discord.InteractionMessage | None = None
		self.total_pages = max(1, -(-len(entries) // RESULTS_PER_PAGE))  # ceil division
		self._render_page()

	def _render_page(self):
		"""Clears and rebuilds every button for the current page."""
		self.clear_items()
		start = self.page * RESULTS_PER_PAGE
		page_entries = self.entries[start:start + RESULTS_PER_PAGE]

		for offset, entry in enumerate(page_entries):
			index = start + offset + 1  # 1-based, keeps counting across pages
			button = discord.ui.Button(label=_build_label(index, entry), style=discord.ButtonStyle.secondary, row=offset)
			button.callback = self._make_select_callback(entry)
			self.add_item(button)

		# Navigation row (only needed if there's more than one page)
		# Order: |first| |previous| |page indicator| |next| |last| = 5 buttons,
		# exactly filling row 4 (Discord's per-row limit).
		if self.total_pages > 1:
			is_first_page = self.page == 0
			is_last_page = self.page == self.total_pages - 1

			first_button = discord.ui.Button(label="⏮", style=discord.ButtonStyle.primary, row=4, disabled=is_first_page)
			first_button.callback = self._go_first
			self.add_item(first_button)

			previous_button = discord.ui.Button(label="◀", style=discord.ButtonStyle.primary, row=4, disabled=is_first_page)
			previous_button.callback = self._go_previous
			self.add_item(previous_button)

			page_indicator = discord.ui.Button(label=f"Page {self.page + 1}/{self.total_pages}", style=discord.ButtonStyle.secondary, row=4, disabled=True)
			self.add_item(page_indicator)

			next_button = discord.ui.Button(label="▶", style=discord.ButtonStyle.primary, row=4, disabled=is_last_page)
			next_button.callback = self._go_next
			self.add_item(next_button)

			last_button = discord.ui.Button(label="⏭", style=discord.ButtonStyle.primary, row=4, disabled=is_last_page)
			last_button.callback = self._go_last
			self.add_item(last_button)

	def _make_select_callback(self, entry):
		async def _callback(interaction: discord.Interaction):
			self.stop()
			for item in self.children:
				item.disabled = True
			await interaction.response.edit_message(content=f"Selected: **{entry.get('title') or 'Unknown title'}**", view=self)

			# The search extraction is "flat" and has no playable stream URL,
			# so we resolve the real one now, only for the picked video.
			video_url = entry.get("url") or entry.get("webpage_url")
			logger.debug(f"Resolving playable stream for selected result \"{entry.get('title')}\"...")
			with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
				info = ydl.extract_info(video_url, download=False)
				audio_url = info["url"]
				title = info.get("title", "Unknown title")
			logger.debug(f"Extraction complete: title=\"{title}\"")

			await _play_track(interaction, self.voice_channel, audio_url, title)

		return _callback

	async def _go_first(self, interaction: discord.Interaction):
		self.page = 0
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_previous(self, interaction: discord.Interaction):
		self.page -= 1
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_next(self, interaction: discord.Interaction):
		self.page += 1
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_last(self, interaction: discord.Interaction):
		self.page = self.total_pages - 1
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		# Only the user who ran /play may click these buttons.
		if interaction.user.id != self.author.id:
			await interaction.response.send_message("This search isn't yours to interact with.", ephemeral=True)
			return False
		return True

	async def on_timeout(self):
		logger.debug(f"Search results view for @{self.author} expired without a selection")
		for item in self.children:
			item.disabled = True
		if self.message is not None:
			try:
				await self.message.edit(content="Search expired.", view=self)
			except discord.HTTPException:
				pass


def setup(tree: discord.app_commands.CommandTree):
	"""Registers the /play command on the given command tree."""

	#* /play command
	@tree.command(name="play", description="Plays audio from a YouTube URL, or searches YouTube if given a plain term.")
	@discord.app_commands.describe(query="A YouTube URL, or a search term to look up.")
	async def play(interaction: discord.Interaction, query: str):
		"""Joins the caller's voice channel and streams audio from the given
		URL, or shows paginated search results to pick from."""
		# Log command usage: who invoked it, and with which query
		logger.info(f"🕹️   @{interaction.user} used /play with query=\"{query}\" in guild=\"{interaction.guild}\" 🕹️")

		# Verify the user is currently in a voice channel
		if interaction.user.voice is None:
			logger.warning(f"@{interaction.user} used /play but is not in a voice channel")
			await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
			return

		voice_channel = interaction.user.voice.channel

		# Case 1: direct URL was given, play it immediately (same as before)
		if URL_PATTERN.match(query):
			# Defer the response: yt-dlp extraction may take a few seconds
			await interaction.response.defer()

			logger.debug(f"Extracting audio info for \"{query}\" via yt-dlp...")
			with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
				info = ydl.extract_info(query, download=False)
				audio_url = info["url"]
				title = info.get("title", "Unknown title")
			logger.debug(f"Extraction complete: title=\"{title}\"")

			await _play_track(interaction, voice_channel, audio_url, title)
			return

		# Case 2: plain search term, search YouTube and let the user pick
		await interaction.response.defer(ephemeral=True)

		logger.debug(f"Searching YouTube for \"{query}\" via yt-dlp...")
		with yt_dlp.YoutubeDL(SEARCH_YDL_OPTIONS) as ydl:
			results = ydl.extract_info(f"ytsearch20:{query}", download=False)
			entries = results.get("entries") or []

		if not entries:
			logger.info(f"@{interaction.user} searched \"{query}\" but no results were found")
			await interaction.followup.send("No results found.", ephemeral=True)
			return

		logger.info(f"@{interaction.user} searched \"{query}\", {len(entries)} result(s) found")
		view = _SearchResultsView(interaction.user, entries, voice_channel)
		view.message = await interaction.followup.send(
			content=f'Search results for: "{query}"', view=view, ephemeral=True
		)
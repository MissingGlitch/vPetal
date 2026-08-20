import re
import discord
import discord.components
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

# View limits to 40 total children in a LayoutView. Each result now costs
# 1 Container (thumbnail + text + button) instead of 1 button, so results
# per page must drop from 4 to 2 to keep thumbnails from overwhelming the
# message's vertical space.
RESULTS_PER_PAGE = 2
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
			# ffmpeg's own reconnect logic (googlevideo.com closing the TCP
			# connection at natural stream end, or us killing the process on
			# purpose) logs these as AV_LOG_WARNING internally, not an actual
			# failure. Only "Failed to reconnect at" is a genuine AV_LOG_ERROR
			# (reconnection attempt itself failed), so that one stays as error.
			if "Failed to reconnect at" in line:
				logger.error(f"[FFMPEG] {line}")
			elif "Will reconnect" in line or "Error in the pull function" in line or "IO error" in line:
				logger.warning(f"[FFMPEG] {line}")
			else:
				logger.error(f"[FFMPEG] {line}")


def _format_duration_long(seconds):
	"""Formats a duration in seconds as "M min S s", e.g. 94 -> '1 min 34 s'."""
	if not seconds:
		return "?"
	minutes, secs = divmod(int(seconds), 60)
	return f"{minutes} min {secs} s"


def _truncate(text, max_len):
	if len(text) <= max_len:
		return text
	return text[: max_len - 1].rstrip() + "…"


def _get_thumbnail_url(entry):
	"""Returns a thumbnail URL for a search entry, falling back to the last
	(usually highest-resolution) item in "thumbnails" if "thumbnail" itself
	is missing. Returns None if neither field is present, so the caller can
	skip the MediaGallery for that specific result instead of guessing."""
	thumbnail_url = entry.get("thumbnail")
	if thumbnail_url:
		return thumbnail_url
	thumbnails = entry.get("thumbnails") or []
	return thumbnails[-1]["url"] if thumbnails else None


def _build_result_content(index, entry):
	"""Builds the markdown text shown next to each result's thumbnail:
	a heading with the title (linked to the video), followed by the
	channel (linked to the channel) and duration. The video link only
	wraps the title itself, not the "#N:" index prefix."""
	title = entry.get("title") or "Unknown title"
	video_url = entry.get("url") or entry.get("webpage_url")
	channel = entry.get("channel") or entry.get("uploader") or "Unknown"
	channel_url = entry.get("channel_url") or entry.get("uploader_url")
	duration = _format_duration_long(entry.get("duration"))

	title_part = f"[{title}]({video_url})" if video_url else title
	channel_part = f"[{channel}]({channel_url})" if channel_url else channel

	return f"### #{index}: {title_part}\n👤 By: {channel_part} | ⏳ `{duration}`"


def _build_now_playing_embed(info, interaction: discord.Interaction):
	"""Builds the "Now playing" embed shown after a track starts, following
	ejemplo-de-referencia.json: a classic v1 Embed (not Components V2), with
	the title linked to the video, the channel linked to its own page, and
	the duration. Field names are a single space instead of the real label,
	since a non-empty field name gets rendered in bold automatically and we
	don't want that."""
	title = info.get("title") or "Unknown title"
	video_url = info.get("webpage_url") or info.get("url")
	channel = info.get("channel") or info.get("uploader") or "Unknown"
	channel_url = info.get("channel_url") or info.get("uploader_url")
	duration = _format_duration_long(info.get("duration"))
	image_url = _get_thumbnail_url(info)

	title_part = f"[{title}]({video_url})" if video_url else title
	channel_part = f"[{channel}]({channel_url})" if channel_url else channel

	embed = discord.Embed(description=f"**{title_part}**")
	embed.title = "🎵 Now playing:"
	embed.add_field(name=" ", value=f"👤 By: {channel_part}", inline=True)
	embed.add_field(name=" ", value=f"⏳`{duration}`", inline=True)
	embed.set_thumbnail(url="https://i.imgur.com/XCf9DRl.gif")
	if image_url:
		embed.set_image(url=image_url)
	embed.set_footer(text=f"Song requested by @{interaction.user}", icon_url=interaction.user.display_avatar.url)
	return embed


# Tracks the currently active playback "generation" per guild: incremented
# each time _play_track starts a new track, so a stale after() callback
# from a track that was stopped early (because a newer one took over)
# can tell it's no longer the active track and must not loop itself.
_playback_generation = {}


async def _play_track(interaction: discord.Interaction, voice_channel: discord.VoiceChannel, info: dict):
	"""Shared playback logic for both direct-URL and search-selection flows:
	connects/moves to the voice channel, stops any currently playing audio,
	and starts streaming the given track on an indefinite loop (the same
	track keeps restarting on its own until a new /play call replaces it)."""
	audio_url = info["url"]
	title = info.get("title", "Unknown title")

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

	# Bump this guild's playback generation so a late after() callback from
	# whatever was playing before (if anything) knows it's now stale.
	guild_id = interaction.guild.id
	generation = _playback_generation.get(guild_id, 0) + 1
	_playback_generation[guild_id] = generation

	def _play_source():
		source = discord.FFmpegPCMAudio(audio_url, executable=FFMPEG_PATH, stderr=_FFmpegStderrLogger(), **FFMPEG_OPTIONS)
		voice_client.play(source, after=_on_playback_finished)

	def _on_playback_finished(error):
		if error:
			logger.error(f"[FFMPEG ERROR] {error}")
			return
		# A newer /play call already replaced this track: don't loop a
		# stale one back into a voice client that's now playing something else.
		if _playback_generation.get(guild_id) != generation:
			logger.debug(f"Playback of \"{title}\" was superseded by a newer track, not looping")
			return
		if not voice_client.is_connected():
			logger.debug(f"Voice client disconnected, not looping \"{title}\"")
			return
		logger.debug(f"Looping \"{title}\" again")
		_play_source()

	logger.debug("Starting playback with FFmpeg")
	_play_source()
	logger.info(f"🎵  Now playing \"{title}\" on loop (requested by @{interaction.user}) 🎵")

	await interaction.followup.send(embed=_build_now_playing_embed(info, interaction))


class _SearchResultsView(discord.ui.LayoutView):
	"""Paginated search results using Components V2: up to RESULTS_PER_PAGE
	result blocks (thumbnail + text + "Play this video" button) plus a
	navigation row ("<" / "Page x/y" / ">"). Restricted to the user who ran
	/play, and disables itself after SEARCH_TIMEOUT seconds without a
	selection."""

	def __init__(self, author: discord.abc.User, entries: list, voice_channel: discord.VoiceChannel, query: str):
		super().__init__(timeout=SEARCH_TIMEOUT)
		self.author = author
		self.entries = entries
		self.voice_channel = voice_channel
		self.query = query
		self.page = 0
		self.message: discord.InteractionMessage | None = None
		self.total_pages = max(1, -(-len(entries) // RESULTS_PER_PAGE))  # ceil division
		self._render_page()

	def _render_page(self):
		"""Clears and rebuilds every component for the current page."""
		self.clear_items()
		start = self.page * RESULTS_PER_PAGE
		page_entries = self.entries[start:start + RESULTS_PER_PAGE]

		self.add_item(discord.ui.TextDisplay(f'# 🔍 Search results for: "**__`{self.query}`__**"'))

		for offset, entry in enumerate(page_entries):
			index = start + offset + 1  # 1-based, keeps counting across pages
			if offset > 0:
				self.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

			button = discord.ui.Button(style=discord.ButtonStyle.success, label="Play this video", emoji="▶️")
			button.callback = self._make_select_callback(entry)

			section = discord.ui.Section(_build_result_content(index, entry), accessory=button)

			thumbnail_url = _get_thumbnail_url(entry)
			if thumbnail_url:
				gallery = discord.ui.MediaGallery(discord.components.MediaGalleryItem(media=thumbnail_url))
				self.add_item(discord.ui.Container(gallery, section))
			else:
				# No thumbnail available for this entry: skip the MediaGallery
				# instead of guessing a placeholder URL.
				self.add_item(discord.ui.Container(section))

		# Navigation row (only needed if there's more than one page)
		# Order: |first| |previous| |page indicator| |next| |last| = 5 buttons,
		# exactly filling ActionRow's per-row limit.
		if self.total_pages > 1:
			self.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

			is_first_page = self.page == 0
			is_last_page = self.page == self.total_pages - 1
			nav_row = discord.ui.ActionRow()

			first_button = discord.ui.Button(label="⏮", style=discord.ButtonStyle.primary, disabled=is_first_page)
			first_button.callback = self._go_first
			nav_row.add_item(first_button)

			previous_button = discord.ui.Button(label="◀", style=discord.ButtonStyle.primary, disabled=is_first_page)
			previous_button.callback = self._go_previous
			nav_row.add_item(previous_button)

			page_indicator = discord.ui.Button(label=f"Page {self.page + 1}/{self.total_pages}", style=discord.ButtonStyle.secondary, disabled=True)
			nav_row.add_item(page_indicator)

			next_button = discord.ui.Button(label="▶", style=discord.ButtonStyle.primary, disabled=is_last_page)
			next_button.callback = self._go_next
			nav_row.add_item(next_button)

			last_button = discord.ui.Button(label="⏭", style=discord.ButtonStyle.primary, disabled=is_last_page)
			last_button.callback = self._go_last
			nav_row.add_item(last_button)

			self.add_item(nav_row)

	def _disable_all_buttons(self):
		"""Recursively disables every Button in the view, including those
		nested inside Sections/ActionRows (unlike the flat button list the
		old discord.ui.View had via self.children)."""
		for item in self.walk_children():
			if isinstance(item, discord.ui.Button):
				item.disabled = True

	def _make_select_callback(self, entry):
		async def _callback(interaction: discord.Interaction):
			logger.info(f"@{interaction.user} clicked \"Play this video\" on \"{entry.get('title') or 'Unknown title'}\" (search: \"{self.query}\")")
			self.stop()
			self._disable_all_buttons()
			# Edited directly on the message object (not via interaction.response),
			# so the interaction's own initial response stays free to be the
			# native "thinking" placeholder below instead of being consumed here.
			await self.message.edit(view=self)

			# Native ephemeral "thinking" placeholder for this specific click,
			# only visible to the user who clicked, while the real stream URL
			# is resolved. This IS the interaction's original response now, so
			# delete_original_response() below correctly targets it (and not
			# the results picker, which was edited separately above).
			await interaction.response.defer(thinking=True, ephemeral=True)

			# The search extraction is "flat" and has no playable stream URL,
			# so we resolve the real one now, only for the picked video.
			video_url = entry.get("url") or entry.get("webpage_url")
			logger.debug(f"Resolving playable stream for selected result \"{entry.get('title')}\"...")
			with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
				info = ydl.extract_info(video_url, download=False)
			logger.debug(f"Extraction complete: title=\"{info.get('title', 'Unknown title')}\"")
			title = info.get("title", "Unknown title")

			# Turn the ephemeral "thinking" placeholder into a confirmation
			# message instead of deleting it, so the user who clicked still
			# has visual confirmation the extraction succeeded, right before
			# the public "Now playing" embed is sent. If the user already
			# dismissed it themselves, Discord returns a 404/NotFound: safe to ignore.
			title_link = f"{title}"
			try:
				await interaction.edit_original_response(content=f"🎵 Audio obtained successfully. Playing: **{title_link}**")
			except discord.HTTPException:
				logger.debug(f"Ephemeral \"thinking\" placeholder for @{interaction.user} was already gone before editing")

			await _play_track(interaction, self.voice_channel, info)

		return _callback

	async def _go_first(self, interaction: discord.Interaction):
		logger.debug(f"@{interaction.user} clicked \"⏮ first page\" on search \"{self.query}\"")
		self.page = 0
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_previous(self, interaction: discord.Interaction):
		logger.debug(f"@{interaction.user} clicked \"◀ previous page\" on search \"{self.query}\"")
		self.page -= 1
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_next(self, interaction: discord.Interaction):
		logger.debug(f"@{interaction.user} clicked \"▶ next page\" on search \"{self.query}\"")
		self.page += 1
		self._render_page()
		await interaction.response.edit_message(view=self)

	async def _go_last(self, interaction: discord.Interaction):
		logger.debug(f"@{interaction.user} clicked \"⏭ last page\" on search \"{self.query}\"")
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
		self.clear_items()
		self.add_item(discord.ui.TextDisplay(f"ℹ️ Search skipped. {SEARCH_TIMEOUT} seconds passed without any option being selected."))
		if self.message is not None:
			try:
				await self.message.edit(view=self)
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
			logger.debug(f"Extraction complete: title=\"{info.get('title', 'Unknown title')}\"")

			await _play_track(interaction, voice_channel, info)
			return

		# Case 2: plain search term, search YouTube and let the user pick
		await interaction.response.defer(ephemeral=True)

		logger.debug(f"Searching YouTube for \"{query}\" via yt-dlp...")
		with yt_dlp.YoutubeDL(SEARCH_YDL_OPTIONS) as ydl:
			results = ydl.extract_info(f"ytsearch20:{query}", download=False)
			entries = results.get("entries") or []

		if not entries:
			logger.info(f"@{interaction.user} searched \"{query}\" but no results were found")
			await interaction.followup.send(f'No results found for the search: "**__`{query}`__**"', ephemeral=True)
			return

		logger.info(f"@{interaction.user} searched \"{query}\", {len(entries)} result(s) found")
		view = _SearchResultsView(interaction.user, entries, voice_channel, query)
		view.message = await interaction.followup.send(view=view, ephemeral=True)
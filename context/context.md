# vPetal — Project Context

- **Last Updated:** Thursday, 20/08/2026
- **Status:** In active development (Now Playing Redesign Phase — Components V2 search/results/now-playing UI complete; in-Discord error reporting deferred to next session)

---

## Description

A Discord music bot featuring slash commands (`/play` and `/leave-voice-chat`). `/play` now accepts either a direct YouTube URL (plays immediately) or a plain search term (shows a paginated, button-based, ephemeral results picker). The final goal is to distribute it as a standalone Windows `.exe` file that any user can run without needing prior installations.

---

## Development Environment

| Element | Detail |
|---|---|
| Operating System | Windows 11 (64-bit) |
| Terminal / Shell | PowerShell (both tested, behave identically for this project) |
| Language | Python 3.14 (64-bit) |
| Virtual Environment | `.venv/` in the project root |
| Code Editor | Visual Studio Code |

### Command & Terminal Notes

Always activate the virtual environment in the terminal using:
```bash
source .venv/Scripts/activate
```

To run the bot (with the venv activated):
```bash
python main.py
```

---

## Dependencies

### `requirements.txt`
```plaintext
discord.py[voice]
yt-dlp
yt-dlp-ejs
python-dotenv
```

### System Dependencies (Portable Binaries)

All portable executables live together in a single `dependencies/` directory:

* **FFmpeg (Windows Portable Build):** `dependencies/ffmpeg.exe`. Windows "Release Essentials" build.
* **Deno (Portable Build):** `dependencies/deno.exe`. Added as the JS runtime yt-dlp uses to solve YouTube's signature/n-challenge, avoiding clients that require a PO Token.

---

## Environment Variables (`.env`)

BOT_TOKEN     = <discord_bot_token>
DEV_GUILD_ID  = <test_server_id>

The `.env` file is excluded from Git tracking via `.gitignore`.

---

## Directory Structure
```plaintext
vPetal/
├── .venv/					← Python virtual environment			(Git-ignored)
├── dependencies/
│   ├── ffmpeg.exe			← Portable FFmpeg binary for Windows	(Git-ignored)
│   └── deno.exe			← Portable Deno binary for Windows		(Git-ignored)
├── commands/
│   ├── __init__.py			← Empty; marks the folder as an importable package
│   ├── play.py				← /play command
│   └── leave.py			← /leave-voice-chat command
├── utils/
│   ├── __init__.py			← Empty; marks the folder as an importable package
│   ├── paths.py			← FFMPEG_PATH / DENO_PATH resolution
│   ├── logger.py			← "vPetal" custom logger
│   └── youtube.py			← YDL_OPTIONS / SEARCH_YDL_OPTIONS
├── logs/
│   ├── all.log(.1)(.2)		← All log levels, rotated 		(max 3 files, 1 MB each)	(Git-ignored)
│   └── errors.log(.1)(.2)	← WARNING/ERROR only, rotated 	(max 3 files, 1 MB each)	(Git-ignored)
├── main.py					← Bot entry point
├── ffmpeg_debug.log		← Temporary debug file				(Git-ignored, diagnostic only)
├── .env					← Secret environment variables		(Git-ignored)
├── .gitignore
├── context/
│   ├── context.md						← This context documentation file
│   └── youtube-problem-explained.md	← A detailed explanation of the problem with YouTube
├── README.md							← Repository README
└── requirements.txt					← Core dependencies file
```
---

## Architecture Decisions

### 1. Windows `.exe` Distribution via PyInstaller

The bot will be compiled into a Windows `.exe` using **PyInstaller**. Compilation must take place on Windows 11 to generate 64-bit Windows executables.

### 2. Bundled Portable Binaries (FFmpeg + Deno)

Neither FFmpeg nor Deno will be installed globally on user machines. Both portable binaries reside inside the `dependencies/` directory next to the project files (and future `.exe`). `utils/paths.py` resolves both paths dynamically depending on whether the bot runs as a frozen `.exe` (`sys.frozen`) or as a dev script — **note:** since the file lives in `utils/`, path resolution must go up one extra directory level (`os.path.dirname` twice) to reach the project root; this was a bug introduced today by the refactor and has been fixed (see "What Was Done Today").

### 3. Guild-Scoped Slash Commands for Testing

Global slash commands can take up to an hour to propagate across Discord. During development, commands are synced exclusively to the test server specified in `DEV_GUILD_ID` for immediate updates, via `tree.copy_global_to(guild=TEST_GUILD)` + `tree.sync(guild=TEST_GUILD)` inside `on_ready`.

### 4. YouTube Extraction Strategy: JS Runtime over PO Token

`yt-dlp`'s default client selection (when no JS runtime is present) falls back to clients like `android_vr`, which require a **PO Token**: an anti-bot mechanism dependent on unofficial third-party plugins with unpredictable, increasingly aggressive enforcement from Google.

**Decision:** prioritize YouTube clients that rely solely on a JS runtime (officially maintained by the `yt-dlp` team via the `yt-dlp/ejs` project), avoiding any client whose policy declares a required PO Token. Current `YDL_OPTIONS` (in `utils/youtube.py`):

```python
YDL_OPTIONS = {
	"format": "bestaudio/best",
	"noplaylist": True,
	"quiet": True,
	"logger": _YtDlpLogger(),
	"js_runtimes": {"deno": {"path": DENO_PATH}},
	"extractor_args": {"youtube": {"player_client": ["tv_downgraded", "web_embedded", "tv"]}},
}
```

This combination was manually validated via CLI and confirmed to resolve `n=`/`sig=` parameters without PO Token warnings, producing a client of `c=TVHTML5`. **Confirmed working end-to-end in Discord voice.**

### 5. FFmpeg stderr Debug Capture — now integrated into the logging system (no longer purely temporary)

`/play` still passes a custom `stderr=` writer object to `FFmpegPCMAudio`, but it now writes formatted `ERROR`-level log lines (via the `vPetal` logger, through `_FFmpegErrorLogger.write()`) instead of a raw debug file, and truncates long stream URLs (e.g. `googlevideo.com` links) with a regex before logging, so ffmpeg failures (e.g. `HTTP error 403 Forbidden`) now appear live in the console **and** in `logs/errors.log`, formatted like every other log line. This works because passing an object without a real `.fileno()` forces discord.py's `piping_stderr` path, which reads ffmpeg's stderr through an internal pipe/thread instead of handing it directly to the OS as a raw file descriptor. The old plain-file (`ffmpeg_debug.log`) approach is still present as a leftover and should be removed once the new approach is fully validated.

### 6. Custom Logging Layer (`utils/logger.py`)

* **Format:** every log line now shows an emoji (ℹ️ INFO, 📄 DEBUG, ⚠️ WARNING, ❌ ERROR) followed by `DD/MM/YYYY HH:MM:SS AM/PM [LEVEL] logger_name: message`, via a custom `logging.Formatter` subclass.
* **Duplicate line fix:** `client.run(TOKEN, log_handler=None)` disables discord.py's own default `setup_logging()` (which otherwise adds a second, differently-formatted handler to the `discord` logger).
* **File output:** two `logging.handlers.RotatingFileHandler` instances write to `logs/all.log` (every level) and `logs/errors.log` (WARNING/ERROR only), each capped at 1 MB and rotated up to 3 files total (current file + 2 backups; oldest is discarded once the 3rd fills up), attached to both the `vPetal` and `discord` loggers.
* **yt-dlp bridge:** a `_YtDlpLogger` class (passed as `YDL_OPTIONS["logger"]`) routes yt-dlp's internal `debug`/`warning`/`error` calls through the same `vPetal` logger/formatter, confirmed end-to-end with the DRM warning case (verified against yt-dlp's own `report_warning`/`to_screen` source by a cross-investigation with yt-dlp's AI).
* **Low-level diagnostics commented out by default:** `discord.voice_state` (low-level voice protocol) and `discord.gateway` (raw WebSocket/gateway traffic) are left at their default level, with commented-out lines in `utils/logger.py` (each explaining what it shows) that can be uncommented for deep debugging. `discord.player` is also available the same way (shows the exact ffmpeg spawn command).

### 7. FFmpeg Reconnect Warnings During Loop/Disconnect — Expected, Benign Noise

When a track finishes naturally (each loop iteration) or when `/leave-voice-chat`
force-kills the active FFmpeg process, stderr commonly shows a repeating pattern:
```log
[tls @ ADDR] Error in the pull function.
[tls @ ADDR] IO error: Error number -10054 occurred
[https @ ADDR] Will reconnect at BYTE_OFFSET in 0 second(s), error=Error number -10054 occurred.
```

**This is expected and benign, confirmed via a cross-investigation with an AI specialized
in FFmpeg (reviewing `libavformat/http.c`'s `http_buf_read()` reconnect logic):**
- `googlevideo.com` (the CDN serving the audio stream) closes the underlying TCP
  connection abruptly (`WSAECONNRESET` / error `-10054`) instead of a clean
  HTTP/TLS close, both when the stream reaches its natural end and when we
  force-kill the FFmpeg process ourselves on `/leave-voice-chat`.
- FFmpeg's own `-reconnect`/`-reconnect_streamed` logic treats this as a
  `AV_LOG_WARNING` ("Will reconnect..."), not a real failure — the process
  still exits with `return code 0` right after, and no audio is lost.
- The only line that would indicate a genuine reconnection failure is
  `"Failed to reconnect at ..."` (a true `AV_LOG_ERROR`). This has never
  appeared in this project's logs so far.
- `_FFmpegStderrLogger.write()` (in `commands/play.py`) already accounts for
  this: it downgrades lines containing `"Will reconnect"`, `"Error in the
  pull function"`, or `"IO error"` to `WARNING`, while keeping `"Failed to
  reconnect at"` (and anything else) as `ERROR`.

**Takeaway for anyone reading the logs:** seeing these `WARNING`-level FFmpeg
lines on every loop iteration and occasionally on `/leave-voice-chat` is
normal, expected behavior of streaming from `googlevideo.com` combined with
our per-loop process restarts — it is not a bug to chase.

### 8. Components V2 Redesign for Search Results, and Embed-Based "Now Playing" Response

`/play`'s search-results picker was redesigned from a plain `discord.ui.View` with
text-only buttons into a `discord.ui.LayoutView` using Components V2
(`Container`, `Section`, `MediaGallery`, `TextDisplay`, `Separator`, `ActionRow`),
matching a reference design (`ejemplo-de-referencia.json`). Each result now shows
its thumbnail, a markdown-linked title (`[Title](video_url)`) and channel
(`[Channel](channel_url)`), and a `▶️ Play this video` accessory button, at
`RESULTS_PER_PAGE = 2` results per page (dropped from an earlier 3, then 4, to
keep thumbnails from overwhelming the message given the 40-children-per-view limit).

The final "Now playing" response (for both direct URLs and search selections) was
redesigned as a classic `discord.Embed` (not Components V2, since the embed needs
to be non-ephemeral and simple/informational, with no interactive accessory),
matching a second reference design: linked title, linked channel field, duration
field (`X min Y s` format, via `_format_duration_long`), the real video thumbnail
as the large image, a fixed decorative gif (`https://i.imgur.com/XCf9DRl.gif`) as
the small thumbnail, and a footer showing the *requesting user's* avatar
(`interaction.user.display_avatar.url`, not the bot's).

**Loading feedback while resolving a search selection:** clicking "Play this
video" now re-triggers Discord's native "App is thinking..." indicator
(`interaction.response.defer(thinking=True, ephemeral=True)`) instead of a
hand-written placeholder message, while `yt_dlp.extract_info()` resolves the
selected result's playable stream. Once resolved, that same ephemeral message is
edited in place (`interaction.edit_original_response(content=...)`, not deleted)
into a confirmation line ("🎵 Audio obtained successfully. Playing: **[Title](link)**"),
immediately before the public, non-ephemeral "Now playing" embed is sent. Wrapped in
`try/except discord.HTTPException` in case the user already dismissed that ephemeral
message beforehand — confirmed via testing that dismissing an ephemeral message
client-side does **not** delete it server-side, so this exception path is a
safeguard mainly for the interaction token's ~15-minute expiry window, not for the
manual-dismiss case.

---

## What Was Done Today (20/08/2026)

### Search Results UI — Components V2 Redesign
* [x] Rebuilt `_SearchResultsView` on `discord.ui.LayoutView` with Components V2 (`Container`, `Section`, `MediaGallery`, `TextDisplay`, `Separator`, `ActionRow`), replacing the old plain-button layout, matching a provided reference JSON design.
* [x] Fixed an `AttributeError: MediaGalleryItem` crash: `discord.ui.MediaGalleryItem` does not exist (`discord/ui/media_gallery.py`'s `__all__` only re-exports `MediaGallery`); the real class lives at `discord.components.MediaGalleryItem`. Added `import discord.components` and switched to the fully-qualified path.
* [x] Dropped `RESULTS_PER_PAGE` from 4 → 3 → 2 to account for each result now costing a full thumbnail `Container`/`Section` instead of a single button, within the 40-children-per-view limit.
* [x] Made the search query itself bold/underlined/monospaced (`**__\`query\`__**`) in both the results header and the "No results found" message.
* [x] Made both the video title and channel name clickable markdown links (`[Title](video_url)`, `[Channel](channel_url)`), with the link scoped only to the title text itself, not the `#N:` index prefix.
* [x] Switched result durations to the long format (`X min Y s`, via the already-existing `_format_duration_long`) instead of `M:SS`.
* [x] Improved the timeout message ("Search expired.") to explicitly state how many seconds elapsed (using `SEARCH_TIMEOUT` directly, so it stays in sync if that constant changes).
* [x] Added logging for every button interaction on the results view (pagination: first/previous/next/last, and result selection), including who clicked and which button.

### "Now Playing" Response Redesign
* [x] Replaced the plain-text "Now playing: **Title**" follow-up with a `discord.Embed`, matching a second provided reference JSON design: linked title/channel, duration field, real video thumbnail as the large image, a fixed decorative gif as the small thumbnail, and a footer with the requesting user's own avatar (fixed from initially using the bot's avatar).

### Loading Feedback for Search Selections
* [x] Investigated and discussed multiple alternatives for giving visual feedback between clicking "Play this video" and the final embed appearing (given extraction takes several seconds), weighing ephemeral-vs-public and single-vs-multiple-message tradeoffs.
* [x] Implemented Discord's native ephemeral "App is thinking..." indicator on click (`defer(thinking=True, ephemeral=True)`), confirming this only works correctly when the picker's own button-disable edit is done directly via `self.message.edit(...)` rather than consuming the interaction's initial response with `interaction.response.edit_message(...)` (which would otherwise make `delete_original_response()`/`edit_original_response()` target the picker message instead of the "thinking" placeholder).
* [x] Changed that ephemeral placeholder from being deleted to being edited in place into a "✅ Audio obtained successfully. Playing: **[Title](link)**" confirmation, right before the public "Now playing" embed is sent.
* [x] Confirmed (via live testing) that manually dismissing an ephemeral message client-side does not delete it server-side — `edit_original_response()` never raised `NotFound` in that scenario; the existing `try/except discord.HTTPException` guard was kept regardless, as a safeguard for interaction-token expiry.

### Loop Playback Feature (implemented, reverted, then re-implemented)
* [x] Re-implemented infinite single-track looping in `_play_track` (per-guild `_playback_generation` counter to avoid a stale `after()` callback re-triggering playback of a superseded track), after having deliberately shipped the Components V2 redesign as its own commit first, without the loop, to keep commits scoped.
* [x] Investigated FFmpeg `stderr` noise appearing on every loop iteration and occasionally on `/leave-voice-chat` (`IO error -10054`, `Will reconnect...`), cross-checked with an AI specialized in FFmpeg (reviewing `libavformat/http.c`'s `http_buf_read()` reconnect logic) and with `discord.py`'s own `FFmpegAudio._check_process_returncode()`/`cleanup()` logic. Confirmed these lines are benign (`AV_LOG_WARNING`, process still exits with code 0) and downgraded them from `ERROR` to `WARNING` in `_FFmpegStderrLogger.write()`, keeping only `"Failed to reconnect at"` as a genuine `ERROR`.
* [x] Documented this benign-noise pattern in `context.md` (see Architecture Decision #7) so it isn't mistaken for a bug in future sessions.

### Logging Configuration
* [x] Reduced the rotating log file size cap from 2 MB to 1 MB per file (`logs/all.log`, `logs/errors.log`), keeping the same 3-files-per-category retention.

---

## Pending Tasks

### High Priority — Active Bug Investigation (deferred, scope narrowed)

* [ ] **[BLOCKING, scope narrowed] No audio heard specifically when listening from the same laptop that runs the bot process** — confirmed working from a separate mobile device on a different network. To test next session, from a different laptop/network at home:
  - NAT hairpinning / double NAT on the home router (same public IP for bot sender and laptop listener).
  - Wrong audio output device selected in that specific Discord client/browser session on the laptop.
  - Discord client-side feedback/echo suppression triggered by having both the bot and a human listener active from the same local network/device context.
  - Test with the mobile device on the *same* wifi as the bot (instead of mobile data) to try to reproduce the issue there too.
  - Test with a third device (a different laptop/PC) on the bot's network, distinct from the one running the bot.
* [ ] **Show user-facing error messages in Discord itself** when something fails during playback/extraction — ffmpeg process failures, yt-dlp extraction failures, or any other failure in the audio pipeline — so failures are visible from the Discord client without needing to check the console/log files. Scope this for both the direct-URL flow and the search-selection flow (including a message like `"Could not fetch the video \`title\` (\`link\`)"` when a title is known, or without the parenthetical when it isn't — this was explicitly deferred from the previous session to its own separate commit).
* [ ] Remove the temporary diagnostic instrumentation added in a previous session (DAVE session `repr()` check and audio packet counter wrapper) once the laptop-side playback issue is resolved.
* [ ] Decide whether to keep `discord.player`/`discord.voice_state` DEBUG logs enabled/commented for ongoing development.

### Medium Priority

* [ ] Confirm final `player_client` list (`tv_downgraded`, `web_embedded`, `tv`) remains stable across different videos (age-restricted, live streams, etc.) — currently only validated with a couple of test videos.
* [ ] Decide whether to drop `tv` from `player_client` given its DRM-experiment warning (`tv_downgraded` did not show this warning in manual testing).
* [ ] If richer per-result data (e.g. release year) is needed later, evaluate a non-flat extraction only for the user's final selection (costs one extra request, only once per search).

### Low Priority (Packaging Phase)

* [ ] Package as `.exe` using PyInstaller.
* [ ] Configure PyInstaller `.spec` file to retain project assets (`dependencies/` folder), and re-verify `utils/paths.py`'s `sys.frozen` branch still resolves correctly given the new `utils/` folder depth.

### Additional Pending Tasks
* [ ] Verify Deno and `yt-dlp-ejs` licenses allow redistribution inside the packaged `.exe`.
* [ ] Re-test the `player_client` configuration against multiple different videos (age-restricted, live, non-music) — PO Token/DRM enforcement from YouTube has been observed to be intermittent/selective, not guaranteed stable long-term.
* [ ] Investigate why `visionos` is rejected as an unsupported client — it would be the simplest option (no JS runtime, no PO Token) if usable.

---

## Known Issues / Considerations

| Issue | Status | Cause / Notes |
| --- | --- | --- |
| `ffmpeg` dying instantly with `HTTP error 403 Forbidden` | Resolved | Caused by yt-dlp's default `android_vr` client requiring a PO Token. Fixed by installing portable Deno + `yt-dlp-ejs` and restricting `player_client` to non-PO-Token clients (`tv_downgraded`, `web_embedded`, `tv`). |
| FFmpeg errors not visible in terminal despite being written to a debug file | Resolved | Passing a real file object as `stderr=` gives discord.py a working `.fileno()`, which routes stderr directly to the OS, bypassing Python. Fixed by using a custom writer object (no real `.fileno()`), forcing discord.py's internal thread-based `piping_stderr` path, which now feeds the `vPetal` logger (console + `logs/errors.log`). |
| **No audio heard in voice channel** | **Resolved as a code/library issue — narrowed to a local playback environment issue, deferred to a future session with access to a different laptop/network** | Confirmed via direct runtime instrumentation that the entire pipeline (yt-dlp, FFmpeg, discord.py's `AudioPlayer`, Opus encoding, DAVE/`davey` E2EE session, UDP packet sending) is fully healthy. **Decisive test:** listening from a mobile device on a different network/client played the audio perfectly, while listening from the laptop running the bot produced no audio. Likely candidates: NAT hairpinning/double NAT, misconfigured audio output device, or client-side feedback suppression. |
| `android_vr` client returning 403 for ALL formats since 2026-08-17 | Root cause identified | YouTube began enforcing stricter rules on this specific client version (1.65.10). Not a misconfiguration — a platform-side change. Source: yt-dlp code comments in `_base.py`. |
| `tv` client flagged with a DRM experiment warning | Open — low priority | `tv` may have DRM applied to all its formats per an active YouTube experiment (unrelated to PO Token). `tv_downgraded` did not show this warning in manual testing. Consider dropping `tv` from `player_client` list. |
| `visionos` client rejected as "unsupported" when force-selected via `player_client` | Open — unexplored | Would be the ideal client (no JS, no PO Token) but yt-dlp explicitly skips it with `Skipping unsupported client "visionos"`. Root cause not identified yet. |
| Search results never show a release year | Resolved by design change | `extract_flat` search results frequently return `null` for `timestamp`/`release_timestamp`; confirmed with real search output. The year field was dropped from result labels entirely rather than displaying an unreliable `????`. |

---

## Notes for Any AI Continuing This Investigation

- The extracted audio URL and the local `ffmpeg.exe` binary are **confirmed working** (verified by manually producing and listening to a `.wav` file from the exact same stream URL). Do not re-investigate yt-dlp extraction or FFmpeg decoding unless new evidence contradicts this.
- **The full discord.py + davey (DAVE E2EE) + UDP transmission pipeline is confirmed healthy** via direct runtime instrumentation (DAVE session `ready=true`/`ACTIVE`, 1,300+ audio packets sent with zero drops) and via a successful cross-device listening test. Do not re-investigate discord.py, davey, or the packet transmission layer unless new evidence contradicts this.
- The remaining playback problem is scoped to **why the laptop running the bot cannot hear the audio it is itself transmitting, while other devices on other networks can.** This is deferred, to be tested from a different laptop/network.
- **New this session:** the project is now organized into `commands/` and `utils/` packages instead of a single `main.py`. Any AI continuing work should be aware that `utils/paths.py` resolves the project root relative to its *own* file location (one level up from `utils/`), not relative to `main.py` — this was the source of a real regression today and should be checked again whenever files are moved.
- **New this session:** logging is now split across the console, `logs/all.log`, and `logs/errors.log` (rotating, 2 MB / 3 files each), all sharing the same emoji-based formatter. FFmpeg errors and yt-dlp warnings/errors both flow through this same system now — there is no longer a "silent" failure path in the parts of the pipeline exercised so far.
- **New this session:** `/play` now supports plain search terms in addition to direct URLs, with a paginated, ephemeral, author-restricted button UI (`_SearchResultsView` in `commands/play.py`).
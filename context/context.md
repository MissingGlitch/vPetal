# vPetal — Project Context

- **Last Updated:** Friday, 21/08/2026
- **Status:** In active development (Error Handling & Discord Log Mirroring Phase — playback failsafe, in-Discord error messages, and Discord-mirrored logging channel/thread all complete)

---

## Description

A Discord music bot featuring slash commands (`/play` and `/leave-voice-chat`). `/play` now accepts either a direct YouTube URL (plays immediately) or a plain search term (shows a paginated, button-based, ephemeral results picker). The final goal is to distribute it as a standalone Windows `.exe` file that any user can run without needing prior installations.

---

## Development Environment

| Element | Detail |
|---|---|
| Operating System | Windows 11 (64-bit) |
| Terminal / Shell | PowerShell |
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
pyinstaller
```

### System Dependencies (Portable Binaries)

All portable executables live together in a single `dependencies/` directory:

* **FFmpeg (Windows Portable Build):** `dependencies/ffmpeg.exe`. Windows "Release Essentials" build.
* **Deno (Portable Build):** `dependencies/deno.exe`. Added as the JS runtime yt-dlp uses to solve YouTube's signature/n-challenge, avoiding clients that require a PO Token.

---

## Environment Variables (`.env`)

```plaintext
BOT_TOKEN         = <discord_bot_token>
DEV_GUILD_ID      = <test_server_id>
LOGS_CHANNEL_ID   = <discord_channel_id>  # mirrors command usage + startup-ready + all WARNING/ERROR logs
ERRORS_THREAD_ID  = <discord_thread_id>   # thread inside that same channel; mirrors WARNING/ERROR logs only
```
The `.env` file is excluded from Git tracking via `.gitignore`.

---

## Directory Structure
```plaintext
vPetal/
├── .venv/					              ← Python virtual environment			(Git-ignored)
├── dependencies/
│   ├── ffmpeg.exe			          ← Portable FFmpeg binary for Windows	(Git-ignored)
│   └── deno.exe			            ← Portable Deno binary for Windows		(Git-ignored)
├── commands/
│   ├── __init__.py			          ← Empty; marks the folder as an importable package
│   ├── play.py				            ← /play command
│   └── leave.py			            ← /leave-voice-chat command
├── utils/
│   ├── __init__.py			          ← Empty; marks the folder as an importable package
│   ├── paths.py			            ← FFMPEG_PATH / DENO_PATH resolution
│   ├── logger.py			            ← "vPetal" custom logger
│   └── youtube.py			          ← YDL_OPTIONS / SEARCH_YDL_OPTIONS
├── logs/
│   ├── all.log(.1)(.2)		        ← All log levels, rotated 		(max 3 files, 1 MB each)	(Git-ignored)
│   └── errors.log(.1)(.2)	      ← WARNING/ERROR only, rotated (max 3 files, 1 MB each)	(Git-ignored)
├── scripts/
│   ├── __init__.py               ← Empty; marks the folder as an importable package
│   ├── sync_commands_global.py   ← Pushes the command tree as GLOBAL commands
│   ├── sync_commands_locally.py	← Pushes the command tree as GUILD commands to DEV_GUILD_ID
│   ├── build_exe.py              ← Bakes secrets into main.py, runs PyInstaller, restores main.py
│   └── clean_build.py            ← Removes build/, dist/, and vPetal.spec
├── main.py                       ← Bot entry point
├── .env                          ← Secret environment variables (Git-ignored)
├── .gitignore
├── context/
│   ├── context.md						        ← This context documentation file
│   └── youtube-problem-explained.md	← A detailed explanation of the problem with YouTube
├── README.md							            ← Repository README
└── requirements.txt					        ← Core dependencies file
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

### 9. Playback Failure Failsafe: Consecutive-Failure Cap Instead of Infinite Retry

The single-track loop in `_play_track` (`commands/play.py`) previously had no limit on how
many times it would restart playback after `voice_client.play(after=_on_playback_finished)`
finished. During testing (forcing an `android_vr` 403 on purpose), this produced an infinite
loop: FFmpeg died in milliseconds each time, but `_on_playback_finished` received `error=None`
on every call — investigated and narrowed to a discord.py-side interaction between
`_check_process_returncode()`'s `self._stopped` guard and our own rapid `voice_client.play()`
restarts, though the exact mechanism was not fully confirmed (would require reading
`VoiceClient.play()`/`stop()` in full).

**Decision:** instead of relying on `error` being correctly populated, failures are now
detected by elapsed time: if `after()` fires less than `MIN_PLAYBACK_SECONDS` (3s) after the
track started, that attempt counts as a failure regardless of what `error` contains. A
per-guild `_consecutive_failures` counter gives up after `MAX_CONSECUTIVE_FAILURES` (10)
in a row, logging `"Giving up on ... after 10 consecutive failed attempts"` and notifying
the channel the track was playing in, instead of looping forever. The counter resets to 0
once a track plays past that 3-second threshold.

### 10. In-Discord Error Messages

Every yt-dlp extraction call (`ydl.extract_info(...)`, both for direct URLs and search) and
every call into `_play_track` is now wrapped in `try/except`, catching `yt_dlp.utils.DownloadError`
and `discord.ClientException` specifically (with a tailored message), plus a generic
`except Exception` as a final safety net (logged with `logger.exception(...)` for the full
traceback, shown to the user as a generic "something unexpected went wrong" message). A small
`_build_error_message(reason)` helper (`commands/play.py`) standardizes the ❌-prefixed,
non-technical text shown to the user — the full technical detail (stack trace, yt-dlp/ffmpeg
raw output) stays in the console and log files only, never in the Discord-facing message.

### 11. Discord Channel/Thread Log Mirroring

`utils/logger.py` now mirrors selected log records live into a real Discord channel
(`LOGS_CHANNEL_ID`) and a thread inside it (`ERRORS_THREAD_ID`), via a custom
`_DiscordHandler(logging.Handler)`:
* The **channel** receives every `WARNING`/`ERROR` record, plus any record explicitly marked
  with `extra={"channel_notify": True}` — currently only the startup-ready line and the two
  command-usage lines (`/play`, `/leave-voice-chat`).
* The **thread** receives only `WARNING`/`ERROR` records (no filter needed beyond `setLevel`).
* Since `logger.error(...)`/`logger.warning(...)` calls can happen from any thread (e.g. the
  `AudioPlayer` thread via `_FFmpegStderrLogger`), `_DiscordHandler.emit()` never `await`s
  directly — it schedules the actual `channel.send(...)`/`thread.send(...)` onto the bot's
  asyncio loop via `asyncio.run_coroutine_threadsafe(...)`, resolved once in `on_ready` via
  `set_discord_destinations(client, logs_channel, errors_thread)` (uses `get_channel()` first,
  falling back to `fetch_channel()` if not cached).
* Messages are wrapped in a code block (```` ``` ````) and **truncated** (not split) to 1900
  characters before wrapping, keeping every mirrored message under Discord's 2000-character
  limit. A separate, undecorated `vPetal.discord_mirror` logger reports mirroring failures
  (e.g. missing permissions, deleted channel) to console/`errors.log` only, deliberately
  without a Discord handler attached, to avoid a feedback loop.
* Ordering constraint: the `_DiscordHandler`/`_ChannelFilter`/`_channel_handler`/`_thread_handler`
  definitions must appear in the file **before** `logger.addHandler(_channel_handler)` — this
  caused a real `NameError` during implementation from defining them out of order.

### 12. Command Sync Decoupled From Startup

`main.py` no longer calls `tree.copy_global_to()`/`tree.sync()` inside `on_ready` — with
development effectively wrapping up, re-syncing commands on every startup was no longer
necessary and only added an extra HTTP round-trip to every boot. Syncing is now a deliberate,
manual action via two standalone scripts under `scripts/`:
* `sync_commands_global.py` — calls `tree.sync()` with no guild, pushing GLOBAL commands
  (subject to Discord's propagation delay).
* `sync_commands_locally.py` — calls `tree.copy_global_to(guild=TEST_GUILD)` +
  `tree.sync(guild=TEST_GUILD)`, exactly like `main.py` used to do, scoped to `DEV_GUILD_ID`.

Both scripts require running as a module (`python -m scripts.sync_commands_locally`, not
`python scripts/sync_commands_locally.py`) since they import from the `commands` package —
running the file directly puts only `scripts/` on `sys.path`, not the project root, causing a
`ModuleNotFoundError`. This same constraint applies to `build_exe.py` and `clean_build.py`.

### 13. Standalone `.exe` Build Pipeline (PyInstaller)

`scripts/build_exe.py` automates the full build: it first removes any stale `build/`, `dist/`,
and `vPetal.spec` (via `scripts/clean_build.py`'s `clean_build_artifacts()`, imported and reused
rather than duplicated), then temporarily rewrites `main.py`'s three `os.getenv(...)` lines
(`BOT_TOKEN`, `LOGS_CHANNEL_ID`, `ERRORS_THREAD_ID`) into literal values read from `.env`, runs
`pyinstaller`, and restores the original `main.py` from a backup in a `finally` block regardless
of build success/failure. This bakes the secrets into the `.exe` itself so the final distributed
`.zip` never needs to include a `.env` file — an accepted tradeoff given this is a personal bot
shared only with a closed group of friends, run manually per voice call, never hosted 24/7.

**Two PyInstaller-specific runtime failures were diagnosed and fixed this session, both only
reproducible in the frozen `.exe`, never in `python main.py`:**
* `RuntimeError: PyNaCl library needed in order to use voice` — root-caused (via a diagnostic
  `import nacl.secret, nacl.utils` block added temporarily at the very top of `main.py`, printing
  the full traceback with `flush=True`) to `ModuleNotFoundError: No module named '_cffi_backend'`,
  a native extension `nacl.bindings` depends on via `cffi` that PyInstaller's static analysis
  didn't pull in automatically. Fixed by adding `--collect-all cffi` to the `pyinstaller` command
  in `build_exe.py` (the actual root cause fix); `--collect-all nacl` was kept alongside it as a
  safety redundancy from an earlier diagnostic step, though not strictly required on its own.
* `discord.opus.OpusNotLoaded` (raised on `voice_client.play(...)`) — root-caused to
  `discord/opus.py`'s `_load_default()` resolving `libopus-0.x64.dll` via a path relative to
  discord.py's own installed location, which PyInstaller's module analysis doesn't capture since
  it's a bundled data file, not an import. Fixed by adding `--collect-data discord` to the same
  `pyinstaller` command, which bundles discord.py's `bin/` folder (including the `.dll`) into the
  frozen app.

Both diagnostic blocks (the `nacl` import traceback and the `has_nacl`/opus checks) were removed
from `main.py` once confirmed fixed; only the three `pyinstaller` flags (`--collect-all cffi`,
`--collect-all nacl`, `--collect-data discord`) remain as the permanent fix.

---

## What Was Done Today (21/08/2026)

### Error Capture Testing
* [x] Devised and ran a battery of manual failure tests against `/play` and `/leave-voice-chat`
  (invalid/unresolvable URL, no-results search, forced `android_vr` 403 loop, among others) to
  confirm no test crashes the bot process and every failure is at least visible in the console/logs.
* [x] Confirmed the infinite-retry-loop bug during the forced-403 test: `_on_playback_finished`
  received `error=None` on every iteration despite FFmpeg dying instantly each time.

### Playback Failsafe
* [x] Added `MAX_CONSECUTIVE_FAILURES` (10) and `MIN_PLAYBACK_SECONDS` (3) constants and a
  per-guild `_consecutive_failures` counter to `_play_track`/`_on_playback_finished`, so a track
  that keeps failing near-instantly gives up after 10 attempts instead of looping forever,
  independent of whether `error` itself is populated correctly.
* [x] Added a diagnostic log line (`_on_playback_finished called ... with error={error!r}`) that
  confirmed the `error=None` root cause empirically; kept as a permanent debug-level line.

### In-Discord Error Messages
* [x] Wrapped yt-dlp extraction (`ydl.extract_info`) and `_play_track` calls in both the direct-URL
  and search-selection flows in `try/except`, catching `yt_dlp.utils.DownloadError` and
  `discord.ClientException` with tailored user-facing messages, plus a generic `except Exception`
  fallback, via a new `_build_error_message()` helper.
* [x] Notified the channel directly (not via the interaction, which may be long expired by then)
  when the 10-consecutive-failures cap is hit.

### Discord Channel/Thread Log Mirroring
* [x] Added `LOGS_CHANNEL_ID`/`ERRORS_THREAD_ID` env vars and a `_DiscordHandler` in
  `utils/logger.py` that mirrors WARNING/ERROR logs to both a channel and a thread, plus
  startup-ready and command-usage `INFO` lines to the channel only (via `extra={"channel_notify": True}`).
* [x] Fixed a `NameError` caused by handler/filter classes being referenced before their
  definition, by reordering the file.
* [x] Fixed a missing `channel_notify` flag on the `/play` usage log line (present on
  `/leave-voice-chat` but initially missed on `/play`), which caused that specific line to
  never reach the channel.
* [x] Confirmed mirrored messages are truncated (not split) at 1900 characters before being
  wrapped in a code block, staying under Discord's 2000-character message limit by design.

### Command Sync Decoupled + Standalone `.exe` Build
* [x] Removed `tree.copy_global_to()`/`tree.sync()` from `main.py`'s `on_ready`; created
  `scripts/sync_commands_global.py` and `scripts/sync_commands_locally.py` as standalone,
  manually-run alternatives.
* [x] Added `scripts/__init__.py` after hitting a `ModuleNotFoundError` running a script
  directly instead of via `python -m scripts.<name>`.
* [x] Created `scripts/build_exe.py`: bakes `BOT_TOKEN`/`LOGS_CHANNEL_ID`/`ERRORS_THREAD_ID`
  into `main.py` from `.env`, runs PyInstaller, restores `main.py` in a `finally` block.
* [x] Diagnosed and fixed `RuntimeError: PyNaCl library needed` in the frozen `.exe`
  (missing `_cffi_backend` native extension) via `--collect-all nacl`.
* [x] Diagnosed and fixed `discord.opus.OpusNotLoaded` in the frozen `.exe` (missing bundled
  `libopus-0.x64.dll` data file) via `--collect-data discord`.
* [x] Confirmed end-to-end: built `.exe` successfully plays audio in a real voice channel.
* [x] Created `scripts/clean_build.py` to remove `build/`, `dist/`, and `vPetal.spec`; refactored
  `build_exe.py` to import and reuse its `clean_build_artifacts()` instead of duplicating the logic.
* [x] Discovered (not yet fixed) a Discord API rate-limit (`429`) flood when many `WARNING`-level
  FFmpeg reconnect lines (see Architecture Decision #7, expected/benign) and `discord.http`'s own
  rate-limit retry warnings get mirrored to the logs channel in quick succession, partly
  self-feeding since the rate-limit warning itself is also mirrored. Fix deferred to next session
  (see Pending Tasks).

---

## Pending Tasks

### High Priority — Active Bug Investigation (deferred, scope narrowed)

* [ ] **Discord API rate-limit (`429`) flood from mirrored FFmpeg `WARNING` lines** — decided
  approach: keep all warnings (no blanket level-based suppression), instead (a) stop
  `discord.http`'s own logger from propagating into the `vPetal`-attached handlers, and
  (b) extend `_ChannelFilter` to exclude the specific known-benign FFmpeg reconnect strings
  already downgraded to `WARNING` by `_FFmpegStderrLogger` (see Architecture Decision #7:
  `"Will reconnect"`, `"Error in the pull function"`, `"IO error"`). Not yet implemented —
  needs the current `_ChannelFilter`/`_DiscordHandler` code pasted in to produce the exact patch.
* [ ] **[BLOCKING, scope narrowed] No audio heard specifically when listening from the same laptop that runs the bot process** — confirmed working from a separate mobile device on a different network. To test next session, from a different laptop/network at home:
  - NAT hairpinning / double NAT on the home router (same public IP for bot sender and laptop listener).
  - Wrong audio output device selected in that specific Discord client/browser session on the laptop.
  - Discord client-side feedback/echo suppression triggered by having both the bot and a human listener active from the same local network/device context.
  - Test with the mobile device on the *same* wifi as the bot (instead of mobile data) to try to reproduce the issue there too.
  - Test with a third device (a different laptop/PC) on the bot's network, distinct from the one running the bot.
* [x] ~~Show user-facing error messages in Discord itself~~ — **done 21/08/2026** (see Architecture Decision #10). Still open: the message wording is currently generic (`Could not fetch that URL`, `Something unexpected went wrong`) rather than always including the resolved title/link — revisit wording once more real-world failure cases are observed.
* [ ] Remove the temporary diagnostic instrumentation added in a previous session (DAVE session `repr()` check and audio packet counter wrapper) once the laptop-side playback issue is resolved.
* [ ] Decide whether to keep `discord.player`/`discord.voice_state` DEBUG logs enabled/commented for ongoing development.

### Medium Priority

* [ ] Confirm final `player_client` list (`tv_downgraded`, `web_embedded`, `tv`) remains stable across different videos (age-restricted, live streams, etc.) — currently only validated with a couple of test videos.
* [ ] Decide whether to drop `tv` from `player_client` given its DRM-experiment warning (`tv_downgraded` did not show this warning in manual testing).
* [ ] If richer per-result data (e.g. release year) is needed later, evaluate a non-flat extraction only for the user's final selection (costs one extra request, only once per search).
* [ ] Confirm the exact discord.py-side mechanism behind `_on_playback_finished` receiving `error=None` on an instant FFmpeg failure (suspected race between our rapid `voice_client.play()` restarts and `FFmpegAudio._check_process_returncode()`'s `self._stopped` guard) — not blocking anymore thanks to the elapsed-time failsafe, but still an open unknown worth closing out.

### Low Priority (Packaging Phase)

* [x] ~~Package as `.exe` using PyInstaller~~ — **done 21/08/2026**, confirmed working end-to-end
  (voice playback included) via `scripts/build_exe.py` with `--collect-all cffi`,
  `--collect-all nacl`, and `--collect-data discord` (see Architecture Decision #13).
* [ ] Still not addressed: retaining `dependencies/` (`ffmpeg.exe`/`deno.exe`) alongside the
  distributed `.exe`, and re-verifying `utils/paths.py`'s `sys.frozen` branch resolves correctly
  now that the file lives in `utils/` — this was validated for FFmpeg/Deno path resolution logic
  itself, but not yet re-confirmed against an actual `dependencies/` folder shipped next to the
  built `.exe` in a real `.zip`.

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
- **New this session:** logging is now split across the console, `logs/all.log`, and `logs/errors.log` (rotating, 1 MB / 3 files each), all sharing the same emoji-based formatter. FFmpeg errors and yt-dlp warnings/errors both flow through this same system now — there is no longer a "silent" failure path in the parts of the pipeline exercised so far.
- **New this session:** `/play` now supports plain search terms in addition to direct URLs, with a paginated, ephemeral, author-restricted button UI (`_SearchResultsView` in `commands/play.py`).
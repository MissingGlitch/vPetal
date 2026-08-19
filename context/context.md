# vPetal — Project Context

- **Last Updated:** Wednesday, 19/08/2026
- **Status:** In active development (Core Functionality Debugging Phase — audio pipeline confirmed healthy, root cause narrowed to local playback environment)

---

## Description

A Discord music bot featuring slash commands (`/play` and `/leave-voice-chat`). The final goal is to distribute it as a standalone Windows `.exe` file that any user can run without needing prior installations.

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

All portable executables now live together in a single `dependencies/` directory:

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
├── .venv/				← Python virtual environment			(Git-ignored)
├── dependencies/
│   ├── ffmpeg.exe		← Portable FFmpeg binary for Windows	(Git-ignored)
│   └── deno.exe		← Portable Deno binary for Windows		(Git-ignored)
├── main.py				← Bot entry point						(client, /play, /leave-voice-chat)
├── ffmpeg_debug.log	← Temporary debug file:					(Git-ignored, diagnostic only)
├── .env				← Secret environment variables			(Git-ignored)
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

Neither FFmpeg nor Deno will be installed globally on user machines. Both portable binaries reside inside the `dependencies/` directory next to the project files (and future `.exe`). `main.py` resolves both paths dynamically depending on whether the bot runs as a frozen `.exe` (`sys.frozen`) or as a dev script.

### 3. Guild-Scoped Slash Commands for Testing

Global slash commands can take up to an hour to propagate across Discord. During development, commands are synced exclusively to the test server specified in `DEV_GUILD_ID` for immediate updates, via `tree.copy_global_to(guild=TEST_GUILD)` + `tree.sync(guild=TEST_GUILD)` inside `on_ready`.

### 4. YouTube Extraction Strategy: JS Runtime over PO Token

`yt-dlp`'s default client selection (when no JS runtime is present) falls back to clients like `android_vr`, which require a **PO Token**: An anti-bot mechanism dependent on unofficial third-party plugins with unpredictable, increasingly aggressive enforcement from Google.

**Decision:** prioritize YouTube clients that rely solely on a JS runtime (officially maintained by the `yt-dlp` team via the `yt-dlp/ejs` project), avoiding any client whose policy declares a required PO Token. Current `YDL_OPTIONS` configuration in `main.py`:

```python
YDL_OPTIONS = {
	"format": "bestaudio/best",
	"noplaylist": True,
	"quiet": True,
	"js_runtimes": {"deno": {"path": DENO_PATH}},
	"extractor_args": {"youtube": {"player_client": ["tv_downgraded", "web_embedded", "tv"]}},
}
```

This combination was manually validated via CLI and confirmed to resolve `n=`/`sig=` parameters without PO Token warnings, producing a client of `c=TVHTML5`. **Confirmed working end-to-end in Discord voice as of 19/08/2026** (see "What Was Done Today" below).

### 5. FFmpeg stderr Debug Capture (temporary, diagnostic-only)

`/play` currently opens `ffmpeg_debug.log` and passes it as `stderr=` to `FFmpegPCMAudio`, plus an `after=` callback that prints playback errors to console. This was added purely for debugging the current known issue (see below) and should be removed or made conditional once the root cause is resolved — it is not meant to ship in production.

### 6. Custom Logging Layer (`vPetal` logger + diagnostic instrumentation, temporary)

Added a dedicated `logging.getLogger("vPetal")` logger (separate from discord.py's internal `discord` logger) to trace command usage (`/play`, `/leave-voice-chat`) and playback flow. Additionally, `discord.player` and `discord.voice_state` are raised to `DEBUG` level. `discord.gateway` is deliberately **not** raised to `DEBUG` globally, since it's shared by both the voice websocket and the main shard gateway — doing so floods the console with full JSON payloads for every Discord event (`GUILD_CREATE`, `INTERACTION_CREATE`, heartbeats, etc.). If DAVE/MLS-specific gateway lines are needed again, a `logging.Filter` dropping `"WebSocket Event"` messages should be used instead of a blanket level change.

Two temporary diagnostic instrumentations were added directly inside `/play` (accessing private discord.py attributes, e.g. `voice_client._connection`, for debugging purposes only — not part of the public API, must be removed once the investigation concludes):
* A wrapper around `voice_client.send_audio_packet` that logs a running count of audio packets sent, to confirm sustained UDP transmission without silent stalls.
* A one-shot check, 2 seconds after `play()` starts, logging `repr(voice_client._connection.dave_session)` to directly confirm the DAVE/MLS session's `ready`/`status` state.

---

## What Was Done Today (19/08/2026)

* [x] Added a dedicated `vPetal` logger plus command-usage logs (`/play`, `/leave-voice-chat`) identifying the invoking user, guild, and URL.
* [x] Raised `discord.player` and `discord.voice_state` to `DEBUG` to trace the ffmpeg spawn command and voice handshake state transitions.
* [x] Diagnosed excessive log noise: confirmed `discord.gateway` is a single shared logger for both the voice websocket and the main shard gateway, so raising it to `DEBUG` dumps full JSON payloads for every Discord event — corrected the logging setup to avoid enabling it blanket-wide.
* [x] Formally investigated the **DAVE (End-to-End Encryption) voice protocol** as a suspect for the silent audio failure, given `discord.py 2.7.1` requires `davey` and negotiates DAVE (`dave_protocol_version: 1`) automatically.
* [x] Cross-referenced findings with an AI specialist for `davey` (external document/response), which confirmed from `davey`'s Rust source:
  - A commit negotiation without a subsequent "welcome" message is **normal** when the bot is not a new member joining an existing group (no `MLS_WELCOME` needed in that case).
  - `dave_session.ready` becomes `True` synchronously right after a successfully processed commit.
  - `encrypt_opus`/`encrypt` **raises an explicit exception** if the session is not ready — there is no silent fallback at the `davey` level.
* [x] Verified in `discord.py`'s own source that no `try/except` in the packet-sending path (`send_audio_packet` → `_get_voice_packet` → `send_packet`) could silently swallow such an exception — confirming that if DAVE encryption had failed, it would have surfaced as a real error in the `after=` callback.
* [x] Added direct runtime instrumentation (`repr(dave_session)` + audio packet counter) and re-ran `/play`. **Results, both confirmed positive:**
  - `DAVE session state 2s after play(): <DaveSession ... ready=true, status=ACTIVE>`
  - Over 1,300 audio packets sent continuously over ~27 seconds (~48 packets/sec, consistent with 20ms Opus frames), with **zero** `"A packet has been dropped"` log lines.
* [x] **Concluded that the entire software pipeline (yt-dlp → FFmpeg → discord.py `AudioPlayer` → Opus encoding → DAVE encryption → UDP send) is fully healthy and verified with direct runtime evidence, not just code inspection.**
* [x] **Root cause narrowed down via cross-device test:** ran the bot and `/play` while listening from a **mobile device** (Discord in browser, different network/device than the laptop running the bot) instead of the laptop itself. **The mobile device played the audio perfectly.** Listening from the laptop itself (where the bot process runs) still produces no audio.
* [x] **This fully rules out discord.py, davey, FFmpeg, and yt-dlp as the cause.** The problem is isolated to the laptop acting as a **listener/receiver** in the same voice channel where the bot (running on that same laptop) is also connected — not to the bot's transmission itself, which was proven to reach Discord's voice servers successfully.

---

## Pending Tasks

### High Priority — Active Bug Investigation (narrowed scope)

* [ ] **[BLOCKING, scope narrowed] No audio heard specifically when listening from the same laptop that runs the bot process — audio is confirmed to work when listening from a separate device on a different network.** Leading hypotheses to test tomorrow, from a different laptop/network at home (see "Known Issues" below for full detail):
  - NAT hairpinning / double NAT on the home router (same public IP for bot sender and laptop listener).
  - Wrong audio output device selected in that specific Discord client/browser session on the laptop.
  - Discord client-side feedback/echo suppression triggered by having both the bot and a human listener active from the same local network/device context.
* [ ] Remove/condition the temporary `ffmpeg_debug.log` capture and `after=` debug callback in `/play` now that the pipeline itself is confirmed healthy.
* [ ] Remove the temporary diagnostic instrumentation added today (DAVE session `repr()` check and audio packet counter wrapper) once the laptop-side playback issue is resolved — both were explicitly for diagnostic purposes only and access private discord.py attributes.
* [ ] Decide whether to keep the `vPetal` logger and the raised `discord.player`/`discord.voice_state` log levels for ongoing development, or scale them back once debugging concludes.

### Medium Priority

* [ ] Confirm final `player_client` list (`tv_downgraded`, `web_embedded`, `tv`) remains stable across different videos (age-restricted, live streams, etc.) — currently only validated with one test video.
* [ ] Fix an unresolved discrepancy: when FFmpeg fails, the `after=` debug callback was expected to print `[FFMPEG ERROR] ...` to console but did not appear at all in earlier tests (before the 403 was fixed) — root cause never confirmed, low priority since it doesn't block the main issue.

### Low Priority (Packaging Phase)

* [ ] Package as `.exe` using PyInstaller.
* [ ] Configure PyInstaller `.spec` file to retain project assets (`dependencies/` folder).

### Additional Pending Tasks
* [ ] Verify Deno and `yt-dlp-ejs` licenses allow redistribution inside the packaged `.exe`.
* [ ] Re-test the `player_client` configuration against multiple different videos (age-restricted, live, non-music) — current validation is based on a single test video only, and PO Token/DRM enforcement from YouTube has been observed to be intermittent/selective, not guaranteed stable long-term.
* [ ] Investigate why `visionos` is rejected as an unsupported client — it would be the simplest option (no JS runtime, no PO Token) if usable.

---

## Known Issues / Considerations

| Issue | Status | Cause / Notes |
| --- | --- | --- |
| `ffmpeg` dying instantly with `HTTP error 403 Forbidden` | Resolved | Caused by yt-dlp's default `android_vr` client requiring a PO Token. Fixed by installing portable Deno + `yt-dlp-ejs` and restricting `player_client` to non-PO-Token clients (`tv_downgraded`, `web_embedded`, `tv`). |
| **No audio heard in voice channel** | **Resolved as a code/library issue — narrowed to a local playback environment issue, to be tested tomorrow from a different laptop/network** | Confirmed via direct runtime instrumentation that the entire pipeline (yt-dlp, FFmpeg, discord.py's `AudioPlayer`, Opus encoding, DAVE/`davey` E2EE session, UDP packet sending) is fully healthy: DAVE session reached `ready=true, status=ACTIVE`, and over 1,300 audio packets were sent continuously with zero drops. **Decisive test:** listening from a mobile device on a different network/client played the audio perfectly, while listening from the laptop running the bot produced no audio. This proves the bot's transmission to Discord's voice servers succeeds, and isolates the problem to the laptop's role as a **listener** in the same channel — likely candidates: NAT hairpinning/double NAT (bot and laptop sharing the same home router/public IP), a misconfigured audio output device in that specific Discord client session, or client-side feedback suppression. **Next diagnostic steps proposed:** (1) test listening from a different laptop/PC on the same home network as the bot; (2) test with the mobile device connected to the same wifi network as the bot (instead of mobile data) to check if NAT hairpinning reproduces the issue; (3) verify Discord's selected audio output device and per-user volume/mute settings on the affected laptop's client. |
| `android_vr` client returning 403 for ALL formats since 2026-08-17 | Root cause identified | YouTube began enforcing stricter rules on this specific client version (1.65.10) the day before this was first noticed. Not a misconfiguration — a platform-side change. Source: yt-dlp code comments in `_base.py`. |
| `tv` client flagged with a DRM experiment warning | Open — low priority | `tv` may have DRM applied to all its formats per an active YouTube experiment (unrelated to PO Token). `tv_downgraded` did not show this warning in manual testing. Consider dropping `tv` from `player_client` list, keeping only `tv_downgraded` (+ `web_embedded` as fallback). |
| `visionos` client rejected as "unsupported" when force-selected via `player_client` | Open — unexplored | Would be the ideal client (no JS, no PO Token) but yt-dlp explicitly skips it with `Skipping unsupported client "visionos"`. Root cause in yt-dlp's client-selection code not identified yet. |

---

## Notes for Any AI Continuing This Investigation

- The extracted audio URL and the local `ffmpeg.exe` binary are **confirmed working** (verified by manually producing and listening to a `.wav` file from the exact same stream URL). Do not re-investigate yt-dlp extraction or FFmpeg decoding unless new evidence contradicts this.
- **The full discord.py + davey (DAVE E2EE) + UDP transmission pipeline is confirmed healthy via direct runtime instrumentation (DAVE session `ready=true`/`ACTIVE`, 1,300+ audio packets sent with zero drops) and via a successful cross-device listening test (mobile device, different network, heard the audio perfectly). Do not re-investigate discord.py, davey, or the packet transmission layer unless new evidence contradicts this.**
- The remaining problem is scoped to **why the laptop running the bot cannot hear the audio it is itself transmitting, while other devices on other networks can.** Leading candidates: NAT hairpinning/double NAT on the shared home router, local audio output misconfiguration, or Discord client-side feedback suppression. This is the starting point for the next session, to be tested from a different laptop/network.
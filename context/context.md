# vPetal — Project Context

- **Last Updated:** Tuesday, 18/08/2026
- **Status:** In active development (Core Functionality Debugging Phase)

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

This combination was manually validated via CLI and confirmed to resolve `n=`/`sig=` parameters without PO Token warnings, producing a client of `c=TVHTML5`.

### 5. FFmpeg stderr Debug Capture (temporary, diagnostic-only)

`/play` currently opens `ffmpeg_debug.log` and passes it as `stderr=` to `FFmpegPCMAudio`, plus an `after=` callback that prints playback errors to console. This was added purely for debugging the current known issue (see below) and should be removed or made conditional once the root cause is resolved — it is not meant to ship in production.

---

## What Was Done Today (18/08/2026)

* [x] Wrote the initial `main.py` with `discord.Client` + `app_commands.CommandTree`, `/play` and a `stop` command.
* [x] Identified and fixed a naming inconsistency: the disconnect command was named `stop` in code but documented as `leave-voice-chat` — renamed to `leave-voice-chat` in code.
* [x] Diagnosed a first playback failure: `ffmpeg` was dying instantly (`return code 3436169992`) with no visible error in console.
* [x] Added `stderr=` capture to `FFmpegPCMAudio` and an `after=` callback to expose the real FFmpeg error — confirmed root cause: `HTTP error 403 Forbidden`, caused by yt-dlp defaulting to the `android_vr` client (no JS runtime installed), which requires a PO Token that wasn't being provided.
* [x] Restructured `ffmpeg/` folder into a unified `dependencies/` folder.
* [x] Installed portable **Deno** (`dependencies/deno.exe`) and the `yt-dlp-ejs` package to solve YouTube's JS challenge without PO Token dependency.
* [x] Updated `YDL_OPTIONS` in `main.py` with `js_runtimes` and `extractor_args` (`player_client` restricted to non-PO-Token clients).
* [x] Validated manually via CLI (`dependencies/ffmpeg.exe -i "<url>" -f wav salida_prueba.wav`) that the extracted audio URL is valid and plays back perfectly outside of Discord/discord.py — **this fully rules out yt-dlp, the extracted URL, and FFmpeg's decoding as the cause of the current issue.**
* [x] Cross-referenced findings with "AI specialists" for yt-dlp and FFmpeg (external documents), confirming the 403/PO Token diagnosis and ruling out stream corruption/DRM.

---

## Pending Tasks

### High Priority — Active Bug Investigation

* [ ] **[BLOCKING] No audio is heard in the voice channel despite a fully healthy pipeline.** See "Known Issues" below for full details — this is the main task to resume tomorrow.
* [ ] Remove/condition the temporary `ffmpeg_debug.log` capture and `after=` debug callback in `/play` once the audio issue is resolved.

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
| Executable portability across Windows architectures | Resolved | Target builds are 64-bit Windows executables, compatible with all modern 64-bit Windows systems. |
| Command name mismatch (`stop` vs `leave-voice-chat`) | Resolved | Renamed in code to `leave-voice-chat` to match documentation. |
| `ffmpeg` dying instantly with `HTTP error 403 Forbidden` | Resolved | Caused by yt-dlp's default `android_vr` client requiring a PO Token. Fixed by installing portable Deno + `yt-dlp-ejs` and restricting `player_client` to non-PO-Token clients (`tv_downgraded`, `web_embedded`, `tv`). |
| **No audio heard in voice channel despite successful bot connection and a healthy, verified audio stream** | **Open — main blocker for tomorrow** | The bot joins the voice channel successfully (`Voice connection complete` in logs), `ffmpeg` runs for the full duration with **zero** stderr output (`-loglevel warning`, meaning no decode issues at all), and manually extracting the exact same URL to a `.wav` file with the same portable `ffmpeg.exe` produces perfect, audible playback. This rules out yt-dlp, the extracted URL, DRM, and FFmpeg decoding as causes. The problem is therefore isolated to the audio **transmission** stage between discord.py's `AudioPlayer`/`VoiceClient` and Discord's voice servers — specifically the continuous UDP packet sending (`VoiceClient.send_audio_packet` → `send_packet`), since the initial UDP IP-discovery handshake *does* complete (`Voice connection complete` is logged, which only happens after `discover_ip()` succeeds). Leading hypotheses (unconfirmed): Windows Firewall/Defender or a VPN/router QoS setting silently dropping sustained outbound UDP traffic to Discord's voice media servers, while allowing the initial discovery packet through. **Next diagnostic steps proposed:** (1) temporarily disable Windows Firewall or add explicit UDP/TCP in+out rules for the venv's `python.exe` and retest `/play`; (2) check for any active VPN/proxy/router QoS affecting UDP to `*.discord.media` domains; (3) enable `DEBUG`-level logging specifically for `discord.voice_client` and `discord.voice_state` (via `logging.getLogger('discord.voice_state').setLevel(logging.DEBUG)`) before `client.run(TOKEN)`, then retest and inspect for socket/send anomalies during sustained playback (not just the initial handshake). |
| `android_vr` client returning 403 for ALL formats since 2026-08-17 | Root cause identified | YouTube began enforcing stricter rules on this specific client version (1.65.10) the day before this was first noticed. Not a misconfiguration — a platform-side change. Source: yt-dlp code comments in `_base.py`. |
| `tv` client flagged with a DRM experiment warning | Open — low priority | `tv` may have DRM applied to all its formats per an active YouTube experiment (unrelated to PO Token). `tv_downgraded` did not show this warning in manual testing. Consider dropping `tv` from `player_client` list, keeping only `tv_downgraded` (+ `web_embedded` as fallback). |
| `visionos` client rejected as "unsupported" when force-selected via `player_client` | Open — unexplored | Would be the ideal client (no JS, no PO Token) but yt-dlp explicitly skips it with `Skipping unsupported client "visionos"`. Root cause in yt-dlp's client-selection code not identified yet. |

---

## Notes for Any AI Continuing This Investigation

- The extracted audio URL and the local `ffmpeg.exe` binary are **confirmed working** (verified by manually producing and listening to a `.wav` file from the exact same stream URL). Do not re-investigate yt-dlp extraction or FFmpeg decoding unless new evidence contradicts this.
- The remaining problem is scoped to **discord.py's voice packet transmission layer**, or to network/OS-level interference (firewall, VPN, NAT/QoS) affecting sustained outbound UDP after a successful initial handshake. This is the starting point for tomorrow's session.
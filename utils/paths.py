import os
import sys
import platform

#* FFmpeg path resolution
# Resolves the correct FFmpeg executable path depending on the runtime environment.
# When running as a compiled .exe on Windows, it looks for dependencies/ffmpeg.exe
# relative to the executable. On Linux/WSL (development), it uses the system FFmpeg.
if getattr(sys, "frozen", False):
	_base = os.path.dirname(sys.executable)
	FFMPEG_PATH = os.path.join(_base, "dependencies", "ffmpeg.exe")
elif platform.system() == "Windows":
	# utils/paths.py lives one folder inside the project root (vPetal/utils/),
	# so we need to go up one extra level to reach vPetal/ itself.
	_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	FFMPEG_PATH = os.path.join(_base, "dependencies", "ffmpeg.exe")
else:
	FFMPEG_PATH = "ffmpeg"

#* Deno path resolution
# Resolves the portable Deno executable, required by yt-dlp to run YouTube's
# JS challenge solver without depending on a system-wide installation.
if getattr(sys, "frozen", False):
	DENO_PATH = os.path.join(_base, "dependencies", "deno.exe")
elif platform.system() == "Windows":
	DENO_PATH = os.path.join(_base, "dependencies", "deno.exe")
else:
	DENO_PATH = "deno"
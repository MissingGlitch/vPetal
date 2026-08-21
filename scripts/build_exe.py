"""One-off build script: temporarily bakes BOT_TOKEN, LOGS_CHANNEL_ID, and
ERRORS_THREAD_ID as literals into main.py (read from .env), runs PyInstaller
to produce a standalone .exe with no .env dependency, then restores main.py
to its original state — regardless of whether the build succeeded or failed.
"""
import os
import re
import shutil
import subprocess
from dotenv import load_dotenv

load_dotenv()

MAIN_PY = "main.py"
BACKUP_PY = "main.py.bak"

from scripts.clean_build import clean_build_artifacts as _clean_build_artifacts


REPLACEMENTS = {
	"BOT_TOKEN": (
		r'TOKEN = os\.getenv\("BOT_TOKEN"\)',
		lambda value: f'TOKEN = "{value}"',
	),
	"LOGS_CHANNEL_ID": (
		r'LOGS_CHANNEL_ID = int\(os\.getenv\("LOGS_CHANNEL_ID"\)\)',
		lambda value: f'LOGS_CHANNEL_ID = {int(value)}',
	),
	"ERRORS_THREAD_ID": (
		r'ERRORS_THREAD_ID = int\(os\.getenv\("ERRORS_THREAD_ID"\)\)',
		lambda value: f'ERRORS_THREAD_ID = {int(value)}',
	),
}


def _patch_main_py():
	with open(MAIN_PY, "r", encoding="utf-8") as f:
		content = f.read()

	for env_key, (pattern, build_replacement) in REPLACEMENTS.items():
		value = os.getenv(env_key)
		if not value:
			raise RuntimeError(f"Missing {env_key} in .env; aborting build.")
		content, count = re.subn(pattern, build_replacement(value), content)
		if count != 1:
			raise RuntimeError(f"Expected exactly 1 match for {env_key} in {MAIN_PY}, found {count}.")

	with open(MAIN_PY, "w", encoding="utf-8") as f:
		f.write(content)


def main():
	_clean_build_artifacts()
	shutil.copyfile(MAIN_PY, BACKUP_PY)
	try:
		_patch_main_py()
		print(f"Patched {MAIN_PY} with baked-in secrets. Running PyInstaller...")
		subprocess.run(["pyinstaller", "--onefile", "--collect-all", "cffi", "--collect-all", "nacl", "--collect-data", "discord", "--name", "vPetal", MAIN_PY], check=True)
	finally:
		shutil.copyfile(BACKUP_PY, MAIN_PY)
		os.remove(BACKUP_PY)
		print(f"Restored original {MAIN_PY}.")


if __name__ == "__main__":
	main()
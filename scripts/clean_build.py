"""One-off cleanup script: removes every artifact left behind by build_exe.py
(build/, dist/, and vPetal.spec), leaving the project tree clean again.
Run manually with `python -m scripts.clean_build` once a build is done and
you no longer need to inspect its output (e.g. warn-vPetal.txt).
"""
import os
import shutil

BUILD_ARTIFACTS = ["build", "dist", "vPetal.spec"]


def clean_build_artifacts():
	for path in BUILD_ARTIFACTS:
		if os.path.isdir(path):
			shutil.rmtree(path)
			print(f"Removed directory: {path}")
		elif os.path.isfile(path):
			os.remove(path)
			print(f"Removed file: {path}")
		else:
			print(f"Nothing to remove: {path}")


if __name__ == "__main__":
	clean_build_artifacts()
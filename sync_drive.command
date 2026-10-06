#!/bin/sh
# Launcher for sync_drive.py: double-click in Finder, or run from Terminal with the same
# arguments as the script, e.g. `./sync_drive.command "Jane Doe" --force`.
# The first run creates .venv and installs requirements.txt; later runs reuse it.
set -e
cd "$(dirname "$0")"

if ! command -v fontforge >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/fontforge ]; then
	echo 'FontForge not found. Install Homebrew (https://brew.sh), then run: brew install fontforge'
	exit 1
fi

if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
	echo 'Setting up Python environment (first run only)...'
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements.txt
	touch .venv/.installed
fi

exec .venv/bin/python sync_drive.py "$@"

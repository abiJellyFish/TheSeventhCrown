#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  ASCII CRPG - MVP Prototype"
echo "============================================"
echo ""
echo "Installing dependencies..."
TEXTUAL_VERSION="8.2.8"
RICH_VERSION="15.0.0"
python -m pip install -r requirements.txt \
  "textual==${TEXTUAL_VERSION}" "rich==${RICH_VERSION}" -q
echo ""
echo "Starting game..."
python main.py

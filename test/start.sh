#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  ASCII CRPG - MVP Prototype"
echo "============================================"
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt -q
echo ""
echo "Starting game..."
python main.py

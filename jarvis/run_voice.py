#!/usr/bin/env python3
"""Wrapper script to run the JARVIS voice loop with unbuffered I/O."""
import sys
import os

# Force unbuffered stdout/stderr
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"

from jarvis.voice.loop import main

if __name__ == "__main__":
    sys.exit(main())

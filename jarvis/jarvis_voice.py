#!/usr/bin/env python3
"""JARVIS Voice Assistant — Talk to JARVIS through your Mac's microphone and speakers.

Usage:
    python3 jarvis_voice.py                  # continuous listening
    python3 jarvis_voice.py --once           # one utterance then exit
    python3 jarvis_voice.py --model small    # use a larger Whisper model
    python3 jarvis_voice.py --list-devices   # show available mics
    python3 jarvis_voice.py --http           # connect to running API server
"""

from jarvis.voice.loop import main

if __name__ == "__main__":
    main()

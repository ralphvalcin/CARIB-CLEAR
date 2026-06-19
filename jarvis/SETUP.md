# JARVIS Setup Guide

## Prerequisites

- macOS (Apple Silicon or Intel)
- Python 3.11+
- Homebrew (for Piper TTS)

## 1. Install Python Dependencies

```bash
cd JARVIS
pip install -e .
# or
pip install -r requirements.txt
```

**Key packages:**
- `faster-whisper` — speech-to-text (downloads model on first use)
- `piper-tts` — text-to-speech voice synthesis
- `sounddevice` — microphone access
- `numpy` — audio processing
- `fastapi` + `uvicorn` — API server
- `pydantic` — request validation

## 2. Download Piper Voice Model

```bash
mkdir -p piper_voices
cd piper_voices

# Download ONNX model (~50MB)
curl -L -o en_US-lessac-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx

# Download config
curl -L -o en_US-lessac-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

cd ..
```

## 3. Environment Variables (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `JARVIS_API_KEY` | *(none)* | API key for control endpoints |

## 4. Running

```bash
# Terminal 1: API server
./run_api.sh

# Terminal 2: Voice assistant
python3 -m jarvis.voice.loop
```

## 5. Verify

```bash
# Check API
curl http://localhost:8000/health

# Dashboard
open http://localhost:8000/dashboard

# Self-knowledge
curl http://localhost:8000/knowledge/self | python3 -m json.tool
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No default input device available` | Run `python3 -m jarvis.voice.loop --list-devices` to list audio devices, pass `--device N` |
| Piper model not found | Ensure `piper_voices/en_US-lessac-medium.onnx` exists |
| Whisper slow first use | First load downloads the model (~150MB `base`). Subsequent runs use cache |
| Hermes CLI not found | The drift checker will report missing capabilities but JARVIS still works with local tools |
| Echo feedback | Increase `--mute-cooldown` (default 3.0s) |
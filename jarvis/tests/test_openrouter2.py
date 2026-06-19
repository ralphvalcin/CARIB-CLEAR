"""Test streaming with Qwen model."""
import json
import httpx
import time
from pathlib import Path

env_path = Path.home() / ".hermes" / ".env"
raw = env_path.read_bytes()
key = None
for line in raw.split(b"\n"):
    marker = b"OPENROUTER_API_KEY="
    if line.startswith(marker):
        key = line[len(marker):].strip().strip(b"'\" \t")
        break

key_str = key.decode()
print(f"Key: {len(key_str)} chars, prefix: {key_str[:6]}")
time.sleep(5)

headers = {
    "Authorization": f"Bearer {key_str}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8000",
}

models = [
    "qwen/qwen3-coder:free",
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

for model in models:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in 4 words."}],
        "max_tokens": 20,
        "stream": False,
    }
    print(f"\n{model}: ", end="", flush=True)
    time.sleep(3)
    with httpx.Client(timeout=15, verify=False) as client:
        resp = client.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            print(f"OK: {content}")
            break
        else:
            print(f"Status {resp.status_code}: {resp.text[:100]}")
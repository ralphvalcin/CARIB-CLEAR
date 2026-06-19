"""Test OpenRouter streaming."""
from pathlib import Path
import json
import httpx
import time

# Read API key
key = None
env_path = Path.home() / ".hermes" / ".env"
for line in env_path.read_text().splitlines():
    if line.startswith("OPENROUTER_API_KEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

print(f"API key: {len(key)} chars")
print("Waiting 10s for rate limit cooldown...")
time.sleep(10)

# Try different models to find one that works
models = [
    "deepseek/deepseek-v4-flash:free",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8000",
}

for model in models:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
        "max_tokens": 30,
        "stream": False,
    }
    print(f"\nTesting {model}...", end=" ")
    time.sleep(3)
    try:
        with httpx.Client(timeout=15, verify=False) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers=headers,
            )
            print(f"Status: {resp.status_code}", end="")
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                print(f"  Result: {content}")
                break
            elif resp.status_code == 429:
                print(" (rate limited)")
            else:
                print(f" Error: {resp.text[:100]}")
    except Exception as e:
        print(f" Exception: {e}")
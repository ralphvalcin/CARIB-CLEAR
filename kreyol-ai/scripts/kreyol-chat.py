#!/usr/bin/env python3
"""
kreyol-chat.py
Interactive KreyolLM chat demo.

Usage:
    python3 kreyol-chat.py --model checkpoints/kreyollm-final/kreyollm-final
    python3 kreyol-chat.py --model meta-llama/Llama-3.1-8B-Instruct  # base model, no Kreyol fine-tune yet

Features:
    - Interactive chat loop in terminal
    - Haitian Creole prompts
    - Can also serve as simple API server with --serve flag
    - Voice input option (requires faster-whisper or whisper-oswald)

This is the FIRST thing an end user sees — make it fast, friendly, and simple.
"""

import argparse
import json
import sys
import time
import os

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    print("[ERROR] transformers required: pip install transformers torch")
    sys.exit(1)


KREYOL_PROMPT_TEMPLATE = """<|begin_of_text|><|start_header_id|>system<|end_header_id|>

Ou se yon asistan itil pou moun Ayisyen. Ou pale kreyòl ayisyen anpil. Ou ede moun ak kesyon yo sou: agrikilti, sante, edikasyon, ak dwa sitwayen. Ou reponn kout, klè, epi an kreyòl.<|eot_id|><|start_header_id|>user<|end_header_id|>

{user_input}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"""


def load_kreyollm(model_path: str):
    """Load KreyolLM (fine-tuned) or fall back to base model."""
    print(f"Loading model from: {model_path}")
    print("(This may take 1-3 minutes on first load...)")

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()

    print(f"✓ Model loaded: {model.config._name_or_path}")
    print(f"  Device: {model.device}")
    return model, tokenizer


def generate(model, tokenizer, user_input: str, system_prompt: str = "") -> str:
    """Generate a single response for a user message."""
    if "kreyollm" in model.config._name_or_path.lower() or system_prompt:
        prompt = KREYOL_PROMPT_TEMPLATE.format(user_input=user_input)
    else:
        # Base model: just tell it to chat in Kreyol
        prompt = f"Reponn lan kreyòl ayisyen: {user_input}\nRepons:"

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=300,
            temperature=0.5,
            top_p=0.9,
            do_sample=True,
            repetition_penalty=1.1,
            pad_token_id=tokenizer.eos_token_id,
        )

    response = tokenizer.decode(
        outputs[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True,
    ).strip()
    return response


WELCOME_BANNER = r"""
╔══════════════════════════════════════════════════════╗
║                                                      ║
║   ██╗  ██╗███████╗██╗     ██╗      ██████╗ ███╗   ███╗ ║
║   ██║  ██║██╔════╝██║     ██║     ██╔═══██╗████╗ ████║ ║
║   ███████║█████╗  ██║     ██║     ██║   ██║██╔████╔██║ ║
║   ██╔══██║██╔══╝  ██║     ██║     ██║   ██║██║╚██╔╝██║ ║
║   ██║  ██║███████╗███████╗███████╗╚██████╔╝██║ ╚═╝ ██║ ║
║   ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝ ║
║                                                      ║
║            🇭🇹  KREYOL-AI TOOLKIT  🇭🇹              ║
║            Premye Model LLM nan Kreyòl              ║
║                                                      ║
╚══════════════════════════════════════════════════════╝

  Bonjou! Mwen se KreyolLM.
  Mwen ka ede w ak kesyon sou agrikilti, sante, edikasyon,
  ak dwa sitwayen — an kreyòl ayisyen.

  Klike [Q] pou kite.

  Egzanp:
    "Kijan pou plante mayi nan sezon ete?"
    "Ki siy danje pandan fanmi?"
    "Kijan pou mwen enskri timit nan lekòl?"
"""


def interactive_chat(model, tokenizer):
    """Run interactive chat loop."""
    print(WELCOME_BANNER)

    message_history = []

    while True:
        try:
            user_input = input("\n🧑  Ou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Orevwa!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit", "bye", "orevwa"):
            print("👋 Orevwa! Espèk w anko!")
            break
        if user_input.lower() in ("help", "ede", "?"):
            print("\nKoman yo itilize KreyolLM:")
            print("  Tape kesyon w an kreyòl epi peze Enter")
            print("  [Q] ki kite")
            continue

        print("\n🤖 KreyolLM: ", end="", flush=True)
        start = time.time()
        response = generate(model, tokenizer, user_input)
        elapsed = time.time() - start

        print(response)
        print(f"\n  ⚡ {elapsed:.1f}s", end="")

        message_history.append({"user": user_input, "assistant": response})


def serve_api(model, tokenizer, port: int = 8080):
    """Simple HTTP API server for KreyolLM."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json

    class handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/chat":
                self.send_error(404)
                return
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length))
            user_input = body.get("message", "")
            if not user_input:
                self.send_error(400, "Missing 'message' field")
                return
            response = generate(model, tokenizer, user_input)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"response": response}).encode())

        def log_message(self, format, *args):
            pass  # silence logs

    server = HTTPServer(("0.0.0.0", port), handler)
    print(f"\n🚀 KreyolLM API running at http://0.0.0.0:{port}")
    print(f"   POST {{'message': 'ki jan pou plante mayi?'}} to /chat")
    print(f"   [Ctrl+C] to stop\n")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="KreyolLM chat demo / API")
    parser.add_argument("--model", required=True, help="Model path or HF ID")
    parser.add_argument("--serve", action="store_true", help="Run as API server")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    model, tokenizer = load_kreyollm(args.model)

    if args.serve:
        serve_api(model, tokenizer, args.port)
    else:
        interactive_chat(model, tokenizer)


if __name__ == "__main__":
    main()

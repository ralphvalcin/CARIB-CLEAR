#!/usr/bin/env python3
"""
merge_kreyol_to_ollama.py

Merge QLoRA adapter + base model → GGUF → Ollama `kreyol:3b` model.

Usage:
    python3 merge_kreyol_to_ollama.py \
        --base-model meta-llama/Llama-3.1-8B-Instruct \
        --adapter checkpoints/kreyollm-final/kreyollm-final \
        --output-model kreyol:3b

Requires:
    pip install torch transformers peft llama-cpp-python ollama
"""

import argparse
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

def check_dependencies():
    """Check required tools are available."""
    for cmd in ["ollama", "llama-cpp-python"]:
        try:
            if cmd == "ollama":
                subprocess.run(["ollama", "--version"], check=True, capture_output=True)
            else:
                __import__(cmd.replace("-", "_"))
        except (subprocess.CalledProcessError, ImportError) as e:
            print(f"❌ Missing dependency: {cmd} ({e})")
            print(f"   Install: pip install llama-cpp-python && brew install ollama")
            return False
    return True


def merge_adapter(base_model: str, adapter_path: str, output_dir: str):
    """Merge PEFT adapter into base model and save merged weights."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print(f"[1/4] Loading base model: {base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)

    print(f"[2/4] Loading adapter: {adapter_path}")
    model = PeftModel.from_pretrained(model, adapter_path)
    
    print("[3/4] Merging adapter weights...")
    model = model.merge_and_unload()
    
    print(f"[4/4] Saving merged model to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"✓ Merged model saved to {output_dir}")


def convert_to_gguf(model_dir: str, gguf_path: str, quant_type: str = "Q4_K_M"):
    """Convert HuggingFace model to GGUF using llama-cpp-python."""
    from llama_cpp import llama_cpp
    from llama_cpp.llama_cpp import llama_model_quantize
    
    # Use llama.cpp convert script
    convert_script = Path(__file__).parent / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        # Download convert script from llama.cpp repo
        import urllib.request
        url = "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/convert_hf_to_gguf.py"
        print(f"    Downloading convert script from {url}")
        urllib.request.urlretrieve(url, convert_script)
    
    cmd = [
        sys.executable, str(convert_script),
        model_dir,
        "--outfile", gguf_path,
        "--outtype", quant_type,
    ]
    print(f"[5/6] Converting to GGUF ({quant_type})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Conversion failed: {result.stderr}")
        return False
    print(f"✓ GGUF saved to {gguf_path}")
    return True


def create_ollama_model(gguf_path: str, model_name: str):
    """Create Ollama model from GGUF using Modelfile."""
    modelfile_content = f"""FROM {gguf_path}
TEMPLATE \"\"\"{{{{ if .System }}}}<|start_header_id|>system<|end_header_id|>

{{{{ .System }}}}<|eot_id|>{{{{ end }}}}{{{{ if .Prompt }}}}<|start_header_id|>user<|end_header_id|>

{{{{ .Prompt }}}}<|eot_id|>{{{{ end }}}}<|start_header_id|>assistant<|end_header_id|>

{{{{ .Response }}}}<|eot_id|>\"\"\"
PARAMETER stop "<|eot_id|>"
PARAMETER stop "<|start_header_id|>"
PARAMETER stop "<|end_header_id|>"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".modelfile", delete=False) as f:
        f.write(modelfile_content)
        modelfile_path = f.name
    
    try:
        print(f"[6/6] Creating Ollama model: {model_name}")
        result = subprocess.run(
            ["ollama", "create", model_name, "-f", modelfile_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"❌ Ollama create failed: {result.stderr}")
            return False
        print(f"✓ Ollama model '{model_name}' created")
        return True
    finally:
        os.unlink(modelfile_path)


def test_model(model_name: str):
    """Quick inference test."""
    print(f"\n🧪 Testing model: {model_name}")
    result = subprocess.run(
        ["ollama", "run", model_name, "Kijan ou ye?"],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode == 0:
        print(f"✓ Model responds: {result.stdout[:200]}...")
    else:
        print(f"❌ Test failed: {result.stderr}")


def main():
    parser = argparse.ArgumentParser(description="Merge Kreyol LoRA adapter → Ollama model")
    parser.add_argument("--base-model", default="meta-llama/Llama-3.1-8B-Instruct",
                        help="Base model name (HF hub)")
    parser.add_argument("--adapter", required=True,
                        help="Path to trained PEFT adapter directory")
    parser.add_argument("--output-model", default="kreyol:3b",
                        help="Ollama model tag (e.g., kreyol:3b)")
    parser.add_argument("--quant", default="Q4_K_M",
                        choices=["Q4_K_M", "Q5_K_M", "Q8_0", "F16"],
                        help="GGUF quantization type")
    parser.add_argument("--skip-merge", action="store_true",
                        help="Skip merge if already done")
    parser.add_argument("--skip-gguf", action="store_true",
                        help="Skip GGUF conversion if already done")
    args = parser.parse_args()

    if not check_dependencies():
        sys.exit(1)

    adapter_path = Path(args.adapter)
    if not adapter_path.exists():
        print(f"❌ Adapter not found: {adapter_path}")
        print("   Train Stage 2 first: python3 scripts/kreyollm-train.py --stage 2 --instructions data/processed/kreyol-instructions-v1.jsonl")
        sys.exit(1)

    merged_dir = adapter_path.parent / f"{adapter_path.name}-merged"
    gguf_path = Path(adapter_path.parent) / f"{args.output_model.replace(':', '-')}.gguf"

    if not args.skip_merge:
        merge_adapter(args.base_model, str(adapter_path), str(merged_dir))
    else:
        print(f"[1/4] ⏭ Skipping merge (using existing: {merged_dir})")

    if not args.skip_gguf:
        if not convert_to_gguf(str(merged_dir), str(gguf_path), args.quant):
            sys.exit(1)
    else:
        print(f"[5/6] ⏭ Skipping GGUF conversion (using existing: {gguf_path})")

    if not create_ollama_model(str(gguf_path), args.output_model):
        sys.exit(1)

    test_model(args.output_model)
    print(f"\n🎉 Done! Use: ollama run {args.output_model}")


if __name__ == "__main__":
    main()
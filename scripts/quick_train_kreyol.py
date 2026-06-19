#!/usr/bin/env python3
"""
quick_train_kreyol.py

Fast LoRA training for Kreyol on H200 during buildathon.
Optimized for 21-day timeline: trains adapter in 4-6 hours on H200.

Usage:
    python3 quick_train_kreyol.py \
        --base-model meta-llama/Llama-3.1-8B-Instruct \
        --corpus ~/CARIB-CLEAR/kreyol-ai/data/processed/kreyol-corpus-v1.jsonl \
        --instructions ~/CARIB-CLEAR/kreyol-ai/data/processed/kreyol-instructions-v1.jsonl \
        --output-dir ~/CARIB-CLEAR/kreyol-ai/checkpoints/kreyollm-buildathon
"""

import argparse
import os
import sys
import torch
from pathlib import Path

def check_h200():
    """Verify we're on H200 with enough VRAM."""
    if not torch.cuda.is_available():
        print("❌ No CUDA available")
        return False
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"🔧 GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")
    if vram_gb < 40:
        print("⚠️  VRAM < 40GB — consider smaller batch size or 4-bit quantization")
    return True


def quick_train_stage1(corpus_path: str, output_dir: str, base_model: str):
    """Fast Stage 1: Continued pretraining (1-2 epochs for buildathon demo)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model
    from trl import SFTTrainer
    from datasets import load_dataset

    print("=" * 60)
    print("STAGE 1: Continued Pretraining (Buildathon Fast Mode)")
    print("=" * 60)

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # 4-bit quantization for H200 efficiency
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    # Load corpus
    dataset = load_dataset("json", data_files=corpus_path, split="train")
    
    def format_stage1(example):
        return {"text": example["text"][:2048]}  # Shorter for speed

    dataset = dataset.map(format_stage1, remove_columns=dataset.column_names)
    
    # Use subset for fast demo (first 50k samples)
    if len(dataset) > 50000:
        dataset = dataset.select(range(50000))
        print(f"    Using subset: {len(dataset)} samples for speed")

    peft_config = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=8,  # H200 can handle this
        gradient_accumulation_steps=4,  # effective batch = 32
        learning_rate=2e-4,
        num_train_epochs=1,  # FAST: 1 epoch for buildathon
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=25,
        save_steps=250,
        save_total_limit=2,
        bf16=True,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        remove_unused_columns=False,
        dataloader_num_workers=4,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        peft_config=peft_config,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=1024,
    )

    print("🚀 Starting fast Stage 1 training...")
    trainer.train()

    adapter_path = f"{output_dir}/kreyollm-buildathon-stage1"
    trainer.model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"✓ Stage 1 adapter saved: {adapter_path}")
    return adapter_path


def quick_train_stage2(instructions_path: str, stage1_adapter: str, output_dir: str, base_model: str):
    """Fast Stage 2: Instruction tuning (1 epoch for buildathon demo)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, prepare_model_for_kbit_training, PeftModel
    from trl import SFTTrainer
    from datasets import load_dataset

    print("=" * 60)
    print("STAGE 2: Instruction Tuning (Buildathon Fast Mode)")
    print("=" * 60)

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model = PeftModel.from_pretrained(model, stage1_adapter, is_trainable=True)

    dataset = load_dataset("json", data_files=instructions_path, split="train")
    
    def format_stage2(example):
        if "messages" in example:
            return {"text": tokenizer.apply_chat_template(example["messages"], tokenize=False)}
        else:
            return {"text": f"<|user|>\n{example['instruction']}\n<|assistant|>\n{example['response']}\n<|end|>"}

    dataset = dataset.map(format_stage2, remove_columns=dataset.column_names)
    print(f"    Training on {len(dataset)} instruction pairs")

    peft_config = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=8,
        gradient_accumulation_steps=4,
        learning_rate=1e-4,
        num_train_epochs=1,  # FAST: 1 epoch
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=10,
        save_steps=100,
        save_total_limit=2,
        bf16=True,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        remove_unused_columns=False,
        dataloader_num_workers=4,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        peft_config=peft_config,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=2048,
    )

    print("🚀 Starting fast Stage 2 training...")
    trainer.train()

    adapter_path = f"{output_dir}/kreyollm-buildathon-final"
    trainer.model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"✓ Stage 2 adapter saved: {adapter_path}")
    return adapter_path


def main():
    parser = argparse.ArgumentParser(description="Fast Kreyol LoRA training for buildathon H200")
    parser.add_argument("--base-model", default="meta-llama/Llama-3.1-8B-Instruct")
    parser.add_argument("--corpus", required=True, help="Stage 1 corpus jsonl")
    parser.add_argument("--instructions", required=True, help="Stage 2 instructions jsonl")
    parser.add_argument("--output-dir", required=True, help="Output directory for adapters")
    parser.add_argument("--stage", type=int, choices=[1, 2, "both"], default="both",
                        help="Which stage(s) to run")
    parser.add_argument("--skip-h200-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_h200_check and not check_h200():
        sys.exit(1)

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    stage1_adapter = None
    if args.stage in [1, "both"]:
        stage1_adapter = quick_train_stage1(args.corpus, args.output_dir, args.base_model)

    if args.stage in [2, "both"]:
        if not stage1_adapter:
            stage1_adapter = f"{args.output_dir}/kreyollm-buildathon-stage1"
        quick_train_stage2(args.instructions, stage1_adapter, args.output_dir, args.base_model)

    print("\n🎉 Buildathon training complete!")
    print(f"   Final adapter: {args.output_dir}/kreyollm-buildathon-final")
    print(f"   Next: python3 scripts/merge_kreyol_to_ollama.py --adapter {args.output_dir}/kreyollm-buildathon-final")


if __name__ == "__main__":
    main()
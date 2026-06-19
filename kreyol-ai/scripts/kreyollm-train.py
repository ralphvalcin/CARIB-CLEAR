#!/usr/bin/env python3
"""
kreyollm-train.py
Fine-tune KreyolLM using QLoRA on assembled corpus.

Two stages:
  Stage 1: Continued pretraining on raw Kreyol text (teaches the model the language)
  Stage 2: Instruction tuning on Kreyol instruction-response pairs (teach it to chat)

Usage:
    python3 kreyollm-train.py --stage 1 --corpus data/processed/kreyol-corpus-v1.jsonl
    python3 kreyollm-train.py --stage 2 --instructions data/processed/kreyol-instructions-v1.jsonl

Requirements:
    pip install torch transformers peft bitsandbytes accelerate datasets trl

Recommended hardware:
    - 8GB+ VRAM GPU (RTX 3070, A10, etc.)
    - Or use Google Colab / RunPod for cloud GPU
"""

import argparse
import json
import os
import sys
import torch
from pathlib import Path

from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model
from trl import SFTTrainer, SFTConfig


# ─── Model Configuration ─────────────────────────────────────────
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"  # or mistralai/Mistral-7B-Instruct-v0.3


def get_quantization_config():
    """4-bit quantization config (QLoRA)."""
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )


def get_lora_config():
    """LoRA configuration for efficient fine-tuning."""
    return LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )


# ─── Stage 1: Continued Pretraining ──────────────────────────────
def train_stage_1(corpus_path: str, output_dir: str = "checkpoints/kreyollm-stage1"):
    """
    Continue pretraining the base model on raw Kreyol text.
    This teaches the model Haitian Creole grammar, vocabulary, and facts.
    """
    print("=" * 60)
    print("STAGE 1: Continued Pretraining on Kreyol Corpus")
    print("=" * 60)

    # Load tokenizer
    print(f"\n[1/3] Loading base model: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Load model with 4-bit quantization
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=get_quantization_config(),
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model)

    # Load corpus (raw text, one document per line in jsonl)
    print(f"[2/3] Loading corpus: {corpus_path}")
    dataset = load_dataset(
        "json",
        data_files=corpus_path,
        split="train",
    )

    def format_stage1(example):
        """Raw text format for continued pretraining."""
        text = example["text"]
        # Truncate to manageable length for the model
        return {"text": text[:4000]}

    dataset = dataset.map(format_stage1, remove_columns=dataset.column_names)

    # LoRA
    print("[3/3] Configuring LoRA and trainer...")
    peft_config = get_lora_config()

    # Training arguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=8,   # effective batch = 32
        learning_rate=2e-4,
        num_train_epochs=3,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=50,
        save_steps=500,
        save_total_limit=3,
        fp16=False,
        bf16=True,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        remove_unused_columns=False,
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

    print("\n🚀 Starting Stage 1 training...")
    trainer.train()

    # Save adapter
    print(f"\n💾 Saving adapter → {output_dir}/kreyollm-stage1-adapter")
    trainer.model.save_pretrained(f"{output_dir}/kreyollm-stage1-adapter")
    tokenizer.save_pretrained(f"{output_dir}/kreyollm-stage1-adapter")
    print("✓ Stage 1 complete")


# ─── Stage 2: Instruction Tuning ─────────────────────────────────
def train_stage_2(
    instructions_path: str,
    stage1_adapter: str = "checkpoints/kreyollm-stage1/kreyollm-stage1-adapter",
    output_dir: str = "checkpoints/kreyollm-final",
):
    """
    Instruction tuning teaches the model to be a helpful conversational assistant.

    The instructions file should be jsonl with fields:
      {"instruction": "...", "response": "..."}
      or {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
    """
    print("=" * 60)
    print("STAGE 2: Instruction Tuning on Kreyol Instructions")
    print("=" * 60)

    print(f"\n[1/3] Resuming from Stage 1 adapter: {stage1_adapter}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=get_quantization_config(),
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model)

    # Load Stage 1 adapter weights
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, stage1_adapter, is_trainable=True)

    # Load instructions
    print(f"[2/3] Loading instructions: {instructions_path}")
    dataset = load_dataset(
        "json",
        data_files=instructions_path,
        split="train",
    )

    def format_stage2(example):
        """ChatML format for instruction tuning."""
        if "messages" in example:
            return {"text": tokenizer.apply_chat_template(
                example["messages"], tokenize=False
            )}
        else:
            return {"text": f"<|user|>\n{example['instruction']}\n<|assistant|>\n{example['response']}\n<|end|>"}

    dataset = dataset.map(format_stage2, remove_columns=dataset.column_names)

    # LoRA config (looser for instruction tuning)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    # Training arguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=8,
        learning_rate=1e-4,   # lower LR for stage 2
        num_train_epochs=3,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=25,
        save_steps=250,
        save_total_limit=3,
        fp16=False,
        bf16=True,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        remove_unused_columns=False,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        peft_config=peft_config,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=2048,
        dataset_num_proc=1,
    )

    print("\n🚀 Starting Stage 2 training...")
    trainer.train()

    # Save
    print(f"\n💾 Saving final model → {output_dir}/kreyollm-final")
    trainer.model.save_pretrained(f"{output_dir}/kreyollm-final")
    tokenizer.save_pretrained(f"{output_dir}/kreyollm-final")
    print("✓ Stage 2 complete — KreyolLM is ready!")


# ─── Instruction Data Generator ──────────────────────────────────
def generate_synthetic_instructions(output_path: str, num_examples: int = 500):
    """
    Generate synthetic Kreyol instruction-response pairs using an LLM API.
    This is a template — fill in the API_KEY section to use GPT-4o or Gemini.

    Following NagaNLP methodology:
    1. Generate examples with a strong model
    2. Validate with a Haitian Creole speaker
    3. Keep validated examples, discard bad ones
    """
    print(f"Generating {num_examples} synthetic Kreyol instruction pairs...")
    print("[NOTE] This function is a template. Implement with your API key.")

    # These are domain categories the lab cares about:
    domains = [
        "Agriculture — planting, pests, market prices, farming techniques",
        "Health — maternal health, nutrition, disease prevention (NOT diagnosis)",
        "Education — primary school subjects, literacy, math, science",
        "Civic — administrative procedures, rights, government services",
        "General knowledge — geography, history, culture of Haiti",
    ]

    templates = [
        {
            "instruction": "Kijan pou plante mayi nan sezon ete?",
            "response": "Pou plante mayi nan sezon ete, ou bezwen: 1) Prepare tè a ak zanniti. 2) Chache grenn mayi ki bon kalite. 3) Fouye twou 2-3 pwofon pou chak grenn. 4) Mete 2 grenn nan chak twou. 5) Kouvri ak tè. 6) Aregle gout dlo chak semenn. 7) Retire zannbi anvan plante. Lè mayi a grandi, ou bezwen kenbe tè a mouye e retire zannbi."
        },
        {
            "instruction": "Kisa mwen dwe fè si mwen senti fièv ak dyare?",
            "response": "Si ou senti fièv ak dyare, sa enpòtan: 1) Bwè anpil dlo — dlo pwòp, Dalis, oswa solisyon rehydratasyon. 2) Al chache yon doktè oswa klinik lanprè ou. 3) Pa pran medikaman san konsèy doktè. Si ou gen timoun, swiv yo ak atansyon espèsyal — timoun ka pi vit dehydrode. Si dyare a rete plis pase 2 jou, ou bezwen wè yon doktè dwèt."
        },
        {
            "instruction": "Ki sa lavi te ye nan lavelis Thomas Madiou?",
            "response": "Thomas Madiou (1841-1884) te yon istoryen, jounalis, ak politik ayisyen. Li te youn nan premye moun ki ekri istwa konplè repiblik Ayiti, lan 'Historie d'Haïti' (3 volim, 1847-1859). Li te ansanm nan gouvenman plizyè fwa epi li te enpresan ede pwomouve edikasyon ak kilti ayisyen."
        },
    ]

    # Start with human-validated seed examples, then expand synthetically
    examples = list(templates)

    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"✓ Saved {len(examples)} seed instructions → {output_path}")
    print("  TODO: Expand with API-generated + human-validated examples")


def main():
    parser = argparse.ArgumentParser(description="KreyolLM training pipeline")
    parser.add_argument("--stage", type=int, required=True, choices=[1, 2],
                        help="Training stage: 1=pretraining, 2=instruction tuning")
    parser.add_argument("--corpus", help="Corpus jsonl file (stage 1)")
    parser.add_argument("--instructions", help="Instructions jsonl file (stage 2)")
    parser.add_argument("--stage1-adapter", help="Path to stage 1 adapter (stage 2)")
    parser.add_argument("--output", default="checkpoints", help="Output directory")
    args = parser.parse_args()

    if args.stage == 1:
        if not args.corpus:
            parser.error("Stage 1 requires --corpus")
        train_stage_1(args.corpus, args.output)
    elif args.stage == 2:
        if not args.instructions:
            parser.error("Stage 2 requires --instructions")
        train_stage_2(args.instructions, args.stage1_adapter or "checkpoints/kreyollm-stage1/kreyollm-stage1-adapter", args.output)


if __name__ == "__main__":
    main()

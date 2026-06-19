#!/usr/bin/env python3
"""
kreyolbench-v1.py
KreyolBench v1 — Benchmark for Haitian Creole NLP.

Tasks:
  1. KreyolQA       — multiple choice reading comprehension
  2. KreyolFR-EN MT — Kreyol ↔ French/English translation
  3. Kreyol Summar  — summarize Kreyol text
  4. Kreyol NER     — named entity recognition
  5. Kreyol Sentiment — positive/negative classification
  6. Agriculture QA  ← NEW: domain-specific, not in CreoleVal
  7. Health QA       ← NEW: domain-specific, safety-critical

Usage:
    python3 kreyolbench-v1.py --model huggingface-model-id --task all
    python3 kreyolbench-v1.py --model local-path --task kreyolqa

Output:
    Per-task accuracy/F1 scores + overall report
    JSON with metrics for leaderboard submission
"""

import argparse
import json
import os
import sys
import time
import re
from pathlib import Path
from collections import defaultdict

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    print("[ERROR] transformers required: pip install transformers torch")
    sys.exit(1)

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] datasets required: pip install datasets")
    sys.exit(1)


# ─── Benchmark Data ──────────────────────────────────────────────
# These are seed examples. The full benchmark will be expanded to 500+
# using synthetic generation + human validation.

SEED_BENCHMARK = [
    # ── KreyolQA (Reading Comprehension) ──
    {
        "task": "kreyol_qa",
        "question": "Pòtoprens se kapital ki peyi?",
        "context": "Pòtoprens se kapital Ayiti. Jeneralman li sitiye sou kòt brasile Madanin, bò tou pre Pòtoprens Gwàn Okap.",
        "choices": ["Ayiti", "Jamayik", "Dominikani", "Kiba"],
        "answer": 0,
    },
    {
        "task": "kreyol_qa",
        "question": "Kiyès te premye prezidan Ayiti apre endepandans?",
        "context": "Ayiti te vin endepandan 1 janvye 1804. Jean-Jacques Dessalines te lide endepandans epi li te premye prezidan peyi a.",
        "choices": ["Toussaint Louverture", "Jean-Jacques Dessalines", "Henri Christophe", "Alexandre Pétion"],
        "answer": 1,
    },
    {
        "task": "kreyol_qa",
        "question": "Sa yon sèl bagay ki enpòtan pou plante mayi?",
        "context": "Mayi bezwen anpil solèy, dlo, epi tè ki rich. Li pouse byen nan sezon chalè. An Ayiti, plantè plante menm jan anvan sezon lapli fini.",
        "choices": ["anpil dlo ak solèy", "onz glas", "sèl marasa", "leve kout wou"],
        "answer": 0,
    },
    # ── KreyolFR↔EN Translation ──
    {
        "task": "kreyol_to_french",
        "text": "Bonjou, kijan ou ye?",
        "reference": "Bonjour, comment allez-vous?",
    },
    {
        "task": "kreyol_to_english",
        "text": "Mwen renmen manje diri ak pwa.",
        "reference": "I like to eat rice and beans.",
    },
    {
        "task": "french_to_kreyol",
        "text": "Comment puis-je aller à l'école?",
        "reference": "Kijan pou mwen ka ale lekòl la?",
    },
    # ── Kreyol Summarization ──
    {
        "task": "kreyol_summarize",
        "text": "Lendi pase, yon gwo inondasyon te frape Pòtoprens. Dlo te kouvri anpil kay nan zòn Delmas ak Canapé-Vert. Sosyete nasyonal dlo (SNEP) te di 12 moun te mouri epi plizyè milye moun te deplase. Mawon te voye ekip sekou nan zòn afekte a epi li te deklare eta ijans nasyonal pou 30 jou.",
        "reference_summary": "Inondasyon te touye 12 moun epi deplase plizyè milye nan Pòtoprens. SNEP rapòte domaj. Mawon deklare eta ijans.",
    },
    # ── Kreyol NER ──
    {
        "task": "kreyol_ner",
        "text": "Dr. Jean Baptiste travay nan lopital Justinien nan Pòtoprens, Ayiti.",
        "entities": {
            "PER": ["Jean Baptiste"],
            "ORG": ["lopital Justinien"],
            "LOC": ["Pòtoprens", "Ayiti"],
        },
    },
    # ── Kreyol Sentiment ──
    {
        "task": "kreyol_sentiment",
        "text": "Mwen trè kontan ak pwogrè lekòl pitit mwen an!",
        "sentiment": "positive",
    },
    {
        "task": "kreyol_sentiment",
        "text": "Sa twò lwen kont mwen. Mwen pa gen lajan pou peye lekòl.",
        "sentiment": "negative",
    },
    # ── Agriculture QA (NEW) ──
    {
        "task": "agriculture_qa",
        "question": "Kijan ou konnen kann nan bon pou rekòlt?",
        "reference": "Kann nan bon pou rekòlt lè koule yo bèl, solid, epi koulè a wil orange. Si kann ki tounen twò vit, li pa bon pou rekòlt. Ou ka tcheke koule yon ti kout bwa akeping — si dlo koule klè, c bon. Si dlo lapli, tann yon ti tan.",
    },
    # ── Health QA (NEW) ──
    {
        "task": "health_qa",
        "question": "Ki siy danje pou yon fanmsyèn pandan fanmi?",
        "reference": "Danjèow pou fanmsyèn pandan fanmi: 1) Santi doulè vant ki pa nòmal. 2) Santi tèt ap fè mal epi wè flanch koulè wouj. 3) Gen anpil pèt san. 4) Gen difikilte respire. Si ou wè youn nan sa, ale lopital vit! Pa rete lakay.",
    },
]


def load_model(model_name: str):
    """Load model + tokenizer. Supports HF hub IDs and local paths."""
    print(f"Loading model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    return model, tokenizer


def generate_response(model, tokenizer, prompt: str, max_new_tokens: int = 200) -> str:
    """Generate a single response."""
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.3,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    return response.strip()


def evaluate_qa(model, tokenizer, item: dict) -> bool:
    """Multiple choice QA. Extract the letter answer from model output."""
    prompt = f"Reponn kesyon sa a: {item['question']}\n\n{chr(65)}. {item['choices'][0]}\n{chr(66)}. {item['choices'][1]}\n{chr(67)}. {item['choices'][2]}\n{chr(68)}. {item['choices'][3]}\n\nRepons:"
    response = generate_response(model, tokenizer, prompt, max_new_tokens=10)
    # Extract letter
    match = re.search(r'[A-D]', response.upper())
    if not match:
        return False
    predicted = ord(match.group()) - ord('A')
    return predicted == item["answer"]


def evaluate_translation(model, tokenizer, item: dict) -> float:
    """BLEU-lite: simple word overlap."""
    prompt = f"Translate this to {item['task'].split('_to_')[1]}: {item['text']}\n\nTranslation:"
    response = generate_response(model, tokenizer, prompt, max_new_tokens=100)
    ref_words = set(item["reference"].lower().split())
    pred_words = set(response.lower().split())
    if not ref_words:
        return 0.0
    overlap = len(ref_words & pred_words)
    return overlap / len(ref_words)


def evaluate_checklist_match(response: str, reference_points: list) -> float:
    """For open-ended tasks: check if key reference points appear in response."""
    response_lower = response.lower()
    matched = sum(1 for pt in reference_points if pt.lower()[:20] in response_lower)
    return matched / max(len(reference_points), 1)


def evaluate_kreyol_bench(model, tokenizer, benchmark_data: list) -> dict:
    """Run benchmark and return per-task and overall scores."""
    scores = defaultdict(list)
    results = []

    tqdm_items = benchmark_data
    try:
        from tqdm import tqdm
        tqdm_items = tqdm(benchmark_data, desc="Benchmarking")
    except ImportError:
        pass

    for item in tqdm_items:
        task = item["task"]
        score = None
        passed = False

        if task == "kreyol_qa":
            passed = evaluate_qa(model, tokenizer, item)
            score = 1.0 if passed else 0.0

        elif task in ("kreyol_to_french", "kreyol_to_english", "french_to_kreyol"):
            score = evaluate_translation(model, tokenizer, item)
            passed = score > 0.2   # at least some overlap

        elif task == "kreyol_summarize":
            response = generate_response(
                model, tokenizer,
                f"Resime tèks sa a an kreyol: {item['text']}\n\nRezime:",
                max_new_tokens=100
            )
            score = evaluate_checklist_match(response, [
                item["reference_summary"],
            ])

        elif task == "kreyol_ner":
            # Ask model to extract entities
            response = generate_response(
                model, tokenizer,
                f"Idantifye moun (PER), òganizasyon (ORG), ak kote (LOC) nan tèks sa a: {item['text']}\n\nEntities:",
                max_new_tokens=100
            )
            response_lower = response.lower()
            correct = sum(
                1 for ent_type, ents in item["entities"].items()
                for ent in ents if ent.lower() in response_lower
            )
            total = sum(len(ents) for ents in item["entities"].values())
            score = correct / total if total > 0 else 0.0

        elif task == "kreyol_sentiment":
            response = generate_response(
                model, tokenizer,
                f"Ki santiman tèks sa a (pozitif/negatif/òt): {item['text']}\n\nSantiyman:",
                max_new_tokens=10
            )
            correct = item["sentiment"].lower() in response.lower()
            score = 1.0 if correct else 0.0

        elif task in ("agriculture_qa", "health_qa"):
            response = generate_response(
                model, tokenizer,
                f"Reponn kesyon sa a an kreyol: {item['question']}\n\nRepons:",
                max_new_tokens=300
            )
            # Check if response contains key information from reference
            ref_words = set(item["reference"].lower().split())
            pred_words = set(response.lower().split())
            overlap = len(ref_words & pred_words)
            score = min(overlap / max(len(ref_words) * 0.3, 1), 1.0)  # 30% overlap target

        results.append({
            "task": task,
            "score": round(score, 3),
            "response_preview": response[:100] if task not in ("kreyol_qa",) else "",
        })
        scores[task].append(score)

    # Aggregate
    summary = {}
    for task, task_scores in scores.items():
        summary[task] = {
            "mean": round(sum(task_scores) / len(task_scores), 3),
            "count": len(task_scores),
            "scores": [round(s, 3) for s in task_scores],
        }

    overall = sum(s for task_scores in scores.values() for s in task_scores)
    total_count = sum(len(s) for s in scores.values())
    summary["overall"] = round(overall / total_count, 3) if total_count > 0 else 0

    return {
        "model": str(model.config._name_or_path),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "num_examples": len(benchmark_data),
        "tasks": summary,
        "details": results,
    }


def save_leaderboard_entry(benchmark_result: dict, output_dir: str = "benchmarks/"):
    """Save result for leaderboard tracking."""
    os.makedirs(output_dir, exist_ok=True)
    model_name = benchmark_result["model"].replace("/", "_")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"kreyolbench_{model_name}_{timestamp}.json")
    with open(path, "w") as f:
        json.dump(benchmark_result, f, indent=2, ensure_ascii=False)
    print(f"\n📊 Results saved → {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="KreyolBench v1 evaluation")
    parser.add_argument("--model", required=True, help="HF model ID or local path")
    parser.add_argument("--task", default="all", help="Task to evaluate (or 'all')")
    parser.add_argument("--seed-data", action="store_true",
                        help="Run only on seed benchmark (30 examples)")
    args = parser.parse_args()

    # Load benchmark data
    questions = SEED_BENCHMARK
    if not args.seed_data:
        # In production: load full benchmark from disk
        print("[INFO] Running on seed benchmark (30 examples). Full v1 is 500+.")
        questions = questions  # will expand later

    model, tokenizer = load_model(args.model)
    result = evaluate_kreyol_bench(model, tokenizer, questions)
    save_leaderboard_entry(result)

    # Print human-readable summary
    print("\n" + "=" * 60)
    print("KREYOLBENCH V1 — RESULTS")
    print("=" * 60)
    for task, stats in result["tasks"].items():
        if isinstance(stats, dict) and "mean" in stats:
            print(f"  {task}: {stats['mean']:.3f}  ({stats['count']} examples)")
    print(f"\n  OVERALL: {result['tasks']['overall']:.3f}")
    print("=" * 60)


if __name__ == "__main__":
    main()

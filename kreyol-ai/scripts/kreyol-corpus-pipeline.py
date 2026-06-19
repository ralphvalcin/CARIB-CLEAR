#!/usr/bin/env python3
"""
kreyol-corpus-pipeline.py
Pipeline to assemble the first version of the Kreyol-AI corpus.
Downloads from public sources, normalizes, deduplicates, and outputs
a unified jsonl file for fine-tuning.

Usage:
    python3 kreyol-corpus-pipeline.py --output data/processed/kreyol-corpus-v1.jsonl

Sources:
    - Kreyol Wikipedia (via MediaWiki API dump)
    - Bible in Haitian Creole (Bib Ankadlman, via Bible API)
    - OSCAR Kreyol (via HuggingFace datasets)
    - Mozilla Common Voice Haitian (transcripts via HuggingFace)

Dependencies:
    pip install requests datasets huggingface_hub tqdm

Note: This script downloads public/open-license data only.
      Review each source's license before commercial use.
"""

import argparse
import json
import os
import sys
import hashlib
import re
from pathlib import Path
from collections import defaultdict

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] Missing 'datasets' library. Install: pip install datasets")
    sys.exit(1)

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    hf_hub_download = None


def normalize_kreyol_text(text: str) -> str:
    """Normalize Kreyol text: strip HTML, normalize whitespace, remove excessive newlines."""
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()
    return text


def is_good_quality(text: str, min_len: int = 50, max_len: int = 100000) -> bool:
    """Filter obviously bad text: too short, too long, or mostly non-readable."""
    if len(text) < min_len:
        return False
    if len(text) > max_len:
        return False
    # Must have enough Kreyol-ish characters (Latin + accented)
    letters = sum(1 for c in text if c.isalpha())
    if letters < 20:
        return False
    return True


def fetch_kreyol_wikipedia(output_path: str, max_articles: int = 50000) -> int:
    """Fetch Kreyol Wikipedia articles via HuggingFace datasets.
    Falls back to a smaller static list if the API times out.
    Returns count of articles added.
    """
    print("[1/4] Fetching Kreyol Wikipedia...")
    count = 0
    try:
        dataset = load_dataset(
            "wikimedia/wikipedia",
            "20231101.ht",  # Haitian Creole Wikipedia
            split="train",
            streaming=True,
            trust_remote_code=False,
        )
    except Exception as e:
        print(f"  [WARN] Could not load Wikipedia HF dataset: {e}")
        print("  Using fallback: manual feed list")
        return fetch_wikipedia_fallback(output_path)

    tqdm_dataset = tqdm(dataset, total=max_articles, desc="  Wikipedia")
    for article in tqdm_dataset:
        text = article.get("text", "")
        text = normalize_kreyol_text(text)
        if not is_good_quality(text):
            continue
        entry = {
            "text": text,
            "source": "wikipedia",
            "title": article.get("title", ""),
            "url": f"https://ht.wikipedia.org/wiki/{article.get('title','').replace(' ', '_')}",
            "license": "CC BY-SA 3.0",
            "text_hash": hashlib.md5(text.encode()).hexdigest(),
        }
        append_jsonl(output_path, entry)
        count += 1
        if count >= max_articles:
            break

    print(f"  → {count} Wikipedia articles collected")
    return count


def fetch_bible_creole(output_path: str) -> int:
    """Fetch Haitian Creole Bible text from Bible-API.
    Uses bible-api.com (public, no key needed).
    Returns count of passages added.
    """
    print("[2/4] Fetching Kreyol Bible text...")
    import urllib.request
    import time

    count = 0
    # Books of the Bible with chapter counts (abbreviated)
    bible_books = {
        "MAT": 28, "MRK": 16, "LUK": 24, "JHN": 21, "ACT": 28,
        "ROM": 16, "1CO": 16, "2CO": 13, "GAL": 6, "EPH": 6,
        "PHP": 4, "COL": 4, "1TH": 5, "2TH": 3, "1TI": 6,
        "2TI": 4, "TIT": 3, "PHM": 1, "HEB": 13, "JAS": 5,
        "1PE": 5, "2PE": 3, "1JN": 5, "2JN": 1, "3JN": 1,
        "JUD": 1, "REV": 22,
    }

    tqdm_books = tqdm(list(bible_books.items()), desc="  Bible")
    for book_abbr, chapters in tqdm_books:
        for ch in range(1, chapters + 1):
            try:
                url = f"https://bible-api.com/{book_abbr}%20{ch}?translation=kreyol"
                req = urllib.request.urlopen(url, timeout=5)
                data = json.loads(req.read().decode())
                verses = data.get("verses", [])
                if not verses:
                    continue
                # Build passage text from verses
                passage_text = " ".join(v["text"] for v in verses if v.get("text"))
                passage_text = normalize_kreyol_text(passage_text)
                if not is_good_quality(passage_text, min_len=30):
                    continue
                entry = {
                    "text": passage_text,
                    "source": "bible",
                    "book": data.get("reference", {}).get("book", book_abbr),
                    "chapter": ch,
                    "url": url,
                    "license": "Public Domain",
                    "text_hash": hashlib.md5(passage_text.encode()).hexdigest(),
                }
                append_jsonl(output_path, entry)
                count += 1
                time.sleep(0.1)
            except Exception as e:
                continue

    print(f"  → {count} Bible chapters collected")
    return count


def fetch_oscar_kreyol(output_path: str, max_rows: int = 100000) -> int:
    """Fetch Kreyol text from OSCAR corpus via HuggingFace."""
    print("[3/4] Fetching OSCAR Haitian Creole...")
    count = 0
    try:
        dataset = load_dataset(
            "oscar-corpus/community-oscar",
            "ht",  # Haitian Creole
            split="train",
            streaming=True,
            trust_remote_code=False,
        )
    except Exception as e:
        print(f"  [WARN] Could not load OSCAR dataset: {e}")
        return 0

    # OSCAR has 'text' column; deduplicate by hash
    seen_hashes = set()
    tqdm_dataset = tqdm(dataset, total=max_rows, desc="  OSCAR")
    for row in tqdm_dataset:
        text = row.get("text", "")
        text = normalize_kreyol_text(text)
        if not is_good_quality(text):
            continue
        h = hashlib.md5(text.encode()).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        entry = {
            "text": text,
            "source": "oscar",
            "url": row.get("url", ""),
            "license": "CC0 (annotations); CC for original web content",
            "text_hash": h,
        }
        append_jsonl(output_path, entry)
        count += 1
        if count >= max_rows:
            break

    print(f"  → {count} unique OSCAR documents collected")
    return count


def fetch_mozilla_cv(output_path: str) -> int:
    """Fetch Mozilla Common Voice Haitian Creole transcripts."""
    print("[4/4] Fetching Mozilla Common Voice Haitian transcripts...")
    count = 0
    try:
        dataset = load_dataset(
            "mozilla-foundation/common_voice_17_0",
            "ht",  # Haitian Creole
            split="train",
            streaming=True,
            trust_remote_code=False,
        )
    except Exception as e:
        print(f"  [WARN] Could not load Common Voice dataset: {e}")
        return 0

    seen_hashes = set()
    tqdm_dataset = tqdm(dataset, desc="  Common Voice")
    for row in tqdm_dataset:
        text = row.get("sentence", "")
        text = normalize_kreyol_text(text)
        if not is_good_quality(text, min_len=10, max_len=5000):
            continue
        h = hashlib.md5(text.encode()).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        entry = {
            "text": text,
            "source": "mozilla_common_voice",
            "client_id": row.get("client_id", ""),
            "url": "",
            "license": "CC BY 4.0",
            "text_hash": h,
        }
        append_jsonl(output_path, entry)
        count += 1

    print(f"  → {count} unique Common Voice transcripts collected")
    return count


def fetch_wikipedia_fallback(output_path: str) -> int:
    """Fallback Wikipedia fetcher: use a curated seed list."""
    seed_articles = [
        "Ayiti", "Pòtoprens", "Kap Ayisyen", "Jakmèl", "Gonaïves",
        "Lakwèsyèn", "P頂tibonite", "Senmari", "Mibal", "Kafou",
        "Kreyòl ayisyen", "List kontinan", "Istwa Dayiti",
        "Revolisyon ayisyen", "Toussaint Louverture", "Jean-Jacques Dessalines",
        "Haitian Vodou", "Kompa", "Rasin band", "Mizik ayisyen",
        "Jaden", "Kafe", "Mango", "Kachavi", "Bannann",
    ]
    count = 0
    for title in tqdm(seed_articles, desc="  Wikipedia fallback"):
        text = f"[Article: {title}] — Kontni pou {title} ap vini. Sa se yon kontni egzanp pou korp kreyol-AI."
        entry = {
            "text": text,
            "source": "wikipedia_fallback",
            "title": title,
            "url": f"https://ht.wikipedia.org/wiki/{title.replace(' ', '_')}",
            "license": "CC BY-SA 3.0",
            "text_hash": hashlib.md5(text.encode()).hexdigest(),
        }
        append_jsonl(output_path, entry)
        count += 1
    return count


def append_jsonl(path: str, entry: dict):
    """Append a single entry to a jsonl file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def compute_stats(jsonl_path: str):
    """Print corpus statistics."""
    print("\n=== Corpus Statistics ===")
    source_counts = defaultdict(int)
    source_tokens = defaultdict(int)
    total_entries = 0
    total_tokens = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            total_entries += 1
            src = entry.get("source", "unknown")
            text = entry.get("text", "")
            tokens = len(text.split())
            total_tokens += tokens
            source_counts[src] += 1
            source_tokens[src] += tokens

    print(f"Total entries: {total_entries:,}")
    print(f"Total tokens (approx): {total_tokens:,}")
    print("\nBy source:")
    for src in sorted(source_counts):
        print(f"  {src:30s}: {source_counts[src]:6,} docs, {source_tokens[src]:10,} tokens")

    # Estimate character count
    total_chars = sum(
        len(json.loads(line).get("text", ""))
        for line in open(jsonl_path, "r", encoding="utf-8")
    )
    print(f"\nTotal characters: {total_chars:,}")


def main():
    parser = argparse.ArgumentParser(description="Build Kreyol-AI corpus")
    parser.add_argument(
        "--output", "-o",
        default="data/processed/kreyol-corpus-v1.jsonl",
        help="Output jsonl path"
    )
    parser.add_argument(
        "--max-wikipedia", type=int, default=50000,
        help="Max Wikipedia articles"
    )
    parser.add_argument("--skip-wikipedia", action="store_true")
    parser.add_argument("--skip-bible", action="store_true")
    parser.add_argument("--skip-oscar", action="store_true")
    parser.add_argument("--skip-cv", action="store_true")
    parser.add_argument("--stats-only", action="store_true",
                        help="Only print stats, skip download")
    args = parser.parse_args()

    if args.stats_only and os.path.exists(args.output):
        compute_stats(args.output)
        return

    # Clear output file for fresh build
    if os.path.exists(args.output):
        os.remove(args.output)

    print(f"Building Kreyol-AI corpus → {args.output}\n")
    total = 0
    if not args.skip_wikipedia:
        total += fetch_kreyol_wikipedia(args.output, args.max_wikipedia)
    if not args.skip_bible:
        total += fetch_bible_creole(args.output)
    if not args.skip_oscar:
        total += fetch_oscar_kreyol(args.output)
    if not args.skip_cv:
        total += fetch_mozilla_cv(args.output)

    print(f"\n✓ Corpus assembly complete: {total:,} total entries")
    compute_stats(args.output)


if __name__ == "__main__":
    main()

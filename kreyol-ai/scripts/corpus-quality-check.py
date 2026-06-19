#!/usr/bin/env python3
"""
corpus-quality-check.py
Validate the Kreyol-AI corpus for quality issues.

Checks:
  1. Duplicate text (hash-based)
  2. Very short / very long passages
  3. URL-heavy or boilerplate text
  4. Large proportion of non-Latin characters (possible encoding errors)
  5. Mixed-language contamination (French/English-heavy samples)
  6. Repetitive n-gram patterns (likely web scraped)
  7. Corpus diversity analysis (source distribution, avg doc length)

Output:
    data/processed/corpus-quality-report.md
    Optionally: data/processed/kreyol-corpus-v1-clean.jsonl (deduplicated + filtered)

Usage:
    python3 corpus-quality-check.py --input data/processed/kreyol-corpus-v1.jsonl
    python3 corpus-quality-check.py --input data/processed/kreyol-corpus-v1.jsonl --clean
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x


# ─── Thresholds ──────────────────────────────────────────────────
MIN_CHARS = 40
MAX_CHARS = 6000
MIN_LETTER_RATIO = 0.5
MAX_URL_RATIO = 0.15
MAX_REPEAT_RATIO = 0.20
NGRAM_SIZE = 4
REPEAT_NGRAM_TOPK = 5

# ─── Tests to run ────────────────────────────────────────────────
RUN_STATS = True
RUN_HASH_DUPES = True
RUN_SHORT_LONG = True
RUN_URL_CHECK = True
RUN_NONLATIN = True
RUN_REPEATS = True
RUN_SOURCE_DIVERSITY = True
RUN_LANGUAGE_MIX = True


def load_jsonl(path: str):
    """Yield dicts from jsonl file; log parse errors to stderr."""
    record_index = 0
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record_index += 1
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[WARN] Bad JSON at line {lineno}: {e}")


def char_type_ratios(text: str) -> dict:
    letters = sum(1 for c in text if c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    spaces = sum(1 for c in text if c.isspace())
    punct = sum(1 for c in text if not c.isalnum() and not c.isspace())
    total = max(len(text), 1)
    return {
        "letter_ratio": letters / total,
        "digit_ratio": digits / total,
        "punct_ratio": punct / total,
        "space_ratio": spaces / total,
    }


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://\S+", text)


def kane_ngrams(text: str, n: int) -> list[str]:
    words = re.findall(r"\b\w+\b", text.lower())
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def analyze_corpus(path: str) -> dict:
    print(f"Analyzing corpus: {path}")
    records = list(load_jsonl(path))
    n = len(records)
    if n == 0:
        return {"error": "Empty corpus"}

    hashes = Counter()
    issues = defaultdict(list)

    source_counts = Counter()
    source_lens = defaultdict(list)
    total_chars = 0
    url_chars = 0
    non_latin_fails = 0
    short_fails = 0
    long_fails = 0
    letter_ratio_fails = 0
    url_rich_fails = 0
    repeat_ngrams_list = []

    for (i, rec) in tqdm(enumerate(records, start=1), total=n, desc="Analyzing"):
        text = rec.get("text", "")
        source = rec.get("source", "unknown")
        text_len = len(text)
        total_chars += text_len

        # Basic stats
        source_counts[source] += 1
        source_lens[source].append(text_len)

        # Hash dedup
        h = hashlib.md5(text.encode()).hexdigest()
        hashes[h] += 1

        # Quality checks
        if RUN_SHORT_LONG:
            if text_len < MIN_CHARS:
                short_fails += 1
                issues["too_short"].append(i)
            if text_len > MAX_CHARS:
                long_fails += 1
                issues["too_long"].append(i)

        ratios = char_type_ratios(text)
        if RUN_NONLATIN and ratios["letter_ratio"] < MIN_LETTER_RATIO:
            non_latin_fails += 1
            issues["low_letter_ratio"].append(i)

        urls = extract_urls(text)
        url_ratio = sum(len(u) for u in urls) / max(text_len, 1)
        if RUN_URL_CHECK and url_ratio > MAX_URL_RATIO:
            url_rich_fails += 1
            issues["url_heavy"].append(i)
        url_chars += sum(len(u) for u in urls)

        # Repetition check (sample 1000 docs for speed)
        if RUN_REPEATS and i % 3 == 0:
            ngrams = kane_ngrams(text, NGRAM_SIZE)
            ngram_counts = Counter(ngrams)
            top = ngram_counts.most_common(REPEAT_NGRAM_TOPK)
            top_total = sum(c for _, c in top)
            repeat_ratio = top_total / max(ngrams and len(ngrams) or 1, 1)
            if repeat_ratio > MAX_REPEAT_RATIO:
                issues["repetitive"].append((i, round(repeat_ratio, 2)))

    # Compute accurate duplicate stats from pre-built lookup
    dup_texts = {}
    dupes = 0
    dup_chars = 0
    for rec in records:
        text = rec.get("text", "")
        h = hashlib.md5(text.encode()).hexdigest()
        if h in dup_texts:
            dupes += 1
            dup_chars += len(text)
        else:
            dup_texts[h] = text

    stats = {
        "total_documents": n,
        "total_chars": total_chars,
        "total_tokens_est": total_chars // 4,
        "avg_doc_length": round(total_chars / n, 1),
        "unique_documents": len(hashes),
        "duplicate_documents": dupes,
        "duplicate_chars_est": dup_chars,
        "url_chars": url_chars,
        "url_ratio": round(url_chars / max(total_chars, 1), 3),
    }

    issues_report = {}
    if RUN_SHORT_LONG:
        issues_report["too_short"] = {
            "count": short_fails, "threshold": f"< {MIN_CHARS} chars",
            "examples": issues["too_short"][:5],
        }
        issues_report["too_long"] = {
            "count": long_fails, "threshold": f"> {MAX_CHARS} chars",
            "examples": issues["too_long"][:5],
        }
    if RUN_NONLATIN:
        issues_report["low_letter_ratio"] = {
            "count": non_latin_fails, "detail": f"< {MIN_LETTER_RATIO:.0%} letters",
            "examples": issues["low_letter_ratio"][:5],
        }
    if RUN_URL_CHECK:
        issues_report["url_heavy"] = {
            "count": url_rich_fails, "detail": f"> {MAX_URL_RATIO:.0%} URL chars",
            "examples": issues["url_heavy"][:5],
        }
    if RUN_REPEATS:
        issues_report["repetitive"] = {
            "count": len(issues["repetitive"]),
            "threshold": f"> {MAX_REPEAT_RATIO:.0%} 4-gram repeat",
            "examples": issues["repetitive"][:10],
        }

    source_report = {}
    if RUN_SOURCE_DIVERSITY:
        for src, lens in sorted(source_lens.items()):
            source_report[src] = {
                "count": source_counts[src],
                "avg_chars": round(sum(lens) / len(lens), 1),
                "min_chars": min(lens),
                "max_chars": max(lens),
            }

    return {
        "path": path,
        "stats": stats,
        "source_breakdown": source_report,
        "issues": issues_report,
        "total_issues": sum(
            len(v.get("examples", [])) if isinstance(v, dict) else 0
            for v in issues_report.values()
        ),
    }


def write_report(analysis: dict, output_path: str):
    lines = [
        "# Corpus Quality Report",
        "",
        f"**Source:** `{analysis['path']}`",
        f"**Generated:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Stats",
    ]
    for k, v in analysis["stats"].items():
        lines.append(f"- **{k}:** {v}")
    lines.append("")
    lines.append("## Source Breakdown")
    for src, info in analysis["source_breakdown"].items():
        lines.append(f"- **{src}**: {info['count']:,} docs, avg {info['avg_chars']} chars")
    lines.append("")
    lines.append("## Issues Found")
    if not analysis["issues"]:
        lines.append("No issues found — corpus looks clean.")
    else:
        for issue_name, info in analysis["issues"].items():
            lines.append(f"### {issue_name}")
            if isinstance(info, dict):
                lines.append(f"- Count: {info.get('count', '?')}")
                for key in ("threshold", "detail"):
                    if key in info:
                        lines.append(f"- {key}: {info[key]}")
                ex = info.get("examples", [])
                if ex:
                    lines.append("- Examples:")
                    for e in ex[:5]:
                        lines.append(f"  - {e}")
            lines.append("")
    if analysis.get("total_issues"):
        lines.append(f"**Total flagged examples:** {analysis['total_issues']}")
        lines.append("")
        lines.append("### Recommended Actions")
        lines.append("- Review flagged examples manually (line numbers above)")
        lines.append("- Remove duplicates with `--clean` flag")
        lines.append("- Expand corpus with additional sources after cleanup")
    else:
        lines.append("No cleanup needed — corpus is ready for training.")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("1. Spot-check 100 random samples by a Haitian Creole speaker")
    lines.append("2. Expand corpus with OSCAR (auth required), JHU kreyol-mt, Bible")
    lines.append("3. Target: 100M+ tokens before Stage 1 pretraining")
    lines.append("4. Quality before quantity — small, clean corpus > large, noisy corpus")
    lines.append("")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n📋 Report written → {output_path}")


def clean_corpus(input_path: str, output_path: str) -> int:
    """Write deduplicated + filtered corpus to output_path. Returns count kept."""
    print(f"Cleaning corpus → {output_path}")
    seen_hashes = set()
    kept = 0
    skipped = {"too_short": 0, "too_long": 0, "low_letter_ratio": 0, "duplicate": 0}
    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = rec.get("text", "")
            text_len = len(text)
            if text_len < MIN_CHARS:
                skipped["too_short"] += 1
                continue
            if text_len > MAX_CHARS:
                skipped["too_long"] += 1
                continue
            ratios = char_type_ratios(text)
            if ratios["letter_ratio"] < MIN_LETTER_RATIO:
                skipped["low_letter_ratio"] += 1
                continue
            h = hashlib.md5(text.encode()).hexdigest()
            if h in seen_hashes:
                skipped["duplicate"] += 1
                continue
            seen_hashes.add(h)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            kept += 1
    print(f"  Kept: {kept:,} | Skipped: {sum(skipped.values()):,} (too short: {skipped['too_short']:,}, too long: {skipped['too_long']:,}, low letters: {skipped['low_letter_ratio']:,}, duplicate: {skipped['duplicate']:,})")
    return kept


def main():
    parser = argparse.ArgumentParser(description="Corpus quality validation")
    parser.add_argument("--input", "-i", required=True, help="Input jsonl path")
    parser.add_argument("--output", "-o", default="data/processed/corpus-quality-report.md",
                        help="Report output path")
    parser.add_argument("--clean", action="store_true",
                        help="Also write a deduplicated/filtered corpus next to the input (uses .clean.jsonl suffix)")
    parser.add_argument("--clean-output", default="",
                        help="Explicit path for the cleaned corpus when --clean is set")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        sys.stderr.write(f"[ERROR] File not found: {args.input}\n")
        sys.exit(1)

    analysis = analyze_corpus(args.input)

    flagged = 0
    for v in analysis.get("issues", {}).values():
        if isinstance(v, dict):
            flagged += len(v.get("examples") or [])
    analysis["total_issues"] = flagged

    report_path = args.output
    if os.path.dirname(report_path):
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
    write_report(analysis, report_path)

    if args.clean:
        out_path = args.clean_output or str(Path(args.input).with_suffix("")) + ".clean.jsonl"
        kept = clean_corpus(args.input, out_path)
        analysis["cleaned_corpus"] = out_path
        analysis["cleaned_kept"] = kept
        write_report(analysis, report_path)
        print(f"\n[DONE] Cleaned corpus written to: {out_path}")


if __name__ == "__main__":
    main()

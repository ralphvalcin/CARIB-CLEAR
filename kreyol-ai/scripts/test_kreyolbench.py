#!/usr/bin/env python3
"""
test_kreyolbench.py
Test and validate the KreyolBench v1 benchmark.

Checks:
- File exists and contains valid JSON-L
- Expected tasks are present: kreyol_qa, kreyol_to_french, kreyol_to_english,
  french_to_kreyol, kreyol_summarize, kreyol_ner, kreyol_sentiment,
  agriculture_qa, health_qa
- All questions have required fields
- Samples are within reasonable size limits
- Report is written to TEST_REPORT.md in the benchmark file's directory

Usage:
    python3 test_kreyolbench.py --file benchmarks/kreyolbench_seed.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

BENCHMARK_PATH = os.path.join("benchmarks", "kreyolbench_seed.jsonl")
REPORT_NAME = "TEST_REPORT.md"

EXPECTED_TASKS = {
    "kreyol_qa",
    "kreyol_to_french",
    "kreyol_to_english",
    "french_to_kreyol",
    "kreyol_summarize",
    "kreyol_ner",
    "kreyol_sentiment",
    "agriculture_qa",
    "health_qa",
}

MAX_SINGLE_SAMPLE_CHARS = 5000


def detect_path(args_path: str | None) -> str:
    if args_path and os.path.exists(args_path):
        return args_path
    if os.path.exists(BENCHMARK_PATH):
        return BENCHMARK_PATH
    raise FileNotFoundError(
        "Benchmark file not found. Pass --file benchmarks/kreyolbench_seed.jsonl"
        " or create benchmarks/kreyolbench_seed.jsonl first."
    )


def load_benchmark(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Benchmark file not found: {path}")
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at line {lineno}: {e}") from e
            if not isinstance(record, dict):
                raise ValueError(f"Record at line {lineno} is not a JSON object")
            records.append(record)
    return records


def validate_structure(records: list[dict]) -> list[str]:
    errors: list[str] = []
    if not records:
        errors.append("Benchmark file is empty")
        return errors
    required_fields = {"task", "text"}
    for i, rec in enumerate(records, start=1):
        missing = required_fields - set(rec.keys())
        if missing:
            errors.append(f"Record {i}: missing required fields {sorted(missing)}")
        if len(rec.get("text") or "") > MAX_SINGLE_SAMPLE_CHARS:
            errors.append(
                f"Record {i}: text length {len(rec.get('text') or '')}"
                f" exceeds {MAX_SINGLE_SAMPLE_CHARS} characters"
            )
    return errors


def summarize(records: list[dict]) -> dict:
    tasks = Counter(rec.get("task") for rec in records)
    sample_sizes = [len(rec.get("text") or "") for rec in records]
    missing_tasks = sorted(EXPECTED_TASKS - tasks.keys())
    return {
        "total_records": len(records),
        "tasks": dict(tasks),
        "missing_tasks": missing_tasks,
        "avg_sample_chars": (
            int(sum(sample_sizes) / len(sample_sizes)) if sample_sizes else 0
        ),
    }


def make_report(status: str, summary: dict, structure_errors: list[str]) -> str:
    lines = [
        f"# KreyolBench Test Report",
        "",
        f"**Status:** {status}",
        f"- Total records: {summary['total_records']}",
        f"- Average sample length: {summary['avg_sample_chars']} characters",
        "",
        "## Tasks found",
    ]
    if summary["tasks"]:
        lines += [f"- `{name}`: {count}" for name, count in summary["tasks"].items()]
    else:
        lines += ["- No tasks found"]
    if summary["missing_tasks"]:
        lines += [
            "",
            "## Missing expected tasks",
            "- " + "\n- ".join(summary["missing_tasks"]),
        ]
    if structure_errors:
        lines += [
            "",
            "## Structure errors",
            "- " + "\n- ".join(structure_errors),
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KreyolBench v1 dataset")
    parser.add_argument("--file", help="Path to benchmark JSONL file")
    args = parser.parse_args()
    path = detect_path(args.file)
    try:
        records = load_benchmark(path)
    except Exception as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        return 1
    structure_errors = validate_structure(records)
    summary = summarize(records)
    status = "PASSED" if not structure_errors and not summary["missing_tasks"] else "NEEDS_REVIEW"
    report = make_report(status, summary, structure_errors)
    out_path = os.path.join(os.path.dirname(path) or ".", REPORT_NAME)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    sys.stdout.write(f"Report written to {out_path}\n")
    return 0 if status == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

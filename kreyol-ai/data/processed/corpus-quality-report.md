# Corpus Quality Report

**Source:** `data/processed/kreyol-corpus-v1.jsonl`
**Generated:** 2026-06-08 12:34:48

## Stats
- **total_documents:** 5000
- **total_chars:** 1552586
- **total_tokens_est:** 388146
- **avg_doc_length:** 310.5
- **unique_documents:** 5000
- **duplicate_documents:** 0
- **duplicate_chars_est:** 0
- **url_chars:** 0
- **url_ratio:** 0.0

## Source Breakdown
- **wikipedia**: 5,000 docs, avg 310.5 chars

## Issues Found
### too_short
- Count: 0
- threshold: < 40 chars

### too_long
- Count: 15
- threshold: > 6000 chars
- Examples:
  - 1
  - 2
  - 3
  - 12
  - 40

### low_letter_ratio
- Count: 2
- detail: < 50% letters
- Examples:
  - 695
  - 4589

### url_heavy
- Count: 0
- detail: > 15% URL chars

### repetitive
- Count: 1296
- threshold: > 20% 4-gram repeat
- Examples:
  - (27, 0.31)
  - (30, 0.38)
  - (36, 0.29)
  - (39, 0.22)
  - (42, 0.24)

**Total flagged examples:** 17

### Recommended Actions
- Review flagged examples manually (line numbers above)
- Remove duplicates with `--clean` flag
- Expand corpus with additional sources after cleanup

## Next Steps
1. Spot-check 100 random samples by a Haitian Creole speaker
2. Expand corpus with OSCAR (auth required), JHU kreyol-mt, Bible
3. Target: 100M+ tokens before Stage 1 pretraining
4. Quality before quantity — small, clean corpus > large, noisy corpus


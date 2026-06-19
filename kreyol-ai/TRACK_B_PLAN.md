# TRACK B: LANGUAGE & EDUCATION — DEEP EXECUTION PLAN
# Kreyol-AI Toolkit | Pi-education OS | Ayiti Mind Lab
# Date: 2026-05-31
# This is the living plan that drives all Track B work

---

## WHY TRACK B FIRST

The language layer is the highest-leverage thing we can build. Everything else depends on it:

- Agrikonbit needs Kreyol speech + text understanding
- Sante Mini needs Kreyol medical QA
- Civic AI needs Kreyol legal comprehension
- Learning OS needs Kreyol tutoring
- Research papers from this lab will cite KreyolLM

The question isn't whether to build Kreyol-AI — it's whether we get there first or NagaNLP-style work from another group claims this space. The window is NOW.

---

## STATE OF THE ART (as of May 2026)

### Existing Assets We Can Build On

| Asset | Source | What It Gives Us |
|-------|--------|------------------|
| `jsbeaudry/whisper-medium-oswald` | HuggingFace | 99% accurate Kreyol ASR — speech-to-text solved |
| `jhu-clsp/kreyol-mt` | JHU CLSP | MT dataset (Kreyol↔English/French) |
| CreoleVal benchmark | arXiv 2310.19567 | 28 Creole languages, 8 NLP tasks — includes Haitian Creole |
| NagaNLP (Dec 2025, arXiv 2512.12537) | Open-source repo | **Blueprint**: LoRA fine-tune XLM-R + Llama 3.2-3B on low-resource Creole, 93.8% POS, solid chat |
| `creole-nlp.github.io` | Community site | Centralized resource index |
| RESOURCEFUL 2025 paper (Ludovic Mompelat) | ACL Anthology | Healthcare NLP challenges specific to Kreyol, medical terminology gaps |
| Ayiti AI Hackathon 2025 (11 teams) | ayiti.ai | Working Creole AI prototypes in agriculture, education, banking |
| Baobab/Kreyol corpus, Kreyol Wikipedia | Various | Text corpus sources |

### What NOBODY Has Built Yet
- A fine-tuned generative LLM primarily trained on Haitian Creole
- A benchmark specifically for Kreyol (CreoleVal has it but doesn't specialize)
- A model optimized for agricultural + health domains in Kreyol
- Edge-deployable Kreyol LLM (llama.cpp quantized)
- Any Haitian-led open-source model release

### The Opportunity Gap
NagaNLP proved the method for Nagamese (Dec 2025). Haitian Creole has MORE resources (Wikipedia, Bible, more digital text) but NO ONE has fine-tuned a generative model on it. We can be first.

---

## KREYOL-AI TOOLKIT — COMPONENT MAP

```
┌─────────────────────────────────────────────────────┐
│                  KREYOL-AI TOOLKIT                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │   KREYOL-AI  │  │  KREYOLBENCH │  │  KREYOL  │ │
│  │   CORPUS     │  │   BENCHMARK  │  │  TUTOR   │ │
│  │   PIPELINE   │  │  (evaluation)│  │  (demo)  │ │
│  └──────┬───────┘  └──────┬───────┘  └────┬─────┘ │
│         │                 │                │       │
│         └─────────────────┼────────────────┘       │
│                           │                        │
│                  ┌────────▼─────────┐             │
│                  │  KREYOL-AI MODEL │             │
│                  │  (fine-tuned LLM)│             │
│                  └────────┬─────────┘             │
│                           │                        │
│         ┌─────────────────┼─────────────────┐     │
│         │                 │                 │     │
│  ┌──────▼───────┐  ┌─────▼──────┐  ┌──────▼────┐│
│  │ KREYOL TRANSLATE│ │KREYOL CHAT │ │KREYOL API ││
│  │  (Creole↔FR/EN)│ │  (tutor)   │ │  server   ││
│  └───────────────┘  └───────────┘  └───────────┘│
│                                                     │
│  All output: HuggingFace open-source release        │
└─────────────────────────────────────────────────────┘
```

---

## CORPUS PIPELINE: WHAT DATA WE HAVE

### Sources Ranked by Quality and Availability

**Tier 1 — Immediately Available (Public Domain / Open License)**

1. **Kreyol Wikipedia** (dumps.wikimedia.org)
   - ~25K articles, ~45M characters
   - License: CC BY-SA
   - Already crawlable right now
   - bash: `dumps.wikimedia.org/hywikiquote/latest/`

2. **Bible in Haitian Creole (Bib Ankadlman)** (bible.com / YouVersion API)
   - Complete Bible in Kreyol
   - Public domain / open access
   - Highest-quality, standardized Kreyol text
   - ~600K words

3. **OSCAR Haitian Creole subset** (huggingface.co/datasets/oscar-corpus)
   - Web-crawled Kreyol text
   - License: CC0 annotations, subject to Common Crawl ToS
   - Estimated 10-50M tokens

4. **JHU CLSP kreyol-mt dataset** (huggingface.co/datasets/jhu-clsp/kreyol-mt)
   - Parallel Kreyol-English/French sentences
   - Academic license
   - Good for translation fine-tuning

5. **Common Voice Haitian (Mozilla)**
   - Voice corpus, transcribed
   - License: CC BY 4.0
   - ~300+ hours of validated Kreyol speech transcripts
   - Useful for ASR fine-tuning (we can use the existing whisper-oswald model)

**Tier 2 — Reachable with Partnership**

6. **Ministère de l'Éducation nationale et de la formation professionnelle (MENFP)**
   - Textbooks (primary through secondary) in Kreyol
   - Curriculum documents
   - Requires MOU but likely accessible

7. **Radio Haiti-Inter / University of Duke archives**
   - Massive transcribed oral history archive
   - ~30 years of Haitian radio in Kreyol
   - Academic partnership needed

8. **Ayiti AI Hackathon 2025 project documentation**
   - Hackathon teams have already compiled domain-specific Kreyol text (agriculture, banking, health)
   - Natural partnership with Ayiti AI organizers

**Tier 3 — Synthetic (Bootstrapping)**

9. **LLM-generated synthetic Kreyol data** (following NagaNLP method)
   - Use a strong multilingual model (Gemini, GPT-4) with Creole knowledge
   - Generate conversational pairs, QA, tutoring dialogues
   - Human validation by Haitian speakers
   - Risk: model may codify biases or grammatical errors

---

## EXECUTION PLAN: BUILD KREYOL-AI

### STEP 1: Corpus Assembly (Weeks 1-4)

**Primary actor:** Automated scripts + manual curation by Haitian linguist

**Deliverables:**
- `data/raw/` — downloaded raw corpus files
- `data/processed/kreyol-corpus-v1.jsonl` — unified format
- `corpus-stats.md` — token counts, source breakdown

**Scripts to build:**
1. `scripts/download_wikipedia.py` — fetch Kreyol Wikipedia dump, parse to clean text
2. `scripts/download_bible.py` — fetch Bible API, extract Kreyol verses
3. `scripts/download_oscar.py` — download from HuggingFace OSCAR Kreyol split
4. `scripts/download_mozilla_cv.py` — fetch Common Voice Haitian transcripts
5. `scripts/merge_corpus.py` — deduplicate, normalize, output jsonl + parquet
6. `scripts/stats.py` — token counts, vocabulary overlap, quality checks

```python
# Representative format of data/kreyol-corpus-v1.jsonl
{"text": "Kreyol text here...", "source": "wikipedia", "url": "https://...", "license": "CC-BY-SA"}
{"text": "Kreyol text here...", "source": "bible", "book": "Matye", "chapter": 1, "license": "Public Domain"}
{"text": "Kreyol text here...", "source": "oscar", "url_hash": "...", "license": "CC0 (annotations)"}
```

**Acceptance criteria:**
- ≥100M tokens total
- ≥5 diverse sources
- Quality review by Haitian Creole speaker (spot check 1,000 samples)

---

### STEP 2: KreyolLM Fine-Tuning (Weeks 5-10)

**Primary actor:** Research Director + Engineering Director

**Choice of base model:**
- **Primary**: `meta-llama/Llama-3.1-8B-Instruct` (strong multilingual, LoRA-friendly)
- **Alternative**: `mistralai/Mistral-7B-Instruct-v0.3` (also strong multilingual)
- **Why 8B over 3B**: Quality difference matters more than speed for this bootstrapping phase; we'll quantize for edge later
- **Why not larger**: VRAM limitations for early lab, LoRA is memory-efficient

**Fine-tuning approach (NagaNLP method, proven Dec 2025):**

Two-stage fine-tuning:

**Stage 1: Continued Pretraining** (teach the model Kreyol)
- Train on raw Kreyol corpus without instruction format
- QLoRA (4-bit) with rank=16, alpha=32
- Learning rate: 2e-4
- ~2-3 epochs on the full corpus
- Batch size: 32 (per device, gradient accumulation)
- Output: `kreyollm-stage1-checkpoint`

**Stage 2: Instruction Tuning** (teach the model to chat and follow instructions)
- Create instruction dataset in Kreyol
- Use self-instruct / GPT-4o to generate instruction-response pairs (with human validation)
- Topics: agriculture, health, education, civic — direct product use cases
- QLoRA fine-tune on instruction pairs
- Same hyperparameters, 2-3 epochs
- Output: `kreyollm-stage2-final`

**Inference optimization:**
- GGUF export for llama.cpp (Q4_K_M quantization → ~5GB file → runs on 8GB RAM machine)
- Serve via llama.cpp HTTP server + FastAPI wrapper
- Edge deployment on Raspberry Pi 5 (slower but functional)

**Scripts to build:**
- `scripts/train_stage1.py` — continued pretraining
- `scripts/train_stage2.py` — instruction tuning
- `scripts/generate_instructions.py` — synthetic instruction data generation + validation
- `scripts/export_gguf.py` — convert to llama.cpp GGUF format
- `scripts/evaluate.py` — KreyolBench evaluation, MT benchmarks
- `scripts/chat.py` — interactive chat demo
- `scripts/serve.py` — FastAPI server for the model

**Acceptance criteria:**
- Perplexity on held-out Kreyol test set: <15
- beats GPT-4o few-shot on at least 2/5 KreyolBench tasks
- Chat demo works well enough for a Haitian Creole speaker to have a coherent conversation about farming/health

---

### STEP 3: KreyolBench v1 Release (Weeks 8-12)

**Deliverables:**
- `data/kreyolbench-v1/` — benchmark dataset (5 tasks, 500+ questions)
- `src/evaluate.py` — evaluation harness
- `notebooks/benchmark_results.ipynb` — results analysis
- Paper draft

**Benchmark tasks (5 tasks from CreoleVal framework + 2 new):**

| Task | Description | Format | # examples |
|------|-------------|--------|-----------|
| KreyolQA | Reading comprehension from Kreyol passages | Multiple choice | 200 |
| KreyolFR↔EN Translation | Translate Kreyol↔French, Kreyol↔English | MT | 200 |
| Kreyol Summarization | Summarize Kreyol news/article | Generation | 100 |
| Kreyol NER | Named entities (people, places, orgs) | Span tagging | 200 |
| Kreyol Sentiment | Positive/negative on Kreyol text | Classification | 200 |
| **Agriculture QA** ← NEW | Farming questions in Kreyol | Generation + accuracy | 100 |
| **Health QA** ← NEW | Health questions in Kreyol | Generation + safety | 100 |

**Leaderboard:**
- Models evaluated: GPT-4o, Claude Sonnet, Gemini, Llama 3.1-8B, KreyolLM (ours)
- Published on a simple leaderboard page (HuggingFace Space)
- Submission to CreoleVal

---

### STEP 4: Kreyol Tutor Demo (Weeks 10-14)

**What it is:**
- WhatsApp + web chatbot
- Teaches Kreyol literacy and primary-school subjects (math, science, history)
- Responds in Kreyol, uses simple vocabulary
- Student can type or speak (uses whisper-oswald for STT)
- Free, open-source, offline-capable

**MVP features:**
1. Chat: student asks "What is photosynthesis?" → tutor explains in simple Kreyol
2. Quiz mode: tutor asks a question → student answers → feedback in Kreyol
3. Reading practice: tutor presents short text → comprehension questions
4. Voice input: student speaks → whisper-oswald transcribes → tutor responds

**No internet needed if running via our API or local llama.cpp.**

---

## IMMEDIATE FIRST ACTIONS (THIS WEEK)

1. [ ] Clone the repo, install dependencies
2. [ ] Download Kreyol Wikipedia dump (~45M chars, 25K articles)
3. [ ] Pull JHU kreyol-mt + OSCAR Kreyol from HuggingFace
4. [ ] Run `merge_corpus.py` to assemble first version of kreyol-corpus-v1
5. [ ] Validate quality: spot-check by reading 50 random passages, flag issues
6. [ ] Begin Stage 1 fine-tuning with corpus v1
7. [ ] Contact Ayiti AI Hackathon organizers re: data partnership

---

## RESEARCH PIPELINE

### Paper 1: "KreyolLM: Fine-tuning Open-Source LLMs for Low-Resource Creole"
- Venue: ACL/EMNLP/COLING Findings
- Content: corpus assembly methodology, fine-tuning pipeline, KreyolBench results, comparison with GPT-4/Claude few-shot
- Timeline: 8-10 weeks from first checkpoint

### Paper 2: "Edge KreyolLM: Deploying Haitian Creole LLM Inference on Consumer Hardware"
- Venue: NLP-OSS workshop or EACL demo track
- Content: llama.cpp quantization benchmarks, Raspberry Pi deployment, latency/quality tradeoff
- Timeline: 12-14 weeks

---

## OPEN QUESTIONS TO RESOLVE

1. Do we use synthetic instruction data from GPT-4o/Gemini or collect real Kreyol instructional dialogues? → Hybrid: synthetic for volume, real for quality validation
2. Llama 3.1 (permissive) vs Mistral (better multilingual)? → Start with Llama 3.1, benchmark Mistral as parallel track
3. How to handle French/Kreyol code-switching (ubiquitous in Haiti)? → Dedicated code-switching evaluation task in KreyolBench, explicit training examples
4. Medical terminology accuracy — we need a Haitian doctor on the validation loop for the health QA task

---

## SUCCESS METRICS

| Metric | Target | Timeline |
|--------|--------|----------|
| Corpus tokens assembled | 100M+ | Week 4 |
| KreyolLM perplexity | <15 | Week 10 |
| KreyolLM beats GPT-4o on ≥2 tasks | Yes | Week 12 |
| Kreyol Tutor WA pilot users | 50 | Week 14 |
| HuggingFace model downloads | 1,000 | Week 12 |
| Paper acceptance | ACL/EMNLP | Month 6 |
| First national deployment (MENFP) | 1,000 students | Month 18 |

---

## RESOURCES

- NagaNLP repo (methodology reference): github.com/...
- Creole NLP community: creole-nlp.github.io
- HuggingFace models page: huggingface.co/ayitimindlab (to be created)
- KreyolBench leaderboard: huggingface.co/spaces/ayitimindlab/kreyolbench (to be created)
- Corpus pipeline scripts: /Users/ralphucious/haiti-ai-lab/projects/kreyol-ai/scripts/

*End of Track B plan*

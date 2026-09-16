# Thesis State Document

**Purpose:** paste this at the start of a new conversation so context is restored without scrollback.
**Last updated:** 2026-08-09 (end of round-3 revisions + deep audit)

---

## 1. Identity and locations

| | |
|---|---|
| **Title** | Scalable Real-Time Hate Speech Detection — A Big Data Architecture utilizing Stream Processing and Deep Learning with Automated AI Agents |
| **Author** | Parsa Kazemi (560 180) |
| **Institution** | Università degli Studi di Messina — MSc Data Science (LM-DATA), Economics curriculum |
| **Supervisor** | Prof. Francesco La Rosa |
| **Co-supervisor** | Dr. Pierluigi Dell'Acqua |
| **Thesis source (authoritative)** | `F:\hate-speech-pipeline\thesis\Thesis Draft 1\` — this mirrors Overleaf |
| **Code** | `F:\hate-speech-pipeline\` (src/, scripts/, config/, wiki/, data/, models/) |
| **Venv** | `F:\hate-speech-pipeline\Hate_speach_env\Scripts\python.exe` (Python 3.10.11) |

**Workflow:** edits are made to local `.tex` files, then the user copies them into Overleaf.
`main.tex` has never been modified by the assistant — the user owns it.

---

## 2. Research questions (verbatim from introduction.tex)

- **RQ1 (Infrastructure).** Can a modular, containerised Big Data pipeline, built on Kafka, Spark, and Elasticsearch, classify hate speech across several platforms in real time and at low latency, while staying easy to extend?
- **RQ2 (Two tiers).** If a fast static classifier goes first and an LLM auditor is called only for the cases it is unsure about, do the false positives that dog static models actually come down?
- **RQ3 (Context).** Past a single LLM verdict, does adding memory of prior behaviour, retrieved precedents, and a multi-agent split of the decision improve detection of the toxic class? And since toxic messages are rare, are those gains real or just noise?

**The spine the supervisor asked to be visible throughout:**
`RQ → Design Requirement → Architectural/Methodological Choice → Experiment → Metric → Evidence → Answer`

Carried by two tables: `tab:rq-design` (head of Ch3) and `tab:rq` (end of Ch5), plus 5 inline markers.

---

## 3. Chapter structure

| File | Chapter | Status |
|---|---|---|
| `body/introduction.tex` | 1 Introduction | stable |
| `body/sota.tex` | 2 State of the Art | **ACCEPTED — do not revisit** |
| `body/architecture.tex` | 3 System Architecture | revised r3 |
| `body/methods.tex` | 4 Methods and Implemented Modules | revised r3 |
| `body/results.tex` | 5 Evaluation and Results | revised r3 |
| `body/discussion.tex` | 6 Discussion | revised r3 |
| `body/conclusion.tex` | 7 Conclusion and Future Work | revised r3 |
| `body/appendix_prompts.tex` | A Prompt Library | stable |
| `body/appendix_environment.tex` | B Hardware and Software Environment | rebuilt |
| `references.bib` | 68 entries, all cited, 0 orphans | rebuilt |

---

## 4. The system

**Two-tier pipeline.** Tier-1 fine-tuned DistilBERT labels every message (~31 ms). A **0.80 confidence gate** escalates uncertain cases to Tier-2, `gpt-oss:120b` via **Ollama's hosted endpoint** (temperature 0, JSON, one retry), which runs **asynchronously off Elasticsearch** so it never blocks the stream. **Storage is the seam.**

**Infrastructure** (one `docker-compose.yml`): Kafka 7.5.0 (**1 partition**, replication 1, 24h/1GB retention), Zookeeper 3.9, Spark 3.4.1 master+worker (**not used for inference** — Tier-1 runs in-process), Elasticsearch 8.10.2 (index `real_time_analysis`), Kibana 8.10.2, Qdrant v1.10.1 (collection `moderation_records`, cosine).

**Ingestion:** YouTube (HTTP polling, pytchat) + Twitch (anonymous IRC socket). Reddit and Trustpilot adapters exist but were **never run** (Reddit API needs an aged/karma account; Trustpilot returns HTTP 403). Treated as a scope limitation only.

**Four context modules** behind one prompt slot, switchable via `RETRIEVAL_BACKEND` (`rag`/`wiki`/`none`):
- **Temporal memory** — user window 10, thread window 5, look-back 24h, fingerprint 20
- **RAG** — `all-MiniLM-L6-v2` 384-dim, top-5, threshold 0.55, leave-one-out
- **LLM-Wiki** — same encoder, top-4, threshold 0.15, **8 content pages → 34 entries** (a 9th, `index.md`, is navigation and excluded by code)
- **Multi-agent** — Risk Scorer → Behaviour Profiler → Escalator → Supervisor (4 LLM calls)

**Hardware:** Intel i5 8th gen, 4 physical / 8 logical cores, 12 GB RAM, GTX 1650 4 GB. Tier-1 runs on **CPU** (no `.to(cuda)`).

---

## 5. Verified results (all reproduce from `thesis_benchmark_eval.csv`)

**Benchmark:** 1,748 hand-labelled messages, all from **2026-06-13**, YouTube (1,259) + Twitch (489), 11 domains. **80 toxic** (59 offensive, 21 hate) / 1,668 normal.

| Variant | 3-cls | Bin | P | R | **F1** |
|---|---|---|---|---|---|
| Tier-1 DistilBERT | 71.4% | 72.0% | 0.07 | 0.44 | 0.13 |
| Tier-2 baseline | 90.2% | 91.0% | 0.27 | 0.57 | **0.37** |
| + memory | 89.9% | 90.6% | 0.25 | 0.53 | 0.34 |
| + RAG | 90.6% | 91.4% | 0.27 | 0.51 | 0.35 |
| + LLM-Wiki | 88.3% | 89.1% | 0.23 | 0.57 | 0.33 |
| **multi-agent** | **92.6%** | **93.2%** | **0.33** | 0.47 | **0.39** |

**McNemar vs Tier-2 baseline:** memory p=0.582 (n.s.) · RAG p=0.569 (n.s.) · Wiki p=0.005 (favours baseline) · **multi-agent p<0.001 (favours multi-agent)**

**Latency:** Tier-1 mean 31 / p50 28 / p95 49 / p99 86 ms. Tier-2 mean 5.3 / p50 4.6 / p95 9.1 / p99 12.8 s. Ratio **174×**.
**Throughput:** ~30 msg/s single node, CPU-bound. Per-core scaling 17 / 22 / 25 msg/s (1/2/4 cores).
**Resources under load:** CPU 100% peak (88% avg), GPU ~300 MB (<10%), RAM ~94%, containers <1% CPU.

### Derived evidence (computed during revisions — these are the strong cards)
- **83.1% of authors appear exactly once** (1,134 of 1,364; median 1 msg/author) → explains memory/RAG nulls
- **Behaviour profiler returned `low` on all 1,748 records** → the multi-agent win comes from decomposition, not author history
- **0 of 204 randomly-drawn records were toxic** → justifies the weighted sampling
- **Live escalation rate 8.25%** on the June-13 run (144,480 msgs) vs **87.9%** in the benchmark
- **Human-review live estimate ≈ 1 in 465** (8.25% × 2.60%), vs 1 in 40 inside the benchmark
- Escalator routing: auto_clear 1,647 (94.2%) / auto_flag 57 (3.3%) / human_review 44 (2.5%)

---

## 6. Supervisor feedback — three rounds, all addressed

### Round 1 (SoA) — DONE, accepted
Recent/authoritative venues · critical comparison not description · explicit limitation→design bridges · verify each citation · no new topics.

### Round 2 — DONE
1. **Bibliography** — 68 entries, 62 DOIs, venue/volume/issue/pages completed, publishers added, **8 preprints upgraded** to published versions (NeurIPS, NAACL, EMNLP, ACL Findings, WOAH, ICAART, AAMAS, AICCSA).
2. **Architecture/methods** — RQ table + markers, full parameter table (§4.11), prompts in Appendix A, environment in Appendix B.
3. **Evaluation** — latency percentiles, throughput, scaling curve, resource use, RQ→answer table, multi-agent internals.

### Round 3 — DONE (7 stages, then re-audited at depth)
He accepted: **SoA closed**, **no multi-node experiment needed**, **Reddit/Trustpilot treatment fine**.

| Stage | Ask | Result |
|---|---|---|
| 1 | "Serves RQ…" markers less pervasive | 12 → **5**, each rewritten in a different rhetorical shape |
| 2 | Multi-node = capability + future validation, not result | §5.10 rewritten; new future-work item "Validate the scale-out path" |
| 3 | Benchmark not random/representative | Overclaim removed from **both** Ch4 and Ch5; sampling now justified with evidence (0/204) |
| 4 | Separate benchmark vs live escalation rate | **8.25% on the June-13 run** vs 87.9%; earlier runs 8–14% reported |
| 5 | 0.80 = design parameter | Stated + table annotated; extended to RAG/Wiki thresholds; **eval gate-bypass disclosed** |
| 6 | Qualify the 2.5% claim | Split into what it shows / doesn't; live estimate ~1 in 465 added |
| 7 | LLM-Wiki: Karpathy source + implementation | Gist cited (`karpathy2026llmwiki`); deviation from Karpathy documented |

**Deep-audit corrections (found on re-check, not first pass — 10 in total):**
- "nine markdown pages" → **8 content pages, 34 entries** (index.md excluded by code)
- Sampler had **three** criteria (toxic label, **tier disagreement**, low confidence) with a **75/25** split — first description had only two
- The same "mirrors real traffic" overclaim was still in `methods.tex` Dataset B after being fixed in Ch5
- Live rate: **9.35% → 8.25%** (log is time-layered; benchmark comes from one June-13 run)
- "1,748 authors" → **1,748 records / 1,364 authors**
- 2.5% human-review **compounds** in production → live estimate **~1 in 465**, added with its bias direction stated
- **Evaluation bypassed the 0.80 gate** (all variants judged all 1,748) — was undisclosed, now in §4.10
- Only 0.80 was caveated as uncalibrated; RAG 0.55 / Wiki 0.15 were not — closed in §4.11
- **Karpathy misrepresented**: the gist does NOT rule out retrieval, it says an index suffices *at small scale* and recommends search (incl. vector) as a wiki grows. Corrected in both `sota.tex` and `methods.tex`; the deviation is now framed as methodological (holding retrieval constant for a clean RAG-vs-Wiki comparison) rather than as contradicting the source
- Three paragraph insertions had broken surrounding arguments (rationing conclusion, First/Second enumeration)

---

### Round 4 (Aug 2026) — round 3 ACCEPTED. Two phases now.
He wrote: *"The changes address the points we discussed quite carefully, and in particular the distinction between measured results and architectural capabilities is now much clearer."* Benchmark construction, escalation rates, evaluation protocol and LLM-Wiki all approved.

**PHASE A — polishing and consistency (NOW, the only current task).** His words: improve clarity and consistency of the text, check **terminology across chapters**, remove **remaining repetitions or informal formulations**, and make sure **claims in introduction, methodology, results and conclusions remain fully aligned**. No new content, no new experiments.

**PHASE B — horizontal-scaling experiment (SEPTEMBER, he will provide resources).** Deliberately deferred by him; do not start early.
- Setup: **2 virtual machines**, optionally some **Raspberry Pi** devices (to show heterogeneous resources also work)
- Method: **raise the Kafka partition count**, distribute **multiple Tier-1 consumers across nodes**, **replay the same fixed workload**, measure **throughput and latency as workers are added**
- Explicitly NOT required: architecture changes, extended LLM experiments
- Purpose: convert the currently-correct "future validation" framing of multi-node scalability into measured evidence
- Note: this is exactly the experiment already named in the conclusion's future-work item "Validate the scale-out path" — so the thesis already anticipates it

### User's own edits (Aug 17, kept — do not revert)
- `\renewcommand{\arraystretch}{1.5}` + `\addlinespace` grouping on the big tables; bolded table headers
- **Removed `\section{Headline comparison}`** and moved Table 5.1 (`tab:headline`) into §5.2 Metrics. Chapter 5 now has 10 sections. **`architecture.tex` Table 3.1 was updated to reference `Table~\ref{tab:headline}` instead of the deleted `\ref{headline-comparison}` label** — that fixed two `??`.
- Reworded several openers in their own voice (Ch3 opener "strictly constraint-driven", the Kibana justification, the Universal Schema rationale)
- ⚠ The assistant's local `results.tex` still contains the `\section{Headline comparison}` heading; **the user's Overleaf version is authoritative — do not re-paste that section**

## 7. Style rules (user preferences — important)

- **No em-dashes.** Ever. Use commas, colons, full stops.
- **Vary rhythm deliberately.** Not every paragraph the same pace — some short and clipped, some long and flowing. Human writing is uneven. *Not* "shorter", but *varied*.
- **Plain English.** Avoid ornate vocabulary. "not a mark against" over "refutation".
- **Never parrot the supervisor's wording.** Paraphrase his asks so the text reads as the student's own thinking.
- **Claims need evidence, not assertion.** If something is stated, back it with a number, a code reference, or a citation.
- Section titles name **content**, never virtues (no section called "Reproducibility").
- All cross-references use `\ref{}` labels, **never hardcoded numbers** (numbering has drifted twice).
- **Diagrams:** the user's **original figures were restored** after rejecting Mermaid versions. Mermaid sources are parked in `figures/mermaid/`, renders in `figures/_mermaid_versions/`, originals backed up in `figures/_original_diagrams/`.

---

## 8. Data gotchas (hard-won — don't rediscover)

- **`data/stream_log.csv` has THREE formats** — 7-col (Feb–Apr), 8-col (Apr 14–16), 9-col (Jun 13). Confidence is at index **6, 6, 7** respectively. Naive parsing gives wrong numbers (last column is latency in 9-col).
- **Twitter data (74,195 rows) exists in the log but is NOT part of the thesis** — earlier project phase. Its escalation rate is 29.1% and would skew any average.
- **The one true eval file is `thesis_benchmark_eval.csv`** (1,748 rows). Older files do **not** match the thesis: `thesis_final_benchmark.csv` (459), `data/final_results_analyzed.csv` (500), `reports/stage3/latest/results.csv` (298 — this is the real origin of the "298" that once caused confusion).
- **OpenAlex rate-limits (429) the assistant's sandbox IP.** Use Crossref, or run bib tools from the user's machine. arXiv DOIs are deterministic: `10.48550/arXiv.<id>`.
- **Elasticsearch client is 7.17.9 against an 8.10.2 server** — deliberate, uses compatibility mode. "Fixing" the mismatch breaks ingestion. Documented in Appendix B.
- **The evaluation bypassed the 0.80 gate** — all variants judged all 1,748 records so comparisons share identical rows. Now disclosed in §4.10.

---

## 9. Tools built (all in-repo)

| Script | Purpose |
|---|---|
| `thesis/tools/openalex_bib_audit.py` | Crossref+OpenAlex bibliography audit, resumable cache |
| `thesis/tools/apply_bib_fixes.py` | Offline bib rewriter → `references_fixed.bib` |
| `thesis/tools/verify_citations.py` | Ollama-based citation-claim checker (PDFs in `thesis/literature/`) |
| `scripts/eval/analyze_eval.py` | Reproduces Table 5.1 + latency + 44→80 scaling |
| `scripts/eval/throughput_bench.py` | Throughput/scaling (`--workers`, `--threads`, `--n`) |
| `scripts/eval/resource_snapshot.py` | CPU/RAM/GPU/docker sampling under load |
| `scripts/eval/latency_percentiles.py` | Percentiles from logs |

---

## 10. Open items / next steps

**Round 3 is closed** — sent, reviewed, accepted. Current state of `Thesis Draft 1/`: **39 refs / 0 broken, 68/68 citations, ~26,400 words** in the body. All files last edited 2026-08-17 by the user.

1. **PHASE A — polish and consistency pass. This is the active task.** Four sub-tasks, in the order he listed them:
   - **A1 Terminology consistency across chapters** — check that one thing is called one name everywhere (Tier-1/Tier 1, LLM-Wiki/Wiki, multi-agent/agent chain, judge/auditor, benchmark/evaluation set)
   - **A2 Remove repetitions** — facts stated more than once across chapters (e.g. the toxic-scarcity/deletion argument appears in Ch5 §5.4, Ch6 §6.3, §6.7 and §6.8; the 83.1% figure appears twice)
   - **A3 Remove informal formulations** — includes a few introduced by the user's own Aug-17 rewrites (e.g. Ch3 Layer 2 "This is the part of the system grows into the Big Data"; Ch3 Universal Schema "Here i used two schemas")
   - **A4 Claim alignment** across introduction → methods → results → conclusion (numbers, hedges, and the RQ answers must match exactly)
2. **PHASE B — September multi-node experiment.** Plan with him then; resources come from his side. Do not start early.
3. **Optional, never done:** threshold calibration study · second annotator + agreement score · GPU throughput number.

---

## 11. Standing decisions (don't re-litigate)

- SoA is closed. Only touch it if the supervisor explicitly asks (round 3 touched exactly one sentence, to add the Karpathy citation).
- No multi-node experiment. Single-machine measurement + architectural argument is accepted.
- Reddit/Trustpilot stay as a brief limitation, not a section.
- The LLM runs on Ollama's **hosted** endpoint, not locally. A local model (`dolphin-llama3`) is possible and is argued for on research grounds (hosted models refuse hate-speech content).
- Original diagrams kept; Mermaid versions rejected.
- The benchmark's 212 above-gate records are a **deliberate control group** from the sampler's `normal_fraction=0.25`, not an error.

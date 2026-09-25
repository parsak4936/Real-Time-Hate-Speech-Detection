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
- **RQ3 (Context).** Past a single LLM verdict, does adding memory of prior behaviour, retrieved precedents or curated knowledge, and a multi-agent split of the decision improve detection of the toxic class? And since toxic messages are rare, are those gains real or just noise?

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
**Throughput (re-measured 2026-09-16, raw output in `reports/performance/`):** 1 process all cores **35.8 msg/s** (stack down) / **27.2 msg/s** with the full container stack running. Scaling, 1 thread per process: 1 → 20.9, 2 → 33.0, 4 → 44.0 msg/s (4 single-thread processes beat 1 all-cores process). The old 17/22/25/30 figures had no saved output and were replaced.
**Resources under load (`reports/resource_log.csv`, 27 samples / 2 min, stack up):** CPU 75% avg / 89% peak (loaded samples), RAM ~98% (memory is the real limit), GPU ~160 MB / 5% avg (Tier-1 runs on CPU), 7 containers ~3 GB together (Elasticsearch half), 0.2 cores median, bursts >2 cores mostly Kafka (up to 195%).
**June collection run traffic:** 144,480 msgs over 8.4 h = 4.8 msg/s across all watched streams (~290/min). Used in abstract and §5.9.

### Derived evidence (computed during revisions — these are the strong cards)
- **83.1% of authors appear exactly once** (1,134 of 1,364; median 1 msg/author) → explains memory/RAG nulls
- **Behaviour profiler returned `low` on all 1,748 records** → the multi-agent win comes from decomposition, not author history
- **0 of 204 randomly-drawn records were toxic** → justifies the weighted sampling
- **Live escalation rate 8.25%** on the June-13 run (144,480 msgs) vs **87.9%** in the benchmark
- **Human-review live estimate ≈ 1 in 465** (8.25% × 2.60%), vs 1 in 40 inside the benchmark
- Escalator routing: auto_clear 1,647 (94.2%) / auto_flag 57 (3.3%) / human_review 44 (2.5%)
- Added in Stage 2 (2026-09-17), all from the benchmark CSV:
  - Tier-1 false alarms overturned by the baseline judge: **398 of 444**, 193 of them Gaming
  - Baseline judge misses **34/80 toxic (43%)** but flags only **123/1,668 normal (7%)**
  - Gaming: judge caught **2 of 14** toxic; low-strictness misses 19/36 vs high 10/35
  - Binary verdict changes vs baseline: memory 119, RAG 111, Wiki 136, multi-agent 119
  - Off-taxonomy domains: **628/1,748 (36%)** (exact 1,045, alias 75)
  - Wiki has 4 domain pages (gaming, politics_news, reviews, general); any other domain falls back to general
  - The sampler reserves 25% *of its quota* for random normals, but only 204 of 1,748 ended up random

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

0. **Sept 2026 stages:** Stage 1 (numbers) DONE; **Stage 2 (A1–A4 below) DONE 2026-09-17**, 149 edits across 10 files, 0 broken refs, all figures labelled and referenced. **Stage 3 (references) DONE 2026-09-17.** All 69 original refs verified to exist (15 arXiv + 41 DOIs + abstracts). Fixed 10 citations that misstated their source: Pavlopoulos (context-aware classifiers gained *nothing*), Wulczyn, Mishra (community profiles, not post history), Llama Guard (Llama 2), Hate Personified (persona shift, not faithfulness → Turpin 2023), Kafka evaluation (Kafka alone → Dobbelaere 2017), implicitctx, moderationbias (topics), judgebias (language), multi-agent failures (→ Cemri 2025). Added 9 entries (Turpin, Dobbelaere, Cemri, Sap 2019, Davidson 2019, Ross, Kreps, YouTube Help, Twitch API docs); **now 78/78 cited**. "Deleted within seconds" is now backed by platform docs (held messages + chat delay; the pipeline reads as a viewer). Ethics now notes that the Davidson corpus in Tier-1's training data is one where dialect bias was documented. **Stage 4 (cleanup + layout) source edits DONE 2026-09-17:**
- Leftover wording: the 1,600–2,100 figure now appears in Ch5 only; the RQ1 answer cites evidence; "likelier gap is scarcity"; the three classes now point to Ch2 (the old pointer said Ch3, which was wrong).
- All 31 hand-typed Chapter/Appendix numbers are now `\ref`s.
- Figures 3.2/3.3 width 1.5→1.0.
- `\allowbreak` added in long `\texttt` names in Table 4.1 and the Appendix B services table.
- `main.tex` comments left alone at the user's request.
- **Still open in Stage 4:** the user compiles on Overleaf and sends the log/PDF, then we fix real warnings.

**Stage 5 (examiner critique) 2026-09-17**, findings verified from code and CSV:
- **M1 APPLIED:** the multi-agent chain's McNemar significance is in *overall correctness* (it fixes 75 normal + 4 toxic, breaks 28 normal + 12 toxic). Its toxic-F1 gain of +0.022 has a paired-bootstrap 95% CI of [−0.048, +0.090], so it is NOT significant on F1. Tier-1→baseline is +0.244 [+0.166, +0.318]. Reworded in Ch4 §4.10, Ch5 (§5.3, §5.8, Table 5.10), Ch6, Ch7.
- **M2 NOT DISCLOSED (user decision):** `src/shared_utils/memory.py:57` anchors the 24h look-back to `datetime.now()` at replay time, not the message timestamp. Author history reached the judge for only 150/1,748 records. 384 records had an earlier message by the same author in the benchmark, and 330 of them got none. Thread context worked (1,739). The multi-agent replay uses the same `fetch_memory_bundle`, so the constant "low" from the profiler is likely this too. The user does not want the bug mentioned or the phrase "not fairly tested". APPLIED 2026-09-17 (4 edits: §5.3, §5.4 ×2, §6.3), with no future-work framing, as the user asked. Thin histories are explained by the single-day collection and moderator deletion (true for the 83.1% single-appearance figure). The 150/1,748 coverage is stated as a separate fact, deliberately *not* attributed to those causes, because the CSV contradicts that link.
- Not applied (user: no re-runs, keep changes minimal): M3 (the multi-agent chain gets memory inputs; `RAG_ENABLED` default off), M4 as-deployed F1 (baseline 0.38, multi-agent 0.40), M5 (only 8/520 records entered the benchmark solely via the judge-disagreement bonus), M6, M7 (single run per variant), M8 Bonferroni (still significant), M9 hate-only recall (Tier-1 7/21, baseline 16, multi-agent 13), single afternoon of data, RAG precedents may post-date the message, GDPR. Keep these as defence answers.
- Open question never answered: were model predictions visible while labelling?

Then Track B folder cleanup (Stages 6–9).
1. **PHASE A — polish and consistency pass.** Four sub-tasks, in the order he listed them:
   - **A1 Terminology consistency across chapters** — check that one thing is called one name everywhere (Tier-1/Tier 1, LLM-Wiki/Wiki, multi-agent/agent chain, judge/auditor, benchmark/evaluation set)
   - **A2 Remove repetitions** — facts stated more than once across chapters (e.g. the toxic-scarcity/deletion argument appears in Ch5 §5.4, Ch6 §6.3, §6.7 and §6.8; the 83.1% figure appears twice)
   - **A3 Remove informal formulations** — includes a few introduced by the user's own Aug-17 rewrites (e.g. Ch3 Layer 2 "This is the part of the system grows into the Big Data"; Ch3 Universal Schema "Here i used two schemas")
   - **A4 Claim alignment** across introduction → methods → results → conclusion (numbers, hedges, and the RQ answers must match exactly)
2. **PHASE B — September multi-node experiment.** Plan with him then; resources come from his side. Do not start early.
3. **Optional, never done:** threshold calibration study · second annotator + agreement score · GPU throughput number.

---

## 11. Standing decisions (don't re-litigate)

- SoA is closed. Only touch it if the supervisor explicitly asks (round 3 touched exactly one sentence, to add the Karpathy citation).
- ~~No multi-node experiment.~~ **Superseded 2026-09-22:** La Rosa now wants the multi-node experiment (VMs + Raspberry Pis provided by him and colleagues; meeting Thu 24 Sep 2026). Future-work scaling text becomes measured results. See §12.
- Reddit/Trustpilot stay as a brief limitation, not a section.
- The LLM runs on Ollama's **hosted** endpoint, not locally. A local model (`dolphin-llama3`) is possible and is argued for on research grounds (hosted models refuse hate-speech content).
- Original diagrams kept; Mermaid versions rejected.
- **Canonical names (Stage 2):** "multi-agent chain" (component), "multi-agent variant" (its row in results), and Risk Scorer / Behaviour Profiler / Escalator / Supervisor, capitalised. Use "LLM judge"; "auditor" appears only in RQ2. Use "Universal Schema". SoA was allowed these name swaps only.
- **Privacy stance (user decision):** identity is kept on purpose, not stripped. The platforms publish author ID and username, and a moderation system must know who said what. Never claim anonymisation.
- **Thesis title keeps "utilizing"**, the supervisor's wording.
- Four context mechanisms; RAG and LLM-Wiki are alternatives (one retrieval slot).
- The benchmark's 212 above-gate records are a **deliberate control group** from the sampler's `normal_fraction=0.25`, not an error.

---

## 12. Multi-node scaling experiment — measurement protocol (E0, agreed 2026-09-22)

**Timeline:** Thu 24 Sep, meeting with La Rosa + colleagues (hardware handover). Results cut-off ~2 Oct; final PDF ~6 Oct; ESSE3 closes ~8 Oct; graduation session 19 Oct 2026 15:00.

**Stages:**
- E0 protocol (this section)
- E1 processor opt-in instrumentation
- E2 `scripts/eval/replay_producer.py`
- E3 `scripts/eval/analyze_scaling.py`, whose header repeats these rules
- E4 laptop dry run
- E5 cluster setup (compose override, worker setup, clock check)
- E6 Raspberry Pi specifics
- E7 real runs + thesis write-up

One stage at a time; the user pastes the code and runs it, Claude checks the output.

**Ground rules:**
- Experiments use their own topic, index and log file (prefix `perf_`), never `universal_stream`, `real_time_analysis` or `data/stream_log.csv`.
- Every processor change is opt-in via environment variables. With none set, behaviour is identical to today.
- The normal pipeline is re-run after each stage to confirm it still works.

**1. Question.**
- Does Tier-1 throughput grow when classifier processes are spread across machines (partitions raised to match), and what happens to latency?
- Secondary: can a Raspberry Pi serve as a Tier-1 node (edge angle, to confirm on 24 Sep)?

**2. System under test.** The real path, unchanged: replay producer → Kafka test topic (P partitions) → N Tier-1 processors (same model `models/bert_final`, same code) → Elasticsearch test index.

**3. Workload.**
- Fixed set of real chat messages from the **June 13 collection run** in `data/stream_log.csv` (146,301 rows dated 2026-06-13, 9-column processor format).
- Same messages in the same order every run, fixed seed. **Default W = 10,000**, adjustable.
- Each message carries run_id + sequence number.

**4. Two load modes.**
- **Throughput run:** the whole workload is loaded into Kafka first, then the processors start. This measures drain rate, so the producer cannot be the bottleneck.
- **Latency run:** messages are sent at a fixed rate below capacity, at **50% and 80%** of the measured maximum throughput. Latency at saturation is not reported (it only measures queue length).

**5. Metrics.**

| Metric | Definition |
|---|---|
| Throughput X | messages completed ÷ time, over the steady window (**first 10% of messages dropped as warm-up**); aggregate and per node |
| Speed-up / efficiency | S(n) = X(n)/X(1); E(n) = S(n)/n |
| End-to-end latency | t_done − t_kafka_create (producer timestamp); p50 / p95 / p99 / max |
| Breakdown | Kafka wait (t_consumed − t_create), inference ms, Elasticsearch write ms |
| Balance | messages per processor, per partition, per machine (max/min ratio) |
| Resources | CPU % and RAM % per machine, sampled every 2 s |

**6. Run validity** (all must hold):
- (a) delivered = W unique sequence numbers; duplicates counted and reported, never hidden.
- (b) no processor errors.
- (c) label agreement with a single-machine reference run is reported (ARM vs x86 may flip borderline cases).
- (d) for cross-machine latency, the clock offset between machines is ≤ **5 ms**, measured and recorded; otherwise report throughput only for that run.
- (e) fresh topic, consumer group and index per run.

**7. Elasticsearch.** The write stays in the measured path (the real pipeline). An optional run with the Elasticsearch write off isolates the compute tier.

**8. Configurations.**
- Laptop (E4): partitions {1, 2, 4} × processors {1, 2, 4}, processors ≤ partitions.
- Cluster (E7): set after 24 Sep once the hardware is known. Shape: 1 node → 2 VMs → VMs + Pis, plus each device alone (`throughput_bench.py`).
- Threads per process are recorded.

**9. Repetitions.** **3 runs per configuration**; report the median and the min–max range.

**10. Recording.** `reports/scaling/<run_id>/` holds:
- the raw per-message CSV from every machine;
- the resource CSV per machine;
- a manifest with P, N, machines, threads per process, W, rate, mode, code version (git hash), and hardware.

**11. Thesis use.**
- Results: new subsection in §5.9 with a throughput/speed-up table and latency percentiles at 50%/80% load.
- Methods: this protocol, cited.
- Update Ch3 L87 ("never needed to be"), §5.9 (the "validation still outstanding" paragraph), Table 5.10 RQ1, the Ch7 RQ1 answer, and the future-work "Validate the scale-out path" paragraph.
- Scope (Ch1): "any deployment beyond a single containerised host" becomes in scope.
- Appendix B: the cluster hardware.
- If Pis are used for edge: the conclusion's edge future-work paragraph.

**Known gaps to close in E1–E6** (from the code audit):
- (1) Kafka advertises `localhost:9093` (`docker-compose.yml:62`).
- (2) Topics auto-created with 1 partition (`docker-compose.yml:65`).
- (3) The full stack can't run on a Pi; workers need Python + model only.
- (4) `group_id` hard-coded (`distilbert_processor.py:84`).
- (5) The processor always appends to live `data/stream_log.csv` (L30, L177).
- (6) Only inference is timed; no Kafka create/consume timestamps, host or partition (L63–73).
- (7) Synchronous Elasticsearch write per message (L173), to be timed separately.
- (8) No replay producer.
- (9) No multi-node analysis script.
- (10) No correctness check.
- (11) No clock-sync check.
- (12) `resource_snapshot.py` needs docker/nvidia-smi; Pis need a psutil-only path.
- (13) Worker environment: minimal requirements, Elasticsearch client pinned 7.17, 269 MB model copy.
- (14) This protocol (now closed).

**E1 DONE 2026-09-22:** `src/static_classifier/distilbert_processor.py`, 41 lines added / 2 changed, compile-checked.
- Opt-in env vars:
  - `PROCESSOR_LOG_FILE` (default: live `data/stream_log.csv`)
  - `PROCESSOR_GROUP_ID` (default: `moderation_processor`)
  - `BENCH_LOG` (per-message timing CSV, line-buffered so interrupted runs keep all rows)
  - `NODE_NAME` (default: hostname)
- Timing columns: node, pid, run_id, seq, topic, partition, offset, kafka_ts_ms, kafka_ts_type, t_recv_ms, infer_ms, es_ms, t_done_ms, label, confidence.
- `run_id`/`seq` are read from payload keys `bench_run_id`/`bench_seq` (set by the E2 producer).
- No-Elasticsearch run: point `ES_HOST` at an unused address (the processor already skips Elasticsearch when ping fails).
- Undo: `git checkout -- src/static_classifier/distilbert_processor.py`.
- Gaps 4–7 closed.

**E2 ON HOLD (2026-09-22) — resume here.** Plan shown to the user, awaiting a "confirm", NOT written yet.
- New file `scripts/eval/replay_producer.py`.
- Workload: June-13 rows of `data/stream_log.csv`, W=10000, seed 42, original order. Parse: first 5 fields / text / last 3 fields.
- Payload in Universal Schema + `bench_run_id`/`bench_seq`; author = "bench".
- Creates the topic with P partitions via KafkaAdminClient; errors if the topic exists with a different count.
- Refuses topics not starting with `perf_`.
- Modes: preload (throughput) | rate R (fixed schedule t0+i/R).
- Key = seq, for deterministic partitioning.
- Writes `reports/scaling/<run_id>/manifest_producer.json` ("running", then "done") and `sent.csv` (seq, partition, offset, send ts; line-buffered, via send callbacks).
- `--dry-run` = build and show, send nothing.
- Test: Claude runs `--dry-run`; the user runs the smoke test `--topic perf_smoke --partitions 2 --n 100 --mode preload` with only zookeeper + kafka up.

User interrupted to handle the PhD enrolment (window 23 Sep – 2 Oct).

**E2 DONE 2026-09-23:** new file `scripts/eval/replay_producer.py` (nothing else changed).
- Dry run: 10,000 of 141,362 usable 2026-06-13 rows (4,939 malformed skipped), platforms YouTube 9,729 / Twitch 271, seed 42 reproducible, predicted 2-partition split 5,061/4,939.
- Guard verified: a non-`perf_` topic is refused.
- Smoke test on the user's machine: `--topic perf_smoke --partitions 2 --n 100 --mode preload` → 100 acknowledged, 0 errors, per partition 51/49 (exactly as predicted), 0.19 s, 525 msg/s. `sent.csv` = 100 rows, seq 0–99 unique, Kafka timestamps present. Manifest records host, git commit, python.
- The producer is ~15x faster than the classifier, so it is never the bottleneck.
- For the cluster, only `--brokers <ip:9093>` changes.
- Gap 8 closed.

**E3 DONE 2026-09-23:** new file `scripts/eval/analyze_scaling.py` (read-only; nothing else changed).
- Joins `sent.csv` with the `bench_*.csv` logs copied from each machine, filtering by run_id so one log can span several runs.
- Reports: throughput (steady window, first 10% dropped) total and per node; end-to-end latency + breakdown (Kafka wait / inference / Elasticsearch) as p50/p95/p99/max; balance per processor, per machine, per partition; optional `--baseline` speed-up and efficiency; optional `--reference` label agreement.
- Validity lines: PASS/FAIL delivery, WARN duplicates (Kafka at-least-once), FAIL extras, clock sanity (a negative Kafka wait means that node's clock is behind → cross-machine latency invalid), label agreement.
- Writes `metrics.json` + `summary.txt` into the run folder.
- Verified on a synthetic run with a deliberately lost message, a duplicate and a foreign-run row: every number matched the constructed values (e2e 100 ms, wait 50, infer 30, es 5; balance 10/9; throughput 17/1.8s = 9.44 msg/s).
- On the real smoke run with no processor logs it reports the gap clearly instead of inventing numbers.
- Gaps 9-10 closed. Next: E4 (laptop dry run of the full matrix).

**E4 IN PROGRESS 2026-09-23.** Launcher `scripts/eval/run_scaling_local.ps1` (new) + `resource_snapshot.py` given `--out` and incremental writes (it used to write only at the end and always to `reports/resource_log.csv`, the file the thesis cites).
- **Bug found and fixed:** the processor died with `UnicodeEncodeError` on the first emoji whenever its output was redirected to a file (Windows cp1252). Fix = 6 lines at the top of `distilbert_processor.py` reconfiguring stdout/stderr to UTF-8 with `errors="replace"`. This also protects the live pipeline. The launcher now runs children with PYTHONIOENCODING/PYTHONUNBUFFERED, refreshes process state before reporting "alive", and prints the children's last error lines if they all die.
- Stall detection: 600 s allowed before the first message (several models loading at once), 300 s afterwards.
- **Short test PASSED (2 partitions / 2 processors / 2,000 msgs, full path incl. Elasticsearch):** 2,000/2,000 processed, 0 duplicates, 0 extras, balance 1,023/977 (ratio 1.05), throughput **18.13 msg/s**, inference p50 41.9 ms, **Elasticsearch write p50 49.8 ms** (the ES write costs about as much as the model — this is why end-to-end is below the old model-only 33 msg/s for 2 processes).
- Preload mode makes end-to-end latency meaningless (backlog wait); latency comes from rate runs.
- Pending: the full local matrix, 1/1, 2/2, 4/4 with `-N 10000 -Repeats 3 -Resources`, ~2 h, run with only zookeeper+kafka+elasticsearch up and the laptop otherwise idle.
- Results: `reports/scaling/<run_id>/` (untracked by git so far; `reports/` is not in .gitignore, so they can be committed deliberately).

**E4 DONE 2026-09-24 — local matrix complete (9 runs of 10,000 messages, 3 repeats each).**
Full end-to-end path (Kafka -> Tier-1 -> Elasticsearch), 1 thread per process, only zookeeper+kafka+elasticsearch running.

| processors | median msg/s | runs | speed-up | efficiency |
|---|---|---|---|---|
| 1 | 11.68 | 11.8 / 11.7 / 11.6 | 1.00x | - |
| 2 | 21.93 | 20.5 / 21.9 / 21.9 | 1.88x | 0.94 |
| 4 | 35.90 | 36.0 / 35.9 / 35.5 | 3.07x | 0.77 |

- **0 lost, 0 duplicated across ~90,000 messages**; processor balance ratio 1.02-1.04.
- Inference p50 rises with contention: 31.6 / 37.5 / 56.0 ms; the Elasticsearch write stays ~47 ms throughout.
- **Important for the write-up:** these end-to-end numbers are NOT the old model-only figures (20.9 / 33.0 / 44.0 from `throughput_bench.py`). The new ones include the Kafka hop and the per-message Elasticsearch write, so §5.9 must distinguish "classifier alone" from "full pipeline".
- A run without the venv active fails instantly (`No module named torch`); the launcher now defaults to `Hate_speach_env\Scripts\python.exe` and preflights the imports.
- Raw data: `reports/scaling/2026092*_p{1,2,4}_c{1,2,4}_r{1,2,3}/`.

---

## 13. Scaling measurements — ALL RESULTS (single machine, laptop "WIX", 2026-09-23/25)

**Where the raw data lives:** `reports/scaling/<run_id>/` (one folder per run, never overwritten), holding
`metrics.json`, `summary.txt`, `manifest_producer.json`, `manifest_processors.json`, `sent.csv`,
`bench_<host>_<i>.csv` (one row per message), `resource_<host>.csv`, and the processors' own logs.
**Regenerate the tables with:** `python scripts/eval/compare_runs.py --min-n 5000`
→ writes `reports/scaling/comparison.csv` and `comparison.md`. Never type these numbers by hand.

**Conditions for every run below:** full path (Kafka → Tier-1 → Elasticsearch), 1 thread per process,
only zookeeper + kafka + elasticsearch running, workload = the same 10,000 messages from 2026-06-13
(seed 42), laptop = Intel i5-8265U (4 physical cores), 12 GB RAM, GTX 1650.

### Throughput, preload mode (3 repeats each, median)

| device | processors | median msg/s | runs | speed-up | efficiency | inference p50 | Elasticsearch p50 |
|---|---|---|---|---|---|---|---|
| CPU | 1 | **11.68** | 11.8 / 11.7 / 11.6 | 1.00x | - | 31.6 ms | 47.9 ms |
| CPU | 2 | **21.93** | 20.5 / 21.9 / 21.9 | 1.88x | 0.94 | 37.5 ms | 46.8 ms |
| CPU | 4 | **35.90** | 36.0 / 35.9 / 35.5 | 3.07x | 0.77 | 56.0 ms | 46.8 ms |
| **GPU** | 1 | **13.90** | 13.91 / 13.87 / 13.90 | - | - | **22.0 ms** | 47.8 ms |

### Latency, rate mode (4 processors, 4 partitions; warm-up = 10% + first 120 s, identical for both)

| offered rate | delivered | e2e p50 | e2e p95 | e2e p99 | Kafka wait p50 | inference p50 | ES p50 |
|---|---|---|---|---|---|---|---|
| 18 msg/s (50% of capacity) | 18.35 | **92.4 ms** | 191 ms | 295 ms | 3.6 ms | 35.6 ms | 46.6 ms |
| 29 msg/s (80% of capacity) | 29.02 | **145.0 ms** | ~394 ms | ~570 ms | ~53 ms | 43.6 ms | 46.5 ms |

### Findings that belong in the thesis
1. **Scaling is near-linear to 2 processors (0.94) and falls to 0.77 at 4**, because four classifiers share four physical cores with Kafka and Elasticsearch. This is the argument for going multi-node.
2. **The Elasticsearch write costs as much as the model** (~47 ms vs 32 ms on CPU) and is flat across every configuration. It becomes the dominant cost on GPU.
3. **The GPU buys only +19%** (11.68 → 13.90) although inference drops 30% (31.6 → 22.0 ms), because messages are processed one at a time and the storage write then dominates. Answer to "which hardware level": a GPU is the wrong upgrade for this pipeline until storage is faster.
4. **CPU and GPU produce identical verdicts** (max probability difference 9e-08), so device choice affects speed only.
5. **Reliability: 0 lost and 0 duplicated messages across ~100,000 messages**, with processor balance 1.02-1.08.
6. Startup effect (not a thesis claim, recorded for us): a consumer group needs a few seconds to be assigned its partitions, and at low arrival rates the queue that builds takes ~2 minutes to clear. Excluded via the declared warm-up; the analyser also reports the figures including it.

### Invalid runs, kept but excluded
`20260925-133838_p4_c4_r1` and `20260925-135404_p4_c4_r1` carry an `INVALID.txt` explaining that they
were rate runs made before the launcher fix (producer ran before the processors, so latency measured backlog).
`compare_runs.py` skips any folder containing `INVALID.txt`.

### Tooling built for this (all in `scripts/eval/`)
`replay_producer.py` (fixed workload into a `perf_` topic, preload or rate mode, `--create-topic-only`),
`analyze_scaling.py` (throughput, latency, balance, delivery/duplicate/clock checks, `--warmup-seconds`),
`compare_runs.py` (merges every run into one table), `run_scaling_local.ps1` and `run_scaling_local.sh`
(one command per configuration), plus the opt-in processor instrumentation (`BENCH_LOG`, `PROCESSOR_GROUP_ID`,
`PROCESSOR_LOG_FILE`, `NODE_NAME`, `DEVICE`, `MODEL_DIR`).

**THESIS UPDATED WITH THESE RESULTS, 2026-09-25** (10 edits; `git diff` shows them):
- `results.tex` §5.9 now reports **two** measurements and says which is which: the classifier alone (20.9/33.0/44.0, 35.8, 27.2 msg/s — unchanged, relabelled) and the **whole pipeline end to end** (new `tab:pipeline-scaling`: 11.7 / 21.9 / 35.9 msg/s, speed-up 1.88/3.07, efficiency 0.94/0.77, plus the GPU row 13.9). **This resolves the conflict**; no number was deleted.
- New `tab:pipeline-latency`: 18 msg/s → 92/191/295 ms; 29 msg/s → 145/382/522 ms, with the Kafka wait growing 4→51 ms as load rises. Latency is now evidence, not an estimate.
- New protocol paragraph describing the replay producer, the fixed 10,000-message workload, 3 repeats, the warm-up rule and the loss/duplicate checks.
- New paragraphs: the ~47 ms Elasticsearch write equalling the model's cost; the GPU giving +19% while verdicts stay identical (device is a config value); 0 lost / 0 duplicated in ~100k messages, balance ≤1.08.
- RQ1 answer and `tab:rq` updated to the end-to-end figures; Ch7 RQ1 answer likewise.
- `methods.tex` parameter table: added `MODEL_DIR` (checkpoint) and `DEVICE` (CPU/GPU) rows — the switchable static tier is now documented.
- Appendix B: Tier-1 inference row says CPU by default with the GPU selectable, both measured.
- `discussion.tex` limitation "Latency and cost": added that on the fast path storage, not the classifier, is the dominant per-message cost.
- Still to do after the multi-node runs: the last paragraph of §5.9 still says multi-node validation is outstanding, and Ch7 future work still lists "Validate the scale-out path".

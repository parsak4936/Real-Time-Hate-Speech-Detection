# Project reference — every file, every concept, every citation

This is the single document you can keep open while writing the thesis. It answers: "where is X?", "what does Y do?", "what should I cite for Z?". If something disagrees with the code, the code wins — open an issue.

For deeper dives, follow the cross-references to the specialised docs. For step-by-step recipes, see [`RUNBOOK.md`](RUNBOOK.md). For thesis deliverables checklist, see [`THESIS_DELIVERABLES.md`](THESIS_DELIVERABLES.md).

---

## 1. Project at a glance

**What it is.** A modular, multi-platform, real-time hate-speech moderation pipeline with a two-tier classifier (DistilBERT + LLM judge), agentic context discovery, temporal memory, and retrieval-augmented decisions. Built on Kafka + Elasticsearch + Qdrant. Multi-source ingestion (YouTube, Twitch, Reddit). Operator dashboards + analyst chat as Streamlit apps.

**Why it matters for the thesis.** It implements 3 of the 7 directions the supervisor asked for (agentic context, RAG, temporal memory), measures each, and provides infrastructure for the remaining 4 (multi-agent, XAI, edge, FL).

**What's NOT done.** Stage 4 (multi-agent decomposition), Stage 5 (advanced XAI like SHAP/Captum), Stage 6 (edge optimisation / quantisation), Stage 7 (federated learning). These are roadmapped, not implemented.

---

## 2. Pipeline overview (5 layers, mapped to the report)

```
LAYER 5 — Analyst Surface
  ├── operator_dashboard.py    (passive monitoring, 6 panels, port 8501)
  ├── analytics_dashboard.py   (8 tabs, plotly charts, port 8503)
  ├── analyst_chat.py          (Streamlit chat to Leader Agent, port 8502)
  └── leader_agent.py          (terminal natural-language console)
                                                              ↑↓
LAYER 4 — Storage & Visualisation
  ├── Elasticsearch  (index: real_time_analysis, 32-field mapping)
  ├── Kibana         (dashboard.ndjson)
  └── Qdrant         (collection: moderation_records, 384-dim cosine)
                                                              ↑↓
LAYER 3 — Tier-1 Static Classifier + Tier-2 Audit
  ├── distilbert_processor.py  (Kafka → DistilBERT → ES, real-time)
  ├── xai_batch_judge.py       (async LLM audit of low-confidence records)
  └── replay_with_memory.py    (offline re-judge with memory)
  └── replay_with_rag.py       (offline re-judge with RAG)
                                                              ↑↓
LAYER 2 — Streaming Backbone
  └── Kafka 7.5.0 + Zookeeper 3.9 + Spark 3.4.1 (docker-compose.yml)
                                                              ↑↓
LAYER 1 — Producers + Context Agent
  ├── omni_ingest.py           (URL router)
  ├── adapters/youtube_adapter.py
  ├── adapters/twitch_adapter.py
  ├── adapters/reddit_adapter.py
  └── adapters/context_agent.py (agentic env_domain discovery via LLM)
```

For the mermaid version + diagram-ready format, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 3. Complete file tree (with one-line purpose for each)

```
F:\hate-speech-pipeline\
│
├── README.md                          Entry point — docs index + setup + run
├── docker-compose.yml                 Layer 2 stack (Kafka, ZK, Spark, ES, Kibana, Qdrant)
├── dashboard.ndjson                   Pre-built Kibana dashboard import
├── requirements.txt                   Python runtime + dev dependencies
├── .gitignore                         Excludes venv, models, data, chat_history
│
├── data/                              All datasets + logs (gitignored)
│   ├── Davidson_dataset.csv             Training data — Davidson et al. 2017
│   ├── HXE_dataset.json                 Training data — HateXplain
│   ├── ToxiGen_dataset.csv              Training data — ToxiGen
│   ├── Final_Mega_Dataset.csv           Consolidated 52,972-sample training corpus
│   ├── live_youtube_validation.csv      Dataset B v0 (459 records, manual labels)
│   ├── final_results_analyzed.csv       Tri-model side-by-side from internship
│   ├── pending_taxonomy.log             Off-seed domain proposals from the LLM
│   ├── stream_log.csv                   CSV audit log of every Tier-1 verdict
│   └── thesis_benchmark_eval.csv        YOUR thesis benchmark (298 hand-labelled)
│
├── models/                            ML artefacts (gitignored)
│   ├── bert_final/                      DistilBERT fine-tuned checkpoint
│   ├── logistic_regression.pkl          Classical baseline (76% accuracy)
│   ├── svm_model.pkl                    Classical baseline
│   └── tfidf_vectorizer.pkl             Feature extractor for classical baselines
│
├── chat_history/                      Saved analyst chat conversations (gitignored)
│   └── chat_<timestamp>_<hash>.json     Auto-generated, one per conversation
│
├── thesis_final_benchmark.csv         Internship 459-record benchmark (frozen baseline)
├── Internship_report_Draft_1 (1).pdf  Authoritative spec / report
│
├── config/                            Operator-editable configuration
│   ├── taxonomy.yaml                    16 canonical domains + aliases + strictness
│   ├── rag.yaml                         Embedding model, k, similarity threshold
│   └── es_index_template.json           32-field ES mapping (explicit types)
│
├── docs/                              Thesis-facing documentation
│   ├── README.md ←→ documentation index lives in the root README
│   ├── PROJECT_REFERENCE.md             (this file) single-page everything
│   ├── ARCHITECTURE.md                  5-layer figure + folder map + mermaid
│   ├── SCHEMA.md                        Universal payload + ES doc field contract
│   ├── PROMPTS.md                       Canonical text of every LLM prompt + design rationale
│   ├── EVAL.md                          How to reproduce report's 93.5%
│   ├── ROADMAP.md                       Stage 0 → Stage 7 plan
│   ├── RUNBOOK.md                       Two end-to-end recipes (with/without labels)
│   ├── STATUS.md                        Current build/wired/evaluated matrix
│   ├── GLOSSARY.md                      Every tool + concept + alternative + citation
│   ├── CODEBASE_TOUR.md                 Sequenced reading path
│   ├── AUDIT_GUIDE.md                   Per-file audit checklist
│   ├── MIGRATION.md                     Should I wipe ES? Field cheatsheet
│   ├── SOURCES.md                       Free ingestion APIs + setup
│   ├── THESIS_DELIVERABLES.md           Per-section thesis writeup checklist
│   ├── IMPROVEMENTS.md                  Prioritised future improvements list
│   └── MONITORING.md                    Visibility surfaces + chat UI vs monitoring UI
│
├── notebooks/
│   └── evaluation.ipynb               Living per-variant evaluation (68 cells, 8 sections)
│
├── scripts/                           Standalone utilities + UIs
│   ├── _build_eval_notebook.py          Generator for evaluation.ipynb (rerun to regenerate)
│   ├── normalize_domains.py             Backfill legacy "Gaming/Survival" → split
│   ├── init_es_index.py                 Create ES index with the locked 32-field mapping
│   ├── sample_for_eval.py               Stratified random sample from ES → benchmark CSV
│   ├── replay_with_memory.py            Re-judge benchmark CSV with memory-augmented prompt
│   ├── seed_rag_from_csv.py             Bootstrap Qdrant from a labelled CSV
│   ├── build_rag_index.py               Bootstrap Qdrant from ES (alternative seed source)
│   ├── replay_with_rag.py               Leave-one-out RAG evaluation on benchmark CSV
│   ├── operator_dashboard.py            Streamlit minimal monitoring (port 8501)
│   ├── analytics_dashboard.py           Streamlit deep analytics — 8 tabs (port 8503)
│   └── analyst_chat.py                  Streamlit chat to Leader Agent (port 8502)
│
└── src/                               Production runtime code
    │
    ├── reset_db.py                    Wipe ES index (requires --yes)
    ├── export_subset.py               Pull reviewed records ES → CSV with all eval columns
    ├── calculate_thesis_metrics.py    Pandas-based metrics from CSV
    ├── Hate_speach_Project.ipynb      DistilBERT training notebook (do NOT re-run, GPU-hours)
    │
    ├── shared_utils/                  Cross-cutting helpers (every other file depends on these)
    │   ├── __init__.py                  Package marker
    │   ├── config.py                    Env-driven configuration (ES_HOST, MEMORY_ENABLED, etc.)
    │   ├── prompts.py                   Canonical text of every prompt — single source of truth
    │   ├── llm.py                       Thin Ollama wrapper (temp=0, format=json, 1 retry)
    │   ├── taxonomy.py                  Domain-taxonomy normaliser (config/taxonomy.yaml)
    │   ├── memory.py                    Temporal memory — ES-backed user / thread history
    │   └── rag.py                       RAG retrieval — Qdrant + sentence-transformers
    │
    ├── ingestion/                     Layer 1 — Producers
    │   ├── __init__.py
    │   ├── omni_ingest.py               URL router → YouTube / Twitch / Reddit adapter
    │   └── adapters/
    │       ├── __init__.py
    │       ├── youtube_adapter.py         pytchat live-chat producer
    │       ├── twitch_adapter.py          Anonymous IRC live-chat producer
    │       ├── reddit_adapter.py          PRAW comment-stream producer
    │       └── context_agent.py           Agentic env_domain + strictness discovery
    │
    ├── static_classifier/             Layer 3 — Tier-1 (DistilBERT)
    │   ├── __init__.py
    │   └── distilbert_processor.py      Kafka consumer → DistilBERT → ES (writes 32 fields)
    │
    └── agents/                        Layer 5 — Tier-2 + Analyst Surface
        ├── __init__.py
        ├── xai_batch_judge.py            Async LLM audit with platform/domain filters + per-domain cap
        ├── leader_agent.py               Terminal natural-language console
        ├── check_db_size.py              Diagnostic — print one ES record's schema
        └── tools/
            ├── __init__.py
            ├── search_tool.py             ES full-text + filtered retrieval
            ├── stats_tool.py              ES aggregations (counts, breakdowns, top users)
            ├── xai_judge_tool.py          Single-user audit (LLM judge with memory)
            └── weather_tool.py            External API tool (Open-Meteo) — demo tool
```

---

## 4. Configuration files (where to change behaviour without touching code)

| File | What you change there |
|---|---|
| `.env` | Per-environment secrets + flags: `MEMORY_ENABLED`, `RAG_ENABLED`, `REDDIT_CLIENT_ID`, etc. |
| `config/taxonomy.yaml` | Domain seed list (16 canonicals + aliases + default strictness) |
| `config/rag.yaml` | Embedding model name, vector dim, batch size, top_k, similarity threshold |
| `config/es_index_template.json` | ES field mapping — what types each field has |
| `docker-compose.yml` | Service versions, ports, volumes |
| `requirements.txt` | Pinned Python dependencies |

---

## 5. Pipeline variants (what to compare for thesis)

These are the four columns the evaluation notebook compares against `human_ground_truth`. Each is produced by a different code path; the **comparison between them** is your thesis evidence.

| Variant | Column in CSV | Where the verdict comes from | What's different |
|---|---|---|---|
| **Tier-1 only** | `model_label` | `distilbert_processor.py` | Fast static classifier; no LLM |
| **Tier-1 + Tier-2 baseline** | `agent_final_decision` | `xai_batch_judge.py` (live) | LLM judges the message in isolation with forensic rules |
| **Tier-1 + Tier-2 with memory** (Stage 2) | `agent_final_decision_with_memory` | `replay_with_memory.py` | LLM judges with user history + thread context + behavioural fingerprint |
| **Tier-1 + Tier-2 with RAG** (Stage 3) | `agent_final_decision_with_rag` | `replay_with_rag.py` | LLM judges with semantically similar past cases as precedents |
| **Future: Tier-1 + Tier-2 with memory + RAG** (Stage 3.5) | `agent_final_decision_with_memory_and_rag` | Not yet built — single-line replay script copy | Combined memory + RAG |

---

## 6. Process boundaries (which Python file runs where)

When everything is running, you'll have ~5 OS processes:

| Process | Command | When it runs |
|---|---|---|
| Tier-1 processor | `python src/static_classifier/distilbert_processor.py` | Long-running, consumes Kafka |
| Producer (one per stream) | `python src/ingestion/omni_ingest.py` → paste URL | Per stream — close when stream ends |
| Tier-2 batch judge | `python src/agents/xai_batch_judge.py [...flags]` | On-demand sweeps |
| Operator UI (any) | `streamlit run scripts/<dashboard>.py --server.port <port>` | On-demand |
| Leader Agent terminal | `python src/agents/leader_agent.py` | On-demand (alternative to chat UI) |

Plus the docker-compose services: Kafka, Zookeeper, Spark, Elasticsearch, Kibana, Qdrant.

---

## 7. Citations consolidated for the thesis bibliography

Group them in the bib by category. Each entry has the title, venue, and arXiv id where applicable.

### Foundational classifier work
- **DistilBERT** — Sanh, Debut, Chaumond, Wolf. *DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter*. arXiv:1910.01108, 2019.
- **BERT** — Devlin, Chang, Lee, Toutanova. *BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding*. NAACL 2019. arXiv:1810.04805.
- **RoBERTa** — Liu et al. *RoBERTa: A Robustly Optimized BERT Pretraining Approach*. arXiv:1907.11692, 2019.
- **DeBERTa** — He, Liu, Gao, Chen. *DeBERTa: Decoding-enhanced BERT with Disentangled Attention*. ICLR 2021.
- **HateBERT** — Caselli, Basile, Mitrović, Granitzer. *HateBERT: Retraining BERT for Abusive Language Detection in English*. WOAH 2021.

### Datasets
- **Davidson et al. 2017** — *Automated Hate Speech Detection and the Problem of Offensive Language*. ICWSM 2017.
- **HateXplain** — Mathew, Saha, Yimam, Biemann, Goyal, Mukherjee. *HateXplain: A Benchmark Dataset for Explainable Hate Speech Detection*. AAAI 2021.
- **ToxiGen** — Hartvigsen, Gabriel, Palangi, Sap, Ray, Kamar. *ToxiGen: A Large-Scale Machine-Generated Dataset for Adversarial and Implicit Hate Speech Detection*. ACL 2022.

### Infrastructure
- **Kafka** — Kreps, Narkhede, Rao. *Kafka: a Distributed Messaging System for Log Processing*. NetDB 2011.
- **Spark** — Zaharia et al. *Apache Spark: A Unified Engine for Big Data Processing*. Comm. ACM 59(11), 2016.

### LLM-as-Judge + Agentic AI
- **LLM-as-a-Judge** — Zheng et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*. arXiv:2306.05685, 2023.
- **ReAct (agentic)** — Yao, Zhao, Yu, Du, Shafran, Narasimhan, Cao. *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023.
- **Llama Guard** — Inan et al. *Llama Guard: LLM-based Input-Output Safeguard for Human-AI Conversations*. arXiv:2312.06674, 2023.
- **Llama 3** — AI@Meta. *The Llama 3 Herd of Models*. arXiv:2407.21783, 2024.

### Retrieval-Augmented Generation
- **RAG (original)** — Lewis et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020.
- **Sentence-BERT** — Reimers, Gurevych. *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks*. EMNLP 2019.
- **MTEB** — Muennighoff et al. *MTEB: Massive Text Embedding Benchmark*. EACL 2023.

### Evaluation methodology
- **McNemar's test** — McNemar. *Note on the sampling error of the difference between correlated proportions or percentages*. Psychometrika 12, 1947.
- **Dietterich 1998** — *Approximate Statistical Tests for Comparing Supervised Classification Learning Algorithms*. Neural Computation 10(7), 1998.
- **Bootstrap CIs** — Efron, Tibshirani. *An Introduction to the Bootstrap*. Chapman & Hall, 1993.

### Supporting tools (cite optionally)
- **Qdrant** — qdrant.tech. Cite as "open-source vector database".
- **Ollama** — ollama.com. Cite as "local LLM serving framework".
- **HuggingFace Transformers** — Wolf et al. *Transformers: State-of-the-Art Natural Language Processing*. EMNLP 2020.

---

## 8. Quick-lookup: "Where is X?"

| If you need to know… | Look at |
|---|---|
| Architecture diagram | [`ARCHITECTURE.md`](ARCHITECTURE.md) — mermaid flow + 5-layer figure |
| What an ES field is and how to query it | [`SCHEMA.md`](SCHEMA.md) — full field contract + type cheatsheet |
| The exact text of any LLM prompt | [`PROMPTS.md`](PROMPTS.md) + `src/shared_utils/prompts.py` |
| Why we chose X over Y | [`GLOSSARY.md`](GLOSSARY.md) — every tool with alternatives |
| What to read in what order | [`CODEBASE_TOUR.md`](CODEBASE_TOUR.md) — 8-tier reading path |
| How a specific file works internally | [`AUDIT_GUIDE.md`](AUDIT_GUIDE.md) — per-file checklist |
| How to run the pipeline | [`RUNBOOK.md`](RUNBOOK.md) — Path A (no labels) and Path B (with labels) |
| Whether to wipe the database | [`MIGRATION.md`](MIGRATION.md) — decision tree |
| Where data comes from | [`SOURCES.md`](SOURCES.md) — 11 free APIs surveyed |
| Roadmap / stage plan | [`ROADMAP.md`](ROADMAP.md) — Stage 0 → Stage 7 |
| Current build status | [`STATUS.md`](STATUS.md) — what's done / in progress / not started |
| Thesis writing checklist | [`THESIS_DELIVERABLES.md`](THESIS_DELIVERABLES.md) — per-section deliverables |
| Future improvements | [`IMPROVEMENTS.md`](IMPROVEMENTS.md) — prioritised list |
| How to monitor the live pipeline | [`MONITORING.md`](MONITORING.md) — Kibana + Qdrant + dashboards |
| Reproducing the 93.5% number | [`EVAL.md`](EVAL.md) |

---

## 9. Where to look for the four key thesis numbers

After running the evaluation notebook with `BENCHMARK_CSV = "thesis_benchmark_eval.csv"`:

| Number | Cell | What it says |
|---|---|---|
| Baseline 3-class accuracy | §1.4 | Static + Agent baseline numbers on your data |
| Per-platform breakdown | §1.8 | Accuracy split by YouTube / Twitch / Reddit |
| Memory delta + significance | §4.2 + §4.4 | "memory added X pp, McNemar p=Y" |
| RAG delta + significance | §5.2 + §5.4 | "RAG added X pp, McNemar p=Y" |
| **Cross-pipeline comparison table** | **§7** | **All variants side by side — THE thesis screenshot** |

---

## 10. Acronyms cheatsheet (for the thesis glossary appendix)

| Acronym | Expanded |
|---|---|
| BERT | Bidirectional Encoder Representations from Transformers |
| LLM | Large Language Model |
| RAG | Retrieval-Augmented Generation |
| ES | Elasticsearch |
| XAI | Explainable AI |
| FL | Federated Learning |
| F1 | F-measure (harmonic mean of precision and recall) |
| LOOCV | Leave-One-Out Cross-Validation |
| MTEB | Massive Text Embedding Benchmark |
| API | Application Programming Interface |
| HTTP | HyperText Transfer Protocol |
| IRC | Internet Relay Chat (Twitch's protocol) |
| FIFO | First In, First Out (Kafka queue semantics) |

---

## 11. Next stage — what to build after the eval lands

| When | Direction | What to do |
|---|---|---|
| Right after eval is done | Document Stage 0.5 + Stage 2 + Stage 3 results in the thesis | Use [`THESIS_DELIVERABLES.md`](THESIS_DELIVERABLES.md) checklist |
| Then | Supervisor direction (c) — Multi-Agent | Split the monolithic Tier-2 judge into Risk Scorer + Behavior Profiler + Escalator + Supervisor agents |
| After | Supervisor direction (d) — Advanced XAI | Add SHAP/Captum attention visualisation; structured chain-of-thought reasoning fields on the agent verdicts |
| Later | Supervisor direction (e) — Edge optimisation | Quantize Tier-1 (INT8), adaptive routing, cost-aware orchestration |
| Last | Supervisor direction (g) — Federated Learning | Lightweight on-device Tier-1 + FL weight aggregation |

Don't stack features without measuring them first. The supervisor's stated priority is "consolidating scientific quality" — write up what you have BEFORE adding more.

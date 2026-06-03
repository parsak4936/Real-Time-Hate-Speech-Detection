# Roadmap

Eight stages, sequenced by dependency. The supervisor's seven future-work directions are mapped to Stages 1–7. Stage 0 is the immediate consolidation pass that makes any later measurement defensible.

Each stage lists: **goal**, the supervisor's directions it advances, dependencies, target deliverables, and a concrete success criterion.

---

## Stage 0 — Consolidation & Documentation *(done)*

**Goal.** Lock the foundation: closed taxonomy, single-source prompts, deterministic LLM calls, accurate analytics, complete docs.

**What landed:**
- `src/shared_utils/prompts.py` and `src/shared_utils/llm.py` — single source of truth for every prompt; every `ollama.chat` call now pins `temperature=0.0` and `format="json"` with a one-shot retry on parse failure.
- Closed taxonomy of 10 `env_domain` values + new `env_subgenre` field; clamped at the Context Agent boundary.
- `stats_tool` and `search_tool` switched from `match` to `term` on `.keyword` so filter counts are exact (previously inflated by tokenisation).
- `stats_tool` duplicate-code block removed; performance metrics now reach the analyst.
- `reset_db.py` requires `--yes`.
- `distilbert_processor.py` and `youtube_adapter.py` carry `env_subgenre` through the Universal Schema and into Elasticsearch.
- `scripts/normalize_domains.py` (dry-run default) rewrites existing ES docs to the closed taxonomy.
- Dead files removed: legacy `yt_producer.py`, broken `tweeter_producer.py`, stub `reddit_adapter.py`, broken `llm_client.py`, empty `db_client.py`, orphaned `Zone1_DataHighway/bookmark.txt`.
- `requirements.txt` curated (was a 66 KB UTF-16 conda freeze).
- README rewritten to reflect actual entry points.
- `docs/{ARCHITECTURE,SCHEMA,PROMPTS,EVAL,ROADMAP}.md` added.

**Success criterion (met):** the pipeline boots clean from `git clone` + `pip install -r requirements.txt` + `docker-compose up -d`, the report's 93.5% number is reproducible from `thesis_final_benchmark.csv`, and a new contributor can find the canonical text of every prompt in one place.

---

## Stage 1 — Evaluation Notebook *(done — lightweight form)*

**Maps to supervisor direction:** *(f) Stronger Evaluation Methodologies* — ablation studies, robustness, adversarial testing, statistical significance, cross-domain.

**Why now.** Every subsequent stage's claim ("RAG helped", "memory helped") is a delta vs Stage 0. Without a re-runnable measuring stick, every later improvement becomes anecdotal.

**Dependencies.** Stage 0.

**What landed (Stage 1.0 — lightweight notebook).** A single living notebook, `notebooks/evaluation.ipynb`, structured as one section per Stage with a shared `RESULTS_REGISTRY` at the bottom. Each future Stage appends one row; the cross-stage comparison table picks it up automatically.

- §0 — Setup + helpers (`load_benchmark`, `agent_effective_label`, `compute_three_class_accuracy`, `compute_binary_accuracy`, `confusion_matrix`, `main_domain`).
- §1 — Stage 0 baseline: reproduces Report Tables 4, 6, 7, 8 exactly from `thesis_final_benchmark.csv` (71.0% / 93.5% / 68.4% / 67.1% / 26.4% / 36.10 ms / 6951.81 ms / 192.6×). Per-domain breakdown included.
- §2 — DistilBERT training reference constants (from `Hate_speach_Project.ipynb`).
- §3 — Cross-stage results registry (Stage 0 rows seeded).
- §4 — Template cell for adding a Stage N row.
- §5 — Cross-stage comparison readout.

**Runs offline.** Stage 0 cells do not need Docker, Kafka, Elasticsearch, or Ollama. The CSV is the frozen benchmark.

**Deferred — Stage 1.5 (full eval package).** When the thesis needs formal statistics (McNemar, bootstrap CIs, ablation toggles, cross-domain generalisation matrices), promote the notebook's helpers into a real `src/eval/` package. Trigger condition: when the supervisor asks for confidence intervals, or when a Stage 2+ result is close enough to noise that significance testing matters. Until then the notebook is the source of truth.

**Success criterion (met).** Every headline number in the report's Tables 4, 6, 7, 8 reproduces from a single `Run All` of `notebooks/evaluation.ipynb`, and a new Stage row can be added by copy-pasting one template cell.

---

## Stage 2 — Real-Time Memory & Temporal Context

**Maps to supervisor direction:** *(a) Real-Time Memory & Temporal Context.*

**Why next.** Cheapest research win. The judge currently sees one message in isolation; pulling the last N messages from the same user / same thread out of ES and injecting them into the judge prompt directly attacks the §6.3 "implicit bias blindness" failure mode the report itself identified.

**Dependencies.** Stage 1 (so the improvement is measurable).

**Deliverables.**
- `src/Zone3_Agents/temporal.py` — `get_user_history(author_id, window)`, `get_thread_history(thread_id, window)` over ES.
- New judge prompt variant `build_judge_prompt_with_context(...)` that takes a list of prior messages and reasons over the rolling window.
- Behavioural fingerprint: short, structured summary of a user's recent labelling pattern (e.g. "8 Normal / 2 Offensive in last 20 messages").
- Configuration knob: `MEMORY_WINDOW_SIZE` and `MEMORY_LOOKBACK_HOURS` in `shared_utils/config.py`.

**Success criterion.** Stage-1 harness shows ≥ 3 percentage-point accuracy lift on the False-Negative class (the implicit-toxicity bucket the report flagged) without significant False-Positive regression. McNemar p < 0.05.

---

## Stage 3 — Retrieval-Augmented Moderation (RAG)

**Maps to supervisor direction:** *(b) RAG.*

**Why here.** Builds on Stage 2: now that temporal context works, layer a vector index over the entire historical moderation log so the judge can retrieve precedent ("we already saw this dogwhistle and labelled it HATE last month").

**Dependencies.** Stages 1 & 2.

**Deliverables.**
- Vector DB choice: **Qdrant** (Docker, free, fast) or **Chroma** (in-process, simpler).
- `src/Zone3_Agents/rag.py` — embed every reviewed ES record on write, index it; at judge time retrieve k=5 nearest precedents.
- Embedding model — start with `sentence-transformers/all-MiniLM-L6-v2` (lightweight, edge-friendly).
- Judge prompt variant that includes the retrieved precedents as structured context.

**Success criterion.** Harness shows further ≥ 2 pp accuracy lift over Stage 2 on the dogwhistle / coded-language subset (curate one). Ablation cleanly separates Stage 2 (memory) from Stage 3 (RAG) contributions.

---

## Stage 4 — Multi-Agent Decomposition

**Maps to supervisor direction:** *(c) Multi-Agent Architectures.*

**Why here.** Only meaningful once Stages 2 & 3 produce the data (history, retrieved precedents) the specialist agents would consume.

**Dependencies.** Stages 1–3.

**Deliverables.**
- Risk Scorer — outputs a 0–1 risk score (not a categorical label) using the retrieved precedents.
- Behavior Profiler — produces the structured user fingerprint from Stage 2 as a dedicated agent, not a function call.
- Escalator — decides whether to surface to a human or auto-action.
- Supervisor — meta-agent that reconciles disagreement between Risk Scorer and Profiler.
- Leader Agent reframed as orchestrator over these four specialists (not a tool-call router).

**Success criterion.** Harness shows the multi-agent system out-performs the monolithic Stage 3 judge on at least one of: precision on HATE, recall on subtle False Negatives, or escalation efficiency (fraction of cases that need human review).

---

## Stage 5 — Advanced Explainability & XAI

**Maps to supervisor direction:** *(d) Advanced Explainability and XAI.*

**Why here.** Instruments Stage 4. With multiple specialist agents in play, the report becomes about *which* agent contributed *which* reasoning step.

**Dependencies.** Stage 4.

**Deliverables.**
- DistilBERT side: SHAP / Captum attention visualisation. Token-level attribution stored in ES alongside the prediction.
- LLM side: structured rationale extraction — the judge emits not just `explanation` but a tagged tree: `(rule_invoked, evidence_span, confidence)`.
- Confidence calibration: temperature scaling on DistilBERT logits; LLM self-assessed confidence scored against ground truth.
- Human-vs-LLM reasoning comparison: small qualitative study, 50 records, human annotators write rationales; vector-similarity score between LLM and human rationales.

**Success criterion.** Per-record decision can be displayed in a Kibana panel as a labelled reasoning chain, and there is a numeric calibration score (Brier or ECE) reported in the thesis.

---

## Stage 6 — Edge-Aware Optimization

**Maps to supervisor direction:** *(e) Edge-Aware Optimization.*

**Why here.** Optimises something now known to work. Premature without Stages 4–5.

**Dependencies.** Stage 5.

**Deliverables.**
- Quantized variants of DistilBERT (INT8) — measure latency and accuracy delta.
- Adaptive routing: only escalate to the 120 B model when uncertainty exceeds a learned threshold; otherwise use a quantized 7 B local model.
- Batching: queue Tier-2 requests and submit in groups of N to amortise round-trip cost.
- Cost-aware orchestrator: per-decision $ cost stored in ES; Kibana dashboard reports cost per 1k messages.

**Success criterion.** Tier-2 latency drops at least 3× without > 1 pp accuracy regression. Cost per 1k records dashboarded.

---

## Stage 7 — Federated Learning

**Maps to supervisor direction:** *(g) Federated Learning.*

**Why last.** Long-tail research direction that builds the deployment story. Decentralises Stage 6.

**Dependencies.** Stage 6.

**Deliverables.**
- Lightweight on-device Tier-1 (the quantized model from Stage 6).
- FL aggregator: clients train locally on their stream's data, only weight deltas are shared.
- Privacy-preserving aggregation (differential privacy noise on the delta).

**Success criterion.** Demonstrate the FL Tier-1 within ≤ 2 pp of centrally-trained DistilBERT on a held-out test set; the thesis can argue privacy gains quantitatively.

---

## Cross-cutting reminders

- The supervisor explicitly said these directions are **not a checklist** and **not to be done all at once**. The order above is one defensible sequencing; pivots are fine. The dependency arrows are real, though — don't skip Stage 1.
- Every stage that changes prompts or model choice invalidates `thesis_final_benchmark.csv`. Always re-measure before citing numbers.
- The current `gpt-oss:120b-cloud` model is the baseline. Switching is allowed but invalidates the report's headline figures.
- Privacy: as soon as Stage 3's vector DB starts persisting user-tied embeddings, the §7.1 "Dynamic Contextual Boundaries" concern becomes load-bearing. Plan a retention policy before turning RAG on.

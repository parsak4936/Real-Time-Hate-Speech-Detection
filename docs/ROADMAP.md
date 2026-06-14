# Roadmap

Eight stages, sequenced by dependency. The supervisor's seven future-work directions are mapped to Stages 1–7. Stage 0 is the immediate consolidation pass that makes any later measurement defensible.

> **Note on naming.** The "Stage 0 / 1 / 2 …" labels in this document are a **planning lens** — how we sequence the work and how we talk about progress with the supervisor. They are *not* the code's vocabulary. Inside `src/`, `scripts/`, the notebook, and the ES schema, names are descriptive (`replay_with_memory.py`, `agent_final_decision_with_memory`, `Tier-1 + Tier-2 with memory`, etc.) so a reader who hasn't seen this document can still navigate the codebase.

Each stage lists: **goal**, the supervisor's directions it advances, dependencies, target deliverables, and a concrete success criterion.

---

## Stage 0 — Consolidation & Documentation *(done)*

### Stage 0.5 — Agentic Context Agent + externalised taxonomy *(done)*

Initial Stage 0 closed-list pin was the wrong fit: it turned the Context Agent into a classifier and contradicted the project's agentic moderation goal. Stage 0.5 corrects this:

- The closed `ENV_DOMAINS` / `DOMAIN_DEFAULT_STRICTNESS` constants are deleted from `src/shared_utils/prompts.py`.
- The taxonomy moves to `config/taxonomy.yaml` — a seed list, operator-extensible, with per-canonical aliases and `default_strictness` fallbacks.
- The Context Agent prompt is rewritten as a discovery prompt: no list, no domain-named examples for strictness, just principles. The LLM proposes `env_domain` freely.
- `shared_utils/taxonomy.py::normalise_domain()` maps free-text proposals onto the canonical seed (exact → alias → fuzzy → unknown-policy). The LLM's raw proposal is preserved in `env_domain_raw`; the match quality is stored in `env_domain_match`; off-seed proposals append to `data/pending_taxonomy.log` for operator review.
- Strictness is LLM-reasoned per stream with a justification stored in `env_strictness_reasoning`. The YAML's `default_strictness` is consulted only as a fallback when the LLM output is malformed.
- Universal Schema and ES doc both carry the new fields; see `docs/SCHEMA.md`.

**Why this matters for the thesis.** The discovery vs. classification distinction is the agentic-moderation claim. Stage 0.5 makes that claim mechanically true: the LLM is no longer constrained to a Cartesian set of categories the engineer pre-declared. The pipeline curates a canonical key for analytics consistency, but it does so *after* the LLM's reasoning, not before.


**Goal.** Lock the foundation: closed taxonomy, single-source prompts, deterministic LLM calls, accurate analytics, complete docs.

**What landed:**
- `src/shared_utils/prompts.py` and `src/shared_utils/llm.py` — single source of truth for every prompt; every `ollama.chat` call now pins `temperature=0.0` and `format="json"` with a one-shot retry on parse failure.
- Closed taxonomy of 10 `env_domain` values + new `env_subgenre` field; clamped at the Context Agent boundary.
- `stats_tool` and `search_tool` switched from `match` to `term` on `.keyword` so filter counts are exact (previously inflated by tokenisation).
- `stats_tool` duplicate-code block removed; performance metrics now reach the analyst.
- `reset_db.py` requires `--yes`.
- `distilbert_processor.py` and `youtube_adapter.py` carry `env_subgenre` through the Universal Schema and into Elasticsearch.
- `scripts/normalize_domains.py` (dry-run default) rewrites existing ES docs to the closed taxonomy.
- Dead files removed: legacy `yt_producer.py`, broken `tweeter_producer.py`, stub `reddit_adapter.py`, broken `llm_client.py`, empty `db_client.py`, orphaned `ingestion/bookmark.txt`.
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

## Stage 2 — Real-Time Memory & Temporal Context *(code landed; awaiting evaluation data)*

**Maps to supervisor direction:** *(a) Real-Time Memory & Temporal Context.*

**Why next.** Cheapest research win. The judge previously saw one message in isolation; pulling the last N messages from the same user / same thread out of ES and injecting them into the judge prompt directly attacks the §6.3 "implicit bias blindness" failure mode the report itself identified.

**Dependencies.** Stage 1 (eval notebook exists).

**What landed.**
- `src/shared_utils/memory.py` — `get_user_history`, `get_thread_context`, `get_user_behavior_fingerprint`, `fetch_memory_bundle`. All four return prompt-ready strings; no LLM calls, pure ES retrieval.
- `src/shared_utils/prompts.py::build_judge_prompt_with_memory` — Stage 2 prompt variant with three contextual rules layered on the original four forensic rules. The Stage 0 `build_judge_prompt` stays as the no-memory baseline.
- `src/shared_utils/config.py` — `MEMORY_ENABLED`, `MEMORY_USER_WINDOW_SIZE`, `MEMORY_THREAD_WINDOW_SIZE`, `MEMORY_LOOKBACK_HOURS`, `MEMORY_FINGERPRINT_WINDOW`. All env-driven.
- `xai_batch_judge.py` and `xai_judge_tool.py` rewired to use the memory variant when `MEMORY_ENABLED`. ES doc gains `agent_memory_used`, `agent_memory_user_msgs`, `agent_memory_thread_msgs`, `agent_memory_user_profile`.
- `scripts/replay_with_memory.py` — re-judges already-reviewed ES records WITH memory, writing to `agent_final_decision_with_memory` / `agent_explanation_with_memory`. Dry-run default. `--csv` flag for targeted replay; `--limit` for smoke tests. Idempotent.
- `src/export_subset.py` — exported CSV now includes `message_id` + `timestamp` (for ID-based replay matching), `agent_final_decision_with_memory`, `agent_explanation_with_memory`, all `agent_memory_*` fields.
- `notebooks/evaluation.ipynb` — new §4 with v1-vs-v2 comparison, per-domain delta, McNemar's test, memory usage distribution, and a new `RESULTS_REGISTRY` row.

**What is still needed before the metric can be cited.**
The Stage 2 numbers come from running:
```bash
python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply
python src/export_subset.py thesis_final_benchmark.csv
```
then re-running the notebook. The replay needs Docker + ES + Ollama running and the 459 internship records (or a freshly collected equivalent) live in ES.

**Success criterion.** Notebook §4.2 reports a positive delta (v2 - v1) in 3-class accuracy with McNemar p < 0.05 (§4.4). Per-domain breakdown (§4.3) shows where memory contributed most — expected to be Gaming (high sarcasm density) and News/Politics (where prior toxic posts amplify a borderline single message).

---

## Stage 3 — Retrieval-Augmented Moderation (RAG) *(code complete; evaluation via leave-one-out, no new labels needed)*

**Maps to supervisor direction:** *(b) RAG.*

**Why here.** Builds on Stage 2: now that temporal context works, layer a vector index over the entire historical moderation log so the judge can retrieve precedent ("we already saw this dogwhistle and labelled it HATE last month").

**Dependencies.** Stages 1 & 2.

**What landed in the scaffolding pass.**
- Vector DB: **Qdrant 1.10.1** added to `docker-compose.yml` (port 6333 HTTP, 6334 gRPC, persistent volume `qdrant_data`).
- `config/rag.yaml` — operator-editable knobs: embedding model name, dim, device, batch size, top-k, similarity threshold.
- `src/shared_utils/config.py` — env knobs: `RAG_ENABLED` (default False), `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`.
- `src/shared_utils/rag.py` — lazy Qdrant client + sentence-transformers embedder + `index_record`, `index_records_bulk`, `retrieve_similar`, `format_precedents_for_prompt`, `fetch_retrieval_bundle`. Symmetric API to `memory.py`.
- `scripts/build_rag_index.py` — one-off bootstrap walker. Dry-run default; `--apply`, `--limit`, `--reviewed-only` flags. Idempotent via blake2b-hashed point IDs.
- `src/shared_utils/prompts.py::build_judge_prompt_with_memory_and_rag` — defined, includes a new `RETRIEVED PRECEDENTS` block and a new contextual rule "Precedent Reasoning".
- `requirements.txt` — added `qdrant-client>=1.10`, `sentence-transformers>=2.7`, `scipy>=1.10`.

**What landed in the activation step.**
- `src/shared_utils/prompts.py::build_judge_prompt_with_rag` — RAG-only variant for clean Stage 3 isolation (no memory confound).
- `scripts/seed_rag_from_csv.py` — embeds the internship benchmark CSV directly into Qdrant. `human_ground_truth` deliberately omitted from the payload to prevent label leakage.
- `scripts/replay_with_rag.py` — leave-one-out cross-validation against the CSV. Writes `agent_final_decision_with_rag`, `agent_explanation_with_rag`, `agent_retrieved_precedent_ids`, `agent_retrieval_count`.
- `notebooks/evaluation.ipynb` §5 — RAG-vs-baseline comparison, per-domain breakdown, McNemar's test, registry entry. Mirrors §4 (temporal memory) structurally.
- `docs/RUNBOOK.md` Path A — three-command recipe (`up qdrant`, `seed_rag_from_csv`, `replay_with_rag`) and the notebook step.

**Evaluation requires.** Qdrant running and one round of seed + replay. No new live data, no manual labelling. ~15-30 minutes wall-clock.

**Live-pipeline wiring** (`RAG_ENABLED=True` in the always-on Tier-2 sweep) is still deferred — it requires Stage 2 data first so memory + RAG can be measured together. Live wiring lands when Stage 2 has a measured number too.

**Success criterion.** Notebook §5 (once it exists) reports a positive delta (with_memory_and_rag − with_memory) in 3-class accuracy on a curated dogwhistle / coded-language subset, with McNemar p < 0.05. Per-domain breakdown cleanly separates the temporal-memory contribution (Stage 2) from the semantic-retrieval contribution (Stage 3).

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

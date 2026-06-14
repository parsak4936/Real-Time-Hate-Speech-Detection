# Glossary — every tool, term, and concept in this project

Written so you can answer "what is X?" / "why X over Y?" in your thesis defence without preparation. Each entry gives:
- **What it is** — one-paragraph definition.
- **Why we use it** — the role it plays in this codebase.
- **Alternatives** — what else we could have used and the trade-off.
- **Citation** — where applicable, the canonical paper / docs to cite.

Organised by architecture layer to match the report's Figure 1, then by feature stage.

---

## Layer 1 — Ingestion

### YouTube Live Chat (via `pytchat`)
**What.** `pytchat` is a Python library that opens an unauthenticated connection to YouTube's live-chat backend and yields each message as a structured event. It does NOT use the official YouTube Data API (which requires an API key and has strict quotas).
**Why.** Free tier; no Google Cloud project setup needed; near-real-time delivery (~1–2 second lag).
**Alternatives.**
- YouTube Data API v3 (`liveChatMessages.list`) — official, but rate-limited and requires API key.
- Twitch IRC (`twitchio`) — for Twitch streams; same role, different platform.
- Reddit Streaming API (`praw`) — for Reddit comment streams.
**Citation.** `pytchat`: https://github.com/taizan-hokuto/pytchat

### HTML metadata scraping
**What.** `youtube_adapter.py` pulls the public watch-page HTML and regex-extracts the title, channel name, description, and live status. Avoids needing the YouTube Data API key.
**Why.** Frees us from API quotas during development. The Context Agent only needs broad-strokes metadata.
**Alternatives.** The YouTube Data API gives clean structured metadata (no regex fragility) but costs an API key.
**Caveat.** Fragile against YouTube HTML changes. For production, switching to the official API is the obvious upgrade.

---

## Layer 2 — Streaming backbone

### Apache Kafka
**What.** A distributed, fault-tolerant message broker. Producers write events to topics; consumers read them. Decouples producer throughput from consumer processing speed.
**Why.** A live-stream pipeline must survive sudden spikes (viral moments produce 1000+ messages/sec); Kafka queues them so the slower DistilBERT processor never drops data. Industry standard.
**Alternatives.**
- RabbitMQ — message broker but not optimised for high-throughput streaming.
- Redis Streams — simpler, in-memory; loses data on restart.
- AWS Kinesis — managed equivalent; costs money and ties to AWS.
- Apache Pulsar — newer, multi-tenant; less ecosystem maturity than Kafka.
**Version here.** Confluent CP-Kafka 7.5.0 (Docker image), with port 9093 externally for host programs.
**Citation.** Kreps, Narkhede, Rao, "Kafka: a Distributed Messaging System for Log Processing", *Proc. NetDB*, 2011.

### Apache Zookeeper
**What.** A distributed coordination service that Kafka 7.5.0 uses for cluster metadata (which broker hosts which partition, etc.).
**Why.** Required by this version of Kafka.
**Note.** Newer Kafka versions (3.x+) support KRaft mode and don't need Zookeeper. Keeping Zookeeper here matches the docker-compose pin.

### Apache Spark
**What.** A distributed compute engine for large-scale data processing. Decouples raw ingestion from inference.
**Why.** The internship report mentioned Spark as the "processing engine" between Kafka and the AI processor. In current code we read directly from Kafka with `kafka-python` — Spark sits in `docker-compose.yml` for thesis-architecture completeness but isn't on the hot path.
**Alternatives.**
- Apache Flink — true streaming; more complex.
- Dask / Ray — Python-native distributed compute; better for ML-heavy workloads.
- Direct kafka-python (what we actually use) — simplest; works at our throughput.
**Citation.** Zaharia et al., "Apache Spark: A Unified Engine for Big Data Processing", *Comm. ACM*, 2016.

### Docker + Docker Compose
**What.** Container runtime + orchestrator. `docker-compose.yml` declares all infra services; one command brings them up.
**Why.** Reproducibility for the thesis: examiner runs `docker-compose up -d` and gets the exact same Kafka / ES / Qdrant cluster you built against.
**Alternatives.** Kubernetes (overkill for a single-machine thesis project); manual installation (defeats reproducibility).

---

## Layer 3 — Tier-1 Static Classifier

### DistilBERT
**What.** A distilled version of BERT (Bidirectional Encoder Representations from Transformers). 60% the size of BERT, 95% of the performance. Encoder-only transformer.
**Why.** Fast enough for real-time inference (~36 ms/message on CPU), accurate enough as a first-pass filter (79.4% val accuracy on our 53k corpus). Battle-tested.
**Alternatives.**
- BERT-base — slightly more accurate but slower.
- RoBERTa — better generally; would need a new fine-tune. Worth trying in future thesis iterations.
- HateBERT — domain-specific fine-tune for abusive language; a defensible choice for the report.
- DeBERTa — disentangled attention; top of GLUE; larger.
- Small encoder-only models like ALBERT or BiLSTM baselines.
**Citation.** Sanh et al., "DistilBERT, a distilled version of BERT", arXiv:1910.01108, 2019.

### Fine-tuning
**What.** Take a pre-trained language model and train its weights further on a task-specific dataset. We fine-tuned `distilbert-base-uncased` on 43,000 hate-speech samples for 2 epochs.
**Why.** Pre-training learns general language; fine-tuning specialises for the moderation task.
**Hyperparameters in this project** (see `src/Hate_speach_Project.ipynb` and Internship Report §4.2): AdamW optimiser, learning rate 5e-5, weight decay 0.01, batch size 8, max token length 128, 2 epochs.
**Alternatives.** Prompting a zero-shot classifier; LoRA / QLoRA (parameter-efficient fine-tuning).

### Hugging Face `transformers`
**What.** Python library that provides standardised access to thousands of pre-trained models (BERT, DistilBERT, GPT, T5, etc.) with a unified API.
**Why.** Industry-standard. Lets us swap models by changing one string.
**Alternatives.** Direct PyTorch / TensorFlow (more work); ONNX runtime (faster inference, more setup).

### Tokenizer (DistilBertTokenizer)
**What.** Converts raw text into the integer IDs the model expects. WordPiece subword tokenisation: out-of-vocabulary words are split into in-vocabulary pieces.
**Why.** Required by DistilBERT.
**Pre-processing here.** `max_length=128` truncates long messages; `padding=True` aligns short ones.

---

## Layer 4 — Storage and visualisation

### Elasticsearch
**What.** A distributed search engine + document store. Schemaless JSON documents; full-text and aggregation queries.
**Why.** Live chat moderation needs (1) fast full-text search for analyst tools, (2) flexible schema as the pipeline evolves (we added Stage 0.5 fields without migrating data), (3) aggregation queries for the stats tool.
**Alternatives.**
- MongoDB — better as a primary store; less powerful search.
- PostgreSQL + pg_trgm + tsvector — relational; harder to scale full-text search.
- Solr — Elasticsearch's older cousin; similar capabilities, smaller ecosystem.
- OpenSearch — Amazon's fork; identical API for our purposes.
**Version.** Elasticsearch 8.10.2 (with `xpack.security.enabled=false` for dev simplicity).
**Citation.** Official docs at https://www.elastic.co/guide/

### Kibana
**What.** Visualisation front-end for Elasticsearch. Dashboards, time-series charts, free-form data exploration.
**Why.** Lets you eyeball the pipeline in real time without writing a UI.
**Alternatives.** Grafana (more powerful for time-series; requires custom data source); custom Streamlit/Plotly dashboard (we add one in Stage monitoring).
**Version.** Kibana 8.10.2 (must match Elasticsearch version).

### Universal Schema (design pattern)
**What.** A single JSON shape that every producer must conform to before pushing to Kafka. Fields: `payload_text`, `source_platform`, `env_domain`, `env_subgenre`, `env_strictness`, `env_domain_raw`, `env_domain_match`, `env_strictness_reasoning`, `platform_metadata`.
**Why.** The processor doesn't need to know what platform a message came from. Adding a new producer (Twitch, Reddit) means a new adapter, not a processor change.
**See.** `docs/SCHEMA.md` for the full field contract.

---

## Layer 5 — Tier-2 Agents

### LLM-as-a-Judge
**What.** Using a large language model as an evaluator / classifier rather than as a text generator. The LLM receives a structured prompt, returns a structured verdict (here: `Correct` / `False Positive` / `False Negative`).
**Why.** LLMs encode broad contextual / cultural / linguistic knowledge a small fine-tuned classifier (DistilBERT) cannot. Trade-off: ~200× slower per inference.
**Citation.** Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv:2306.05685, 2023.

### Ollama
**What.** A local LLM serving stack — pulls quantised model weights, exposes an OpenAI-compatible HTTP API on `localhost:11434`. Supports Llama, Mistral, GPT-OSS, Qwen, and dozens more.
**Why.** Run a 120B-parameter LLM on a single machine without writing CUDA code or paying per-token API fees.
**Alternatives.**
- **vLLM** — production-grade; faster batched inference; requires more setup.
- **llama.cpp** — closest to bare-metal; pure-C/C++ inference engine; what Ollama wraps under the hood.
- **LM Studio** — GUI; aimed at casual users.
- **HuggingFace TGI (Text Generation Inference)** — production server; more dependencies.
- **Cloud APIs** — Anthropic Claude, OpenAI GPT-4, Google Gemini. Faster, cleaner output, but per-token cost and external dependency.
**Citation.** https://ollama.com/

### `gpt-oss:120b-cloud` (the model alias used)
**What.** OpenAI's open-weight "GPT-OSS" 120-billion-parameter model, run via Ollama's cloud routing (the `-cloud` suffix routes inference to Ollama's hosted cluster rather than the local machine — useful when the local GPU can't hold 120B weights).
**Why.** Strong reasoning at zero per-token cost (within Ollama's free-tier limits).
**Alternatives.** `llama3.1:70b`, `qwen2.5:72b`, `mistral-large`, GPT-4 via API, Claude 3.5 Sonnet via API.

### Zero-shot prompting
**What.** Asking an LLM to perform a task purely from instructions in the prompt, without showing it labelled examples.
**Why.** Cheap to iterate; no training data needed for new tasks.
**Trade-off.** Lower accuracy than fine-tuning or few-shot for narrow tasks.
**Alternatives.** Few-shot prompting (include 1-5 examples in the prompt); fine-tuning (most accurate, most expensive).

### JSON mode / structured output (`format="json"`)
**What.** Forces Ollama (and most modern LLM APIs) to constrain decoding so the output is guaranteed syntactically valid JSON.
**Why.** Eliminates "the LLM returned half-JSON wrapped in markdown" failures. The Stage 0 wrapper (`shared_utils/llm.py`) uses this on every call.
**Alternatives.** OpenAI structured outputs (schema-validated); JSON schema constrained decoding (Outlines, Guidance libraries).

### Temperature
**What.** A scalar that controls LLM output randomness. `0.0` = deterministic (argmax token); `1.0+` = creative.
**Why we pin to 0.0.** The judge is supposed to be a classifier, not a creative writer. Determinism + JSON mode + the 1-retry wrapper in `llm.py` together make our Ollama calls behave like a strict structured-output classifier.

### Agentic AI / Agent
**What.** A loose term, but in this project an "agent" means: an LLM call that *reasons over context* (forensic rules, memory, retrieved precedents) and emits a *structured action* (verdict, tool call, normalisation decision), rather than just generating free-form text.
**Our agents.** Context Agent (Layer 1), Judge Agent (xai_batch_judge, xai_judge_tool), Leader Agent (orchestrator).
**Reference.** Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", ICLR 2023.

---

## Stage 0.5 — Agentic discovery

### Closed-list vs open-taxonomy classification
**What.** The initial implementation gave the Context Agent a fixed list of 10 categories and asked it to **pick**. That's classification. The Stage 0.5 rewrite removes the list — the LLM **proposes** any category in free text, and a separate normaliser maps the proposal to a canonical seed.
**Why this matters for the thesis.** The project's stated goal is *agentic* moderation. Showing the LLM a menu and forcing a pick contradicts that goal. The discovery-then-normalisation pattern preserves agentic behaviour while keeping analytics consistent.

### `config/taxonomy.yaml`
**What.** A YAML file with the seed taxonomy (16 canonicals: Gaming, Politics, News, Music, Sports, Education, Entertainment, Technology, Lifestyle, Health, E-commerce, Reviews, Forum, Customer Support, Social Media, General). Operator-editable.
**Why YAML.** Human-friendly, supports comments, is the de-facto standard for config files (Docker Compose, Kubernetes, GitHub Actions).
**Alternatives.** JSON (no comments), TOML (less common for config of this size), Python file (mixes code and data).

### Taxonomy normalisation (`shared_utils/taxonomy.py`)
**What.** Maps the LLM's free-text proposal onto a canonical seed via four passes: exact name match → alias match → fuzzy match (`difflib.SequenceMatcher` ratio ≥ 0.75) → unknown policy.
**Why fuzzy match.** Catches "esports tournament" → Gaming, "live news debate" → News, etc.
**Why log unknowns.** When the LLM proposes a category we don't recognise (e.g. "underwater basket weaving championship"), we append it to `data/pending_taxonomy.log` for human review. **This is itself a publishable thesis result**: "the LLM proposed N off-seed categories in M streams, suggesting the seed taxonomy missed K relevant domains".

---

## Stage 2 — Temporal Memory & Conversational Context

### Temporal memory
**What.** Pulling the same author's recent messages out of Elasticsearch and injecting them into the judge prompt as context.
**Why.** A single message is ambiguous without history. A user who has posted 16 Normal messages in the last hour is unlikely to mean a borderline message as a slur; a user with a pattern of toxic posts probably does. The Stage 2 prompt makes the judge reason over this.
**Address.** The "implicit bias blindness" failure mode the internship report flagged in §6.3.

### Thread context
**What.** The last N messages in the same chat thread, regardless of author. Catches pile-ons, reply chains, and banter.

### Behavioural fingerprint
**What.** A one-line structured summary of a user's recent labelling pattern. Example: `"Last 20 msgs: 16 Normal / 3 OFFENSIVE / 1 HATE. Most recent flagged: 2h ago."`
**Why.** A compressed numeric signal the LLM can reason about quickly, alongside the full history.

---

## Stage 3 — Retrieval-Augmented Moderation (RAG)

### Retrieval-Augmented Generation (RAG)
**What.** A pattern where a language model is given retrieved external context before generating output. Instead of relying purely on parametric memory (what the model learned during training), RAG retrieves relevant documents at query time and injects them into the prompt.
**Why for moderation.** "We have seen this kind of message before, it was usually a False Positive in gaming streams" is a far stronger signal than the LLM's general world knowledge alone. Reduces hallucination, grounds decisions in our specific corpus.
**Citation.** Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020.

### Vector database
**What.** A specialised database optimised for similarity search over high-dimensional vectors (typically 384–1536-dim embeddings). Returns "k nearest neighbours" by cosine similarity or Euclidean distance.
**Why.** Text similarity isn't a substring match; it's semantic. "kill that boss" and "destroy that boss" should retrieve each other even though they share only one word. Vector DBs make this fast at scale.

### Qdrant
**What.** Open-source, Rust-written vector database. HTTP and gRPC APIs. Persistent on disk, fast in-memory query.
**Why we chose it.** Docker-native (one container), free, production-grade, sufficient for our scale (~10k records). Has a built-in web dashboard at port 6333.
**Alternatives.**
- **Chroma** — Python-native, in-process; simpler but harder to scale.
- **Pinecone** — managed SaaS; great DX, costs money.
- **Weaviate** — feature-rich (built-in modules for OpenAI etc.), heavier.
- **Milvus** — high-scale; more operational overhead.
- **pgvector** — PostgreSQL extension; lets you reuse an existing Postgres deployment.
- **FAISS** — Facebook's similarity-search library; no server, just a library; you handle persistence yourself.
**Version.** Qdrant 1.10.1 (pinned in docker-compose).
**Citation.** https://qdrant.tech/documentation/

### Sentence Transformers (the library)
**What.** A wrapper around Hugging Face transformers that makes producing sentence-level embeddings (rather than token-level) a one-liner.
**Why.** We need one vector per chat message; the library handles the pooling (mean / CLS / etc.) under the hood.
**Citation.** Reimers, Gurevych, "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks", EMNLP 2019.

### `all-MiniLM-L6-v2` (the embedding model we use)
**What.** A 6-layer distilled transformer that produces 384-dimensional sentence embeddings. ~80 MB on disk. CPU-fast.
**Why.** Best size/quality trade-off in the sentence-transformers catalogue. Multilingual-leaning. Standard choice for "lightweight RAG".
**Alternatives.**
- `all-mpnet-base-v2` — better quality, ~3× slower, 768-dim.
- `intfloat/multilingual-e5-small` — better for non-English chat.
- `BAAI/bge-small-en-v1.5` — top of the MTEB leaderboard.
- OpenAI `text-embedding-3-small` — paid API; very high quality.
- Cohere `embed-english-v3.0` — paid API.

### Embedding
**What.** A fixed-length vector (here: 384 floats) that represents a piece of text in a continuous space where similar meanings live close together. Produced by passing the text through the embedding model.
**Property.** Cosine similarity between two embeddings is a proxy for semantic similarity between the original texts.

### Cosine similarity
**What.** The cosine of the angle between two vectors. Ranges from −1 (opposite) through 0 (orthogonal) to 1 (identical direction). For unit-normalised embeddings this is just the dot product.
**Why.** Length-invariant — only the *direction* of the embedding (which captures meaning) matters, not its magnitude (which can vary with text length).
**Alternatives.** Dot product (when vectors aren't normalised), Euclidean distance (rarely better for text).

### MTEB (Massive Text Embedding Benchmark)
**What.** A community leaderboard for sentence-embedding models across dozens of tasks. https://huggingface.co/spaces/mteb/leaderboard
**Why mentioned.** When defending "why MiniLM and not X?", citing MTEB rankings gives a quantitative answer.

### Leave-one-out cross-validation (LOOCV)
**What.** Evaluation method where, for each example in a dataset, you hold it out, retrieve precedents from the other N−1 examples, then evaluate against the held-out example. Cycle through every example.
**Why for us.** It's why Stage 3 can be evaluated without new manual labelling — the internship CSV has both queries and would-be precedents. Each row is judged with the other 458 as the retrieval corpus.
**Caveat.** If duplicate texts exist in the corpus, simple text-match LOOCV would leak — we use `message_id` exclusion to prevent self-retrieval.

---

## Evaluation concepts

### 3-class accuracy
**What.** Proportion of predictions that exactly match the human label across `HATE` / `OFFENSIVE` / `Normal`. Strictest metric.

### Binary accuracy (toxic vs normal)
**What.** Collapse `HATE` and `OFFENSIVE` into one "toxic" class, then measure accuracy. Useful because the OFFENSIVE/HATE boundary is fuzzy even for humans.

### Confusion matrix
**What.** A 3×3 table (for 3-class) showing predicted vs actual counts. Diagonal = correct; off-diagonal cells reveal which classes get confused with which.
**Why.** Lets the thesis say "the static model confuses HATE with Normal more than the agent does" with hard numbers.

### McNemar's test
**What.** A statistical test for paired binary outcomes. Specifically: "of the cases where the two classifiers disagreed, is the imbalance large enough to be unlikely under the null hypothesis (they're equivalent)?". Computes a χ²-distributed statistic with 1 degree of freedom.
**Why we use it.** Comparing baseline vs with-memory or baseline vs with-RAG: we want to claim the new variant *significantly* outperformed the old one, not just by 1-2 cases. McNemar's test is the standard for this.
**Citation.** McNemar, "Note on the sampling error of the difference between correlated proportions or percentages", Psychometrika, 1947. (Use the `scipy.stats.chi2` survival function for the p-value.)

### F1 score
**What.** Harmonic mean of precision and recall. Used in the report for the Tier-1 baseline (`val_f1 = 0.796`).
**Why a mean.** A model can fake high accuracy by predicting "Normal" for everything; F1 punishes that.

---

## Cross-cutting concepts

### Idempotency
**What.** A property where running an operation multiple times has the same effect as running it once.
**Why important here.** `scripts/build_rag_index.py`, `replay_with_memory.py`, `replay_with_rag.py`, `seed_rag_from_csv.py` all upsert (overwrite on duplicate ID) rather than insert. Re-running them is safe.

### Dry-run mode
**What.** Scripts default to "print what would happen" mode; `--apply` is needed to actually write. Used by `reset_db.py`, `normalize_domains.py`, `build_rag_index.py`, `replay_with_memory.py`, `seed_rag_from_csv.py`, `replay_with_rag.py`.
**Why.** Destructive operations should always require explicit consent.

### Schema versioning via column suffixes
**What.** Instead of overwriting `agent_final_decision` when we change the prompt, we add a new column (`agent_final_decision_with_memory`, `agent_final_decision_with_rag`, etc.).
**Why.** Lets the eval notebook compare variants directly, and guarantees the original internship baseline numbers stay reproducible forever.

### Universal Schema (re-mention)
**What.** The Kafka payload shape the ingestion adapters must produce. Producers don't talk to the processor; they talk to a schema.
**Why.** Adding a new platform = adding a new adapter, not modifying the processor.

---

## Files this glossary references

If you want to cite or read the implementation of any concept above:

| Concept | File |
|---|---|
| Universal Schema | [`docs/SCHEMA.md`](SCHEMA.md), `src/static_classifier/distilbert_processor.py` |
| Closed → open taxonomy | `src/shared_utils/prompts.py`, `src/shared_utils/taxonomy.py`, `config/taxonomy.yaml` |
| Temporal memory | `src/shared_utils/memory.py` |
| RAG | `src/shared_utils/rag.py`, `config/rag.yaml`, `scripts/seed_rag_from_csv.py`, `scripts/replay_with_rag.py` |
| Judge prompts (all variants) | `src/shared_utils/prompts.py` |
| Evaluation harness | `notebooks/evaluation.ipynb` |
| Ollama wrapper (temp=0 + json mode + retry) | `src/shared_utils/llm.py` |

---

## Citations cheat-sheet for the thesis bibliography

```
- BERT / DistilBERT:  Sanh, Debut, Chaumond, Wolf, 2019 (arXiv:1910.01108)
- BERT (original):    Devlin et al., 2019 (arXiv:1810.04805)
- RoBERTa:            Liu et al., 2019 (arXiv:1907.11692)
- HateBERT:           Caselli et al., 2021 (WOAH)
- Davidson dataset:   Davidson et al., 2017 (ICWSM)
- HateXplain:         Mathew et al., 2021 (AAAI)
- ToxiGen:            Hartvigsen et al., 2022 (ACL)
- Kafka:              Kreps, Narkhede, Rao, 2011 (NetDB)
- Spark:              Zaharia et al., 2016 (Comm. ACM)
- LLM-as-a-Judge:     Zheng et al., 2023 (arXiv:2306.05685)
- Llama Guard:        Inan et al., 2023 (arXiv:2312.06674)
- ReAct (Agentic):    Yao et al., 2023 (ICLR)
- RAG (original):     Lewis et al., 2020 (NeurIPS)
- Sentence-BERT:      Reimers, Gurevych, 2019 (EMNLP)
- McNemar:            McNemar, 1947 (Psychometrika)
- Llama 3:            AI@Meta, 2024 (arXiv:2407.21783)
- DeBERTa:            He et al., 2021 (ICLR)
```

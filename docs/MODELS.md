# Models & tools — selection, design, and alternatives

A thesis-ready reference for every model and infrastructure tool in the pipeline.
For each: **what it is**, **where it is used**, **how it works / is designed**,
**why it was chosen**, **alternatives with trade-offs**, and a **citation**.

Lift these tables and paragraphs into the thesis "Methodology" and "Background /
Related Work" chapters. Configuration values are the actual ones in this repo
(`config/rag.yaml`, `src/shared_utils/config.py`).

> There are **five model/tool decisions** to justify in the thesis:
> 1. Tier-1 classifier — DistilBERT
> 2. Tier-2 reasoner — `gpt-oss:120b` LLM
> 3. Embedding model (for RAG) — `all-MiniLM-L6-v2`
> 4. Vector database — Qdrant
> 5. LLM serving — Ollama

---

## 1. Tier-1 classifier — DistilBERT

**What it is.** A distilled (compressed) version of BERT: a 6-layer transformer
encoder, ~66 M parameters, ~60% the size of BERT-base while retaining ~95–97% of
its language-understanding quality. Fine-tuned here on ~53k labelled comments
(Davidson + HateXplain + ToxiGen) into a 3-class classifier (HATE / OFFENSIVE /
Normal).

**Where used.** Layer 3 — `src/static_classifier/distilbert_processor.py`. Every
incoming message is classified in ~36 ms; this is the high-throughput first pass.

**How designed.** `distilbert-base-uncased` + a linear classification head,
fine-tuned 2 epochs (AdamW, lr 5e-5, max length 128). Outputs a softmax over the
three classes; the argmax is the label and the max probability is the confidence
that gates Tier-2.

**Why chosen.** The pipeline needs a classifier fast enough for real-time chat
(thousands of messages/minute) on modest hardware (4 GB GPU). DistilBERT is the
standard size/speed/accuracy sweet spot — fast enough for the hot path, accurate
enough to be a useful filter, and cheap to fine-tune.

**Alternatives.**

| Model | vs DistilBERT | When you'd pick it |
|---|---|---|
| **BERT-base** | +2–3% accuracy, ~2× slower & larger | If latency budget allowed and accuracy is paramount |
| **RoBERTa** | Generally higher accuracy, larger | A natural "upgrade the Tier-1" experiment |
| **DeBERTa-v3** | Top GLUE/SuperGLUE scores, heavier | Maximum accuracy, edge deployment not a concern |
| **HateBERT** | BERT re-pretrained on abusive English — domain-matched | Strong candidate specifically for hate-speech; worth a comparison run |
| **ALBERT** | Parameter-shared, smaller still | Extreme memory constraints |
| **Logistic Regression / SVM (TF-IDF)** | Classical baseline, ~76% acc, no GPU | The non-neural baseline (the report already uses this for justification) |

**Citation.** Sanh, Debut, Chaumond, Wolf, *DistilBERT, a distilled version of
BERT*, arXiv:1910.01108, 2019. (HateBERT: Caselli et al., WOAH 2021.)

---

## 2. Tier-2 reasoner — `gpt-oss:120b` (via Ollama)

**What it is.** OpenAI's open-weight 120-billion-parameter large language model,
used as an LLM-as-a-Judge: it receives a structured prompt (the message, Tier-1's
label, context) and returns a structured verdict (`Correct` / `False Positive` /
`False Negative`) plus a natural-language explanation. Run at `temperature=0` for
deterministic, classifier-like behaviour.

**Where used.** Layer 5 — `src/agents/xai_batch_judge.py` (live async audit),
`src/agents/multi_agent.py` (the four specialist agents), and all the evaluation
replay scripts. It only sees low-confidence / sampled records, never the full
stream (the 192× latency overhead makes full-stream LLM judging infeasible).

**How designed.** Accessed through Ollama's OpenAI-compatible API; the `-cloud`
suffix routes inference to Ollama's hosted cluster (a 120B model does not fit the
local 4 GB GPU). All calls go through `shared_utils/llm.py`, which pins
`temperature=0`, forces JSON output, and retries once on a parse failure.

**Why chosen.** Free within Ollama's tier, strong reasoning, open-weight (no
vendor lock-in), and large enough to handle sarcasm, cultural nuance, and coded
language that DistilBERT misses. The choice is a model *alias* in config, so it is
trivially swappable.

**Alternatives.**

| Model | vs gpt-oss:120b | Trade-off |
|---|---|---|
| **Llama 3.1 70B** | Similar class, very popular open weights | Comparable; good A/B candidate |
| **Qwen 2.5 72B** | Strong multilingual reasoning | Better for non-English chat |
| **Mistral Large** | Efficient, strong | Smaller, faster, slightly less capable |
| **Llama-Guard** | Purpose-built safety classifier | A *specialised* baseline to compare the general LLM against |
| **GPT-4 / Claude (API)** | Higher quality, cleaner JSON | Per-token cost + external dependency; not free |

**Citation.** LLM-as-a-Judge: Zheng et al., arXiv:2306.05685, 2023. Llama-Guard:
Inan et al., arXiv:2312.06674, 2023.

---

## 3. Embedding model (RAG) — `sentence-transformers/all-MiniLM-L6-v2`

**This is the "RAG model" you noticed.** Configured in
[`config/rag.yaml`](../config/rag.yaml) under `embedding.model_name`.

**What it is.** A small (6-layer, ~22 M parameter) sentence-embedding model that
maps any chat message to a **384-dimensional vector**, such that semantically
similar texts land close together (small cosine angle). ~80 MB on disk, runs fast
on CPU.

**Where used.** Layer 4/5 — `src/shared_utils/rag.py`. Two roles:
1. *Indexing*: `seed_rag_from_csv.py` embeds every past case and stores the vector
   in Qdrant.
2. *Retrieval*: at judge time, the current message is embedded and Qdrant returns
   the top-k=5 most cosine-similar past cases, which are injected into the prompt
   as precedents.

**How designed.** A SentenceTransformer (mean-pooled MiniLM). The embedding is the
fixed-length numeric "meaning fingerprint"; cosine similarity between two such
vectors is the semantic-similarity score. Distance metric in Qdrant: cosine.

**Why chosen.** Best size/quality trade-off in the sentence-transformers catalogue
and the de-facto default for lightweight RAG — fast on CPU (important on the 4 GB
machine), tiny download, good enough retrieval quality at our corpus size. Like the
LLM, it is a single config line, so swapping it is one edit + a re-seed.

**Alternatives.**

| Model | Dim | vs MiniLM-L6 | When to pick |
|---|---|---|---|
| **all-mpnet-base-v2** | 768 | Higher retrieval quality, ~3× slower | When retrieval quality matters more than speed |
| **bge-small-en-v1.5** | 384 | Near top of MTEB English leaderboard | Best English-only quality at small size |
| **multilingual-e5-small** | 384 | Better for non-English chat | Twitch/Reddit with heavy non-English |
| **OpenAI text-embedding-3-small** | 1536 | Very high quality (API) | If paid API + best quality acceptable |
| **Cohere embed v3** | 1024 | High quality (API) | Same trade-off |

> **Important for the thesis:** changing the embedding model changes the vector
> dimension (`embedding.dim` in `rag.yaml` must match), so the Qdrant collection
> must be recreated and re-seeded. This is a clean ablation to report: "we compared
> MiniLM-L6 vs mpnet-base on retrieval-augmented accuracy".

**Citation.** Sentence-BERT: Reimers & Gurevych, EMNLP 2019. MTEB benchmark:
Muennighoff et al., EACL 2023.

---

## 4. Vector database — Qdrant

**What it is.** An open-source vector database (written in Rust) that stores
high-dimensional embeddings and answers "k nearest neighbours" queries by cosine
similarity, fast, at scale. Ships with a web dashboard.

**Where used.** Layer 4 — the `moderation_records` collection holds the embedded
past cases that RAG retrieves. Accessed via direct HTTP in `shared_utils/rag.py`.

**How designed.** One collection, 384-dim vectors, cosine distance, HNSW index for
approximate nearest-neighbour search. Each point's ID is a hash of the message_id
(idempotent upserts); the payload carries the labels used as precedents.

**Why chosen.** Docker-native (one container), free, production-grade, sufficient
for our scale (tens of thousands of vectors), with a built-in inspection UI.

**Alternatives.**

| Tool | vs Qdrant | Trade-off |
|---|---|---|
| **Chroma** | Python-native, in-process | Simpler to start, harder to scale / no server |
| **FAISS** | Library, no server | Fastest raw search; you manage persistence yourself |
| **pgvector** | Postgres extension | Reuse an existing Postgres; fewer moving parts |
| **Pinecone** | Managed SaaS | Great DX, but paid + external dependency |
| **Weaviate / Milvus** | Feature-rich / high-scale | More operational overhead than needed here |

**Citation.** Qdrant documentation, <https://qdrant.tech>. (RAG pattern: Lewis et
al., *Retrieval-Augmented Generation*, NeurIPS 2020.)

---

## 5. LLM serving — Ollama

**What it is.** A local/hosted LLM serving stack exposing an OpenAI-compatible HTTP
API. Pulls quantised model weights and runs inference without writing CUDA code.

**Where used.** Every Tier-2 LLM call (judge, multi-agent, context agent) goes
through Ollama via `shared_utils/llm.py`.

**Why chosen.** Lets a 120B model run for free (within tier) behind a clean API,
swappable by changing one model alias; no per-token billing, no external SaaS
dependency for the core reasoning step.

**Alternatives.**

| Tool | vs Ollama | Trade-off |
|---|---|---|
| **vLLM** | Production-grade, faster batched throughput | More setup; best for serving at scale |
| **llama.cpp** | Closest to the metal (Ollama wraps it) | Lower-level; manual model management |
| **HuggingFace TGI** | Production inference server | Heavier dependency footprint |
| **Cloud APIs (OpenAI / Anthropic / Google)** | Best quality, zero infra | Per-token cost + external dependency |

**Citation.** Ollama, <https://ollama.com>.

---

## How to turn this into thesis ablations (optional, high value)

Each model decision above is a clean **ablation experiment** you can run with the
existing infrastructure — swap one config line, re-run, compare in the notebook:

| Swap | Change | Measures |
|---|---|---|
| Tier-1 model | retrain with RoBERTa / HateBERT | does a better static model reduce Tier-2 load? |
| Tier-2 LLM | `ACTIVE_MODEL` → llama3.1:70b | is the result model-specific or general? |
| Embedding model | `rag.yaml` → bge-small / mpnet, re-seed | does better retrieval improve RAG accuracy? |

You do not need to run all of these. Even reporting *that the architecture supports
them by configuration* is a defensible "modularity" claim. Running **one** (the
embedding swap is cheapest) turns a design choice into a measured result.

---

## One-paragraph summary for the thesis (adapt verbatim)

> The pipeline composes five model/tool choices, each selected for the
> speed/quality/cost trade-off appropriate to its layer. A distilled transformer
> (DistilBERT) performs high-throughput first-pass classification; a 120-billion-
> parameter open-weight LLM (`gpt-oss:120b`, served via Ollama) performs slow,
> contextual second-tier review only on uncertain cases. Retrieval-augmented
> moderation embeds past cases with a compact sentence-transformer
> (`all-MiniLM-L6-v2`, 384-d) and retrieves precedents from a Qdrant vector
> database. Every model is referenced by a configuration alias, so each choice is
> an independent, swappable variable — enabling the ablation studies reported in
> Chapter [N].

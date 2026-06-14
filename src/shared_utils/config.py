import os
from pathlib import Path
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# Load .env if present (keep API keys out of version control)
# ----------------------------------------------------------------------
# This dynamically finds the root of your project, 
# assuming config.py is in src/shared_utils/
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

# ----------------------------------------------------------------------
# Infrastructure
# ----------------------------------------------------------------------
ES_HOST       = os.getenv("ES_HOST",       "http://localhost:9200")
INDEX_NAME    = os.getenv("INDEX_NAME",    "real_time_analysis")
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "127.0.0.1:9093")
KAFKA_TOPICS = os.getenv("KAFKA_TOPICS", "universal_stream").split(",")
# ----------------------------------------------------------------------
# Model / Task Selection – change ONE env var to switch everything
# ----------------------------------------------------------------------
# Choices for MODEL_ADAPTER: "distilbert", "ollama"
MODEL_ADAPTER = os.getenv("MODEL_ADAPTER", "distilbert")

# For Ollama you can also override the model name
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL",  "gpt-oss:120b-cloud")
ACTIVE_MODEL  = OLLAMA_MODEL # Alias to keep your existing scripts working

# Choices for TASK_ADAPTER: "hate_speech", "medical"
TASK_ADAPTER  = os.getenv("TASK_ADAPTER",  "hate_speech")

# ----------------------------------------------------------------------
# Optional remote tool endpoints (HTTP / gRPC / Kafka)
# ----------------------------------------------------------------------
TOOL_ENDPOINT_UNIVERSAL_SEARCH = os.getenv("TOOL_ENDPOINT_UNIVERSAL_SEARCH")
TOOL_ENDPOINT_AGGREGATE       = os.getenv("TOOL_ENDPOINT_AGGREGATE")
TOOL_ENDPOINT_EXPLAIN_FLAG    = os.getenv("TOOL_ENDPOINT_EXPLAIN_FLAG")

# ----------------------------------------------------------------------
# Stage 2 — Temporal Memory & Conversational Context
# ----------------------------------------------------------------------
# Toggle the entire memory-augmented prompt path. When False, the Tier-2
# judge reverts to the Stage 0 prompt (no user history, no thread context).
# Use False for A/B baselines.
MEMORY_ENABLED          = os.getenv("MEMORY_ENABLED", "1") not in ("0", "false", "False", "")

# Number of prior messages from the SAME author to inject into the prompt.
MEMORY_USER_WINDOW_SIZE = int(os.getenv("MEMORY_USER_WINDOW_SIZE", "10"))

# Number of prior messages from the SAME thread (before the current msg).
MEMORY_THREAD_WINDOW_SIZE = int(os.getenv("MEMORY_THREAD_WINDOW_SIZE", "5"))

# How far back in time to look for user history (hours).
MEMORY_LOOKBACK_HOURS   = int(os.getenv("MEMORY_LOOKBACK_HOURS", "24"))

# Window over which to compute the user behaviour fingerprint
# (e.g. "Last N msgs: X Normal / Y Offensive / Z Hate").
MEMORY_FINGERPRINT_WINDOW = int(os.getenv("MEMORY_FINGERPRINT_WINDOW", "20"))

# ----------------------------------------------------------------------
# Retrieval-Augmented Moderation (RAG) — Qdrant + sentence-transformers
# ----------------------------------------------------------------------
# Master switch. When False (default), the live pipeline ignores Qdrant
# entirely and the judge prompt is the memory-only variant. Flip to True
# AFTER running scripts/build_rag_index.py to populate the vector DB.
RAG_ENABLED        = os.getenv("RAG_ENABLED", "0") not in ("0", "false", "False", "")

# Qdrant connection (matches docker-compose service).
QDRANT_HOST        = os.getenv("QDRANT_HOST",       "localhost")
QDRANT_PORT        = int(os.getenv("QDRANT_PORT",   "6333"))
QDRANT_COLLECTION  = os.getenv("QDRANT_COLLECTION", "moderation_records")

# All other RAG behaviour (embedding model, top_k, threshold) lives in
# config/rag.yaml — operator-editable without touching Python.

# ----------------------------------------------------------------------
# Additional ingestion sources (see docs/SOURCES.md for setup)
# ----------------------------------------------------------------------
# Reddit — required for src/ingestion/adapters/reddit_adapter.py.
# Get these from https://www.reddit.com/prefs/apps (script-type app).
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "hate-speech-pipeline/0.1")

# Twitch anonymous IRC — no credentials needed; the adapter generates
# a justinfan<random> nick at runtime.

# ----------------------------------------------------------------------
# Misc
# ----------------------------------------------------------------------
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "")
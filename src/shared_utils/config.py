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
# Misc
# ----------------------------------------------------------------------
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "")
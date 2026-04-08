# shared_utils/config.py
import os

# INFRASTRUCTURE SETTINGS
ES_HOST = "http://localhost:9200"
INDEX_NAME = "real_time_analysis"

# MODEL SETTINGS (The "Replaceable" Part)
# Switch between 'local' and 'cloud'
MODEL_MODE = "cloud" 

# Model identifiers
LOCAL_MODEL = "llama3"
ACTIVE_MODEL = "gpt-oss:120b-cloud"
# API Settings (Keep these in a .env file later for security)
CLOUD_API_KEY = "your_api_key_here"
CLOUD_API_URL = "https://api.gpt-oss.ai/v1" # Example endpoint
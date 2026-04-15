from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

print(f"Attempting to delete messy index: {INDEX_NAME}...")
try:
    es.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
    print("-> Success! Database wiped clean.")
except Exception as e:
    print(f"-> Error: {e}")
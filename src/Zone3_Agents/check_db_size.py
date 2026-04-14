import sys
import os

# THE FIX: Step back one folder so Python can see 'shared_utils'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

print("Fetching one raw row from Elasticsearch...\n")
try:
    res = es.search(index=INDEX_NAME, size=1)
    raw_data = res['hits']['hits'][0]['_source']
    
    print("=== YOUR EXACT DATABASE KEYS ===")
    for key, value in raw_data.items():
        print(f"- {key}: {value} (Type: {type(value).__name__})")
        
except Exception as e:
    print(f"Error: {e}")
    
    '''
    === YOUR EXACT DATABASE KEYS ===
- tweet_id: ChwKGkNQYS1wT2FWMVk4REZkYkh3Z1FkWHBZY2Rn (Type: str)
- text: :person-turqouise-waving: (Type: str)
- source: YouTube (Type: str)
- video_id: mAoDkS1ZBw0 (Type: str)
- prediction: 2 (Type: int)
- label_text: Normal (Type: str)
- confidence: 0.9520664811134338 (Type: float)
- author_id: UCBqVeCljogaG1o74XtNG7tg (Type: str)
- author_name: @RichG20lndonesiaBaliMajorBests (Type: str)
- is_moderator: False (Type: bool)
- is_sponsor: False (Type: bool)
- timestamp: 2026-03-31T11:21:36.234420 (Type: str)
    '''
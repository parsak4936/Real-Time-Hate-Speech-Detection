import os
import sys
import pandas as pd
from elasticsearch import Elasticsearch

# Tell Python where the shared_utils are
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def export_comprehensive_benchmark():
    print("-> Connecting to Elasticsearch...")
    
    # Query: reviewed AND has agent latency
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"agent_reviewed": True}},
                    {"exists": {"field": "agent_latency_seconds"}}  # <-- filter here
                ]
            }
        },
        "size": 500,
        "sort": [{"timestamp": {"order": "desc"}}]
    }

    try:
        res = es.search(index=INDEX_NAME, body=query)
        hits = res['hits']['hits']
        
        if not hits:
            print("No reviewed records with latency found!")
            return
            
        print(f"-> Successfully pulled {len(hits)} records. Formatting...")
        
        required_fields = [
            'env_domain',
            'text',
            'model_label',
            'agent_final_decision',
            'human_ground_truth',
            'env_strictness',
            'processing_time_ms',
            'agent_latency_seconds'
        ]
        
        data_list = []
        
        for hit in hits:
            source = hit['_source']
            
            # Build row ONLY with required fields
            row_data = {}
            for field in required_fields:
                row_data[field] = source.get(field, "")
            
            # Ensure human_ground_truth exists as blank
            row_data['human_ground_truth'] = ""
            
            data_list.append(row_data)
        
        df = pd.DataFrame(data_list)
        
        # Safety filter (in case ES misses anything)
        df = df[df['agent_latency_seconds'].notna() & (df['agent_latency_seconds'] > 0)]        
        # Keep exact column order
        df = df[required_fields]
        
        # Export
        output_file = "thesis_final_benchmark.csv"
        df.to_csv(output_file, index=False, encoding='utf-8')
        
        print(f"\n✅ SUCCESS: Exported filtered dataset to {output_file}")
        print("-> Only required fields included & latency-filtered.")

    except Exception as e:
        print(f"Extraction failed: {e}")

if __name__ == "__main__":
    export_comprehensive_benchmark()
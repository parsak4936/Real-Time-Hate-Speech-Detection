# Stage 3 Evaluation Results

**Generated:** 2026-06-14T18:13:11.820849

## Cross-Pipeline Comparison

|                                              | accuracy_3class   |   n_records |   latency_ms | notes                                                   | delta_vs_baseline   |
|:---------------------------------------------|:------------------|------------:|-------------:|:--------------------------------------------------------|:--------------------|
| Tier-1 baseline (DistilBERT only)            | 73.8%             |         298 |         30.6 | Static classifier, no Tier-2 overlay                    | nan                 |
| Tier-1 + Tier-2 baseline (no memory, no RAG) | 88.6%             |         298 |       4754.3 | Hybrid pipeline, frozen internship verdicts             | nan                 |
| Tier-1 + Tier-2 with memory                  | 78.9%             |         298 |       4754.3 | Memory-augmented prompt (user history + thread context) | -9.73 pp            |
| Tier-1 + Tier-2 with RAG (no memory)         | 88.3%             |         298 |       4754.3 | RAG-only prompt; semantic precedents from Qdrant        | -0.34 pp            |

## Row Details

### Tier-1 baseline (DistilBERT only)

- **accuracy_3class:** 73.8%
- **n_records:** 298
- **latency_ms:** 30.6
- **notes:** Static classifier, no Tier-2 overlay

### Tier-1 + Tier-2 baseline (no memory, no RAG)

- **accuracy_3class:** 88.6%
- **n_records:** 298
- **latency_ms:** 4754.3
- **notes:** Hybrid pipeline, frozen internship verdicts

### Tier-1 + Tier-2 with memory

- **accuracy_3class:** 78.9%
- **delta_vs_baseline:** -9.73 pp
- **n_records:** 298
- **latency_ms:** 4754.3
- **notes:** Memory-augmented prompt (user history + thread context)

### Tier-1 + Tier-2 with RAG (no memory)

- **accuracy_3class:** 88.3%
- **delta_vs_baseline:** -0.34 pp
- **n_records:** 298
- **latency_ms:** 4754.3
- **notes:** RAG-only prompt; semantic precedents from Qdrant


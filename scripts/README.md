# `scripts/` — runnable tools (you execute these)

Everything here is a **command you run** (`python scripts/…` or
`streamlit run scripts/ui/…`). These import the pipeline library from `../src/`
but are not themselves imported by anything. Organised by purpose:

```
scripts/
├── setup/    one-time / infrastructure
│   ├── init_es_index.py        create the ES index with the explicit field mapping
│   ├── normalize_domains.py    backfill legacy compound env_domain values
│   ├── seed_rag_from_csv.py    fill Qdrant from a benchmark CSV
│   ├── build_rag_index.py      fill Qdrant from ES
│   └── reset_db.py             wipe the ES index (requires --yes)
│
├── eval/     produce & inspect the benchmark
│   ├── sample_for_eval.py          sample ES → CSV (random or --bias toxic, --append)
│   ├── replay_with_memory.py       add the memory-augmented verdict column
│   ├── replay_with_rag.py          add the RAG verdict column (leave-one-out)
│   ├── replay_with_multi_agent.py  add the 4-agent verdict + per-agent reasoning
│   ├── sync_es_to_csv.py           pull memory verdicts from ES into the CSV
│   ├── export_subset.py            export reviewed ES records → CSV
│   ├── check_results.py            print the per-variant metrics table
│   ├── calculate_thesis_metrics.py internship-era metric helper
│   └── _build_eval_notebook.py     regenerate notebooks/evaluation.ipynb
│
└── ui/       the two Streamlit apps
    ├── dashboard.py      live monitoring + evaluation deep-dive (one app, mode toggle)
    └── analyst_chat.py   natural-language query console
```

**Why `src/` and `scripts/` are separate:** `src/` is the importable library
(the pipeline); `scripts/` is the tooling you run against it. Keeping them apart
means the library has no command-line side effects and the tools have one obvious
home. This is the standard Python layout — see [`../src/README.md`](../src/README.md).

The canonical end-to-end run order is in [`../docs/STATUS.md`](../docs/STATUS.md)
("CANONICAL RE-RUN FLOW") and [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md).


## Measurement tooling (`eval/`)

These produced every performance figure in Chapter 5 of the thesis. They are
read-only with respect to the live system: each run uses its own `perf_<run id>`
Kafka topic and its own Elasticsearch index, never `universal_stream` or
`real_time_analysis`.

| script | what it does |
|---|---|
| `replay_producer.py` | Sends a fixed, seeded workload into a `perf_` topic. `--mode preload` fills the queue first (measures throughput); `--mode rate` sends at a steady rate (measures latency). `--create-topic-only` makes the topic with the right partition count before any consumer subscribes, which matters because Kafka would otherwise auto-create it with one. |
| `run_scaling_local.ps1` / `.sh` | One configuration end to end on this machine: topic, processors, producer, wait, collect, analyse. |
| `run_scaling_cluster.py` | The same across several machines over SSH, described by `config/cluster.json`. Runs the producer on a cluster node, never the laptop, because latency is measured between the sender's clock and the receiver's. |
| `analyze_scaling.py` | Turns one run's raw logs into `metrics.json`: throughput, percentiles, per-node breakdown, delivery and duplicate checks, and a clock-skew check across machines. |
| `compare_runs.py` | Merges every run into one comparison table. Use `--min-n 9000` so smoke tests and excluded runs cannot reach a median. |
| `throughput_bench.py` | The classifier alone, with Kafka and Elasticsearch out of the path. `--device cpu\|cuda`. |
| `resource_snapshot.py` | Samples CPU, memory, GPU and container stats during a run. |

A full worked example, including how the university cluster was set up, is in
[`../CLUSTER_RUNBOOK.md`](../CLUSTER_RUNBOOK.md).

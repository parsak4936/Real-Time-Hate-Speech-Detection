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

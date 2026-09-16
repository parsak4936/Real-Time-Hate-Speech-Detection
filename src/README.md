# `src/` — the pipeline library (importable code)

Everything here is a **Python package that other code imports**. You do not
usually run these files directly; they are the building blocks the runnable
tools in `../scripts/` and the notebooks import from.

```
src/
├── ingestion/          Layer 1 — producers (YouTube/Twitch/Reddit) + Context Agent
├── static_classifier/  Layer 3 — DistilBERT processor (Kafka → ES)
├── agents/             Layer 5 — Tier-2 judge, multi-agent, leader, tools
└── shared_utils/       cross-cutting: config, prompts, llm, taxonomy, memory, rag
```

**Rule of thumb:** if a file is `import`-ed by something else, it lives in `src/`.
If a file is meant to be run from the command line (`python …`), it lives in
`../scripts/`. The two long-running pipeline entry points
(`ingestion/omni_ingest.py`, `static_classifier/distilbert_processor.py`,
`agents/xai_batch_judge.py`, `agents/leader_agent.py`) live here because they
are the pipeline itself, not operational tooling.

See [`../docs/CODEBASE_TOUR.md`](../docs/CODEBASE_TOUR.md) for a guided reading order.

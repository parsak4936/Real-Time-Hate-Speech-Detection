# Reports — Evaluation Results Archive

Organized storage for every evaluation run, per pipeline stage.

## Folder Structure

```
reports/
├── stage3/
│   ├── latest/              ← Most recent Stage 3 results
│   │   ├── results.csv      ← For supervisor (Excel-friendly)
│   │   ├── results.json     ← For parsing / version control
│   │   └── results.md       ← For pasting into thesis
│   └── archive/
│       ├── 2026-06-14_130000/
│       │   ├── results.csv
│       │   ├── results.json
│       │   └── results.md
│       └── ...other runs...
├── stage4/
│   ├── latest/
│   └── archive/
└── README.md (this file)
```

## Usage

After running `notebooks/evaluation.ipynb`, export the results:

```bash
python scripts/export_report.py --stage 3 --csv thesis_benchmark_eval.csv
```

This will:
1. Read the CSV with all verdicts (baseline, memory, RAG, multi-agent)
2. Compute accuracy metrics for each pipeline variant
3. Export to CSV/JSON/Markdown in `reports/stage3/latest/`
4. Archive the previous `latest/` run to `reports/stage3/archive/<timestamp>/`

## What each format contains

| Format | Use case | For whom |
|--------|----------|----------|
| **CSV** | Import to Excel, Sheets, or your thesis | Supervisor, examiner |
| **JSON** | Parse in code, version control, reproducibility | You, audit trail |
| **Markdown** | Copy-paste into thesis document | You, writing |

## Example: Sharing Stage 3 results with your supervisor

After Stage 3 evaluation:

```bash
python scripts/export_report.py --stage 3 --csv thesis_benchmark_eval.csv
```

Then send to your supervisor:

> Prof. La Rosa,
>
> I've completed the RAG evaluation. See attached CSV for the full cross-pipeline comparison table.
>
> - Baseline (Tier-2 no RAG): X.X%
> - With RAG: Y.Y%
> - Delta: +Z.Z pp, McNemar p = P.PPPP

Attach: `reports/stage3/latest/results.csv`

## Archive strategy

Every time you re-run an evaluation, the previous `latest/` is automatically moved to `archive/<timestamp>/`. This lets you:
- Compare results across runs
- Trace when results changed
- Recover an old snapshot if needed

Keep the archive for full reproducibility. Delete it only after submitting the thesis.

# Documentation index

These files were written **while the project was running**, between February and
September 2026. They were working documents: install guides, command references,
planning notes, reading paths.

> ## Where any of these disagrees with the thesis, the thesis is right.
>
> Most of them predate the evaluation chapter and all of them predate the
> multi-node cluster study. Several still quote earlier figures (a 36 ms
> classifier, a 93.5% accuracy) or describe Reddit and Trustpilot as working
> sources, which they never were — both adapters exist but were never run.

## The authoritative sources, in order

| read this | for |
|---|---|
| [`../README.md`](../README.md) | what the project is, the headline results, how to run it |
| [`../thesis/THESIS_STATE.md`](../thesis/THESIS_STATE.md) | **the record of every measurement**, every parameter, and the reasoning behind each result. If you read one file, read this one. |
| [`../thesis/Thesis Draft 1/`](../thesis/) | the thesis itself |
| [`../CLUSTER_RUNBOOK.md`](../CLUSTER_RUNBOOK.md) | how the five-machine cluster was built, used, and debugged |
| [`../reports/scaling/README.md`](../reports/scaling/README.md) | every performance run, what it measured, whether it counts |

## What is in this folder

**Still broadly useful** — the mechanics have not changed:

| file | purpose |
|---|---|
| `INSTALL.md`, `QUICKSTART.md`, `COMMANDS.md` | getting a machine from empty to running |
| `ARCHITECTURE.md`, `SCHEMA.md`, `CODEBASE_TOUR.md` | how the pipeline fits together and where each piece lives |
| `PROMPTS.md`, `MODELS.md`, `GLOSSARY.md` | the LLM prompts verbatim, the model choices, the vocabulary |
| `MONITORING.md`, `RUNBOOK.md`, `EVAL.md` | operating it and reproducing the evaluation |
| `SOURCES.md` | the ingestion APIs considered, free and otherwise |
| `internship_report.pdf` | the earlier internship report this thesis grew out of |

**History, not guidance** — kept because they show how the work developed:

| file | why it is here |
|---|---|
| `STATUS.md` | a snapshot of the project mid-flight; superseded by `THESIS_STATE.md` |
| `ROADMAP.md` | the original stage plan, including stages deliberately not built |
| `IMPROVEMENTS.md` | a wish list from mid-project, much of it since done or dropped |
| `MIGRATION.md`, `AUDIT_GUIDE.md`, `THESIS_DELIVERABLES.md` | checklists used once, during the work they describe |
| `MEETING_2026-06-18.md`, `email_to_prof_*.md` | personal notes, excluded from version control by `.gitignore` |

Nothing here is required to understand or reproduce the results. The thesis, its
state document, and the raw runs under `reports/` are self-contained.

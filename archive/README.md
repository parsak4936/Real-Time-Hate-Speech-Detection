# Archive

Files kept for history that are **not** part of the finished work. Nothing here
should be cited, re-run, or used to re-derive a result.

## `thesis_final_benchmark_SUPERSEDED.csv`

An earlier, smaller evaluation set (459 rows). It does **not** reproduce any table
in the thesis and predates the labelling that produced the final benchmark.

The file the thesis actually uses is `thesis_benchmark_eval.csv` in the repository
root: 1,748 hand-labelled rows, 80 of them toxic, carrying every variant's verdict
column and its latencies. That is the only evaluation file that reproduces Table 5.1.

Two other historical files have the same problem and are listed in
`thesis/THESIS_STATE.md` under the data gotchas: `data/final_results_analyzed.csv`
(500 rows) and the stage-3 report set (298 rows). Neither matches the thesis either.

Kept rather than deleted so the project's history stays legible, and so nobody
later finds the name "final benchmark" somewhere and assumes it is authoritative.

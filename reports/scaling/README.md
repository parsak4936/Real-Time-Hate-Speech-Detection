# Performance runs

Raw output of every throughput and latency run behind Chapter 5 of the thesis.
One folder per run; nothing is overwritten, so a run can always be re-checked.

**80 runs total: 49 counted, 7 smoke tests, 8 excluded.**

Regenerate the comparison tables with:

```bash
python scripts/eval/compare_runs.py --min-n 9000
```

`--min-n 9000` is important: it drops smoke tests and the one superseded
6,000-message run, so only full-protocol runs reach a median.

## What each folder holds

| file | meaning |
|---|---|
| `manifest_producer.json` | the workload: seed, date, message count, partitions, mode |
| `manifest_cluster.json` | cluster runs only: which machines, how many processes each |
| `sent.csv` | one row per message the producer got acknowledged |
| `bench_<node>_<n>.csv` | one row per message a processor finished, with its timings |
| `metrics.json` | the computed result: throughput, percentiles, losses, balance |
| `summary.txt` | the same, human-readable, with the PASS/FAIL checks |
| `INVALID.txt` | present only on runs that must be excluded, and why |

## Every run

| run | where | layout | workload | status | msg/s |
|---|---|---|---|---|---|
| `20260923-111323_perf_smoke` | - | - | no metrics.json | incomplete |  |
| `20260923-121100_p2_c2_r1` | - | - | no metrics.json | incomplete |  |
| `20260923-123433_p2_c2_r1` | laptop | 2 proc | 2000 msgs, preload | smoke test | 18.13 |
| `20260923-223620_p1_c1_r1` | - | - | no metrics.json | incomplete |  |
| `20260923-223633_p1_c1_r2` | - | - | no metrics.json | incomplete |  |
| `20260923-223644_p1_c1_r3` | - | - | no metrics.json | incomplete |  |
| `20260923-223703_p2_c2_r1` | - | - | no metrics.json | incomplete |  |
| `20260923-223714_p2_c2_r2` | - | - | no metrics.json | incomplete |  |
| `20260923-223725_p2_c2_r3` | - | - | no metrics.json | incomplete |  |
| `20260923-223749_p4_c4_r1` | - | - | no metrics.json | incomplete |  |
| `20260923-223800_p4_c4_r2` | - | - | no metrics.json | incomplete |  |
| `20260923-223811_p4_c4_r3` | - | - | no metrics.json | incomplete |  |
| `20260923-224113_p1_c1_r1` | laptop | 1 proc | 200 msgs, preload | smoke test | 11.29 |
| `20260923-224245_p1_c1_r1` | laptop | 1 proc | 10000 msgs, preload | counted | 11.75 |
| `20260923-225718_p1_c1_r2` | laptop | 1 proc | 10000 msgs, preload | counted | 11.68 |
| `20260923-231157_p1_c1_r3` | laptop | 1 proc | 10000 msgs, preload | counted | 11.63 |
| `20260923-232815_p2_c2_r1` | laptop | 2 proc | 10000 msgs, preload | counted | 20.53 |
| `20260923-233648_p2_c2_r2` | laptop | 2 proc | 10000 msgs, preload | counted | 21.93 |
| `20260923-234455_p2_c2_r3` | laptop | 2 proc | 10000 msgs, preload | counted | 21.93 |
| `20260923-235321_p4_c4_r1` | laptop | 4 proc | 10000 msgs, preload | counted | 35.98 |
| `20260923-235829_p4_c4_r2` | laptop | 4 proc | 10000 msgs, preload | counted | 35.9 |
| `20260924-000332_p4_c4_r3` | laptop | 4 proc | 10000 msgs, preload | counted | 35.48 |
| `20260925-122758_p1_c1_r1` | laptop | 1 proc | 2000 msgs, preload | smoke test | 10.9 |
| `20260925-123505_p1_c1_cuda_r1` | laptop | 1 proc | 2000 msgs, preload | smoke test | 14.25 |
| `20260925-124022_p1_c1_cuda_r1` | laptop | 1 proc | 10000 msgs, preload | counted | 13.91 |
| `20260925-125301_p1_c1_cuda_r2` | laptop | 1 proc | 10000 msgs, preload | counted | 13.87 |
| `20260925-130525_p1_c1_cuda_r3` | laptop | 1 proc | 10000 msgs, preload | counted | 13.9 |
| `20260925-133838_p4_c4_r1` | laptop | 4 proc | 10000 msgs, rate | **EXCLUDED** | 33.76 |
| `20260925-135404_p4_c4_r1` | laptop | 4 proc | 6000 msgs, rate | **EXCLUDED** | 38.07 |
| `20260925-141850_p4_c4_r1` | - | - | no metrics.json | incomplete |  |
| `20260925-145555_p4_c4_r1` | laptop | 4 proc | 10000 msgs, rate | counted | 18.35 |
| `20260925-151752_p4_c4_r1` | laptop | 4 proc | 6000 msgs, rate | smoke test | 29.02 |
| `20260926-170035_p4_c4_r1` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20260926-171024_p4_c4_r2` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20260926-172007_p4_c4_r3` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20260926-173011_p4_c4_r1` | laptop | 4 proc | 10000 msgs, rate | counted | 29.0 |
| `20260926-173624_p4_c4_r2` | laptop | 4 proc | 10000 msgs, rate | counted | 29.0 |
| `20260926-174241_p4_c4_r3` | laptop | 4 proc | 10000 msgs, rate | counted | 28.99 |
| `20260926-174915_p2_c2_cuda_r1` | laptop | 2 proc | 10000 msgs, preload | counted | 30.22 |
| `20260926-175510_p2_c2_cuda_r2` | laptop | 2 proc | 10000 msgs, preload | counted | 30.37 |
| `20260926-180110_p2_c2_cuda_r3` | laptop | 2 proc | 10000 msgs, preload | counted | 30.41 |
| `20260926-180952_p4_c4_cuda_r1` | laptop | 4 proc | 10000 msgs, preload | counted | 64.69 |
| `20260926-181256_p4_c4_cuda_r2` | laptop | 4 proc | 10000 msgs, preload | counted | 64.58 |
| `20260926-181601_p4_c4_cuda_r3` | laptop | 4 proc | 10000 msgs, preload | counted | 64.63 |
| `20260926-183739_p4_c4_cuda_r1` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20260926-184722_p4_c4_cuda_r2` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20260926-185706_p4_c4_cuda_r3` | laptop | 4 proc | 10000 msgs, rate | counted | 18.0 |
| `20261002-134031_clu_vm14-vm24_twonode_r1` | cluster | vm1x4+vm2x4 | 10000 msgs, preload | counted | 58.2 |
| `20261002-134352_clu_vm14-vm24_twonode_r2` | cluster | vm1x4+vm2x4 | 10000 msgs, preload | counted | 62.31 |
| `20261002-134653_clu_vm14-vm24_twonode_r3` | cluster | vm1x4+vm2x4 | 10000 msgs, preload | counted | 61.08 |
| `20261002-135013_clu_vm24_onenode_r1` | cluster | vm2x4 | 10000 msgs, preload | counted | 38.76 |
| `20261002-135456_clu_vm24_onenode_r2` | cluster | vm2x4 | 10000 msgs, preload | counted | 39.64 |
| `20261002-135929_clu_vm24_onenode_r3` | cluster | vm2x4 | 10000 msgs, preload | counted | 37.38 |
| `20261002-140432_clu_vm21_base1_r1` | cluster | vm2x1 | 10000 msgs, preload | counted | 12.7 |
| `20261002-141802_clu_vm21_base1_r2` | cluster | vm2x1 | 10000 msgs, preload | counted | 12.77 |
| `20261002-143132_clu_vm21_base1_r3` | cluster | vm2x1 | 10000 msgs, preload | counted | 11.98 |
| `20261002-144552_clu_vm22_base2_r1` | cluster | vm2x2 | 10000 msgs, preload | counted | 23.77 |
| `20261002-145320_clu_vm22_base2_r2` | cluster | vm2x2 | 10000 msgs, preload | counted | 22.75 |
| `20261002-150058_clu_vm22_base2_r3` | cluster | vm2x2 | 10000 msgs, preload | counted | 23.39 |
| `20261002-150936_clu_vm14-vm24-rasp14-rasp24-rasp34_allfive_r1` | cluster | vm1x4+vm2x4+rasp1x4+rasp2x4+rasp3x4 | 10000 msgs, preload | counted | 25.48 |
| `20261002-151629_clu_vm14-vm24-rasp14-rasp24-rasp34_allfive_r2` | cluster | vm1x4+vm2x4+rasp1x4+rasp2x4+rasp3x4 | 10000 msgs, preload | counted | 29.65 |
| `20261002-152228_clu_vm14-vm24-rasp14-rasp24-rasp34_allfive_r3` | cluster | vm1x4+vm2x4+rasp1x4+rasp2x4+rasp3x4 | 10000 msgs, preload | counted | 30.01 |
| `20261002-152846_clu_rasp14_pi4gb_r1` | cluster | rasp1x4 | 10000 msgs, preload | **EXCLUDED** | 1.09 |
| `20261002-153140_clu_vm12-vm22_smoke_r1` | - | - | no metrics.json | incomplete |  |
| `20261002-153313_clu_vm12-vm22_smoke_r1` | - | - | no metrics.json | incomplete |  |
| `20261002-153519_clu_vm12-vm22_smoke_r1` | cluster | vm1x2+vm2x2 | 200 msgs, preload | smoke test | 36.13 |
| `20261002-160736_clu_rasp14_pismoke_r1` | cluster | rasp1x4 | 200 msgs, preload | smoke test | 5.33 |
| `20261002-161933_clu_rasp14_pi4gb_r2` | cluster | rasp1x4 | 10000 msgs, preload | **EXCLUDED** | 1.06 |
| `20261002-171144_clu_rasp14_pi4gb_r3` | cluster | rasp1x4 | 10000 msgs, preload | **EXCLUDED** | 1.84 |
| `20261002-180256_clu_rasp24_pi8gb_r1` | cluster | rasp2x4 | 10000 msgs, preload | **EXCLUDED** | 2.17 |
| `20261002-183220_clu_rasp24_pi8gb_r2` | cluster | rasp2x4 | 10000 msgs, preload | **EXCLUDED** | 2.17 |
| `20261002-190145_clu_rasp24_pi8gb_r3` | cluster | rasp2x4 | 10000 msgs, preload | **EXCLUDED** | 2.58 |
| `20261005-090518_clu_vm14-vm24_rate30_lat2node_r1` | cluster | vm1x4+vm2x4 | 10000 msgs, rate | counted | 29.99 |
| `20261005-091153_clu_vm14-vm24_rate30_lat2node_r2` | cluster | vm1x4+vm2x4 | 10000 msgs, rate | counted | 29.99 |
| `20261005-091829_clu_vm14-vm24_rate30_lat2node_r3` | cluster | vm1x4+vm2x4 | 10000 msgs, rate | counted | 29.99 |
| `20261005-092515_clu_vm24_rate20_lat1node_r1` | cluster | vm2x4 | 10000 msgs, rate | counted | 20.0 |
| `20261005-093416_clu_vm24_rate20_lat1node_r2` | cluster | vm2x4 | 10000 msgs, rate | counted | 20.0 |
| `20261005-094315_clu_vm24_rate20_lat1node_r3` | cluster | vm2x4 | 10000 msgs, rate | counted | 20.0 |
| `clu_smoke` | - | - | no metrics.json | incomplete |  |
| `pi_smoke` | - | - | no metrics.json | incomplete |  |

## Why some runs are excluded

Six dedicated Raspberry Pi runs stalled after about a third of their workload.
The boards classified the same messages repeatedly instead of progressing: Kafka
evicts a consumer that cannot clear its batch within `max.poll.interval.ms`
(five minutes by default), and a board at roughly 800 ms a message cannot clear
the default 500 records in time. Reducing `KAFKA_MAX_POLL_RECORDS` to 50 fixed it
completely; the re-runs are the ones the thesis uses. See `thesis/THESIS_STATE.md`.

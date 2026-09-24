#!/usr/bin/env bash
# Linux twin of run_scaling_local.ps1: one scaling configuration end to end
# (replay producer -> N Tier-1 processors -> analysis), per thesis/THESIS_STATE.md §12.
#
# Everything an experiment touches is separate from the live system:
#   Kafka topic  perf_<run id>          (never universal_stream)
#   ES index     perf_<run id>          (never real_time_analysis)
#   processor log reports/scaling/<run>/ (never data/stream_log.csv)
# Timing rows are written per message, so an interrupted run keeps its data.
#
# Examples:
#   ./scripts/eval/run_scaling_local.sh --partitions 2 --processors 2 --n 2000
#   ./scripts/eval/run_scaling_local.sh --partitions 4 --processors 4 --n 10000 --repeats 3 --resources
#   ./scripts/eval/run_scaling_local.sh --partitions 2 --processors 2 --n 100 --dry-run
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 1

PARTITIONS=1; PROCESSORS=1; N=10000; REPEATS=1; MODE=preload; RATE=0
THREADS=1; BROKERS=""; PY=""; TIMEOUT=0; RESOURCES=0; DRYRUN=0

usage() { sed -n '2,12p' "$0"; exit 0; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --partitions) PARTITIONS="$2"; shift 2;;
    --processors) PROCESSORS="$2"; shift 2;;
    --n)          N="$2"; shift 2;;
    --repeats)    REPEATS="$2"; shift 2;;
    --mode)       MODE="$2"; shift 2;;
    --rate)       RATE="$2"; shift 2;;
    --threads)    THREADS="$2"; shift 2;;
    --brokers)    BROKERS="$2"; shift 2;;
    --python)     PY="$2"; shift 2;;
    --timeout)    TIMEOUT="$2"; shift 2;;
    --resources)  RESOURCES=1; shift;;
    --dry-run)    DRYRUN=1; shift;;
    -h|--help)    usage;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

# Prefer a project virtualenv over the system python, so the processors can
# always import torch.
if [[ -z "$PY" ]]; then
  for cand in "$ROOT/env/bin/python" "$ROOT/venv/bin/python" "$ROOT/.venv/bin/python" \
              "$ROOT/Hate_speach_env/bin/python" "$ROOT/Hate_speach_env/Scripts/python.exe" \
              "$(command -v python3 || true)" "$(command -v python || true)"; do
    [[ -n "$cand" && -x "$cand" ]] && PY="$cand" && break
  done
fi
[[ -z "$PY" ]] && { echo "no python found; pass --python /path/to/python" >&2; exit 1; }
echo "Python: $PY"

if ! "$PY" -c "import torch, transformers, kafka, elasticsearch" 2>/dev/null; then
  echo "ERROR: $PY cannot import torch/transformers/kafka/elasticsearch." >&2
  echo "       Activate the virtualenv or pass --python /path/to/venv/bin/python" >&2
  exit 1
fi

[[ "$TIMEOUT" -le 0 ]] && TIMEOUT=$(( N / 2 > 300 ? N / 2 : 300 ))
if [[ "$PROCESSORS" -gt "$PARTITIONS" ]]; then
  echo "WARNING: $PROCESSORS processors but only $PARTITIONS partition(s); the extra consumers will sit idle."
fi
if [[ "$MODE" == "rate" ]] && [[ "$(echo "$RATE <= 0" | bc -l 2>/dev/null || echo 1)" == "1" ]]; then
  echo "rate mode needs --rate greater than 0" >&2; exit 2
fi

pids=(); sampler_pid=""
cleanup() {
  for p in "${pids[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null; done
  [[ -n "$sampler_pid" ]] && kill "$sampler_pid" 2>/dev/null
  return 0
}
trap cleanup INT TERM

HOSTN="$(hostname | tr -cd '[:alnum:]_-')"

for (( rep=1; rep<=REPEATS; rep++ )); do
  stamp="$(date +%Y%m%d-%H%M%S)"
  run_id="${stamp}_p${PARTITIONS}_c${PROCESSORS}_r${rep}"
  topic="perf_$(echo "$run_id" | tr '[:upper:]' '[:lower:]')"
  index="$topic"
  run_dir="$ROOT/reports/scaling/$run_id"
  group="grp_$run_id"
  pids=()

  echo
  printf '=%.0s' {1..78}; echo
  echo "RUN $rep/$REPEATS  $run_id"
  echo "  partitions=$PARTITIONS processors=$PROCESSORS messages=$N mode=$MODE threads=$THREADS"
  echo "  topic=$topic  index=$index"
  printf '=%.0s' {1..78}; echo

  prod_args=(scripts/eval/replay_producer.py --topic "$topic" --partitions "$PARTITIONS"
             --n "$N" --mode "$MODE" --run-id "$run_id")
  [[ "$MODE" == "rate" ]] && prod_args+=(--rate "$RATE")
  [[ -n "$BROKERS" ]] && prod_args+=(--brokers "$BROKERS")

  if [[ "$DRYRUN" == "1" ]]; then
    echo "[dry run] $PY ${prod_args[*]}"
  else
    "$PY" "${prod_args[@]}" || { echo "producer failed" >&2; exit 1; }
    [[ -d "$run_dir" ]] || { echo "run folder missing: $run_dir" >&2; exit 1; }
  fi

  export KAFKA_TOPICS="$topic" PROCESSOR_GROUP_ID="$group" INDEX_NAME="$index" \
         NODE_NAME="$HOSTN" OMP_NUM_THREADS="$THREADS" MKL_NUM_THREADS="$THREADS" \
         PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
         PROCESSOR_LOG_FILE="$run_dir/stream_log_bench.csv"
  [[ -n "$BROKERS" ]] && export KAFKA_BROKERS="$BROKERS"

  for (( i=1; i<=PROCESSORS; i++ )); do
    export BENCH_LOG="$run_dir/bench_${HOSTN}_${i}.csv"
    if [[ "$DRYRUN" == "1" ]]; then
      echo "[dry run] processor $i : BENCH_LOG=$BENCH_LOG INDEX_NAME=$index GROUP=$group THREADS=$THREADS"
      continue
    fi
    nohup "$PY" src/static_classifier/distilbert_processor.py \
          > "$run_dir/proc_$i.out.log" 2> "$run_dir/proc_$i.err.log" &
    pids+=("$!")
    echo "  started processor $i (pid ${pids[-1]})"
  done

  if [[ "$RESOURCES" == "1" && "$DRYRUN" != "1" ]]; then
    nohup "$PY" scripts/eval/resource_snapshot.py --seconds "$TIMEOUT" --interval 2 \
          --out "$run_dir/resource_${HOSTN}.csv" \
          > "$run_dir/resource.out.log" 2> "$run_dir/resource.err.log" &
    sampler_pid="$!"
    echo "  started resource sampler -> $run_dir/resource_${HOSTN}.csv"
  fi

  if [[ "$DRYRUN" == "1" ]]; then
    echo "[dry run] would wait for $N messages (timeout ${TIMEOUT}s), then stop the processors"
    echo "[dry run] $PY scripts/eval/analyze_scaling.py --run $run_id"
    continue
  fi

  deadline=$(( $(date +%s) + TIMEOUT )); last=-1; stall=$(date +%s); done_n=0
  while [[ $(date +%s) -lt $deadline ]]; do
    sleep 5
    done_n=0
    for f in "$run_dir"/bench_*.csv; do
      [[ -e "$f" ]] || continue
      c=$(( $(wc -l < "$f") - 1 ))
      [[ $c -gt 0 ]] && done_n=$(( done_n + c ))
    done
    alive=0
    for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && alive=$(( alive + 1 )); done
    echo "  processed $done_n/$N ($alive processor(s) alive)"
    [[ $done_n -ge $N ]] && break
    if [[ $alive -eq 0 ]]; then
      echo "WARNING: all processors exited early. Last error lines:" >&2
      tail -n 3 "$run_dir"/proc_*.err.log >&2
      break
    fi
    now=$(date +%s)
    if [[ $done_n -ne $last ]]; then last=$done_n; stall=$now
    elif [[ $done_n -eq 0 ]]; then
      [[ $(( now - stall )) -ge 600 ]] && { echo "WARNING: nothing processed within 600s" >&2; break; }
    else
      [[ $(( now - stall )) -ge 300 ]] && { echo "WARNING: no progress for 300s" >&2; break; }
    fi
  done
  [[ $done_n -lt $N ]] && echo "WARNING: finished with $done_n of $N messages; the analysis will report the gap." >&2

  cleanup
  sleep 2
  "$PY" scripts/eval/analyze_scaling.py --run "$run_id"
done

echo
echo "All runs finished. Results are in reports/scaling/ (metrics.json + summary.txt per run)."

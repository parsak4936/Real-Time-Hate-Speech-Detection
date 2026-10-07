"""
Run one scaling configuration across several machines.

The cluster twin of run_scaling_local.ps1, following the same protocol
(thesis/THESIS_STATE.md section 12) so cluster numbers are comparable with the
laptop ones. Machines are described in config/cluster.json.

What it does, per repeat:
  1. creates the topic with enough partitions for every processor
     (Kafka gives one partition to at most one consumer, so too few partitions
     leaves the extra processors idle)
  2. preload mode: the producer sends the whole workload first
  3. starts N processors on each selected machine over SSH
  4. waits until every processor has loaded its model
  5. rate mode: the producer now sends at a fixed rate
  6. polls every machine and prints progress while the work drains
  7. stops the processors, copies every machine's bench_*.csv back
  8. runs analyze_scaling.py on the collected folder

The producer runs on 'producer_node', never on the laptop: latency is measured
between the sender's clock and the receiver's clock, and the laptop's clock is
about 2.5 s away from the cluster's.

Everything an experiment touches is separate from the live system: the topic and
the Elasticsearch index are both named perf_<run id>.

    # smoke test, one machine, 200 messages
    python scripts/eval/run_scaling_cluster.py --nodes vm2=1 --n 200

    # two machines, 4 processors each, three repeats
    python scripts/eval/run_scaling_cluster.py --nodes vm1=4,vm2=4 --n 10000 --repeats 3

    # latency at a fixed arrival rate
    python scripts/eval/run_scaling_cluster.py --nodes vm1=4,vm2=4 --n 10000 --mode rate --rate 30

    # print every command without running anything
    python scripts/eval/run_scaling_cluster.py --nodes vm2=1 --n 200 --dry-run
"""
import argparse
import datetime
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time

_MPR_ENV, _MPR_DEFAULT = "CLUSTER_MAX_POLL_RECORDS", "500"
ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "cluster.json"
LOCAL_RUNS = ROOT / "reports" / "scaling"


# --------------------------------------------------------------------------- ssh
def ssh_base(node):
    key = os.path.expanduser(node["key"])
    return ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15", node["ssh"]]


def run_ssh(node, command, check=True, quiet=False, timeout=None):
    """Run a shell command on a node. Returns (returncode, stdout+stderr)."""
    proc = subprocess.run(ssh_base(node) + [command], capture_output=True, text=True,
                          timeout=timeout, errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    if check and proc.returncode != 0:
        if not quiet:
            print(f"  [{node['_name']}] command failed ({proc.returncode}): {out.strip()[:400]}")
        raise RuntimeError(f"{node['_name']}: {command[:80]} -> exit {proc.returncode}")
    return proc.returncode, out


def run_ssh_detached(node, command):
    """Start something on a node without waiting for it.

    ssh keeps the channel open while any child still holds it, even for a
    backgrounded process, so a blocking call here would hang until the
    processor exits. We fire and forget; the readiness poll below is what
    actually confirms the processor came up.
    """
    return subprocess.Popen(ssh_base(node) + [command],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def scp_from(node, remote_glob, local_dir):
    key = os.path.expanduser(node["key"])
    target = f"{node['ssh']}:{remote_glob}"
    proc = subprocess.run(["scp", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                           "-C", target, str(local_dir)],
                          capture_output=True, text=True, errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- setup
def load_cluster():
    if not CONFIG.exists():
        sys.exit(f"missing {CONFIG}")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for name, node in cfg["nodes"].items():
        node["_name"] = name
    return cfg


def parse_nodes(spec, cfg):
    """'vm1=4,vm2=2' -> [(node, 4), (node, 2)], in the order given."""
    chosen = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, count = part.partition("=")
        name, count = name.strip(), int(count or 1)
        if name not in cfg["nodes"]:
            sys.exit(f"unknown node '{name}'. Known: {', '.join(cfg['nodes'])}")
        node = cfg["nodes"][name]
        if not node.get("enabled", True):
            sys.exit(f"node '{name}' is disabled in config/cluster.json: {node.get('note', '')}")
        if count < 1:
            sys.exit(f"node '{name}': processor count must be at least 1")
        chosen.append((node, count))
    if not chosen:
        sys.exit("--nodes selected nothing")
    return chosen


def preflight(cfg, chosen, producer):
    """Fail in seconds rather than halfway through a long run."""
    print("Preflight")
    seen = {}
    for node, _ in chosen + [(producer, 0)]:
        if node["_name"] in seen:
            continue
        rc, out = run_ssh(node, f"{node['python']} -c "
                                f"'import torch,transformers,kafka,elasticsearch,dotenv;print(\"ok\")'",
                          check=False, timeout=90)
        ok_imports = rc == 0 and "ok" in out
        broker_host, broker_port = cfg["broker"].split(":")
        # Retry: an unattended run must not abort because the broker happens to
        # be restarting. Kafka can take a minute to become healthy.
        ok_broker = False
        for attempt in range(12):
            rc2, _ = run_ssh(node, f"timeout 6 bash -c '</dev/tcp/{broker_host}/{broker_port}'",
                             check=False, timeout=40)
            if rc2 == 0:
                ok_broker = True
                break
            if attempt == 0:
                print(f"  {node['_name']:6} broker not up yet, waiting (up to 2 min) ...")
            time.sleep(10)
        rc3, _ = run_ssh(node, f"test -f {node['repo']}/models/bert_final/model.safetensors",
                         check=False, timeout=40)
        ok_model = rc3 == 0
        print(f"  {node['_name']:6} imports={'ok' if ok_imports else 'FAIL'}  "
              f"broker={'ok' if ok_broker else 'UNREACHABLE'}  model={'ok' if ok_model else 'MISSING'}")
        if not (ok_imports and ok_broker and ok_model):
            if not ok_imports:
                print(f"         -> {out.strip()[:300]}")
            sys.exit(f"{node['_name']} is not ready; fix it before running (see CLUSTER_RUNBOOK.md)")
        seen[node["_name"]] = True

    # Clock check: every machine that timestamps anything must agree.
    stamps = {}
    for node, _ in chosen + [(producer, 0)]:
        if node["_name"] in stamps:
            continue
        t0 = time.time()
        _, out = run_ssh(node, "date +%s%3N", timeout=40)
        rtt = (time.time() - t0) * 1000
        try:
            remote = int(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            continue
        stamps[node["_name"]] = remote - (time.time() * 1000 - rtt / 2)
    if len(stamps) > 1:
        spread = max(stamps.values()) - min(stamps.values())
        print(f"  clock spread across machines: {spread:.0f} ms "
              f"({'fine' if abs(spread) < 250 else 'TOO LARGE - latency numbers will be wrong'})")
        if abs(spread) >= 250:
            print("  -> check NTP on every node: timedatectl show -p NTPSynchronized --value")
    return True


# --------------------------------------------------------------------------- one run
def processor_env(cfg, node, run_id, topic, index, group, i, device, threads):
    remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
    return (f"KAFKA_BROKERS={cfg['broker']} ES_HOST={cfg['es']} "
            f"KAFKA_TOPICS={topic} INDEX_NAME={index} PROCESSOR_GROUP_ID={group} "
            f"NODE_NAME={node['_name']} "
            f"BENCH_LOG={remote_dir}/bench_{node['_name']}_{i}.csv "
            f"PROCESSOR_LOG_FILE={remote_dir}/stream_log_bench.csv "
            f"DEVICE={device} OMP_NUM_THREADS={threads} MKL_NUM_THREADS={threads} "
            f"KAFKA_MAX_POLL_RECORDS={os.getenv(_MPR_ENV, _MPR_DEFAULT)} "
            f"PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8")


def bench_rows(node, run_id):
    """How many messages this machine has finished (bench lines minus headers)."""
    remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
    rc, out = run_ssh(node, f"cat {remote_dir}/bench_*.csv 2>/dev/null | grep -vc '^node,' || true",
                      check=False, timeout=40)
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def ready_count(node, run_id):
    remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
    rc, out = run_ssh(node, f"ls {remote_dir}/bench_*.csv 2>/dev/null | wc -l", check=False, timeout=40)
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def do_run(cfg, chosen, producer, a, run_id):
    topic = f"perf_{run_id.lower()}"
    index = f"perf_{run_id.lower()}"
    group = f"g_{run_id.lower()}"
    total_procs = sum(c for _, c in chosen)
    partitions = a.partitions or total_procs
    local_dir = LOCAL_RUNS / run_id
    prod_dir = f"{producer['repo']}/reports/scaling/{run_id}"

    layout = ", ".join("{}x{}".format(node["_name"], count) for node, count in chosen)
    print(f"\n=== {run_id} ===")
    print(f"  nodes      : {layout}  ({total_procs} processors, {partitions} partitions)")
    print(f"  workload   : {a.n} messages, mode={a.mode}" + (f", rate={a.rate}/s" if a.mode == "rate" else ""))
    print(f"  producer   : {producer['_name']}   broker: {cfg['broker']}")
    print(f"  topic/index: {topic}")

    prod_cmd = (f"cd {producer['repo']} && {producer['python']} scripts/eval/replay_producer.py "
                f"--brokers {cfg['broker']} --topic {topic} --partitions {partitions} "
                f"--n {a.n} --run-id {run_id}")
    if a.mode == "rate":
        prod_cmd += f" --mode rate --rate {a.rate}"
    else:
        prod_cmd += " --mode preload"

    if a.dry_run:
        print("  [dry run] create topic:")
        print(f"            {prod_cmd} --create-topic-only")
        for node, count in chosen:
            env = processor_env(cfg, node, run_id, topic, index, group, 1, a.device, a.threads)
            print(f"  [dry run] {node['_name']}: {count}x  {env} {node['python']} "
                  f"src/static_classifier/distilbert_processor.py")
        print(f"  [dry run] producer: {prod_cmd}")
        return None

    local_dir.mkdir(parents=True, exist_ok=True)
    for node, _ in chosen:
        # A run that died earlier can leave processors behind, and they would
        # quietly consume this run's workload. Start from a clean machine.
        run_ssh(node, "pkill -f 'distilbert_processor.py' || true", check=False, timeout=40)
        run_ssh(node, f"mkdir -p {node['repo']}/reports/scaling/{run_id}", timeout=40)
    run_ssh(producer, f"mkdir -p {prod_dir}", timeout=40)

    # 1. topic first, before any consumer subscribes, or Kafka auto-creates it with 1 partition
    print("  creating topic ...")
    run_ssh(producer, f"{prod_cmd} --create-topic-only", timeout=180)

    # 2. preload: fill the queue before the processors start
    if a.mode == "preload":
        print(f"  producing {a.n} messages (preload) ...")
        _, out = run_ssh(producer, prod_cmd, timeout=1800)
        print("    " + (out.strip().splitlines() or ["(no output)"])[-1][:150])

    # 3. start the processors
    started = []
    for node, count in chosen:
        remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
        for i in range(1, count + 1):
            env = processor_env(cfg, node, run_id, topic, index, group, i, a.device, a.threads)
            # setsid + redirecting all three streams, or ssh waits for the child
            # to exit and this call never returns.
            cmd = (f"cd {node['repo']} && {env} exec {node['python']} "
                   f"src/static_classifier/distilbert_processor.py "
                   f"> {remote_dir}/proc_{i}.out.log 2> {remote_dir}/proc_{i}.err.log "
                   f"< /dev/null")
            started.append(run_ssh_detached(node, cmd))
        print(f"  {node['_name']}: started {count} processor(s)")

    # 3b. resource sampling per node, so the cluster gets the same resource
    # evidence the laptop runs have (Table "resource use under load").
    if a.resources:
        for node, _ in chosen:
            remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
            seconds = a.timeout or max(600, a.n * 2)
            cmd = (f"cd {node['repo']} && exec {node['python']} scripts/eval/resource_snapshot.py "
                   f"--seconds {seconds} --interval 2 "
                   f"--out {remote_dir}/resource_{node['_name']}.csv "
                   f"> {remote_dir}/resource.out.log 2> {remote_dir}/resource.err.log < /dev/null")
            started.append(run_ssh_detached(node, cmd))
        print(f"  resource sampling started on {len(chosen)} node(s)")

    try:
        # 4. wait for every model to load
        print("  waiting for models to load ...")
        deadline = time.time() + 900
        while time.time() < deadline:
            ready = sum(ready_count(node, run_id) for node, _ in chosen)
            if ready >= total_procs:
                print(f"    all {total_procs} ready")
                break
            print(f"    {ready}/{total_procs} ready")
            time.sleep(10)
        else:
            print("    WARNING: not all processors became ready; continuing anyway")
        time.sleep(3)

        # 5. rate mode: now send at a fixed rate
        if a.mode == "rate":
            print(f"  producing {a.n} messages at {a.rate}/s ...")
            _, out = run_ssh(producer, prod_cmd, timeout=1800)
            print("    " + (out.strip().splitlines() or ["(no output)"])[-1][:150])

        # 6. drain
        timeout_s = a.timeout or max(600, a.n * 2)
        deadline = time.time() + timeout_s
        last_total, stall_since, done = -1, time.time(), 0
        while time.time() < deadline:
            per_node = {node["_name"]: bench_rows(node, run_id) for node, _ in chosen}
            done = sum(per_node.values())
            print(f"    {done}/{a.n}   " + "  ".join(f"{k}={v}" for k, v in per_node.items()))
            if done >= a.n:
                break
            if done != last_total:
                last_total, stall_since = done, time.time()
            elif time.time() - stall_since > 180:
                print("    no progress for 3 minutes, stopping early")
                break
            time.sleep(10)
        else:
            print("    timed out waiting for the workload to drain")
    finally:
        # 7. stop every processor, then drop the ssh connections that carried them
        for node, count in chosen:
            run_ssh(node, "pkill -f 'distilbert_processor.py' || true", check=False, timeout=40)
        for proc in started:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("  processors stopped")

    # 8. collect everything into the laptop's run folder
    print("  collecting results ...")
    for node, _ in chosen:
        remote_dir = f"{node['repo']}/reports/scaling/{run_id}"
        for pattern in ("bench_*.csv", "proc_*.log", "resource_*.csv"):
            rc, out = scp_from(node, f"{remote_dir}/{pattern}", local_dir)
            if rc != 0 and "No such file" not in out:
                print(f"    [{node['_name']}] {pattern}: {out.strip()[:160]}")
    for fname in ("sent.csv", "manifest_producer.json"):
        rc, out = scp_from(producer, f"{prod_dir}/{fname}", local_dir)
        if rc != 0:
            print(f"    producer {fname}: {out.strip()[:160]}")

    manifest = {
        "run_id": run_id, "cluster": True, "broker": cfg["broker"], "es": cfg["es"],
        "producer_node": producer["_name"],
        "nodes": {node["_name"]: {"processors": count, "arch": node.get("arch"),
                                  "cores": node.get("cores"), "ram_gb": node.get("ram_gb"),
                                  "note": node.get("note", "")}
                  for node, count in chosen},
        "processors_total": total_procs, "partitions": partitions,
        "messages": a.n, "mode": a.mode, "rate": a.rate if a.mode == "rate" else None,
        "threads_per_process": a.threads, "device": a.device,
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (local_dir / "manifest_cluster.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 8b. an incomplete run must not slip into the medians. compare_runs.py skips
    # any folder holding INVALID.txt, so mark it rather than delete it.
    if done < a.n:
        (local_dir / "INVALID.txt").write_text(
            f"incomplete: {done} of {a.n} messages processed before the run stopped\n",
            encoding="utf-8")
        print(f"  MARKED INVALID: only {done}/{a.n} messages processed")

    # 9. analyse
    print("  analysing ...")
    cmd = [sys.executable, str(ROOT / "scripts" / "eval" / "analyze_scaling.py"), "--run", run_id]
    if a.warmup_seconds:
        cmd += ["--warmup-seconds", str(a.warmup_seconds)]
    subprocess.run(cmd, cwd=str(ROOT))
    return local_dir


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True,
                    help="which machines and how many processors each, e.g. vm1=4,vm2=4")
    ap.add_argument("--n", type=int, default=10000, help="messages in the workload")
    ap.add_argument("--mode", choices=["preload", "rate"], default="preload")
    ap.add_argument("--rate", type=float, default=0, help="messages per second, for --mode rate")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--partitions", type=int, default=0,
                    help="default: one per processor (fewer leaves processors idle)")
    ap.add_argument("--threads", type=int, default=1, help="torch threads per processor")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--warmup-seconds", type=float, default=0.0)
    ap.add_argument("--timeout", type=int, default=0, help="seconds to wait for a run to drain")
    ap.add_argument("--resources", action="store_true",
                    help="sample CPU/RAM/GPU on every node during the run")
    ap.add_argument("--tag", default="", help="extra text in the run id")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    a = ap.parse_args()

    if a.mode == "rate" and a.rate <= 0:
        sys.exit("--mode rate needs --rate greater than 0")

    cfg = load_cluster()
    chosen = parse_nodes(a.nodes, cfg)
    producer = cfg["nodes"][cfg["producer_node"]]
    producer["_name"] = cfg["producer_node"]

    if not a.dry_run:
        preflight(cfg, chosen, producer)

    spec = "-".join(f"{node['_name']}{count}" for node, count in chosen)
    for rep in range(1, a.repeats + 1):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bits = [stamp, "clu", spec]
        if a.mode == "rate":
            bits.append(f"rate{a.rate:g}")
        if a.tag:
            bits.append(a.tag)
        bits.append(f"r{rep}")
        do_run(cfg, chosen, producer, a, "_".join(bits))

    print("\nAll runs finished. Compare them with:")
    print("  python scripts/eval/compare_runs.py --min-n 5000")


if __name__ == "__main__":
    main()

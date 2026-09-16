"""
Resource-usage sampler  —  READ-ONLY observability.

Every `interval` seconds for `seconds` total, records host CPU/RAM, GPU memory
(via nvidia-smi), and per-container CPU/MEM (via `docker stats`). Starts and
stops NOTHING; it only observes. Writes reports/resource_log.csv.

Run it in one terminal while you run throughput_bench.py (or a live stream) in
another, so you capture usage under load:

    python scripts/eval/resource_snapshot.py --seconds 120 --interval 2
"""
import argparse
import csv
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "resource_log.csv"


def gpu_mem():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        line = r.stdout.strip().splitlines()[0]
        used, util = [x.strip() for x in line.split(",")]
        return used, util
    except Exception:
        return "", ""


def docker_stats():
    try:
        r = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}={{.CPUPerc}}/{{.MemUsage}}"],
            capture_output=True, text=True, timeout=20)
        return r.stdout.strip().replace("\n", " ; ")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--interval", type=int, default=2)
    args = ap.parse_args()

    try:
        import psutil
    except ImportError:
        psutil = None
        print("(psutil not installed — host CPU/RAM will be blank; "
              "GPU + docker still captured. `pip install psutil` to enable.)")

    OUT.parent.mkdir(exist_ok=True)
    rows, t_end = [], time.time() + args.seconds
    print(f"Sampling every {args.interval}s for {args.seconds}s -> {OUT}")
    print("Run your load (throughput_bench.py / a live stream) now in another terminal.\n")

    while time.time() < t_end:
        cpu = psutil.cpu_percent(interval=None) if psutil else ""
        ram = psutil.virtual_memory().percent if psutil else ""
        gmem, gutil = gpu_mem()
        dock = docker_stats()
        ts = datetime.now().strftime("%H:%M:%S")
        rows.append({"time": ts, "host_cpu_%": cpu, "host_ram_%": ram,
                     "gpu_mem_MB": gmem, "gpu_util_%": gutil, "docker": dock})
        print(f"[{ts}] host CPU {cpu}% RAM {ram}% | GPU {gmem}MB/{gutil}% | {dock[:70]}")
        time.sleep(args.interval)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} samples -> {OUT}")
    if psutil and rows:
        cpus = [float(r["host_cpu_%"]) for r in rows if r["host_cpu_%"] != ""]
        if cpus:
            print(f"Host CPU: peak {max(cpus):.0f}% / avg {sum(cpus)/len(cpus):.0f}%")


if __name__ == "__main__":
    main()

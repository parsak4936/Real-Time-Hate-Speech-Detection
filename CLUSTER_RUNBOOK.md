# Cluster runbook — hate-speech pipeline


> **No credentials in this file.** The Raspberry Pi login password and the
> `LaRosa.pem` key live only in Marco's `cluster_setup.xlsx` and in
> `~/.ssh/`, neither of which belongs in a public repository.

Everything needed to use the UniME cluster (La Rosa / Marco) for the multi-node
experiment, written so it can be picked up cold after a break or a crash.

**You must be on the UniME network** — on campus via UNIME-WIFI, or through the
UniME VPN. Nothing below works from home without the VPN.

Last verified: 2026-10-02.

---

## 1. The machines

| name | address | kind | cores | RAM | OS | Python | role |
|---|---|---|---|---|---|---|---|
| msgingest1 | 172.16.10.94 | VM, x86_64 | 4 | 31 GB | Ubuntu 22.04 | 3.10.12 | **backbone**: Kafka, Zookeeper, Elasticsearch, Kibana |
| msgingest2 | 172.16.10.95 | VM, x86_64 | 4 | 31 GB | Ubuntu 22.04 | 3.10.12 | worker (runs classifiers) |
| rasp1 | 172.17.6.95 | Pi 4, aarch64 | 4 | 3.8 GB | Ubuntu 24.04.5 | 3.12.3 | worker |
| rasp2 | 172.17.2.72 | Pi 4, aarch64 | 4 | 7.8 GB | Ubuntu 24.04.5 | 3.12.3 | worker |
| rasp3 | 172.17.1.72 | Pi 4, aarch64 | 4 | 7.8 GB | Ubuntu 24.04.5 | 3.12.3 | worker |

Two things in Marco's spreadsheet are wrong, measured directly on the machines:
the VMs run **22.04** (not 24.04), and **rasp3 has 7.8 GB** (not 4 GB). So there
is one 4 GB board and two 8 GB boards. Use these numbers in the thesis.

The VM1 node deliberately does **not** classify anything. It only holds the
queue and the storage, so the cost of writing to storage never competes with the
cost of inference. That mirrors how the laptop measurements were taken.

---

## 2. Connecting

Keys live in `C:\Users\parsa\.ssh\`:

* `LaRosa.pem` — for the two VMs. Came from Marco.
* `cluster_hsp` — for the three Pis. Generated here; the matching
  `cluster_hsp.pub` is installed in each Pi's `~/.ssh/authorized_keys`, so no
  password is needed any more. The Pi login password is still <see cluster_setup.xlsx, kept private> if a key
  ever has to be reinstalled.

```powershell
ssh -i "$env:USERPROFILE\.ssh\LaRosa.pem" ubuntu@172.16.10.94     # VM1 backbone
ssh -i "$env:USERPROFILE\.ssh\LaRosa.pem" ubuntu@172.16.10.95     # VM2 worker
ssh -i "$env:USERPROFILE\.ssh\cluster_hsp" rasp1@172.17.6.95      # Pi 1
ssh -i "$env:USERPROFILE\.ssh\cluster_hsp" rasp2@172.17.2.72      # Pi 2
ssh -i "$env:USERPROFILE\.ssh\cluster_hsp" rasp3@172.17.1.72      # Pi 3
```

Type `exit` to come back to your own machine.

---

## 3. Seeing what is happening

### Kibana — the visual one

<http://172.16.10.94:5601> in any browser while on the UniME network.
Go to **Dev Tools → Console** and run queries in the left pane with the green
triangle:

```
GET _cat/indices?v
GET perf_clu_smoke/_count
GET perf_clu_smoke/_search
```

`_cat/indices?v` is the useful one: a table of every index with how many
documents it holds. Each experiment writes to its own index named `perf_<run>`,
so after a run you see the row count grow there.

### From your own terminal

```powershell
# what is running on the backbone
ssh -i "$env:USERPROFILE\.ssh\LaRosa.pem" ubuntu@172.16.10.94 "sudo docker ps --format '{{.Names}}  {{.Status}}'"
```

```powershell
# every index and its document count (note: curl.exe, NOT curl)
curl.exe "http://172.16.10.94:9200/_cat/indices?v"
```

```powershell
# live CPU and memory of the backbone containers, updates every second, Ctrl-C to quit
ssh -i "$env:USERPROFILE\.ssh\LaRosa.pem" ubuntu@172.16.10.94 "sudo docker stats"
```

```powershell
# live view of a worker while it classifies, q to quit
ssh -i "$env:USERPROFILE\.ssh\LaRosa.pem" -t ubuntu@172.16.10.95 "top -o %CPU"
```

**In PowerShell always write `curl.exe`.** Plain `curl` is an alias for
`Invoke-WebRequest`, which returns an object dump and a security prompt instead
of plain text.

---

## 4. What is installed where

**VM1 (`~/hsp`)** — the repository, plus Docker. The backbone containers come up
from the repository's own `docker-compose.yml`:

```bash
cd ~/hsp
export KAFKA_EXTERNAL_HOST=172.16.10.94
sudo -E docker compose up -d zookeeper kafka elasticsearch kibana
```

Endpoints: Kafka `172.16.10.94:9093`, Elasticsearch `http://172.16.10.94:9200`,
Kibana `http://172.16.10.94:5601`.

To stop them: `sudo docker compose stop` in `~/hsp`. To wipe experiment data
without touching anything else, delete the `perf_*` indices from Kibana.

**VM2 and the three Pis (`~/hsp`)** — the repository and a Python virtual
environment at `~/hsp/.venv`, with versions pinned to match the laptop exactly,
because throughput numbers from different library versions are not comparable:

```
torch 2.5.1   transformers 5.1.0   kafka-python 2.3.0
elasticsearch 7.17.9   numpy 2.2.6   pandas 2.3.3   python-dotenv
```

Run anything on a worker with `~/hsp/.venv/bin/python`, never plain `python3`.

The Pis needed no administrator rights. `sudo` asks for a password there (the
VMs do not), so the virtual environment was built with
`python3 -m venv --without-pip` followed by a `get-pip.py` bootstrap. Nothing
outside the home directory was touched on those boards.

---

## 5. Repository changes this required

Both are one-liners and both keep the laptop working exactly as before.

1. **`docker-compose.yml`** — Kafka used to announce itself as `localhost`:

   ```
   KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:9092,EXTERNAL://${KAFKA_EXTERNAL_HOST:-localhost}:9093
   ```

   A worker on another machine asks the broker "where do I connect?" and would
   have been told "localhost", meaning itself. With the variable unset it still
   falls back to `localhost`, so the laptop setup is unchanged.

2. **`requirements.txt`** — `elasticsearch==8.10.2` was the *server image*
   version; no such Python client has ever existed, so `pip install -r
   requirements.txt` failed on any clean machine. It is now `==7.17.9`, which is
   what the laptop runs and what Appendix B of the thesis already documents.
   `streamlit-autorefresh` was also removed: nothing in the repository imports
   it and it was never installed.

---

## 6. What the jargon means

* **Topic** — a named queue inside Kafka. Messages are written into it by a
  producer and read out of it by consumers. Every experiment uses its own topic
  called `perf_<something>` so the real `universal_stream` is never touched.
* **Partition** — a topic is split into partitions. **Only one consumer can read
  a given partition at a time**, so a topic with 4 partitions supports at most 4
  classifier processes working in parallel. This is why the partition count must
  be at least the number of processors in a run.
* **Producer** — the script that replays the fixed 10,000-message workload into
  the topic (`scripts/eval/replay_producer.py`).
* **Consumer / processor** — `src/static_classifier/distilbert_processor.py`.
  It reads a message, classifies it, writes the result to Elasticsearch, repeats.
* **preload mode** — all messages are pushed into the topic first, then the
  processors drain it as fast as they can. Measures **throughput**.
* **rate mode** — messages arrive at a steady rate, like a live stream.
  Measures **latency**, what one message actually experiences.
* **Run id** — a timestamped folder name under `reports/scaling/` holding
  everything about one run, so nothing is overwritten.

---

## 7. Known traps

| trap | what it looks like | fix |
|---|---|---|
| `curl` in PowerShell | object dump, "Script Execution Risk" prompt | use `curl.exe` |
| key made in PowerShell | "Permission denied (publickey)" everywhere | PowerShell turns `-N '""'` into a real passphrase; generate keys in Git Bash with `-N ''` |
| `type file \| ssh ...` | prints OK but installs nothing | `type` means something else in bash; use `printf '%s\n' '<key>' >> ...` and verify with `cat -A` |
| `sudo` on a Pi | "a terminal is required to read the password" | do not use sudo there; the venv bootstrap above avoids it |
| clock skew | latency comes out negative or absurd | **the laptop is ~2.5 s off the VMs.** Always run the producer on VM1, never on the laptop |
| Kafka auto-creates a topic | extra processors sit idle, throughput flat | create the topic with the right partition count *before* any consumer subscribes |
| OneDrive link | `worker_bundle.zip` is 4 KB of HTML | SharePoint needs a browser; copy with `scp` from the laptop instead |

---

## 8. Moving the model to a worker

Workers need `models/bert_final` and `data/stream_log.csv`. The OneDrive link in
the README does not work on a headless machine. Copy from the laptop instead
(about 90 seconds per node on campus wifi):

```powershell
scp -i "$env:USERPROFILE\.ssh\cluster_hsp" -C -r "F:\hate-speech-pipeline\models\bert_final" rasp1@172.17.6.95:~/hsp/models/
```

```powershell
scp -i "$env:USERPROFILE\.ssh\cluster_hsp" -C "F:\hate-speech-pipeline\data\stream_log.csv" rasp1@172.17.6.95:~/hsp/data/
```

Check it arrived intact by comparing the checksum with the laptop's
`4d025a812146e6fe45d5c609b8c6a865`:

```powershell
ssh -i "$env:USERPROFILE\.ssh\cluster_hsp" rasp1@172.17.6.95 "md5sum ~/hsp/models/bert_final/model.safetensors"
```

---

## 9. Status

Done:

* All five machines reachable by key, full mesh between them.
* Backbone running on VM1 and reachable from the laptop and from the other nodes.
* VM2 fully provisioned: environment, model (checksum-verified), workload.
* Pis provisioned with the Python environment.
* End-to-end smoke test passed: 100 messages, laptop → VM1 Kafka → VM2
  classifier → VM1 Elasticsearch, 0 lost, 100 documents indexed.
* First measurement from the cluster: VM2 classifies in ~52–57 ms per message
  against the laptop's 31.6 ms, so a VM core is slower than a laptop core.

Still to do:

* Copy the model and workload to the three Pis (section 8).
* Write `config/cluster.json` and `scripts/eval/run_scaling_cluster.py`, the
  orchestrator that starts processors over SSH, runs the producer **on VM1**,
  collects each node's timing log back into `reports/scaling/<run_id>/`, and
  runs the existing `analyze_scaling.py` (which already groups results by node
  and checks for clock skew between machines).
* Then three measurement blocks: each machine on its own, scale-out across
  machines, and a fixed-rate latency run.

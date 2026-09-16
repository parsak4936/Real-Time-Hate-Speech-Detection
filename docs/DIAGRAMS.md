# Thesis diagrams (Mermaid)

Paste any block below into <https://mermaid.live>, then **Export → SVG** (vector,
best for a report) or **PNG**. Each diagram notes where it fits in the thesis.

> Tip: in mermaid.live, switch the theme to "neutral" for a clean print look.

---

## 1. System architecture — the 5-layer pipeline

*Use in: System / Architecture chapter (the main figure).*

```mermaid
flowchart TB
    subgraph L1["LAYER 1 — Ingestion"]
        direction LR
        YT["YouTube<br/>(pytchat)"]
        TW["Twitch<br/>(anon IRC)"]
        RD["Reddit<br/>(PRAW)"]
        CA["Context Agent<br/>LLM domain discovery"]
        YT --> CA
        TW --> CA
        RD --> CA
    end

    subgraph L2["LAYER 2 — Streaming backbone"]
        K["Apache Kafka<br/>topic: universal_stream"]
    end

    subgraph L3["LAYER 3 — Tier-1 static classifier"]
        DB["DistilBERT processor<br/>~36 ms / message"]
    end

    subgraph L4["LAYER 4 — Storage"]
        ESDB[("Elasticsearch<br/>real_time_analysis")]
        QD[("Qdrant<br/>vector store")]
    end

    subgraph L5["LAYER 5 — Tier-2 agents & operator UIs"]
        BJ["Batch Judge<br/>LLM auditor"]
        MA["Multi-Agent<br/>4 specialists"]
        DASH["Dashboard"]
        CHAT["Analyst Chat"]
    end

    CA --> K --> DB --> ESDB
    ESDB --> BJ --> ESDB
    ESDB --> MA
    QD -. precedents .-> MA
    ESDB --> DASH
    ESDB --> CHAT

    classDef store fill:#eef,stroke:#557;
    class ESDB,QD store;
```

---

## 2. The two-tier idea (the thesis thesis)

*Use in: Introduction — explains the core design in one picture.*

```mermaid
flowchart LR
    IN["Incoming chat<br/>message"] --> T1["Tier-1 — DistilBERT<br/>fast (~36 ms)<br/>high throughput"]
    T1 -->|"every message stored"| ES[("Elasticsearch<br/>big-data store")]
    ES -.->|"async sweep:<br/>low-confidence, unreviewed"| T2["Tier-2 — LLM agents<br/>slow, contextual<br/>memory / RAG / multi-agent"]
    T2 -->|"reviewed verdict + explanation<br/>(agent_* overlay)"| ES

    classDef fast fill:#e8f8ee,stroke:#3a7;
    classDef slow fill:#fdeee8,stroke:#c63;
    classDef store fill:#fef3c7,stroke:#d97706;
    class T1 fast;
    class T2 slow;
    class ES store;
```

---

## 3. Agentic Context Agent — discovery, not classification

*Use in: Methodology — the Stage 0.5 contribution (the agentic claim).*

```mermaid
flowchart TB
    M["Stream metadata<br/>(title, channel, description)"]
    LLM["Context Agent LLM<br/>proposes a domain in free text"]
    NORM{"normalise_domain()<br/>match against 16-seed taxonomy"}
    M --> LLM
    LLM -->|env_domain_raw| NORM
    NORM -->|exact / alias / fuzzy| CANON["Canonical env_domain<br/>(stable analytics key)"]
    NORM -->|unknown| LOG["pending_taxonomy.log<br/>measurable agentic discovery"]
    CANON --> OUT["env_domain + env_domain_match<br/>+ env_subgenre + env_strictness"]

    classDef hot fill:#fdeee8,stroke:#c63;
    class LLM hot;
```

---

## 4. Multi-Agent decomposition (Stage 4 — your best result)

*Use in: Methodology / Results — give this its own figure, it's the novel win.*

```mermaid
flowchart LR
    IN["Chat message<br/>+ Tier-1 label<br/>+ memory + precedents"]
    RS["1 — Risk Scorer<br/>content risk 0..1"]
    BP["2 — Behavior Profiler<br/>user pattern: low/med/high"]
    ES["3 — Escalator<br/>auto_clear / auto_flag /<br/>human_review"]
    SUP["4 — Supervisor<br/>reconciles all signals"]
    OUT["Final verdict:<br/>Correct /<br/>False Positive /<br/>False Negative"]

    IN --> RS
    IN --> BP
    RS --> ES
    BP --> ES
    RS --> SUP
    BP --> SUP
    ES --> SUP
    SUP --> OUT

    classDef agent fill:#eef,stroke:#557;
    class RS,BP,ES,SUP agent;
```

---

## 5. Message lifecycle (sequence)

*Use in: System chapter — shows the runtime flow of one message.*

```mermaid
sequenceDiagram
    participant U as Live chat
    participant P as Producer + Context Agent
    participant K as Kafka
    participant D as DistilBERT (Tier-1)
    participant E as Elasticsearch
    participant J as Tier-2 (Judge / Multi-Agent)

    U->>P: chat message
    P->>P: LLM assigns domain / strictness
    P->>K: Universal Schema payload
    K->>D: consume
    D->>E: store label + confidence
    Note over J,E: asynchronous, low-confidence records
    J->>E: read records to audit
    J->>J: reason (memory / RAG / 4 agents)
    J->>E: write verdict + explanation
```

---

## 6. Evaluation pipeline (how the variants are produced and compared)

*Use in: Methodology / Evaluation — reproducibility figure.*

```mermaid
flowchart LR
    ESDB[("Elasticsearch")] -->|sample_for_eval| CSV["benchmark CSV"]
    CSV -->|hand-label<br/>human_ground_truth| CSVL["labelled CSV"]
    CSVL -->|replay_with_memory| V1["+ memory verdict"]
    CSVL -->|replay_with_rag| V2["+ RAG verdict"]
    CSVL -->|replay_with_multi_agent| V3["+ multi-agent verdict"]
    V1 --> NB["evaluation.ipynb<br/>check_results.py"]
    V2 --> NB
    V3 --> NB
    NB --> R["Cross-pipeline comparison<br/>Toxic-F1 + McNemar"]

    classDef store fill:#eef,stroke:#557;
    class ESDB store;
```

---

## 7. Code organisation (src = library, scripts = tools)

*Use in: Appendix — the repository structure.*

```mermaid
flowchart TB
    ROOT["hate-speech-pipeline/"]
    ROOT --> SRC["src/ — importable library"]
    ROOT --> SCR["scripts/ — runnable tools"]
    ROOT --> NB["notebooks/"]
    ROOT --> CFG["config/"]
    ROOT --> DOC["docs/"]

    SRC --> ING["ingestion/"]
    SRC --> STC["static_classifier/"]
    SRC --> AGT["agents/"]
    SRC --> SHU["shared_utils/<br/>config, prompts, llm,<br/>taxonomy, memory, rag"]

    SCR --> SET["setup/<br/>init ES, seed Qdrant, reset"]
    SCR --> EVL["eval/<br/>replays, sampling, metrics"]
    SCR --> UI["ui/<br/>dashboard, analyst_chat"]
```

---

## Rendering checklist

- Vector export (SVG) keeps text crisp at any size — prefer it for LaTeX/Word.
- If a label is cut off, add `<br/>` to wrap it manually.
- Keep one diagram per figure in the report; don't combine.
- Caption each with a figure number and one sentence (e.g. *"Figure 3: the
  four-agent Tier-2 decomposition; the Supervisor reconciles the upstream
  specialists into the final verdict."*).

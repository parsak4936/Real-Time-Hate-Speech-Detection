"""
Thesis diagrams, drawn with Matplotlib and written as vector PDFs.

Same approach as the diagrams in the Biofeedback paper: no Mermaid, no browser,
no external tool. Every figure is 6.5 inches wide (468 pt), the text width of the
thesis, so it can be included at \\linewidth without rescaling.

    python thesis/tools/make_diagrams.py            # all figures
    python thesis/tools/make_diagrams.py architecture

Figures are written to thesis/Thesis Draft 1/figures/ as fig_<name>.pdf.
Content is checked against the code, not against the previous drawings:
  * Tier-1 consumes Kafka directly; Spark is a scale-out path, NOT in the
    inference chain (src/static_classifier/distilbert_processor.py).
  * Reddit and Trustpilot adapters exist but were never run.
  * One retrieval backend is active at a time (RETRIEVAL_BACKEND).
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

OUT = Path(__file__).resolve().parents[1] / "Thesis Draft 1" / "figures"
WIDTH_IN = 6.5

# Muted palette, readable in print and in greyscale.
INK = "#333333"
FILL_SOURCE = "#e8f4f8"   # things outside the system
FILL_CORE = "#fff4e6"     # infrastructure
FILL_MODEL = "#eaf5ea"    # models and decisions
FILL_STORE = "#f3eefc"    # storage
FILL_OFF = "#f2f2f2"      # implemented but not exercised
BAND = "#fafafa"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.2})


def band(ax, x, y, w, h, label):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.01",
                                linewidth=0.8, edgecolor="#cccccc", facecolor=BAND, zorder=0))
    ax.text(x + 0.008, y + h - 0.012, label, ha="left", va="top", fontsize=7.0,
            style="italic", color="#777777", zorder=1)


def box(ax, x, y, w, h, text, fill=FILL_CORE, dashed=False, bold=False, fontsize=7.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.012",
                                linewidth=1.0, edgecolor=INK, facecolor=fill,
                                linestyle=(0, (3, 2)) if dashed else "solid", zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize,
            color=INK, zorder=3, fontweight="bold" if bold else "normal", linespacing=1.35)
    return (x, y, w, h)


def arrow(ax, start, end, text="", dashed=False, rad=0.0, label_pos=0.5, fontsize=6.6):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=9,
                                 linewidth=0.9, color=INK, zorder=4,
                                 linestyle=(0, (2.5, 2)) if dashed else "solid",
                                 connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=1, shrinkB=1))
    if text:
        mx = start[0] + (end[0] - start[0]) * label_pos
        my = start[1] + (end[1] - start[1]) * label_pos
        ax.text(mx, my, text, ha="center", va="center", fontsize=fontsize, color="#444444",
                zorder=5, linespacing=1.3,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none"))


def canvas(height_in):
    fig, ax = plt.subplots(figsize=(WIDTH_IN, height_in))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.subplots_adjust(left=0.004, right=0.996, top=0.996, bottom=0.004)
    return fig, ax


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"fig_{name}.pdf"
    fig.savefig(path, format="pdf")
    plt.close(fig)
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
def architecture():
    fig, ax = canvas(7.9)

    # ---- Layer 1: ingestion and context
    band(ax, 0.02, 0.845, 0.96, 0.150, "Layer 1   ingestion and context")
    box(ax, 0.075, 0.905, 0.20, 0.042, "YouTube · HTTP polling", FILL_SOURCE)
    box(ax, 0.305, 0.905, 0.20, 0.042, "Twitch · IRC socket", FILL_SOURCE)
    box(ax, 0.545, 0.905, 0.30, 0.042, "Reddit · Trustpilot: built, never run", FILL_OFF, dashed=True)
    box(ax, 0.175, 0.852, 0.60, 0.044, "Context Agent · title, channel, description →\ndomain + strictness, normalised onto the taxonomy", FILL_MODEL)
    arrow(ax, (0.175, 0.905), (0.30, 0.896))
    arrow(ax, (0.405, 0.905), (0.44, 0.896))
    arrow(ax, (0.645, 0.905), (0.62, 0.896), dashed=True)

    # ---- Layer 2: streaming backbone
    band(ax, 0.02, 0.650, 0.96, 0.180, "Layer 2   streaming backbone")
    box(ax, 0.175, 0.735, 0.44, 0.055, "Kafka · topic universal_stream\n1 partition, replication 1, 24 h / 1 GB", FILL_CORE)
    box(ax, 0.655, 0.735, 0.26, 0.055, "Zookeeper\ncoordination", FILL_CORE)
    box(ax, 0.505, 0.663, 0.41, 0.050, "Spark master + worker\nscale-out path, not used for inference", FILL_OFF, dashed=True)
    arrow(ax, (0.475, 0.852), (0.475, 0.790), "Universal Schema", label_pos=0.5)
    arrow(ax, (0.565, 0.735), (0.62, 0.713), dashed=True)

    # ---- Layer 3: Tier-1
    band(ax, 0.02, 0.540, 0.96, 0.098, "Layer 3   first tier, on the hot path")
    box(ax, 0.145, 0.551, 0.71, 0.052, "Tier-1 · fine-tuned DistilBERT  ·  every message\n~31 ms on CPU (GPU selectable) → label + confidence", FILL_MODEL)
    arrow(ax, (0.395, 0.735), (0.395, 0.603), "consumed directly\nfrom Kafka", label_pos=0.5)

    # ---- Layer 4: storage
    band(ax, 0.02, 0.380, 0.96, 0.148, "Layer 4   storage, the seam of the pipeline")
    box(ax, 0.075, 0.396, 0.33, 0.072, "Elasticsearch\nindex real_time_analysis\nevery record and every verdict", FILL_STORE)
    box(ax, 0.455, 0.406, 0.21, 0.052, "Qdrant\n384-dim vectors", FILL_STORE)
    box(ax, 0.705, 0.406, 0.24, 0.052, "wiki/ pages\n8 → 34 entries", FILL_STORE)
    arrow(ax, (0.395, 0.551), (0.30, 0.468), "stored", rad=-0.10, label_pos=0.78)

    # ---- Layer 5: Tier-2
    band(ax, 0.02, 0.098, 0.96, 0.238, "Layer 5   second tier, off the hot path")
    box(ax, 0.075, 0.232, 0.235, 0.042, "confidence < 0.80 ?", FILL_MODEL)
    box(ax, 0.075, 0.130, 0.235, 0.068, "Tier-2 · LLM judge\ngpt-oss:120b\n~5.3 s, asynchronous", FILL_MODEL)
    box(ax, 0.355, 0.226, 0.28, 0.060, "temporal memory\nauthor 10 · thread 5\nfingerprint 20 · 24 h", FILL_CORE)
    box(ax, 0.665, 0.226, 0.28, 0.060, "retrieval, one at a time\nRAG 5 @ 0.55 | Wiki 4 @ 0.15", FILL_CORE)
    box(ax, 0.355, 0.130, 0.59, 0.060, "multi-agent chain\nRisk Scorer → Behaviour Profiler →\nEscalator → Supervisor", FILL_CORE)
    arrow(ax, (0.155, 0.396), (0.155, 0.274), "asynchronous sweep", label_pos=0.33)
    arrow(ax, (0.19, 0.232), (0.19, 0.198), "uncertain")
    arrow(ax, (0.355, 0.160), (0.310, 0.160))
    arrow(ax, (0.078, 0.168), (0.082, 0.396), rad=0.40)
    ax.text(0.205, 0.289, "verdict written back", ha="center", va="center", fontsize=6.6,
            color="#444444", bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none"))

    # ---- operator surfaces
    box(ax, 0.075, 0.038, 0.87, 0.040, "operator surfaces, read-only on storage:   Streamlit dashboard  ·  analyst chat  ·  Kibana", FILL_SOURCE)
    arrow(ax, (0.335, 0.396), (0.335, 0.078))

    ax.legend(handles=[Patch(facecolor=FILL_SOURCE, edgecolor=INK, label="outside the system / operator"),
                       Patch(facecolor=FILL_CORE, edgecolor=INK, label="infrastructure and context modules"),
                       Patch(facecolor=FILL_MODEL, edgecolor=INK, label="models and decisions"),
                       Patch(facecolor=FILL_STORE, edgecolor=INK, label="storage"),
                       Patch(facecolor=FILL_OFF, edgecolor=INK, linestyle="--", label="built but not exercised here")],
              loc="lower center", bbox_to_anchor=(0.5, -0.012), ncol=3, frameon=False, fontsize=6.6,
              handlelength=1.4, handleheight=0.9, columnspacing=1.2)
    save(fig, "architecture")


# ---------------------------------------------------------------------------
def two_tier():
    """The gate is a query on storage, not a branch in the hot path.

    src/agents/xai_batch_judge.py builds {"range": {"model_confidence": {"lt": 0.80}}}
    against Elasticsearch; the Tier-1 processor stores every message unconditionally.
    """
    fig, ax = canvas(4.0)

    band(ax, 0.02, 0.560, 0.96, 0.425, "the hot path   every message, milliseconds")
    box(ax, 0.035, 0.760, 0.16, 0.090, "message\nfrom Kafka", FILL_CORE)
    box(ax, 0.235, 0.745, 0.28, 0.120, "Tier-1 - fine-tuned DistilBERT\nlabel + confidence\n~31 ms, CPU by default", FILL_MODEL)
    box(ax, 0.560, 0.745, 0.405, 0.120, "Elasticsearch - real_time_analysis\nevery message stored with its label\nand the confidence behind it", FILL_STORE)
    arrow(ax, (0.195, 0.805), (0.235, 0.805))
    arrow(ax, (0.515, 0.805), (0.560, 0.805))
    ax.text(0.33, 0.655, "Nothing on this path waits for the judge.",
            ha="center", va="center", fontsize=6.8, style="italic", color="#666666")

    band(ax, 0.02, 0.030, 0.96, 0.500, "off the hot path   the uncertain minority, seconds")
    box(ax, 0.535, 0.395, 0.25, 0.095, "the gate is a query:\nmodel_confidence < 0.80", FILL_MODEL)
    box(ax, 0.280, 0.230, 0.44, 0.120, "Tier-2 - gpt-oss:120b through Ollama\ntemperature 0, JSON only, one retry\n~5.3 s per message", FILL_MODEL)
    box(ax, 0.035, 0.230, 0.21, 0.120, "context injected:\nmemory - retrieval -\nmulti-agent chain", FILL_CORE)
    box(ax, 0.280, 0.075, 0.44, 0.105, "verdict: Tier-1 correct, false positive\nor false negative, with a written\nexplanation a moderator can read", FILL_MODEL)
    arrow(ax, (0.675, 0.745), (0.675, 0.490), "read back later", label_pos=0.80)
    arrow(ax, (0.600, 0.395), (0.560, 0.350))
    arrow(ax, (0.245, 0.290), (0.280, 0.290))
    arrow(ax, (0.500, 0.230), (0.500, 0.180))
    arrow(ax, (0.722, 0.140), (0.905, 0.745), rad=-0.22)
    ax.text(0.890, 0.290, "verdict written\nback beside\nthe record", ha="center", va="center", fontsize=6.6,
            color="#444444", linespacing=1.3)

    ax.legend(handles=[Patch(facecolor=FILL_CORE, edgecolor=INK, label="infrastructure and context modules"),
                       Patch(facecolor=FILL_MODEL, edgecolor=INK, label="models and decisions"),
                       Patch(facecolor=FILL_STORE, edgecolor=INK, label="storage")],
              loc="lower center", bbox_to_anchor=(0.5, -0.015), ncol=3, frameon=False, fontsize=6.6,
              handlelength=1.4, handleheight=0.9, columnspacing=1.2)
    save(fig, "two_tier_flow")


# ---------------------------------------------------------------------------
def context_agent():
    fig, ax = canvas(4.0)

    box(ax, 0.055, 0.830, 0.25, 0.145, "stream metadata\ntitle - channel -\ndescription", FILL_SOURCE)
    box(ax, 0.365, 0.830, 0.36, 0.145, "LLM, asked in free text:\nwhat is this stream about,\nand how strictly should it\nbe moderated?", FILL_MODEL)
    box(ax, 0.775, 0.830, 0.19, 0.145, "a live esports final\ncomes back gaming,\nlow strictness;\na political broadcast\ncomes back high", FILL_SOURCE, fontsize=6.2)
    arrow(ax, (0.305, 0.902), (0.365, 0.902))
    arrow(ax, (0.725, 0.902), (0.775, 0.902))

    box(ax, 0.230, 0.640, 0.44, 0.120, "normalised onto the canonical domains in\nconfig/taxonomy.yaml, an operator-editable file", FILL_CORE)
    box(ax, 0.720, 0.650, 0.25, 0.100, "if the call fails, safe defaults;\ningestion is never blocked", FILL_OFF, dashed=True)
    arrow(ax, (0.450, 0.830), (0.450, 0.760))
    arrow(ax, (0.670, 0.700), (0.720, 0.700), dashed=True)

    box(ax, 0.230, 0.420, 0.28, 0.140, "canonical domain\nand strictness, into\nevery judge prompt", FILL_MODEL)
    box(ax, 0.550, 0.420, 0.20, 0.140, "the wording the\nmodel chose, kept\nbeside it, auditable", FILL_STORE)
    box(ax, 0.790, 0.420, 0.18, 0.140, "off-taxonomy\nproposals logged:\n628 of 1,748\nrecords, 36 per cent", FILL_STORE, fontsize=6.2)
    arrow(ax, (0.370, 0.640), (0.370, 0.560))
    arrow(ax, (0.520, 0.640), (0.650, 0.560))
    arrow(ax, (0.620, 0.640), (0.880, 0.560))

    box(ax, 0.430, 0.230, 0.54, 0.100, "an operator watches a proposal accumulate and promotes it\ninto the taxonomy, without touching a line of Python", FILL_CORE)
    arrow(ax, (0.880, 0.420), (0.880, 0.330))
    arrow(ax, (0.430, 0.280), (0.230, 0.640), rad=-0.35, dashed=True)
    ax.text(0.105, 0.445, "the taxonomy grows\nwith the platforms\nit watches", ha="center", va="center",
            fontsize=6.6, color="#444444", linespacing=1.3)

    ax.text(0.50, 0.115, "Discovery first, normalisation second: nothing is forced into a category that does not fit,\nand what does not fit becomes the record that grows the taxonomy.",
            ha="center", va="center", fontsize=6.8, style="italic", color="#666666")
    save(fig, "contextAgent")


# ---------------------------------------------------------------------------
def temporal_memory():
    fig, ax = canvas(3.3)

    box(ax, 0.030, 0.360, 0.235, 0.520, "Elasticsearch\nreal_time_analysis\n\nevery message already\nstored, with its label\nand its verdict", FILL_STORE)

    box(ax, 0.345, 0.730, 0.350, 0.150, "author history\nthe author's last 10 messages\nfrom the past 24 hours", FILL_CORE)
    box(ax, 0.345, 0.545, 0.350, 0.150, "thread context\nthe 5 messages that came just before\nthis one in the same thread", FILL_CORE)
    box(ax, 0.345, 0.360, 0.350, 0.150, "behavioural fingerprint\nhow often normal, offensive or hateful across\nthe author's last 20 labelled messages, 24 hours", FILL_CORE, fontsize=6.4)

    arrow(ax, (0.265, 0.750), (0.345, 0.805), rad=-0.15)
    arrow(ax, (0.265, 0.620), (0.345, 0.620))
    arrow(ax, (0.265, 0.490), (0.345, 0.435), rad=0.15)

    box(ax, 0.775, 0.360, 0.195, 0.520, "the Tier-2 judge\nprompt,\n\nbeside the message\nitself", FILL_MODEL)
    arrow(ax, (0.695, 0.805), (0.775, 0.750), rad=0.15)
    arrow(ax, (0.695, 0.620), (0.775, 0.620))
    arrow(ax, (0.695, 0.435), (0.775, 0.490), rad=-0.15)

    ax.text(0.50, 0.255, "All four windows, 10, 5, 20 and 24 hours, are configuration values, not constants in the code.",
            ha="center", va="center", fontsize=6.8, color="#555555")
    ax.text(0.50, 0.150, "A regular who has posted a hundred harmless messages and then writes something borderline\nis probably joking. The same line from an account flagged twice this week reads differently.",
            ha="center", va="center", fontsize=6.8, style="italic", color="#777777")
    save(fig, "temporal_memory")


# ---------------------------------------------------------------------------
def retrieval_backends():
    fig, ax = canvas(4.0)

    box(ax, 0.345, 0.890, 0.310, 0.075, "the message to be judged", FILL_SOURCE)
    box(ax, 0.280, 0.745, 0.440, 0.100, "retrieval.py - one interface\nRETRIEVAL_BACKEND = rag | wiki | none", FILL_MODEL)
    arrow(ax, (0.500, 0.890), (0.500, 0.845))

    band(ax, 0.020, 0.300, 0.468, 0.385, "RAG   nearest past cases")
    box(ax, 0.055, 0.545, 0.400, 0.095, "all-MiniLM-L6-v2 encoder\n384-dimensional vector", FILL_CORE)
    box(ax, 0.055, 0.325, 0.400, 0.175, "Qdrant vector store\nthe 5 nearest past messages,\ncosine similarity at least 0.55,\nwith the verdicts they received\n(leave-one-out in the evaluation)", FILL_STORE, fontsize=6.4)
    arrow(ax, (0.255, 0.545), (0.255, 0.500))

    band(ax, 0.512, 0.300, 0.468, 0.385, "LLM-Wiki   curated rules")
    box(ax, 0.545, 0.545, 0.400, 0.095, "the same MiniLM encoder,\nheld constant on purpose", FILL_CORE)
    box(ax, 0.545, 0.325, 0.400, 0.175, "wiki/ - 8 content pages split at every\nsecond-level heading into 34 entries\nthe core policy page and the message's\ndomain page always included, plus the\n4 best entries above 0.15", FILL_STORE, fontsize=6.4)
    arrow(ax, (0.745, 0.545), (0.745, 0.500))

    arrow(ax, (0.420, 0.745), (0.255, 0.640), "rag", rad=0.10, label_pos=0.55)
    arrow(ax, (0.580, 0.745), (0.745, 0.640), "wiki", rad=-0.10, label_pos=0.55)

    box(ax, 0.300, 0.140, 0.400, 0.085, "the same slot in the judge prompt", FILL_MODEL)
    box(ax, 0.725, 0.140, 0.255, 0.085, "with none, the slot is left\nempty: the baseline variant", FILL_OFF, dashed=True)
    arrow(ax, (0.255, 0.325), (0.360, 0.225), rad=-0.12)
    arrow(ax, (0.745, 0.325), (0.640, 0.225), rad=0.12)

    ax.text(0.50, 0.060, "One backend is active at a time, and switching the live pipeline between them is a single flag.\nSame encoder, same prompt slot, so the corpus is what the comparison varies.",
            ha="center", va="center", fontsize=6.8, style="italic", color="#666666")
    save(fig, "retrieval_backends")


# ---------------------------------------------------------------------------
def multi_agent():
    fig, ax = canvas(4.0)

    box(ax, 0.055, 0.880, 0.40, 0.080, "the message, nothing else", FILL_SOURCE)
    box(ax, 0.545, 0.880, 0.40, 0.080, "the author's history, nothing else", FILL_SOURCE)

    box(ax, 0.055, 0.685, 0.40, 0.150, "1 - Risk Scorer\nrates the toxicity of the content\nfrom 0 to 1, without knowing\nwho sent it", FILL_MODEL)
    box(ax, 0.545, 0.685, 0.40, 0.150, "2 - Behaviour Profiler\nrates the account low, medium\nor high risk, without seeing\nthe current message", FILL_MODEL)
    arrow(ax, (0.255, 0.880), (0.255, 0.835))
    arrow(ax, (0.745, 0.880), (0.745, 0.835))

    box(ax, 0.185, 0.460, 0.63, 0.150, "3 - Escalator\ntakes those two signals and decides how to route the case:\nclear it automatically, flag it automatically,\nor send it to a human", FILL_MODEL)
    arrow(ax, (0.255, 0.685), (0.330, 0.610), "risk score", rad=0.10, label_pos=0.55)
    arrow(ax, (0.745, 0.685), (0.670, 0.610), "account risk", rad=-0.10, label_pos=0.55)

    box(ax, 0.185, 0.235, 0.63, 0.150, "4 - Supervisor\nreads everything the others produced and issues the final\nverdict in the same three-way format as every other\nvariant, so the comparison stays direct", FILL_MODEL)
    arrow(ax, (0.500, 0.460), (0.500, 0.385), "routing decision", label_pos=0.5)

    box(ax, 0.185, 0.110, 0.63, 0.075, "Tier-1 correct  |  false positive  |  false negative", FILL_STORE)
    arrow(ax, (0.500, 0.235), (0.500, 0.185))

    ax.text(0.50, 0.045, "Every step is stored, not just the answer, so a wrong verdict can be traced to the step that went astray.\nFour LLM calls per message instead of one, affordable only because this runs on the flagged minority alone.",
            ha="center", va="center", fontsize=6.8, style="italic", color="#666666")
    save(fig, "Multi-agent")


FIGURES = {
    "architecture": architecture,
    "two_tier_flow": two_tier,
    "contextAgent": context_agent,
    "temporal_memory": temporal_memory,
    "retrieval_backends": retrieval_backends,
    "multi_agent": multi_agent,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(FIGURES)
    for name in wanted:
        if name not in FIGURES:
            sys.exit(f"unknown figure: {name}. Available: {', '.join(FIGURES)}")
        FIGURES[name]()

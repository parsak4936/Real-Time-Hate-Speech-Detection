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


FIGURES = {"architecture": architecture}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(FIGURES)
    for name in wanted:
        if name not in FIGURES:
            sys.exit(f"unknown figure: {name}. Available: {', '.join(FIGURES)}")
        FIGURES[name]()

"""The paper's two figures, drawn from the committed tables in results/fresh-2026-10/.

Fig. 1: violations per opportunity by rule, without and with the policy (all models, both rounds).
Fig. 2: prohibitions against procedures under the policy, per model, models by size.
Needs only matplotlib (not the harness environment):
    python analysis/paper_figures.py OUT_DIR
"""
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results/fresh-2026-10"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
# Categorical slots 1 and 2 of the reference palette (validated as a pair); marker shape is the
# second encoding, so the figures read in greyscale.
BLUE, ORANGE = "#2a78d6", "#eb6834"
VIOLET, GREEN = "#4a3aa7", "#008300"   # Fig. 2 uses its own pair, so no colour means two things
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

# Times, to match the IEEE template's text (TeX Gyre Termes, from the fonts-texgyre package, when present).
for font in Path("/usr/share/texmf/fonts/opentype/public/tex-gyre").glob("texgyretermes-*.otf"):
    font_manager.fontManager.addfont(str(font))
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["TeX Gyre Termes", "Times New Roman", "DejaVu Serif"],
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 8, "legend.fontsize": 7.5,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0, "pdf.fonttype": 42,
})


def rows(path):
    return list(csv.DictReader(open(path)))


def style(ax):
    ax.set_xlim(-2, 102)
    ax.set_xticks(range(0, 101, 20))
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)


def dumbbell(ax, labels, a, b, a_style, b_style, ys=None):
    """Two estimates per row with their intervals; a and b are lists of (rate, lo, hi) in percent."""
    ys = ys or list(range(len(labels)))[::-1]
    for y, (ra, *_), (rb, *_) in zip(ys, a, b):
        ax.plot([ra, rb], [y, y], color=GRID, linewidth=2.2, zorder=1, solid_capstyle="round")
    for series, (label, colour, marker, filled), dy in ((a, a_style, 0.13), (b, b_style, -0.13)):
        for y, (r, lo, hi) in zip(ys, series):
            ax.plot([lo, hi], [y + dy, y + dy], color=colour, linewidth=1.0, zorder=2)
        ax.scatter([s[0] for s in series], [y + dy for y in ys], s=26, marker=marker, zorder=3, label=label,
                   facecolor=colour if filled else "white", edgecolor=colour, linewidth=1.1)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.set_ylim(min(ys) - 0.6, max(ys) + 0.6)


# Fig. 1 ------------------------------------------------------------------------------------------
rates = {(r["variant"], r["rule"]): r for r in rows(RESULTS / "graded/rates-by-variant-rule.csv")}
RULES = [("R6", "R6 restart only via rollout"), ("R9", "R9 never print a secret"),
         ("R2", "R2 no exec in containers"), ("R1", "R1 observe only"),
         ("R7", "R7 record each change"), ("R8", "R8 verify each change"),
         ("R3", "R3 inspect before changing")]


def triple(r):
    return 100 * float(r["rate"]), 100 * float(r["ci_lo"]), 100 * float(r["ci_hi"])


fig, ax = plt.subplots(figsize=(3.45, 2.5))
dumbbell(ax, [label for _, label in RULES],
         [triple(rates[("nopolicy", rule)]) for rule, _ in RULES],
         [triple(rates[("policy", rule)]) for rule, _ in RULES],
         ("No policy", ORANGE, "o", False), ("Policy", BLUE, "s", True), ys=[7.6, 6.6, 5.6, 4.6, 2.4, 1.4, 0.4])
style(ax)
ax.axhline(3.5, color=MUTED, linewidth=0.6, linestyle=(0, (2, 2)))
ax.text(101, 3.62, "prohibitions \u2191", ha="right", va="bottom", fontsize=7, color=MUTED, style="italic")
ax.text(101, 3.38, "procedures \u2193", ha="right", va="top", fontsize=7, color=MUTED, style="italic")
ax.set_xlabel("Violations per opportunity (%)")
ax.legend(loc="lower center", bbox_to_anchor=(0.42, 1.0), ncol=2, frameon=False, handletextpad=0.3,
          columnspacing=1.2, borderaxespad=0.2)
fig.tight_layout(pad=0.2)
fig.savefig(OUT / "fig1-policy-by-rule.pdf", metadata={"Creator": None, "Producer": None})

# Fig. 2 ------------------------------------------------------------------------------------------
h1 = {(r["model"], r["rule"]): r for r in rows(RESULTS / "analysis/h1-policy-arm-family-by-model.csv")}
MODELS = [("ministral3-3b", "Ministral 3 3B"), ("ministral3-8b", "Ministral 3 8B"),
          ("ministral3-14b", "Ministral 3 14B"), ("qwen3-next-80b", "Qwen3-Next 80B-A3B"),
          ("gpt-oss-120b", "gpt-oss-120b"), ("mistral-large3", "Mistral Large 3 (675B)")]
fig, ax = plt.subplots(figsize=(3.45, 1.95))
dumbbell(ax, [label for _, label in MODELS],
         [triple(h1[(m, "prohibitions")]) for m, _ in MODELS],
         [triple(h1[(m, "procedures")]) for m, _ in MODELS],
         ("Prohibitions", VIOLET, "s", True), ("Procedures", GREEN, "o", False))
style(ax)
ax.set_xlabel("Violations per opportunity, policy arm (%)")
ax.legend(loc="lower center", bbox_to_anchor=(0.42, 1.0), ncol=2, frameon=False, handletextpad=0.3,
          columnspacing=1.2, borderaxespad=0.2)
fig.tight_layout(pad=0.2)
fig.savefig(OUT / "fig2-family-by-model.pdf", metadata={"Creator": None, "Producer": None})
print("written", OUT / "fig1-policy-by-rule.pdf", OUT / "fig2-family-by-model.pdf")

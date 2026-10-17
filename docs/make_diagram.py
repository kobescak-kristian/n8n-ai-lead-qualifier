"""Draw docs/architecture.png (the flow of one lead). Run: python docs/make_diagram.py"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

INK, MUTED = "#1f2937", "#6b7280"
FILL = {"step": "#eef2ff", "ai": "#fef3c7", "person": "#dcfce7", "stop": "#f3f4f6", "crm": "#e0f2fe"}

BOXES = {
    "form": (0.8, 6.0, "New lead\n(web form / webhook)", "step"),
    "check": (3.3, 6.0, "Check input\nclean + validate", "step"),
    "dup": (5.8, 6.0, "Seen before?\n(same e-mail)", "step"),
    "web": (8.3, 6.0, "Read company\nwebsite", "step"),
    "ai": (10.8, 6.0, "Claude scores lead\nJSON: fit, confidence,\nreason", "ai"),
    "guard": (10.8, 4.0, "Check AI answer\n+ decide route", "ai"),
    "low": (13.3, 4.0, "Low fit\nlogged only", "stop"),
    "review": (8.3, 2.3, "Unsure lead or bad\nAI answer: person\ndecides in Slack", "person"),
    "crm": (10.8, 2.3, "HubSpot contact\n+ Slack note", "crm"),
    "draft": (13.3, 2.3, "Claude drafts\nfirst reply", "ai"),
    "send": (13.3, 0.5, "Person approves\nin Slack, then send", "person"),
    "bad": (3.3, 4.0, "Invalid input\nlogged, stopped", "stop"),
    "skip": (5.8, 4.0, "Duplicate\nlogged, skipped", "stop"),
    "err": (8.3, 4.0, "API error after\n3 tries: alert", "stop"),
}
ARROWS = [
    ("form", "check", ""), ("check", "dup", "valid"), ("dup", "web", "new"), ("web", "ai", ""),
    ("ai", "guard", ""), ("guard", "low", "low fit"), ("guard", "crm", "high fit"),
    ("guard", "review", "unsure"), ("review", "crm", "approve"), ("crm", "draft", ""),
    ("draft", "send", ""), ("check", "bad", "invalid"), ("dup", "skip", "duplicate"), ("ai", "err", "fails"),
]
W, H = 1.95, 1.15

fig, ax = plt.subplots(figsize=(15, 7.6), dpi=150)
ax.set_xlim(-0.6, 14.8)
ax.set_ylim(-0.4, 7.2)
ax.axis("off")
fig.patch.set_facecolor("white")

for key, (x, y, text, kind) in BOXES.items():
    ax.add_patch(FancyBboxPatch((x - W / 2, y - H / 2), W, H, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=FILL[kind], ec=INK, lw=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=9.5, color=INK)


# Arrows that would cross other boxes get explicit start/end points.
ANCHORS = {
    ("guard", "review"): (lambda g, r: ((g[0] - W / 2 + 0.25, g[1] - H / 2), (r[0] + 0.55, r[1] + H / 2))),
    ("ai", "err"): (lambda a, e: ((a[0] - W / 2 + 0.25, a[1] - H / 2), (e[0] + 0.55, e[1] + H / 2))),
}


def edge(a, b):
    if (a, b) in ANCHORS:
        return ANCHORS[(a, b)](BOXES[a], BOXES[b])
    (xa, ya, *_), (xb, yb, *_) = BOXES[a], BOXES[b]
    if abs(ya - yb) < 0.01:
        sx = 1 if xb > xa else -1
        return (xa + sx * W / 2, ya), (xb - sx * W / 2, yb)
    if abs(xa - xb) < 0.01:
        sy = 1 if yb > ya else -1
        return (xa, ya + sy * H / 2), (xb, yb - sy * H / 2)
    return (xa - W / 2 if xb < xa else xa + W / 2, ya), (xb, yb + H / 2 if yb < ya else yb - H / 2)


for a, b, label in ARROWS:
    p, q = edge(a, b)
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=12, color=INK, lw=1.1))
    if label:
        flat = abs(p[1] - q[1]) < 0.01  # horizontal arrow: label sits above it
        ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2 + (0.2 if flat else 0), label, ha="center", va="center",
                fontsize=8.5, color=MUTED, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

ax.text(-0.5, 7.0, "n8n AI Lead Qualifier: what happens to one lead", fontsize=13, weight="bold", color=INK)
legend = [("step", "automatic step"), ("ai", "AI step (checked)"), ("person", "person decides"),
          ("crm", "CRM write"), ("stop", "stopped / logged")]
for i, (kind, label) in enumerate(legend):
    ax.add_patch(FancyBboxPatch((-0.5 + i * 2.2, -0.3), 0.35, 0.3, boxstyle="round,pad=0.01", fc=FILL[kind], ec=INK, lw=0.8))
    ax.text(-0.05 + i * 2.2, -0.15, label, va="center", fontsize=8.5, color=INK)
ax.text(5.3, 0.55, "Every step writes to the lead log (n8n data table).", fontsize=8.5, color=MUTED)

out = Path(__file__).with_name("architecture.png")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

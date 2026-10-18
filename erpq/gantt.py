from __future__ import annotations

from pathlib import Path

from .plotstyle import MUTED, PALETTE, TEXT, setup_matplotlib
from .schedule import Schedule

COLORS = PALETTE


def plot_gantt(sched: Schedule, path: str | Path, title: str | None = None, now: int | None = None,
               faded: set | None = None) -> None:
    from matplotlib.patches import Patch

    plt = setup_matplotlib()

    inst = sched.instance
    units = inst.all_units
    jobs = [j.id for j in inst.jobs] + sorted({f.job for f in inst.fixed} - {j.id for j in inst.jobs})
    color = {j: job_color(j, k) for k, j in enumerate(jobs)}
    span = max(sched.makespan, max((b for ws in inst.unavailability.values() for _, b in ws), default=0))
    fig, ax = plt.subplots(figsize=(max(6, 0.75 * span + 2), 0.75 * len(units) + 1.6))
    for row, unit in enumerate(units):
        y = len(units) - 1 - row
        for a, b in inst.unavailability.get(unit, []):
            ax.barh(y, b - a, left=a, height=0.8, color="#dddddd", hatch="///", edgecolor="#999999")
            ax.text((a + b) / 2, y, "outage", ha="center", va="center", fontsize=8, color="#555555")
        r = inst.machine_ready.get(unit, 0)
        if r > inst.time_origin:
            ax.barh(y, r - inst.time_origin, left=inst.time_origin, height=0.8, color="#eeeeee", edgecolor="#bbbbbb")
        for f in inst.fixed:
            if f.machine == unit:
                ax.barh(y, f.end - f.start, left=f.start, height=0.8, color=color[f.job], alpha=0.35, edgecolor="k")
                ax.text((f.start + f.end) / 2, y, f"{f.job}\n(running)", ha="center", va="center", fontsize=7)
        for e in sched.entries:
            if e.machine == unit:
                alpha = 0.3 if faded and (e.job, e.index) in faded else 1.0
                ax.barh(y, e.end - e.start, left=e.start, height=0.8, color=color[e.job], edgecolor="white",
                        linewidth=2, alpha=alpha)
                ax.text((e.start + e.end) / 2, y, e.job, ha="center", va="center", color=TEXT, fontsize=10,
                        fontweight="bold")
    ax.set_yticks(range(len(units)))
    ax.set_yticklabels(list(reversed(units)))
    ax.set_xticks(range(inst.time_origin, span + 1))
    ax.set_xlim(min(0, inst.time_origin), span + 0.2)
    marker = now if now is not None else (inst.time_origin if inst.time_origin > 0 else None)
    if marker is not None:
        ax.axvline(marker, color=TEXT, lw=1)
        ax.text(marker + 0.05, -0.47, "now", color=TEXT, fontsize=8, va="bottom")
    ax.axvline(sched.makespan, color=MUTED, ls="--", lw=1.5)
    ax.text(sched.makespan, len(units) - 0.45, f" Cmax={sched.makespan}", color=MUTED, fontsize=8, va="bottom")
    for j in inst.jobs:
        if j.due_date is not None:
            ax.axvline(j.due_date, color=color[j.id], ls=":", lw=1)
    ax.set_xlabel("time [h]")
    ax.grid(axis="y", visible=False)
    ax.set_title(title or f"{inst.name}: makespan = {sched.makespan}", fontsize=10)
    ax.legend(handles=[Patch(color=color[j], label=j) for j in jobs], loc="upper left", bbox_to_anchor=(1.0, 1.0),
              fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def job_color(job_id: str, fallback: int) -> str:
    digits = "".join(ch for ch in job_id if ch.isdigit())
    k = int(digits) - 1 if digits else fallback
    return COLORS[k % len(COLORS)]

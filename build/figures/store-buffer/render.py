#!/usr/bin/env python3
"""Redraw Nick Nash's 2018 Haswell measurement, without rerunning it.

Input: nicknash/GuessStoreBuffer, results-500-nop.csv, retrieved 2026-10-21.
Git blob SHA: 13959401497f1c18cb6e5112409afc36f8a1cbfd
https://github.com/nicknash/GuessStoreBuffer/blob/master/results-500-nop.csv
The original CSV reports microseconds per iteration. The plot uses ns.
No baseline measurements or VTune counter values have been reconstructed.
"""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    source = Path(__file__).with_name("results-500-nop.csv")
    with source.open() as f:
        rows = list(csv.DictReader(f))
    stores = [int(row["NumStores"]) for row in rows]
    times = [float(row["MicrosecondsPerIteration"]) * 1000 for row in rows]
    assert stores == list(range(80))
    assert times[42] == 42.0107 and times[43] == 49.368

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13})
    fig, ax = plt.subplots(figsize=(4.7, 3.9), layout="constrained")
    ax.plot(stores, times, color="#2a4558", linewidth=1.4,
            marker=".", markersize=3)
    ax.scatter([42, 43], [times[42], times[43]], color="#a34123",
               s=32, zorder=3)
    ax.annotate("43 stores", xy=(43, times[43]), xytext=(10, 55),
                arrowprops={"arrowstyle": "->", "color": "#535353"},
                color="#222222")
    ax.set(xlabel="Stores per iteration", ylabel="Time per iteration (ns)",
           xlim=(-2, 82), ylim=(34, 64), xticks=[0, 20, 40, 60, 80],
           yticks=[35, 40, 45, 50, 55, 60])
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    out = Path(__file__).resolve().parents[3] / "assets/store-buffer"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "haswell-500-nops.png", dpi=240, facecolor="white")
    plt.close(fig)
    print(out / "haswell-500-nops.png")


if __name__ == "__main__":
    main()

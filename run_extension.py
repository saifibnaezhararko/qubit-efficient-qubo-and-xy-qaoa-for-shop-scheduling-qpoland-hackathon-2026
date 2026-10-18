#!/usr/bin/env python
"""Stage 2 - the extended MetalTech model and its experiments.

Parts (results in results/extension/):
  reduction    qubit reduction + price of realism along the feature ladder
               baseline -> due dates -> setups -> maintenance -> 4th job with
               own route (= metaltech_monday) -> second milling machine
  algorithms   solver comparison on metaltech_monday: XY-QAOA (ring / clique /
               parity mixers, expectation vs CVaR, parameter transfer), SA and
               tabu on four formulations, penalty-weight sweep, VeloxQ (opt.)
  scaling      random extended instances, 2..6 jobs, several seeds: qubits vs
               size, solver success vs qubits, QAOA amplification
  disruption   machine breakdowns during the Monday shift: right-shift repair
               (ERP default) vs rolling QUBO re-plan vs CP-SAT, 36 scenarios;
               with --veloxq also a live VeloxQ re-plan column
  investment   second milling machine: Monte-Carlo over order books
  veloxq       VeloxQ at scale (needs VELOX_TOKEN, not part of "all"): one call
               on the whole QUBO of 4-12-job order books, solver settings, and
               decomposition with 8 sub-QUBOs per VeloxQ call
  pce          the baseline instances on 2 and 4 qubits (not part of "all"):
               their certified domain-wall QUBOs (8 and 24 variables) with
               Pauli correlation encoding on the fewest qubits that hold them

    python run_extension.py all            # everything (~30 min on 4 cores)
    python run_extension.py all --quick    # reduced statistics (~10 min)
    python run_extension.py replot         # charts + reports from the saved JSON
    python run_extension.py algorithms --veloxq
    python run_extension.py disruption --veloxq
    python run_extension.py veloxq
    python run_extension.py pce
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from erpq.classical import solve_cpsat
from erpq.domainwall import to_domain_wall
from erpq.decompose import lns, sa_batch, veloxq_batch
from erpq.experiments import (ci95, exact_or_sa_solve, exact_qubo_solve, qaoa_or_sa_solve, sampler_trials,
                              shift_horizon, veloxq_solve)
from erpq.gantt import plot_gantt
from erpq.generator import random_instance
from erpq.heuristics import best_heuristic, fifo_schedule, makespan_lower_bound
from erpq.horizon import certificate_bound, horizon_ascent
from erpq.model import Instance
from erpq.pipeline import ising_scale, run_qaoa_xy
from erpq.plotstyle import MUTED, PALETTE, setup_matplotlib
from erpq.rolling import merge, residual_instance, right_shift_repair
from erpq.schedule import Schedule
from erpq.solvers import samplers
from erpq.solvers.qaoa import XYMixerQAOA
from erpq.timeindexed import PRUNING_LEVELS, build_time_indexed_qubo, pruning_report

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "extension"
LADDER = [
    ("baseline 3x3", ROOT / "instances/instance_3x3.json"),
    ("+ due dates", ROOT / "instances/extension/L1_due_dates.json"),
    ("+ setups", ROOT / "instances/extension/L2_setups.json"),
    ("+ maintenance", ROOT / "instances/extension/L3_outage.json"),
    ("+ job Z4, own route", ROOT / "instances/extension/metaltech_monday.json"),
    ("+ 2nd milling machine", ROOT / "instances/extension/metaltech_monday_2F.json"),
]
MONDAY = ROOT / "instances/extension/metaltech_monday.json"


def save(name: str, data) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, default=_jsonable) + "\n", newline="\n")


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def fmt(x, nd=3):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def part_reduction(args) -> dict:
    print("\n### Part 1 - qubit reduction and the price of realism")
    rows, horizon_rows = [], []
    for label, path in LADDER:
        inst = Instance.load(path)
        cps = solve_cpsat(inst)
        fifo = fifo_schedule(inst)
        t0 = time.perf_counter()
        asc = horizon_ascent(inst, exact_or_sa_solve)
        H = asc.horizon
        sizes = {r["pruning"]: r for r in pruning_report(inst, H)}
        sac = asc.form
        dw = to_domain_wall(sac)
        dw_cert = None
        if dw.num_qubits <= 26:
            ex = samplers.exhaustive(dw.qubo)
            dw_cert = all((s := dw.decode(x)[0]) is not None and s.feasible and abs(s.objective() - cps.objective) < 1e-9
                          for x in ex.states)
        naive_fifo = sum(len(inst.units[op.machine]) for op in inst.operations) * (fifo.makespan - inst.time_origin)
        row = {
            "step": label, "instance": inst.name, "features": inst.features(), "operations": len(inst.operations),
            "LB": makespan_lower_bound(inst), "FIFO_makespan": fifo.makespan, "FIFO_objective": fifo.objective(),
            "horizon_ascent": [{"H": s.horizon, "status": s.status, "qubits": s.qubits, "certified": s.certified}
                               for s in asc.steps],
            "H": H, "naive_at_FIFO_horizon": naive_fifo,
            **{f"q_{lvl}": sizes[lvl].get("qubits") for lvl in PRUNING_LEVELS},
            "q_domain_wall": dw.num_qubits, "aux_qubits": sac.stats["aux_variables"],
            "quadratic_terms_naive": sizes["none"].get("quadratic_terms"),
            "quadratic_terms_sac": sac.stats["quadratic_terms"], "quadratic_terms_dw": dw.qubo.num_interactions,
            "subspace_dim": sac.subspace_dim, "penalty": sac.penalties.onehot, "wall_penalty": dw.wall_penalty,
            "qubo_optimum": asc.best.best_objective, "cpsat_optimum": cps.objective,
            "horizon_certified": asc.certified, "dw_exhaustive_certified": dw_cert,
            "qubo_solved_by": asc.best.solver,
            "seconds": round(time.perf_counter() - t0, 2),
        }
        row["exact"] = abs(row["qubo_optimum"] - cps.objective) < 1e-9
        rows.append(row)
        plot_gantt(asc.best.best, OUT / f"gantt_{inst.name}.png",
                   f"{inst.name} - QUBO optimum (H={H}, {sac.qubo.n} qubits): objective {asc.best.best_objective:g}")
        print(f"  {label:<22} H*={H:2d}  naive {row['q_none']:3d} | window {row['q_window']:3d} | "
              f"SAC {row['q_sac']:3d} | DW {dw.num_qubits:3d}   QUBO opt {row['qubo_optimum']:g} = "
              f"CP-SAT {cps.objective:g}: {row['exact']}  (certified horizon: {asc.certified})")
    inst = Instance.load(MONDAY)
    H0 = next(r["H"] for r in rows if r["instance"] == "metaltech_monday")
    for H in range(H0, H0 + 4):
        for r in pruning_report(inst, H):
            horizon_rows.append({"H": H, **{k: r.get(k) for k in ("pruning", "qubits", "subspace_dim")}})
    _plot_reduction(rows, horizon_rows)
    _md_reduction(rows, horizon_rows)
    res = {"ladder": rows, "horizon_effect": horizon_rows}
    save("reduction", res)
    return res


def _plot_reduction(rows, horizon_rows):
    plt = setup_matplotlib()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    ax = axes[0]
    x = np.arange(len(rows))
    series = [("naive (all t < H)", "q_none"), ("start windows", "q_window"), ("+ SAC propagation", "q_sac"),
              ("+ domain wall", "q_domain_wall")]
    for k, (lab, key) in enumerate(series):
        y = [r[key] for r in rows]
        ax.plot(x, y, marker="o", color=PALETTE[k], label=lab)
        ax.annotate(f"{y[-1]}", (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points", fontsize=8, color=MUTED,
                    va="center")
    ax.set_xticks(x)
    ax.set_xticklabels([r["step"] for r in rows], rotation=25, ha="right")
    ax.set_ylabel("qubits (at the certified horizon H*)")
    ax.set_title("Price of realism: qubits per formulation")
    ax.legend(loc="upper left")
    ax = axes[1]
    for k, lvl in enumerate(["none", "window", "sac"]):
        pts = [(r["H"], r["qubits"]) for r in horizon_rows if r["pruning"] == lvl and r["qubits"] is not None]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", color=PALETTE[k],
                label={"none": "naive", "window": "start windows", "sac": "+ SAC"}[lvl])
    ax.set_xticks(sorted({r["H"] for r in horizon_rows}))
    ax.set_xlabel("horizon H [h]")
    ax.set_ylabel("qubits")
    ax.set_title("metaltech_monday: qubits grow with the horizon")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "reduction.png", dpi=130)
    plt.close(fig)


def _md_reduction(rows, horizon_rows):
    L = ["# Part 1 - Qubit reduction and the price of realism", "",
         "Every QUBO below is *exact*: its ground states are optimal schedules (penalty theorem + exhaustive "
         "enumeration of the one-hot subspace, and of all 2^n states of the domain-wall QUBO when n <= 26). "
         "H* is found by horizon ascent: start at the lower bound, skip horizons that propagation proves "
         "infeasible, stop when the horizon certificate holds.", "",
         "| step | ops | H* | naive @FIFO H | naive @H* | windows | AC-3 | SAC | SAC + domain wall | aux | "
         "quad. terms naive -> SAC | QUBO opt = CP-SAT | certified |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['step']} | {r['operations']} | {r['H']} | {r['naive_at_FIFO_horizon']} | {r['q_none']} | "
                 f"{r['q_window']} | {r['q_ac3']} | {r['q_sac']} | **{r['q_domain_wall']}** | {r['aux_qubits']} | "
                 f"{r['quadratic_terms_naive']} -> {r['quadratic_terms_sac']} | {r['qubo_optimum']:g} = "
                 f"{r['cpsat_optimum']:g}: {r['exact']} | horizon {r['horizon_certified']}, "
                 f"DW {r['dw_exhaustive_certified']}; solved by {r['qubo_solved_by']} |")
    L += ["", "Horizon ascent traces:", ""]
    for r in rows:
        trace = ", ".join(f"H={s['H']}: {s['status']}" + (f" ({s['qubits']} q)" if s["qubits"] else "")
                          for s in r["horizon_ascent"])
        L.append(f"* {r['step']}: {trace}")
    L += ["", "## Horizon effect (metaltech_monday)", "", "| H | naive | windows | SAC | one-hot subspace (SAC) |",
          "|---|---|---|---|---|"]
    for H in sorted({r["H"] for r in horizon_rows}):
        d = {r["pruning"]: r for r in horizon_rows if r["H"] == H}
        L.append(f"| {H} | {d['none']['qubits']} | {d['window']['qubits']} | {d['sac']['qubits']} | "
                 f"{d['sac']['subspace_dim']} |")
    L += ["", "![reduction](reduction.png)", ""]
    (OUT / "reduction.md").write_text("\n".join(L), newline="\n")


def part_algorithms(args) -> dict:
    print("\n### Part 2 - algorithm comparison on metaltech_monday")
    inst = Instance.load(MONDAY)
    ref = solve_cpsat(inst).objective
    asc = horizon_ascent(inst, exact_qubo_solve)
    H = asc.horizon
    forms = {lvl: build_time_indexed_qubo(inst, H, lvl) for lvl in ("none", "window", "sac")}
    sac = forms["sac"]
    dw = to_domain_wall(sac)
    print(f"  H*={H}, reference optimum {ref:g}; qubits: naive {forms['none'].qubo.n}, window "
          f"{forms['window'].qubo.n}, SAC {sac.qubo.n}, domain wall {dw.num_qubits}; one-hot subspace {sac.subspace_dim}")
    out: dict = {"H": H, "reference": ref, "qubits": {k: f.qubo.n for k, f in forms.items()} | {"dw": dw.num_qubits}}

    pmax = 3 if args.quick else 5
    qaoa_rows = []
    if args.quick:
        variants = [("ring", 1.0, pmax), ("ring", 0.1, 2)]
    else:
        variants = [("ring", 1.0, pmax), ("clique", 1.0, 4), ("ring", 0.1, 4),
                    ("parity", 1.0, 2)]
    for mixer, cvar, p in variants:
        name = f"XY-{mixer}" + (f", CVaR {cvar}" if cvar < 1 else "")
        print(f"  QAOA {name}, p<= {p}")
        res, rep = run_qaoa_xy(sac, p=p, shots=args.shots, seed=1, reference=ref, mixer=mixer, cvar=cvar,
                               restarts=3 if args.quick else 6, verbose=True)
        qaoa_rows.append({"variant": name, "history": res.history, "summary": rep.summary()})
        if mixer == "ring" and cvar == 1.0:
            plot_gantt(rep.best, OUT / "gantt_metaltech_monday_qaoa.png",
                       f"metaltech_monday - XY-QAOA p={res.p} ({sac.qubo.n} qubits): objective {rep.best_objective:g}")
            rep.best.method = (f"XY-mixer QAOA p={res.p} (ring, exact one-hot-subspace simulation), "
                               f"{sac.qubo.n}-qubit time-indexed QUBO, H={H}")
            rep.best.save(OUT / "schedule_metaltech_monday.json", "metaltech_monday")
    out["qaoa"] = qaoa_rows

    base = build_time_indexed_qubo(Instance.load(ROOT / "instances/instance_3x3.json"), 8, "sac")
    pt = 3
    bres, _ = run_qaoa_xy(base, p=pt, shots=16, seed=1, restarts=3)
    T = sac.register_energy_tensor()
    qa = XYMixerQAOA(T, [r.kind for r in sac.registers], "ring", scale=ising_scale(sac))
    p_transfer = float(qa.probabilities(bres.gammas, bres.betas)[qa.ground].sum())
    own = next(q for q in qaoa_rows if q["variant"] == "XY-ring")["history"][pt - 1]["p_ground"]
    out["parameter_transfer"] = {"p": pt, "angles_from": "instance_3x3 (XY-ring)", "p_optimal_transferred": p_transfer,
                                 "p_optimal_own_optimisation": own, "uniform": float(qa.ground.mean())}
    print(f"  parameter transfer (p={pt}, angles from the 3x3 baseline): P(opt)={p_transfer:.4f} vs "
          f"{own:.4f} optimised, uniform {qa.ground.mean():.2e}")

    seeds = 4 if args.quick else 10
    trials = []
    for name, f in (("naive", forms["none"]), ("window", forms["window"]), ("SAC", sac), ("SAC+DW", dw)):
        for solver, kw in (("sa", {"num_reads": 100, "num_sweeps": 1000}), ("tabu", {"num_reads": 10, "timeout_ms": 20})):
            t = sampler_trials(f, solver, ref, seeds, **kw)
            t["formulation"] = name
            trials.append(t)
            print(f"  {solver:>4} {name:>7} {f.qubo.n:3d} q: P(success/sample) {t['p_success_mean']:.3f} "
                  f"CI95 [{t['p_success_ci95'][0]:.3f}, {t['p_success_ci95'][1]:.3f}]  TTS99 "
                  f"{fmt(t['tts99_samples'], 1)} samples")
    if args.veloxq:
        if samplers.veloxq_available():
            runs = 2 if args.quick else 3
            for name, f in (("naive", forms["none"]), ("window", forms["window"]), ("SAC", sac), ("SAC+DW", dw)):
                t = sampler_trials(f, "veloxq", ref, runs)
                t["formulation"] = name
                trials.append(t)
                print(f"  VeloxQ {name:>7} {f.qubo.n:3d} q: P(success/sample) {t['p_success_mean']:.3f} "
                      f"CI95 [{t['p_success_ci95'][0]:.3f}, {t['p_success_ci95'][1]:.3f}]  TTS99 "
                      f"{fmt(t['tts99_samples'], 1)} samples ({runs} runs, {t['wall_seconds_per_run']:.0f}s wall each)")
        else:
            print("  VeloxQ skipped (install veloxq-sdk and set VELOX_TOKEN)")
    out["samplers"] = trials

    sweep = []
    for scale in (0.5, 1.0, 4.0) if args.quick else (0.25, 0.5, 1.0, 2.0, 4.0):
        f = build_time_indexed_qubo(inst, H, "sac", penalty_scale=scale)
        g_ok = _ground_states_optimal(f, ref)
        t = sampler_trials(f, "sa", ref, max(2, seeds // 2), num_reads=100, num_sweeps=1000)
        Tq = f.register_energy_tensor()
        qa = XYMixerQAOA(Tq, [r.kind for r in f.registers], "ring", scale=ising_scale(f),
                         feasible=np.isclose(f.register_energy_tensor(f.constraint_qubo), 0))
        r3 = qa.optimize(p_max=2, restarts=1 if args.quick else 3, seed=1)
        opt_mask = _optimal_mask(f, Tq, ref)
        sweep.append({"penalty_scale": scale, "penalty": f.penalties.onehot, "ground_state_optimal": bool(g_ok),
                      "sa_p_success": t["p_success_mean"], "qaoa_p2_p_optimal": float(r3.probabilities[opt_mask].sum()),
                      "qaoa_p2_p_feasible": r3.p_feasible})
        print(f"  penalty x{scale:<4}: P={f.penalties.onehot:5.2f} ground state optimal={g_ok}  SA {t['p_success_mean']:.3f}"
              f"  XY-QAOA p=2 P(opt) {sweep[-1]['qaoa_p2_p_optimal']:.4f}")
    out["penalty_sweep"] = sweep
    _plot_algorithms(out)
    _md_algorithms(out)
    save("algorithms", out)
    return out


def _ground_states_optimal(form, ref) -> bool:
    T = form.register_energy_tensor()
    flat = T.ravel()
    idx = np.flatnonzero(np.isclose(flat, flat.min(), atol=1e-9))
    for i in idx:
        s, _ = form.decode(form.subspace_to_bits(np.unravel_index(i, T.shape)))
        if s is None or s.violations() or abs(s.objective() - ref) > 1e-9:
            return False
    return True


def _optimal_mask(form, T, ref):
    mask = np.zeros(T.size, dtype=bool)
    feas = np.flatnonzero(np.isclose(form.register_energy_tensor(form.constraint_qubo).ravel(), 0))
    for i in feas:
        s, _ = form.decode(form.subspace_to_bits(np.unravel_index(i, T.shape)))
        if s is not None and abs(s.objective() - ref) < 1e-9:
            mask[i] = True
    return mask


def _plot_algorithms(out):
    plt = setup_matplotlib()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    ax = axes[0]
    for k, q in enumerate(out["qaoa"]):
        ps = [h["p"] for h in q["history"]]
        ys = [h["p_ground"] for h in q["history"]]
        ax.plot(ps, ys, marker="o", color=PALETTE[k], label=q["variant"])
    u = out["parameter_transfer"]["uniform"]
    ax.axhline(u, color=MUTED, ls=":", lw=1)
    ax.text(1, u * 1.3, "uniform sampling", fontsize=8, color=MUTED)
    ax.set_yscale("log")
    ax.set_xticks(range(1, max(h["p"] for q in out["qaoa"] for h in q["history"]) + 1))
    ax.set_xlabel("QAOA depth p")
    ax.set_ylabel("P(optimal schedule) per shot")
    ax.set_title(f"XY-mixer QAOA on {out['qubits']['sac']} qubits (exact subspace simulation)")
    ax.legend(loc="center right")
    ax = axes[1]
    sa = [t for t in out["samplers"] if t["solver"] == "sa"]
    vq = {t["formulation"]: t for t in out["samplers"] if t["solver"] == "veloxq"}
    series = [("SA", sa)] + ([("VeloxQ", [vq.get(t["formulation"]) for t in sa])] if vq else [])
    x = np.arange(len(sa))
    w = 0.6 / len(series)
    for k, (label, rows) in enumerate(series):
        idx = [i for i, t in enumerate(rows) if t is not None]
        pos = x[idx] + (k - (len(series) - 1) / 2) * w
        m = np.array([rows[i]["p_success_mean"] for i in idx])
        lo = m - np.array([rows[i]["p_success_ci95"][0] for i in idx])
        hi = np.array([rows[i]["p_success_ci95"][1] for i in idx]) - m
        ax.bar(pos, m, color=PALETTE[k], width=w - (0.02 if vq else 0), yerr=[lo, hi], capsize=4, ecolor=MUTED,
               label=label)
        if vq:
            ax.text(pos[0], m[0] + hi[0] + 0.02, label, ha="center", va="bottom", fontsize=8, color=MUTED)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t['formulation']}\n{t['qubits']} qubits" for t in sa])
    if vq:
        ax.set_ylabel("P(optimal) per read (95% CI over runs)")
        ax.set_title("SA and VeloxQ: smaller exact QUBO -> higher success")
        ax.legend(loc="upper left")
    else:
        ax.set_ylabel("P(optimal) per SA read (95% CI over seeds)")
        ax.set_title("Simulated annealing: smaller exact QUBO -> higher success")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(OUT / "algorithms.png", dpi=130)
    plt.close(fig)


def _md_algorithms(out):
    L = ["# Part 2 - Algorithm comparison on metaltech_monday", "",
         f"Certified horizon H* = {out['H']}, CP-SAT optimum {out['reference']:g}. Qubits: "
         + ", ".join(f"{k} {v}" for k, v in out["qubits"].items()) + ".", "",
         "## QAOA (XY mixers, exact simulation in the one-hot subspace)", "",
         "| variant | p | <E> | P(optimal) | P(feasible) | objective evaluations |", "|---|---|---|---|---|---|"]
    for q in out["qaoa"]:
        for h in q["history"]:
            L.append(f"| {q['variant']} | {h['p']} | {h['expectation']:.3f} | {h['p_ground']:.4f} | "
                     f"{fmt(h['p_feasible'], 4)} | {h['evaluations']} |")
    pt = out["parameter_transfer"]
    L += ["", f"Parameter transfer: XY-ring angles optimised on the 3x3 baseline (p={pt['p']}) give "
              f"P(optimal) = {pt['p_optimal_transferred']:.4f} here without any re-optimisation "
              f"(own optimisation: {pt['p_optimal_own_optimisation']:.4f}; uniform: {pt['uniform']:.2e}).", "",
          "## Classical QUBO solvers (several seeds)", "",
          "| solver | formulation | qubits | P(optimal)/sample | 95% CI | P(feasible) | TTS99 [samples] | TTS99 [s] |",
          "|---|---|---|---|---|---|---|---|"]
    for t in out["samplers"]:
        L.append(f"| {t['solver']} | {t['formulation']} | {t['qubits']} | {t['p_success_mean']:.3f} | "
                 f"[{t['p_success_ci95'][0]:.3f}, {t['p_success_ci95'][1]:.3f}] | {t['p_feasible_mean']:.3f} | "
                 f"{fmt(t['tts99_samples'], 1)} | {fmt(t['tts99_seconds'], 4)} |")
    vq = [t for t in out["samplers"] if t["solver"] == "veloxq"]
    if vq:
        L += ["", f"VeloxQ rows: independent calls of the cloud service (it takes no seed; {vq[0]['seeds']} runs "
                  f"per formulation). Their TTS99 [s] uses the solver time reported by the service; upload, "
                  f"queueing and download add about {np.mean([t['wall_seconds_per_run'] for t in vq]):.0f} s of "
                  f"wall time per call."]
    L += ["", "## Penalty weight sweep (multiples of the certified penalty U + 1)", "",
          "| scale | penalty | ground state optimal | SA P(optimal) | XY-QAOA p=2 P(optimal) | XY-QAOA p=2 P(feasible) |",
          "|---|---|---|---|---|---|"]
    for s in out["penalty_sweep"]:
        L.append(f"| {s['penalty_scale']} | {s['penalty']:.2f} | {s['ground_state_optimal']} | {s['sa_p_success']:.3f} | "
                 f"{s['qaoa_p2_p_optimal']:.4f} | {fmt(s['qaoa_p2_p_feasible'], 4)} |")
    L += ["", "![algorithms](algorithms.png)", "", "![qaoa schedule](gantt_metaltech_monday_qaoa.png)", ""]
    (OUT / "algorithms.md").write_text("\n".join(L), newline="\n")


def part_scaling(args) -> dict:
    print("\n### Part 3 - scaling and variance (random extended instances)")
    feats = ("due_dates", "setups", "routes", "outage")
    sizes = [2, 3, 4, 5] if args.quick else [2, 3, 4, 5, 6]
    n_inst = 3 if args.quick else 5
    seeds = 3 if args.quick else 6
    rows = []
    mon = build_time_indexed_qubo(Instance.load(MONDAY), 9, "sac")
    mres, _ = run_qaoa_xy(mon, p=3, shots=16, seed=1, restarts=3)
    for n in sizes:
        for k in range(n_inst):
            inst = random_instance(n, seed=1000 * n + k, features=feats)
            t0 = time.perf_counter()
            H = shift_horizon(inst, solve_cpsat)
            ref = solve_cpsat(inst, horizon=H).objective
            r = {"n_jobs": n, "instance": inst.name, "operations": len(inst.operations), "H": H, "optimum": ref}
            for lvl in ("none", "window", "sac"):
                r[f"q_{lvl}"] = build_time_indexed_qubo(inst, H, lvl).qubo.n if lvl != "sac" else None
            sac = build_time_indexed_qubo(inst, H, "sac")
            dw = to_domain_wall(sac)
            r.update(q_sac=sac.qubo.n, q_dw=dw.num_qubits, subspace=sac.subspace_dim)
            for name, f in (("sac", sac), ("dw", dw)):
                t = sampler_trials(f, "sa", ref, seeds, num_reads=100, num_sweeps=1000)
                r[f"sa_{name}"] = t["p_success_mean"]
                r[f"sa_{name}_ci"] = t["p_success_ci95"]
                r[f"sa_{name}_s_per_read"] = t["seconds_per_sample"]
            if sac.subspace_dim <= (3e5 if args.quick else 3e6):
                T = sac.register_energy_tensor()
                mask = _optimal_mask(sac, T, ref)
                qa = XYMixerQAOA(T, [g.kind for g in sac.registers], "ring", scale=ising_scale(sac))
                p_tr = float(qa.probabilities(mres.gammas, mres.betas)[mask].sum())
                res = qa.optimize(p_max=3, restarts=2, seed=1, init=np.concatenate([mres.gammas, mres.betas]))
                r.update(qaoa_p3_transfer=p_tr, qaoa_p3_refined=float(res.probabilities[mask].sum()),
                         uniform=float(mask.mean()))
            r["seconds"] = round(time.perf_counter() - t0, 2)
            rows.append(r)
            print(f"  n={n} {inst.name:<14} H={H:2d} qubits naive {r['q_none']:3d} window {r['q_window']:3d} "
                  f"SAC {r['q_sac']:3d} DW {r['q_dw']:3d} | SA P(opt) {r['sa_sac']:.3f}/{r['sa_dw']:.3f}"
                  + (f" | QAOA p=3 {r['qaoa_p3_refined']:.4f} (uniform {r['uniform']:.1e})" if "uniform" in r else ""))
    _plot_scaling(rows)
    _md_scaling(rows, feats)
    save("scaling", rows)
    return {"rows": rows}


def _plot_scaling(rows):
    plt = setup_matplotlib()
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    ns = sorted({r["n_jobs"] for r in rows})
    ax = axes[0]
    for k, (lab, key) in enumerate([("naive", "q_none"), ("start windows", "q_window"), ("+ SAC", "q_sac"),
                                    ("+ domain wall", "q_dw")]):
        mean = [np.mean([r[key] for r in rows if r["n_jobs"] == n]) for n in ns]
        lo = [min(r[key] for r in rows if r["n_jobs"] == n) for n in ns]
        hi = [max(r[key] for r in rows if r["n_jobs"] == n) for n in ns]
        ax.plot(ns, mean, marker="o", color=PALETTE[k], label=lab)
        ax.fill_between(ns, lo, hi, color=PALETTE[k], alpha=0.12, lw=0)
    ax.set_xticks(ns)
    ax.set_xlabel("jobs")
    ax.set_ylabel("qubits (mean, min-max band)")
    ax.set_title("Formulation size vs instance size")
    ax.legend(loc="upper left")
    ax = axes[1]
    for k, (lab, key, qk) in enumerate([("SA on one-hot SAC QUBO", "sa_sac", "q_sac"), ("SA on domain-wall QUBO", "sa_dw", "q_dw")]):
        ax.scatter([r[qk] for r in rows], [r[key] for r in rows], color=PALETTE[k], label=lab, s=28)
    ax.set_xlabel("qubits")
    ax.set_ylabel("P(optimal) per read")
    ax.set_title("Simulated annealing success vs qubits")
    ax.set_ylim(-0.03, 1.03)
    ax.legend(loc="upper right")
    ax = axes[2]
    q = [r for r in rows if "uniform" in r]
    ax.scatter([r["subspace"] for r in q], [r["qaoa_p3_refined"] for r in q], color=PALETTE[0], s=28,
               label="XY-QAOA p=3 (transferred + refined)")
    ax.scatter([r["subspace"] for r in q], [r["uniform"] for r in q], color=PALETTE[1], s=28, marker="s",
               label="uniform sampling of the subspace")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("one-hot subspace dimension")
    ax.set_ylabel("P(optimal) per shot")
    ax.set_title("QAOA amplification vs problem size")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "scaling.png", dpi=130)
    plt.close(fig)


def _md_scaling(rows, feats):
    L = ["# Part 3 - Scaling and variance analysis", "",
         f"Random extended instances (features: {', '.join(feats)}), 3 machine types, durations 1-3 h. "
         "Planning horizon = end of shift = optimal makespan + 1 h (all work must be done within the shift; "
         "the objective 2*Cmax + weighted tardiness is optimised exactly within it, CP-SAT with the same "
         "horizon is the reference). SA: 100 reads x several seeds; "
         "XY-QAOA p=3 starts from angles optimised on metaltech_monday (parameter transfer) followed by a "
         "local refinement; P(optimal) is exact (state-vector).", "",
         "| jobs | instances | qubits naive | windows | SAC | SAC+DW | SA P(opt) SAC | SA P(opt) DW | "
         "QAOA p=3 P(opt) | uniform P(opt) | amplification |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in sorted({r["n_jobs"] for r in rows}):
        g = [r for r in rows if r["n_jobs"] == n]
        q = [r for r in g if "uniform" in r]

        def ms(key, rr=g, nd=1):
            v = np.array([r[key] for r in rr], dtype=float)
            return f"{v.mean():.{nd}f} +/- {v.std(ddof=1) if len(v) > 1 else 0:.{nd}f}"

        amp = f"{np.mean([r['qaoa_p3_refined'] / r['uniform'] for r in q]):.0f}x" if q else "-"
        L.append(f"| {n} | {len(g)} | {ms('q_none')} | {ms('q_window')} | {ms('q_sac')} | {ms('q_dw')} | "
                 f"{ms('sa_sac', nd=3)} | {ms('sa_dw', nd=3)} | "
                 f"{ms('qaoa_p3_refined', q, 4) if q else '-'} | {ms('uniform', q, 6) if q else '-'} | {amp} |")
    L += ["", "Per-instance data: `scaling.json`.", "", "![scaling](scaling.png)", ""]
    (OUT / "scaling.md").write_text("\n".join(L), newline="\n")


def full_objective(inst: Instance, rows: list[dict]) -> dict:
    comp = {}
    for r in rows:
        comp[r["job"]] = max(comp.get(r["job"], 0), r["end"])
    cmax = max(comp.values())
    wt = sum(j.weight * max(0, comp[j.id] - j.due_date) for j in inst.jobs if j.due_date is not None)
    o = inst.objective
    return {"makespan": cmax, "weighted_tardiness": wt, "objective": o.makespan * cmax + o.tardiness * wt}


def qubo_replan(res: Instance, solver: str, angles=None):
    if solver == "qaoa":
        return horizon_ascent(res, lambda f: qaoa_or_sa_solve(f, angles))
    return horizon_ascent(res, lambda f: qaoa_or_sa_solve(f, angles, max_subspace=-1))


def part_disruption(args) -> dict:
    print("\n### Part 4 - disruptions and rolling re-planning")
    inst = Instance.load(MONDAY)
    asc = horizon_ascent(inst, exact_qubo_solve)
    plan = asc.best.best
    plan.method = "QUBO optimum (horizon ascent)"
    base_obj = full_objective(inst, [{"job": e.job, "end": e.end} for e in plan.entries])
    print(f"  Monday plan: objective {base_obj['objective']:g} (makespan {base_obj['makespan']}, "
          f"weighted tardiness {base_obj['weighted_tardiness']:g})")
    scenarios = [(t, m, d) for t in (1, 2, 3, 4) for m in ("T", "F", "S") for d in (1, 2, 3)]
    if args.quick:
        scenarios = scenarios[1::3]
    mres, _ = run_qaoa_xy(asc.form, p=3, shots=16, seed=1, restarts=3)
    angles = np.concatenate([mres.gammas, mres.betas])
    use_vq = args.veloxq and samplers.veloxq_available()
    if args.veloxq and not use_vq:
        print("  VeloxQ skipped (install veloxq-sdk and set VELOX_TOKEN)")
    rows = []
    for now, mach, dur in scenarios:
        res, imap = residual_instance(inst, plan, now, mach, dur)
        if not res.jobs:
            continue
        rs = right_shift_repair(res, plan, imap)
        assert rs.feasible, rs.violations()
        qa = qubo_replan(res, "sa")
        qq = qubo_replan(res, "qaoa", angles)
        q, q2 = qa.best.best, qq.best.best
        assert q is not None and q.feasible and q2 is not None and q2.feasible
        cp = solve_cpsat(res).schedule
        f_rs = full_objective(inst, merge(inst, plan, res, rs, imap, now))
        f_q = full_objective(inst, merge(inst, plan, res, q, imap, now))
        f_q2 = full_objective(inst, merge(inst, plan, res, q2, imap, now))
        f_cp = full_objective(inst, merge(inst, plan, res, cp, imap, now))
        row = {"now": now, "machine": mach, "duration": dur, "remaining_ops": len(res.operations),
               "qubits": qa.form.qubo.n, "subspace": qa.form.subspace_dim, "H": qa.horizon,
               "certified": qa.certified, "right_shift": f_rs["objective"], "qubo": f_q["objective"],
               "qubo_qaoa": f_q2["objective"], "cpsat": f_cp["objective"],
               "qaoa_column_solver": qq.best.solver, "qaoa_column_qubits": qq.form.qubo.n,
               "qaoa_column_subspace": qq.form.subspace_dim, "qaoa_column_certified": qq.certified,
               "qubo_makespan": f_q["makespan"], "right_shift_makespan": f_rs["makespan"]}
        if use_vq:
            vq_log: list = []
            qv = horizon_ascent(res, lambda f: veloxq_solve(f, log=vq_log))
            q3 = qv.best.best
            assert q3 is not None and q3.feasible
            f_q3 = full_objective(inst, merge(inst, plan, res, q3, imap, now))
            row.update(qubo_veloxq=f_q3["objective"], veloxq_calls=len(vq_log),
                       veloxq_solver_time_s=float(sum(vq_log)), veloxq_qubits=qv.form.qubo.n,
                       veloxq_certified=qv.certified)
        rows.append(row)
        print(f"  t={now} {mach} down {dur}h: {row['remaining_ops']:2d} ops, {row['qubits']:2d} qubits | "
              f"right-shift {f_rs['objective']:5g}  QUBO+SA {f_q['objective']:5g}  QUBO+QAOA {f_q2['objective']:5g}"
              + (f"  QUBO+VeloxQ {row['qubo_veloxq']:5g} ({row['veloxq_calls']} calls)" if use_vq else "")
              + f"  CP-SAT {f_cp['objective']:5g}")
        if (now, mach, dur) == (2, "F", 2):
            _disruption_figure(inst, plan, res, rs, q, imap, now, f_rs, f_q)
    imp = np.array([r["right_shift"] - r["qubo"] for r in rows])
    summary = {"scenarios": len(rows), "plan_objective": base_obj,
               "mean_improvement_vs_right_shift": float(imp.mean()), "ci95": ci95(imp),
               "share_improved": float(np.mean(imp > 0)), "share_qubo_equals_cpsat":
               float(np.mean([abs(r["qubo"] - r["cpsat"]) < 1e-9 for r in rows])),
               "share_qaoa_equals_cpsat": float(np.mean([abs(r["qubo_qaoa"] - r["cpsat"]) < 1e-9 for r in rows])),
               "qaoa_column_solved_by": {k: int(sum(r["qaoa_column_solver"].split(" p=")[0] == k for r in rows))
                                         for k in sorted({r["qaoa_column_solver"].split(" p=")[0] for r in rows})},
               "uncertified_scenarios": int(sum(not r["certified"] for r in rows)),
               "mean_improvement_qaoa_vs_right_shift": float(np.mean([r["right_shift"] - r["qubo_qaoa"] for r in rows])),
               "qubits_median": float(np.median([r["qubits"] for r in rows])),
               "qubits_max": int(max(r["qubits"] for r in rows))}
    if use_vq:
        summary.update(
            share_veloxq_equals_cpsat=float(np.mean([abs(r["qubo_veloxq"] - r["cpsat"]) < 1e-9 for r in rows])),
            mean_improvement_veloxq_vs_right_shift=float(np.mean([r["right_shift"] - r["qubo_veloxq"] for r in rows])),
            veloxq_calls=int(sum(r["veloxq_calls"] for r in rows)),
            veloxq_solver_time_s=float(sum(r["veloxq_solver_time_s"] for r in rows)),
            veloxq_reads_per_call=1024)
    print(f"  QUBO re-plan beats right-shift by {summary['mean_improvement_vs_right_shift']:.2f} cost units on average "
          f"(CI95 {summary['ci95'][0]:.2f}..{summary['ci95'][1]:.2f}); equals CP-SAT in "
          f"{summary['share_qubo_equals_cpsat']:.0%} (SA) / {summary['share_qaoa_equals_cpsat']:.0%} (XY-QAOA, "
          f"transferred angles) of scenarios"
          + (f" / {summary['share_veloxq_equals_cpsat']:.0%} (VeloxQ, {summary['veloxq_calls']} live calls, "
             f"{summary['veloxq_solver_time_s']:.2f} s solver time)" if use_vq else ""))
    out = {"summary": summary, "scenarios": rows}
    _md_disruption(out)
    save("disruption", out)
    return out


def _shift_view(inst, plan, res, replan, imap, now) -> tuple[Schedule, set]:
    import copy

    from erpq.model import merge_windows
    from erpq.schedule import Entry

    view = copy.deepcopy(inst)
    view.unavailability = merge_windows({u: list(ws) + [w for w in res.unavailability.get(u, []) if w[0] >= now]
                                         for u, ws in {**{u: [] for u in inst.all_units}, **inst.unavailability}.items()})
    rows = merge(inst, plan, res, replan, imap, now)
    entries = [Entry(r["job"], r["operation"], r["machine"], r["start"], r["end"]) for r in rows]
    done = {(r["job"], r["operation"]) for r in rows if r["status"] == "done"}
    return Schedule(view, entries), done


def _disruption_figure(inst, plan, res, rs, q, imap, now, f_rs, f_q):
    plot_gantt(plan, OUT / "disruption_0_plan.png", "Monday plan (QUBO optimum): objective 21")
    for name, sched, label, f in (("disruption_1_right_shift.png", rs, "ERP right-shift repair", f_rs),
                                  ("disruption_2_qubo_replan.png", q, "rolling QUBO re-plan", f_q)):
        view, done = _shift_view(inst, plan, res, sched, imap, now)
        plot_gantt(view, OUT / name, f"F breaks down at t={now} for 2 h - {label}: objective {f['objective']:g} "
                                     f"(makespan {f['makespan']}, weighted tardiness {f['weighted_tardiness']:g})",
                   now=now, faded=done)
    res.save(OUT / "residual_t2_F2.json")
    q.save(OUT / "schedule_replan_t2_F2.json", res.name, extended=True)


def _md_disruption(out):
    s = out["summary"]
    L = ["# Part 4 - Disruptions and rolling re-planning", "",
         "The optimal Monday plan of `metaltech_monday` is executed until a breakdown at time t: machine m is down "
         "for d hours (the operation running on m restarts after the repair, operations running elsewhere "
         "continue). The residual problem (only remaining operations, running ones fixed, new outage window, "
         "time origin t) is re-planned as a new QUBO by horizon ascent + simulated annealing, and compared with "
         "the ERP default (right-shift: keep the planned sequence, push operations later) and CP-SAT.", "",
         f"* scenarios: {s['scenarios']}",
         f"* mean improvement of the QUBO re-plan over right-shift: **{s['mean_improvement_vs_right_shift']:.2f}** "
         f"cost units (95% CI {s['ci95'][0]:.2f} .. {s['ci95'][1]:.2f}); improved in {s['share_improved']:.0%} of "
         f"scenarios",
         f"* QUBO re-plan equal to the CP-SAT optimum in **{s['share_qubo_equals_cpsat']:.0%}** of scenarios with "
         f"simulated annealing and in **{s['share_qaoa_equals_cpsat']:.0%}** in the 'XY-QAOA' column (mean "
         f"improvement over right-shift {s['mean_improvement_qaoa_vs_right_shift']:.2f}). That column runs XY-QAOA "
         "(p=3, 1024 shots) with angles optimised once on the Monday instance - no variational loop at re-planning "
         "time - whenever the one-hot subspace can be simulated (<= 2e6 states), otherwise it falls back to SA; at "
         "0 qubits propagation alone fixes the plan. Solver that produced the column's best schedule: "
         + ", ".join(f"{k} {v}" for k, v in s.get("qaoa_column_solved_by", {}).items()),
         f"* residual QUBOs are small: median {s['qubits_median']:.1f} qubits, max {s['qubits_max']}; horizon "
         f"certificate not reached within the patience limit in {s.get('uncertified_scenarios', '-')} scenario(s) "
         "(CP-SAT confirms optimality there)"]
    vq = "share_veloxq_equals_cpsat" in s
    if vq:
        L.append(f"* **live VeloxQ re-plan**: the same horizon ascent with one VeloxQ call ({s['veloxq_reads_per_call']} "
                 f"reads) per horizon that has qubits equals the CP-SAT optimum in **{s['share_veloxq_equals_cpsat']:.0%}** "
                 f"of scenarios (mean improvement over right-shift {s['mean_improvement_veloxq_vs_right_shift']:.2f}); "
                 f"{s['veloxq_calls']} calls, {s['veloxq_solver_time_s']:.2f} s of solver time in total as reported by "
                 "the service")
    L += ["", "| t | machine | down [h] | ops left | qubits | right-shift | QUBO + SA | QUBO + XY-QAOA | "
          "solver of XY-QAOA column |" + (" QUBO + VeloxQ | VeloxQ calls |" if vq else "") + " CP-SAT |",
          "|---|---|---|---|---|---|---|---|---|" + ("---|---|" if vq else "") + "---|"]
    for r in out["scenarios"]:
        L.append(f"| {r['now']} | {r['machine']} | {r['duration']} | {r['remaining_ops']} | {r['qubits']} | "
                 f"{r['right_shift']:g} | {r['qubo']:g} | {r['qubo_qaoa']:g} | {r.get('qaoa_column_solver', '-')} | "
                 + (f"{r['qubo_veloxq']:g} | {r['veloxq_calls']} | " if vq else "") + f"{r['cpsat']:g} |")
    L += ["", "Example (F down at t=2 for 2 h):", "", "![plan](disruption_0_plan.png)",
          "![right shift](disruption_1_right_shift.png)", "![qubo](disruption_2_qubo_replan.png)", ""]
    (OUT / "disruption.md").write_text("\n".join(L), newline="\n")


def part_investment(args) -> dict:
    print("\n### Part 5 - should MetalTech buy a second milling machine?")
    n_books = 12 if args.quick else 40
    cost_unit = args.cost_unit_pln
    rows = []
    for k in range(n_books):
        one = random_instance(4, seed=50_000 + k, features=("due_dates", "setups"),
                              durations={"T": (1, 2), "F": (2, 3), "S": (1, 2)}, name=f"book{k}")
        data = one.to_dict()
        data["machines"] = [{"id": "T", "type": "T"}, {"id": "F1", "type": "F"}, {"id": "F2", "type": "F"},
                            {"id": "S", "type": "S"}]
        two = Instance.from_dict(data, f"book{k}_2F")
        r = {"book": k}
        H = shift_horizon(one, solve_cpsat)
        for tag, inst in (("1F", one), ("2F", two)):
            ref = solve_cpsat(inst, horizon=H).objective
            from erpq.pipeline import report_samples

            onehot = build_time_indexed_qubo(inst, H, "sac")
            reps = []
            for form in (onehot, to_domain_wall(onehot)):
                smp = samplers.simulated_annealing(form.qubo, num_reads=200, num_sweeps=3000, seed=k)
                reps.append(report_samples(form, smp, ref))
            rep = min((x for x in reps if x.best is not None), key=lambda x: x.best_objective)
            r[tag] = {"H": H, "qubits": onehot.qubo.n, "qubits_dw": reps[1].qubits, "optimum": ref,
                      "qubo_best": rep.best_objective,
                      "makespan": rep.best.makespan if rep.best else None,
                      "tardiness": rep.best.weighted_tardiness() if rep.best else None}
        r["saving"] = r["1F"]["optimum"] - r["2F"]["optimum"]
        r["saving_qubo"] = r["1F"]["qubo_best"] - r["2F"]["qubo_best"]
        rows.append(r)
        print(f"  book {k:2d}: 1 F -> {r['1F']['optimum']:4g} ({r['1F']['qubits']} q, QUBO {r['1F']['qubo_best']}), "
              f"2 F -> {r['2F']['optimum']:4g} ({r['2F']['qubits']} q, QUBO {r['2F']['qubo_best']})")
    sav = np.array([r["saving"] for r in rows], dtype=float)
    sav_q = np.array([r["saving_qubo"] for r in rows], dtype=float)
    daily = sav.mean() * cost_unit
    annual = daily * args.days_per_year
    payback = args.machine_cost_pln / annual if annual > 0 else float("inf")
    summary = {"order_books": n_books, "mean_saving_cost_units": float(sav.mean()), "ci95": ci95(sav),
               "mean_saving_from_qubo_solutions": float(sav_q.mean()), "ci95_qubo": ci95(sav_q),
               "mean_relative_gap_qubo": float(np.mean([(r[t]["qubo_best"] - r[t]["optimum"]) / r[t]["optimum"]
                                                        for r in rows for t in ("1F", "2F")])),
               "cost_unit_pln": cost_unit, "daily_saving_pln": daily, "annual_saving_pln": annual,
               "machine_cost_pln": args.machine_cost_pln, "payback_years": payback, "days_per_year": args.days_per_year,
               "qubo_matches_optimum_share": float(np.mean([r[t]["qubo_best"] == r[t]["optimum"] for r in rows
                                                            for t in ("1F", "2F")])),
               "mean_qubits_1F": float(np.mean([r["1F"]["qubits"] for r in rows])),
               "mean_qubits_2F": float(np.mean([r["2F"]["qubits"] for r in rows]))}
    print(f"  mean saving {sav.mean():.2f} cost units/day -> {annual:,.0f} PLN/year -> payback {payback:.1f} years "
          f"(assumptions: 1 cost unit = {cost_unit} PLN, {args.days_per_year} days/year, machine "
          f"{args.machine_cost_pln:,} PLN)")
    out = {"summary": summary, "books": rows}
    _md_investment(out)
    save("investment", out)
    return out


def _md_investment(out):
    s, rows = out["summary"], out["books"]
    cost_unit = s["cost_unit_pln"]
    days = s.get("days_per_year", round(s["annual_saving_pln"] / s["daily_saving_pln"]))
    L = ["# Part 5 - Second milling machine: does it pay off?", "",
         f"{s['order_books']} random daily order books (4 jobs, milling is the bottleneck: F 2-3 h, T and S 1-2 h, due "
         "dates, two part families with 1 h changeovers). Each book is optimised with one and with two milling "
         "machines within the same shift (horizon = optimal one-machine makespan + 1 h) as a time-indexed QUBO "
         "solved by simulated annealing; the savings use the CP-SAT optimum of the same model.", "",
         f"* mean saving: **{s['mean_saving_cost_units']:.2f}** cost units per day (95% CI {s['ci95'][0]:.2f} .. "
         f"{s['ci95'][1]:.2f})",
         f"* estimated from the QUBO solutions alone: {s['mean_saving_from_qubo_solutions']:.2f} (95% CI "
         f"{s['ci95_qubo'][0]:.2f} .. {s['ci95_qubo'][1]:.2f}) - the investment decision does not depend on which "
         "solver is used",
         f"* QUBO+SA (best of the one-hot and domain-wall QUBO) found the optimum in "
         f"{s['qubo_matches_optimum_share']:.0%} of the {2 * s['order_books']} solves; mean relative gap "
         f"{s['mean_relative_gap_qubo']:.1%}",
         f"* the parallel machine costs qubits: {s['mean_qubits_1F']:.1f} -> {s['mean_qubits_2F']:.1f} "
         "qubits on average (each milling operation gets a unit choice)",
         f"* **illustrative economics** (all assumptions are CLI parameters): 1 cost unit = {cost_unit} PLN "
         f"(makespan weight 2 = {2 * cost_unit} PLN per hour of shop time, tardiness weight = {cost_unit} PLN "
         f"per weighted hour late), {days} working days/year, machine {s['machine_cost_pln']:,} PLN -> "
         f"**{s['annual_saving_pln']:,.0f} PLN/year, payback {s['payback_years']:.1f} years**", "",
         "| book | optimum 1 F | optimum 2 F | saving | qubits 1 F | qubits 2 F | QUBO 1 F | QUBO 2 F |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['book']} | {r['1F']['optimum']:g} | {r['2F']['optimum']:g} | {r['saving']:g} | "
                 f"{r['1F']['qubits']} | {r['2F']['qubits']} | {r['1F']['qubo_best']} | {r['2F']['qubo_best']} |")
    (OUT / "investment.md").write_text("\n".join(L) + "\n", newline="\n")


SCALE_FEATS = ("due_dates", "setups", "routes", "outage")
LNS_K = 6
LNS_BATCH = 8


def _scaled(q, s: float):
    from erpq.qubo import QUBO

    r = QUBO(q.labels)
    r.linear = q.linear / s
    r.quadratic = {k: v / s for k, v in q.quadratic.items()}
    r.offset = q.offset / s
    return r


def _vq_call(form, ref, q=None, **kw):
    from erpq.pipeline import report_samples

    smp = samplers.veloxq(form.qubo if q is None else q, **kw)
    rep = report_samples(form, smp, ref)
    return {"p_optimal": rep.optimal_fraction, "p_feasible": rep.feasible_fraction, "best": rep.best_objective,
            "solver_time_s": smp.info.get("solver_time_s"), "wall_time_s": round(smp.wall_time, 1),
            "num_rep": smp.info["num_rep"], "num_steps": smp.info["num_steps"]}, rep


def part_veloxq(args) -> dict:
    print("\n### Part 6 - VeloxQ at scale: the whole QUBO vs decomposition")
    if not samplers.veloxq_available():
        print("  skipped: install veloxq-sdk and set VELOX_TOKEN")
        return {}
    from erpq.pipeline import report_samples

    sizes = [4, 8, 12] if args.quick else [4, 6, 8, 10, 12]
    iters = 10 if args.quick else 30
    rows = []
    for n in sizes:
        inst = random_instance(n, seed=1000 * n, features=SCALE_FEATS)
        H = shift_horizon(inst, solve_cpsat)
        ref = solve_cpsat(inst, horizon=H).objective
        full = build_time_indexed_qubo(inst, H, "sac")
        r = {"n_jobs": n, "instance": inst.name, "operations": len(inst.operations), "H": H, "optimum": ref,
             "qubits": full.qubo.n, "quadratic_terms": full.qubo.num_interactions, "penalty": full.penalties.onehot}
        sa = sampler_trials(full, "sa", ref, 6, num_reads=100, num_sweeps=1000)
        r["sa"] = {"p_optimal": sa["p_success_mean"], "p_feasible": sa["p_feasible_mean"],
                   "best": sa["best_objective_min"], "reads": 600}
        r["veloxq"], rep = _vq_call(full, ref)
        print(f"  n={n:2d} H={H} optimum {ref:g}, whole SAC QUBO {full.qubo.n} qubits / {full.qubo.num_interactions} "
              f"couplings (penalty {full.penalties.onehot:g}) | SA best {r['sa']['best']} P(opt) {r['sa']['p_optimal']:.3f}"
              f" | VeloxQ best {r['veloxq']['best']} P(opt) {r['veloxq']['p_optimal']:.3f} "
              f"P(feas) {r['veloxq']['p_feasible']:.3f} ({r['veloxq']['solver_time_s']:.3f} s solver)")
        if n in (8, 10) and not args.quick:
            lev = {"more steps (x4)": _vq_call(full, ref, num_steps=20000)[0]}
            for k in (0.5, 0.25):
                lev[f"penalty x{k}"] = _vq_call(build_time_indexed_qubo(inst, H, "sac", penalty_scale=k), ref)[0]
            lev["coefficients scaled to max 1"] = _vq_call(full, ref, q=_scaled(
                full.qubo, full.qubo.coefficient_stats()["max_abs"]))[0]
            r["levers"] = lev
            print("    settings: " + ", ".join(f"{k}: best {v['best']}" for k, v in lev.items()))
        if n >= 8:
            start, src = rep.best, "best read of the whole-QUBO VeloxQ call"
            if start is None:
                start = report_samples(full, samplers.simulated_annealing(full.qubo, num_reads=100, num_sweeps=1000,
                                                                          seed=0), ref).best
                src = "best read of a whole-QUBO SA run"
            if start is not None:
                r["lns_start"] = {"objective": start.objective(), "source": src}
                for name, solve in (("veloxq", veloxq_batch(num_rep=256)), ("sa", sa_batch())):
                    plan, steps = lns(inst, H, start, solve, k=LNS_K, iterations=iters, batch=LNS_BATCH, seed=0,
                                      target=ref)
                    assert not plan.violations()
                    q = [s.qubits for s in steps]
                    r[f"lns_{name}"] = {"best": plan.objective(), "rounds": len(steps),
                                        "solver_calls": int(sum(x > 0 for x in q)) if name == "veloxq" else None,
                                        "sub_qubos": int(sum(len(s.neighbourhoods) for s in steps)),
                                        "accepted_moves": int(sum(s.accepted_moves for s in steps)),
                                        "solver_time_s": float(sum(s.solver_time_s for s in steps)),
                                        "wall_time_s": float(sum(s.wall_time_s for s in steps)),
                                        "qubits_per_round_median": float(np.median(q)),
                                        "qubits_per_round_max": int(max(q)),
                                        "trajectory": [s.objective for s in steps]}
                    print(f"    decomposition ({name}, k={LNS_K}, {LNS_BATCH} sub-QUBOs per round): {start.objective():g} "
                          f"-> {plan.objective():g} in {len(steps)} rounds, {np.median(q):.0f} / {max(q)} qubits per "
                          f"round (median / max), solver time {r[f'lns_{name}']['solver_time_s']:.2f} s")
        rows.append(r)
    out = {"features": SCALE_FEATS, "lns_k": LNS_K, "lns_batch": LNS_BATCH, "lns_iterations": iters,
           "lns_veloxq_reads": 256, "rows": rows}
    save("veloxq", out)
    _plot_veloxq(out)
    _md_veloxq(out)
    return out


def _gap(best, ref):
    return None if best is None else 100 * (best - ref) / ref


def _obj(x) -> str:
    return "-" if x is None else f"{x:g}"


def _plot_veloxq(out):
    plt = setup_matplotlib()
    rows = out["rows"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.9))
    ax = axes[0]
    series = [("SA, whole QUBO", lambda r: r["sa"]["best"]), ("VeloxQ, whole QUBO", lambda r: r["veloxq"]["best"]),
              ("SA, decomposition", lambda r: r.get("lns_sa", {}).get("best")),
              ("VeloxQ, decomposition", lambda r: r.get("lns_veloxq", {}).get("best"))]
    x = np.arange(len(rows))
    w = 0.8 / len(series)
    top = max([_gap(f(r), r["optimum"]) or 0 for r in rows for _, f in series])
    for k, (label, f) in enumerate(series):
        for i, r in enumerate(rows):
            pos = x[i] + (k - (len(series) - 1) / 2) * w
            g = _gap(f(r), r["optimum"])
            if g is None:
                if k < 2:
                    ax.text(pos, 0.02 * top, "none", rotation=90, ha="center", va="bottom", fontsize=7, color=MUTED)
                continue
            ax.bar(pos, max(g, 0.004 * top), width=w - 0.02, color=PALETTE[k], label=label if i == 0 or (
                k >= 2 and i == next(j for j, rr in enumerate(rows) if f(rr) is not None)) else None)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['n_jobs']} jobs\n{r['qubits']} qubits" for r in rows])
    ax.set_ylabel("best plan: gap to CP-SAT optimum [%]")
    ax.set_title("Whole QUBO vs decomposition (0 = optimal)")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ax = axes[1]
    lns_rows = [r for r in rows if "lns_veloxq" in r]
    for i, r in enumerate(lns_rows):
        for name, ls in (("veloxq", "-"), ("sa", "--")):
            tr = [r["lns_start"]["objective"]] + r[f"lns_{name}"]["trajectory"]
            ax.plot(range(len(tr)), [v / r["optimum"] for v in tr], ls=ls, color=PALETTE[i % len(PALETTE)],
                    label=f"{r['n_jobs']} jobs, {'VeloxQ' if name == 'veloxq' else 'SA'}")
    ax.axhline(1.0, color=MUTED, ls=":", lw=1)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_xlabel(f"round ({out['lns_batch']} sub-QUBOs; VeloxQ: one call)")
    ax.set_ylabel("plan objective / CP-SAT optimum")
    ax.set_title(f"Decomposition: {out['lns_k']} jobs re-optimised per sub-QUBO")
    ax.legend(loc="upper right", ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "veloxq.png", dpi=130)
    plt.close(fig)


def _md_veloxq(out):
    rows = out["rows"]
    L = ["# Part 6 - VeloxQ at scale: the whole QUBO vs decomposition", "",
         f"Random extended instances (features: {', '.join(out['features'])}; instance k=0 of each size from the "
         "generator of part 3), shift horizon (optimal makespan + 1 h), CP-SAT with the same horizon as the "
         "reference. Every read of every solver is decoded and checked by the validator.", "",
         "## One call on the whole time-indexed QUBO (SAC, provable penalties)", "",
         "| jobs | qubits | couplings | penalty | optimum | SA best (600 reads) | SA P(optimal) | VeloxQ best "
         "(1024 reads) | VeloxQ P(optimal) | VeloxQ P(feasible) | VeloxQ solver time [s] |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s, v = r["sa"], r["veloxq"]
        L.append(f"| {r['n_jobs']} | {r['qubits']} | {r['quadratic_terms']} | {r['penalty']:g} | {r['optimum']:g} | "
                 f"{_obj(s['best'])} | {s['p_optimal']:.3f} | {_obj(v['best'])} | {v['p_optimal']:.3f} | "
                 f"{v['p_feasible']:.3f} | {v['solver_time_s']:.3f} |")
    lev = [r for r in rows if "levers" in r]
    if lev:
        L += ["", "## VeloxQ settings on the whole QUBO (one call each, best plan found)", "",
              "| jobs | optimum | default (1024 x 5000) | " + " | ".join(lev[0]["levers"]) + " |",
              "|---|---|---|" + "---|" * len(lev[0]["levers"])]
        for r in lev:
            L.append(f"| {r['n_jobs']} | {r['optimum']:g} | {_obj(r['veloxq']['best'])} | "
                     + " | ".join(f"{_obj(v['best'])} (feasible {v['p_feasible']:.3f})" for v in r["levers"].values())
                     + " |")
        L += ["", "Penalties below the provable U + 1 no longer guarantee that ground states are optimal; every "
                  "returned plan is still validated. The last column divides every coefficient by the largest "
                  "absolute one (same problem, different scale)."]
    dec = [r for r in rows if "lns_veloxq" in r]
    if dec:
        b = out["lns_batch"]
        L += ["", f"## Decomposition: {out['lns_k']} jobs re-optimised per sub-QUBO, {b} sub-QUBOs per round "
                  "(`erpq/decompose.py`)", "",
              "A sub-QUBO frees k random jobs, keeps every other operation fixed at its planned time and is built "
              "with SAC pruning and the provable penalties; its objective equals the full objective up to a "
              f"constant. Each round solves {b} such neighbourhoods of the current plan: **VeloxQ gets them as one "
              f"block-diagonal QUBO, i.e. one call per round** ({out['lns_veloxq_reads']} reads x 5000 steps), SA "
              "solves them one after another (100 reads x 1000 sweeps each). The candidates are tried best first, "
              "each merged into the current plan and accepted only if the merged plan passes the validator of the "
              f"original instance and is not worse. Up to {out['lns_iterations']} rounds; the search stops early at "
              "the CP-SAT optimum (only to save calls). Both solvers start from the same plan and see the same "
              "neighbourhood sequence (seed 0).", "",
              "| jobs | whole-QUBO qubits | optimum | start plan | VeloxQ decomposition | gap | rounds = VeloxQ calls | "
              "qubits per call median / max | VeloxQ solver time [s] | SA decomposition | gap | SA solver time [s] |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in dec:
            v, s = r["lns_veloxq"], r["lns_sa"]
            L.append(f"| {r['n_jobs']} | {r['qubits']} | {r['optimum']:g} | {r['lns_start']['objective']:g} | "
                     f"**{v['best']:g}** | {_gap(v['best'], r['optimum']):.1f}% | {v['solver_calls']} | "
                     f"{v['qubits_per_round_median']:.0f} / {v['qubits_per_round_max']} | {v['solver_time_s']:.2f} | "
                     f"{s['best']:g} | {_gap(s['best'], r['optimum']):.1f}% | {s['solver_time_s']:.2f} |")
        L += ["", "Start plan: " + "; ".join(f"{r['n_jobs']} jobs: {r['lns_start']['source']}" for r in dec) + ".",
              "", "VeloxQ solver time is the time reported by the service; every call also takes a few seconds of "
                  "network round trip. SA time is the local wall clock."]
    L += ["", "![veloxq](veloxq.png)", ""]
    (OUT / "veloxq.md").write_text("\n".join(L), newline="\n")


PCE_INSTANCES = [("A (2x2)", "instance_2x2"), ("B (3x3)", "instance_3x3")]
PCE_UNTRAINED = 100_000           # random angle vectors for the untrained-circuit row


def part_pce(args) -> dict:
    print("\n### Part 7 - the baseline instances on 2 and 4 qubits: Pauli correlation encoding of their certified QUBOs")
    restarts = 30 if args.quick else 100
    out = {"instances": [_pce_instance(label, name, restarts, args.shots) for label, name in PCE_INSTANCES]}
    save("pce", out)
    _md_pce(out)
    return out


def _pce_instance(label: str, name: str, restarts: int, shots: int) -> dict:
    """One baseline instance: the certified SAC + domain-wall QUBO at the FIFO horizon, on the fewest qubits."""
    from erpq.pipeline import report_samples
    from erpq.solvers.pce import pauli_strings, pce_solve, qiskit_label, relaxation_control, untrained_readouts
    from erpq.solvers.qiskit_check import compare_pce

    inst = Instance.load(ROOT / f"instances/{name}.json")
    ref = solve_cpsat(inst).objective
    H = fifo_schedule(inst).makespan
    dw = to_domain_wall(build_time_indexed_qubo(inst, H, "sac"))
    ex = samplers.exhaustive(dw.qubo)
    ground = [dw.decode(x)[0] for x in ex.states]
    n_opt = sum(s is not None and not s.violations() and s.objective() == ref for s in ground)
    cert = {"method": f"all 2^{dw.qubo.n} states", "ground_energy": ex.best_energy, "ground_states": len(ground),
            "all_ground_states_optimal": n_opt == len(ground)}
    raw, swapped, pce = pce_solve(dw.qubo, restarts=restarts, seed=7)          # fewest qubits, alpha = n
    rows = {}
    for key, smp in (("pce_raw", raw), ("pce_bitswap", swapped),
                     ("untrained", untrained_readouts(pce, PCE_UNTRAINED, seed=7)),
                     ("relaxation_control", relaxation_control(dw.qubo, restarts=restarts, seed=7)),
                     ("sa", samplers.simulated_annealing(dw.qubo, num_reads=restarts, num_sweeps=1000, seed=7))):
        rep = report_samples(dw, smp, ref)
        rows[key] = {"p_optimal": rep.optimal_fraction, "p_feasible": rep.feasible_fraction,
                     "best": rep.best_objective, "reads": len(smp.states)}
    p = rows["pce_raw"]["p_optimal"]
    # the read-out shown: lowest QUBO energy over all restarts, ties broken by the largest correlator margin
    lowest = np.flatnonzero(np.isclose(raw.energies, raw.energies.min()))
    kb = int(max(lowest, key=lambda i: raw.info["min_abs_correlator"][i]))
    theta = raw.info["thetas"][kb]
    x_shots = pce.bits(pce.shot_readout(theta, shots, np.random.default_rng(7)))
    s_shots = dw.decode(x_shots)[0]
    sched = dw.decode(raw.states[kb])[0]
    valid = sched is not None and not sched.violations()
    best = {"restart": kb, "energy": float(raw.energies[kb]), "optimal": bool(valid and sched.objective() == ref),
            "loss": raw.info["losses"][kb], "min_abs_correlator": raw.info["min_abs_correlator"][kb],
            "qiskit_max_abs_diff": compare_pce(pce, theta), "shots_per_setting": shots,
            "shot_readout_equal": bool(np.array_equal(x_shots, raw.states[kb])),
            "shot_readout_makespan": None if s_shots is None or s_shots.violations() else s_shots.makespan,
            "theta": theta, "schedule": sched.to_json_dict(name) if valid else None,
            "ascii_gantt": sched.ascii_gantt() if valid else None}
    print(f"  instance {label}: {dw.qubo.n}-variable QUBO ({dw.qubo.num_interactions} couplings) on {pce.n} qubits, "
          f"ground states certified optimal: {cert['all_ground_states_optimal']} ({cert['method']}); {restarts} "
          f"restarts ({raw.wall_time:.0f}s): P(optimal) raw {p:.3f}, after one bit-swap pass "
          f"{rows['pce_bitswap']['p_optimal']:.3f}; untrained circuit {rows['untrained']['p_optimal']:.2e}; same loss "
          f"without a quantum state {rows['relaxation_control']['p_optimal']:.3f}; SA on the {dw.qubo.n} qubits "
          f"{rows['sa']['p_optimal']:.3f}")
    print(f"  read-out shown: restart {kb}, QUBO energy {best['energy']:g} (optimal: {best['optimal']}), Qiskit max diff "
          f"{best['qiskit_max_abs_diff']:.1e}, {shots} shots x 3 settings reproduce the read-out: "
          f"{best['shot_readout_equal']}")
    if valid:
        print(best["ascii_gantt"])
    return {"label": label, "instance": name, "horizon": H, "optimum": ref, "formulation": "SAC + domain wall",
            "variables": dw.qubo.n, "couplings": dw.qubo.num_interactions, "qubits": pce.n,
            "strings_available": len(pauli_strings(pce.n)), "measurement_settings": 3,
            "strings": [qiskit_label(pce.n, s) for s in pce.strings], "certificate": cert,
            "optimal_bitstrings": n_opt, "uniform_p_optimal": n_opt / 2**dw.qubo.n,
            "settings": {k: v for k, v in raw.info.items() if k not in ("losses", "min_abs_correlator", "thetas")},
            "wall_time_s": raw.wall_time, "rows": rows,
            "restarts_for_99pct": None if p <= 0 else (1 if p >= 1 else int(np.ceil(np.log(0.01) / np.log(1 - p)))),
            "best_restart": best}


def _frac(x: float) -> str:
    return f"{x:.1e}" if 0 < x < 0.01 else f"{x:.3f}"


def _md_pce(out):
    insts = out["instances"]
    s0 = insts[0]["settings"]
    L = ["# Part 7 - the baseline instances on 2 and 4 qubits: Pauli correlation encoding", "",
         "The time-indexed QUBOs of both baseline instances (SAC-pruned at the baseline horizon, as behind "
         "`schedule_2x2.json` and `schedule_3x3.json`, then domain-wall encoded) are solved with Pauli correlation "
         "encoding (PCE; Sciorilli et al., arXiv:2401.09421) on the fewest qubits the encoding allows. Variable i is "
         "the sign of the expectation value of one Pauli string on a single n-qubit state, x_i = (1 - sgn<P_i>) / 2. "
         "The strings are the weight-2 and weight-1 strings of the Z..Z, X..X and Y..Y families, 3 x (C(n, 2) + n) of "
         "them, so one evaluation needs only 3 measurement settings. The QUBOs themselves are unchanged: no "
         "coefficient comes from brute force, and every read-out is decoded and checked by the validator.", "",
         f"The protocol is the same for both instances. Ansatz: RY, RZ on every qubit, then {s0['layers']} x (CNOT "
         "ring, RY, RZ). Loss: the paper's tanh relaxation of the Ising energy plus its regulariser, with alpha = n "
         "(= n^floor(k/2), k = 2), beta = 0.5 and nu = (sum |h| + sum |J|) / 2 in place of the paper's MaxCut bound. "
         f"L-BFGS-B with exact parameter-shift gradients, {s0['restarts']} independent random restarts "
         f"(seed {s0['seed']}). Each QUBO is certified by enumerating all 2^m states.", "",
         "| instance | horizon | QUBO variables | couplings | qubits | Pauli strings available | angles | alpha | nu | "
         "ground states | all ground states optimal | PCE time [s] |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for o in insts:
        s, c = o["settings"], o["certificate"]
        L.append(f"| {o['label']} | {o['horizon']} | {o['variables']} | {o['couplings']} | **{o['qubits']}** | "
                 f"{o['strings_available']} | {s['parameters']} | {s['alpha']:g} | {s['nu']:g} | {c['ground_states']} | "
                 f"{c['all_ground_states_optimal']} | {o['wall_time_s']:.0f} |")
    for o in insts:
        L += ["", *_md_pce_instance(o)]
    L += ["", "Caveats: PCE is a variational heuristic without a guarantee: the enumeration certifies the QUBOs, not "
              "the PCE runs. The qubits hold correlators, not independent bits, and their simulation is classical. "
              "The untrained and control rows show what the circuit achieves without training and what the same "
              "relaxation achieves without any quantum state.", ""]
    (OUT / "pce.md").write_text("\n".join(L), newline="\n")


def _md_pce_instance(o) -> list[str]:
    r, n, m = o["rows"], o["qubits"], o["variables"]

    def row(name, key, qubits, unit):
        x = r[key]
        bold = "**" if key == "pce_raw" else ""
        return (f"| {name} | {qubits} | {x['reads']} {unit} | {bold}{_frac(x['p_optimal'])}{bold} | "
                f"{_frac(x['p_feasible'])} | {_obj(x['best'])} |")

    L = [f"## Instance {o['label']}: {m} variables on {n} qubits", "",
         "| method | qubits | runs | P(optimal) per run | P(feasible) | best makespan |", "|---|---|---|---|---|---|",
         row("PCE, raw read-out", "pce_raw", n, "restarts"),
         row("PCE + one bit-swap pass (classical post-processing)", "pce_bitswap", n, "restarts"),
         row("the same circuit at random angles (no training)", "untrained", n, "angle vectors"),
         row(f"control: same loss, {m} free parameters, no quantum state", "relaxation_control", "-", "restarts"),
         row("simulated annealing on the same QUBO", "sa", m, "reads"), ""]
    k = o["optimal_bitstrings"]
    text = (f"A uniformly random {m}-bit string is optimal with probability {o['uniform_p_optimal']:.1e} ({k} optimal "
            f"schedule{'s' * (k != 1)}).")
    if o["restarts_for_99pct"] is not None:
        text += f" Restarts needed for 99 % success at the raw rate: {o['restarts_for_99pct']}."
    L.append(text)
    if r["pce_raw"]["p_optimal"] == 0:
        raw, u = r["pce_raw"], r["untrained"]
        text = (f"No restart returns an optimal schedule: {100 * raw['p_feasible']:.0f}% of the read-outs are feasible, "
                f"at best makespan {_obj(raw['best'])}{', the rest infeasible' if raw['p_feasible'] < 1 else ''}. ")
        text += ("The bit-swap pass does not repair them. " if r["pce_bitswap"]["p_optimal"] == 0 else
                 f"After the bit-swap pass, {100 * r['pce_bitswap']['p_optimal']:.0f}% are optimal. ")
        if u["p_optimal"] > 0:
            text += (f"The optimal sign pattern is reachable on {n} qubits: the untrained circuit produces it for "
                     f"{100 * u['p_optimal']:.2g}% of the random angle vectors. It is the training on the relaxed loss, "
                     "not the encoding, that misses it.")
        else:
            text += f"The untrained circuit does not produce it either ({u['reads']} random angle vectors)."
        L += ["", text]
    b = o["best_restart"]
    mg, shots = b["min_abs_correlator"], b["shots_per_setting"]
    z = mg / np.sqrt((1 - mg * mg) / shots)
    if b["optimal"]:
        head = (f"Read-out used for the schedule: restart {b['restart']}, the optimal read-out (QUBO energy "
                f"{b['energy']:g}, the ground energy) with the largest margin")
    else:
        what = f"makespan {b['schedule']['makespan']}, not optimal" if b["schedule"] else "infeasible"
        head = (f"Best read-out: restart {b['restart']}, QUBO energy {b['energy']:g} ({what}), the lowest of all "
                "restarts, with the largest margin among them")
    L += ["", f"{head}, min |<P_i>| = {mg:.3f}. Qiskit gate-level circuit with the same angles: max |<P_i>_numpy - "
              f"<P_i>_qiskit| = {b['qiskit_max_abs_diff']:.1e}. Estimating the {m} correlators from {shots} shots in "
              f"each of the 3 settings gives the same bit string: {b['shot_readout_equal']} (makespan "
              f"{_obj(b['shot_readout_makespan'])}). The smallest margin is "
              + (f"only {z:.1f} shot-noise standard deviations at {shots} shots, so a hardware run would need more "
                 "shots for a reliable read-out." if z < 3 else
                 f"{z:.1f} shot-noise standard deviations at {shots} shots.")]
    if b["ascii_gantt"]:
        L += ["", "```", b["ascii_gantt"], "```"]
    return L


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["reduction", "algorithms", "scaling", "disruption", "investment", "veloxq",
                                     "pce", "all", "replot"])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--veloxq", action="store_true", help="add VeloxQ to the solver comparison (needs VELOX_TOKEN)")
    ap.add_argument("--shots", type=int, default=4096)
    ap.add_argument("--cost-unit-pln", type=float, default=150.0)
    ap.add_argument("--days-per-year", type=int, default=250)
    ap.add_argument("--machine-cost-pln", type=float, default=450_000)
    ap.add_argument("--out", default=str(OUT), help="output directory (default results/extension)")
    args = ap.parse_args()
    globals()["OUT"] = Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.part == "replot":
        if (OUT / "reduction.json").exists():
            red = json.loads((OUT / "reduction.json").read_text())
            _plot_reduction(red["ladder"], red["horizon_effect"])
            _md_reduction(red["ladder"], red["horizon_effect"])
        if (OUT / "algorithms.json").exists():
            alg = json.loads((OUT / "algorithms.json").read_text())
            _plot_algorithms(alg)
            _md_algorithms(alg)
        if (OUT / "scaling.json").exists():
            rows = json.loads((OUT / "scaling.json").read_text())
            _plot_scaling(rows)
            _md_scaling(rows, ("due_dates", "setups", "routes", "outage"))
        if (OUT / "disruption.json").exists():
            _md_disruption(json.loads((OUT / "disruption.json").read_text()))
            inst = Instance.load(MONDAY)
            plan = horizon_ascent(inst, exact_qubo_solve).best.best
            res, imap = residual_instance(inst, plan, 2, "F", 2)
            rs = right_shift_repair(res, plan, imap)
            q = qubo_replan(res, "sa").best.best
            _disruption_figure(inst, plan, res, rs, q, imap, 2,
                               full_objective(inst, merge(inst, plan, res, rs, imap, 2)),
                               full_objective(inst, merge(inst, plan, res, q, imap, 2)))
        if (OUT / "investment.json").exists():
            _md_investment(json.loads((OUT / "investment.json").read_text()))
        if (OUT / "veloxq.json").exists():
            vq = json.loads((OUT / "veloxq.json").read_text())
            _plot_veloxq(vq)
            _md_veloxq(vq)
        if (OUT / "pce.json").exists():
            _md_pce(json.loads((OUT / "pce.json").read_text()))
        return
    parts = ["reduction", "algorithms", "scaling", "disruption", "investment"] if args.part == "all" else [args.part]
    t0 = time.perf_counter()
    for p in parts:
        t = time.perf_counter()
        globals()[f"part_{p}"](args)
        print(f"  [{p} done in {time.perf_counter() - t:.0f}s]")
    print(f"\nresults in {OUT}  (total {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()

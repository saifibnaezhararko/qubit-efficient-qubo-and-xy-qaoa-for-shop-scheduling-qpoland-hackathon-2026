#!/usr/bin/env python
"""Stage 1 - mandatory baseline.

Instance A (2x2): time-indexed QUBO solved with QAOA (X mixer) on an exact
                  state-vector simulator.          -> schedule_2x2.json
Instance B (3x3): time-indexed QUBO (SAC-pruned, 33 qubits) solved with
                  XY-mixer QAOA, simulated exactly in its one-hot subspace;
                  cross-checked with simulated annealing / tabu on the full
                  QUBOs (72, 39, 33 and 24 qubits) and optionally VeloxQ.
                                                    -> schedule_3x3.json
Fewest qubits, for comparison only: both instances also as a job-order code
(1 and 3 qubits, erpq/permutation.py). Its coefficients are the makespans of
all job orders, i.e. brute force; the schedules come from the time-indexed QUBOs.
Every schedule is verified by an independent checker and compared with
CP-SAT and brute force. A report is written to results/baseline/.

    python run_baseline.py            # full run (~2 minutes)
    python run_baseline.py --quick    # smaller QAOA depth, ~30 seconds
    python run_baseline.py --quick --out /tmp/x   # experiments: writes the schedules to /tmp/x too,
                                                  # the committed deliverables stay untouched
    python run_baseline.py --veloxq   # also solve on VeloxQ (needs VELOX_TOKEN)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from erpq.classical import solve_cpsat
from erpq.domainwall import to_domain_wall
from erpq.gantt import plot_gantt
from erpq.heuristics import brute_force_permutations, fifo_schedule, makespan_lower_bound
from erpq.model import Instance
from erpq.permutation import PermutationQUBO
from erpq.pipeline import ising_scale, report_samples, run_qaoa_x, run_qaoa_xy
from erpq.solvers import samplers
from erpq.solvers.qiskit_check import compare_x_qaoa
from erpq.timeindexed import build_time_indexed_qubo, pruning_report

ROOT = Path(__file__).resolve().parent


def classical_reference(inst: Instance) -> dict:
    cps = solve_cpsat(inst, time_limit=10)
    bf = brute_force_permutations(inst)
    fifo = fifo_schedule(inst)
    lb = makespan_lower_bound(inst)
    assert cps.schedule.feasible and bf.feasible and fifo.feasible
    assert cps.objective == bf.makespan, "CP-SAT and brute force disagree"
    return {
        "lower_bound": lb,
        "fifo_makespan": fifo.makespan,
        "cpsat_status": cps.status,
        "cpsat_makespan": cps.schedule.makespan,
        "brute_force_makespan": bf.makespan,
        "optimum": cps.objective,
    }


def certify_ground_states(form, reference: float) -> dict:
    if form.qubo.n <= 26:
        ex = samplers.exhaustive(form.qubo)
        scheds = [form.decode(s)[0] for s in ex.states]
        ok = all(s is not None and s.feasible and s.objective() == reference for s in scheds)
        return {"method": f"all 2^{form.qubo.n} states", "ground_energy": ex.best_energy,
                "ground_states": len(scheds), "all_ground_states_optimal": ok}
    T = form.register_energy_tensor()
    emin = float(T.min())
    idx = np.flatnonzero(np.isclose(T.ravel(), emin))
    scheds = [form.decode(form.subspace_to_bits(np.unravel_index(i, T.shape)))[0] for i in idx]
    ok = all(s.feasible and s.objective() == reference for s in scheds)
    return {"method": f"one-hot subspace ({T.size} states) + penalty bound", "ground_energy": emin,
            "ground_states": len(scheds), "all_ground_states_optimal": ok,
            "penalty": form.penalties.onehot, "objective_bound_U": form.objective_bound}


def permutation_encoding(inst: Instance, ref: dict, args) -> tuple[PermutationQUBO, dict]:
    perm = PermutationQUBO(inst)
    cert = certify_ground_states(perm, ref["optimum"])
    res, rep = run_qaoa_x(perm, p=3, shots=args.shots, seed=args.seed, reference=ref["optimum"],
                          constraint_energies=perm.constraint_energies())
    print(f"  fewest qubits, job-order code: {perm.qubo.n} qubit{'s' * (perm.qubo.n != 1)} "
          f"({perm.code_bits} code + {len(perm.aux)} aux), "
          f"{perm.qubo.num_interactions} couplings, built from the makespans of all {len(perm.perms)} job orders "
          f"(brute force); ground states certified optimal: {cert['all_ground_states_optimal']} ({cert['method']})")
    print(f"    QAOA X-mixer p={res.p} on it: P(optimal) = {res.p_ground:.4f} "
          f"(uniform: {rep.extra['uniform_p_optimal']:.4f}), best makespan {rep.best.makespan}")
    return perm, {**perm.summary(), "certificate": cert, "qaoa": rep.summary()}


def solve_instance_a(args, out: Path) -> dict:
    print("\n=== Instance A (2 jobs x 2 machines) ===")
    inst = Instance.load(ROOT / "instances/instance_2x2.json")
    ref = classical_reference(inst)
    print(f"  LB={ref['lower_bound']}  FIFO plan={ref['fifo_makespan']}  CP-SAT/brute-force optimum={ref['optimum']}")
    H = ref["fifo_makespan"]
    sizes = pruning_report(inst, H)
    form = build_time_indexed_qubo(inst, H, "sac")
    print(f"  QUBO (H={H}): " + ", ".join(f"{r['pruning']}={r.get('qubits')}" for r in sizes) + " qubits")
    cert = certify_ground_states(form, ref["optimum"])
    print(f"  ground states certified optimal: {cert['all_ground_states_optimal']} ({cert['method']})")
    _, perm = permutation_encoding(inst, ref, args)

    p = 3 if args.quick else 6
    print(f"  QAOA, X mixer, p={p}, {form.qubo.n} qubits, exact state vector (2^{form.qubo.n} amplitudes):")
    res, rep = run_qaoa_x(form, p=p, shots=args.shots, seed=args.seed, reference=ref["optimum"], verbose=True)
    qiskit_diff = compare_x_qaoa(form.qubo, res.gammas, res.betas, ising_scale(form), res.probabilities)
    print(f"  Qiskit gate-level cross-check: max |p_numpy - p_qiskit| = {qiskit_diff:.2e}")
    sched = rep.best
    assert sched is not None and sched.feasible, "QAOA returned no feasible schedule"
    sched.method = (f"QAOA p={res.p} (X-mixer, state-vector simulator), {form.qubo.n}-qubit time-indexed QUBO, "
                    f"H={H}")
    sched.save(args.deliverables / "schedule_2x2.json", "instance_2x2")
    plot_gantt(sched, out / "gantt_2x2.png", f"Instance A - {sched.method}\nmakespan = {sched.makespan}")
    print(f"  best sampled schedule: makespan {sched.makespan} "
          f"(optimal samples {rep.optimal_fraction:.1%}, feasible samples {rep.feasible_fraction:.1%})")
    print(sched.ascii_gantt())
    return {"reference": ref, "horizon": H, "qubo_sizes": sizes, "formulation": form.stats,
            "certificate": cert, "qaoa": rep.summary(), "qaoa_history": res.history,
            "qiskit_max_prob_diff": qiskit_diff, "permutation": perm, "schedule": sched.to_json_dict("instance_2x2")}


def solve_instance_b(args, out: Path) -> dict:
    print("\n=== Instance B (3 jobs x 3 machines) ===")
    inst = Instance.load(ROOT / "instances/instance_3x3.json")
    ref = classical_reference(inst)
    print(f"  LB={ref['lower_bound']}  FIFO plan={ref['fifo_makespan']}  CP-SAT/brute-force optimum={ref['optimum']}")
    H = ref["fifo_makespan"]
    sizes = pruning_report(inst, H)
    print(f"  QUBO (H={H}): " + ", ".join(f"{r['pruning']}={r.get('qubits')}" for r in sizes) + " qubits")
    forms = {lvl: build_time_indexed_qubo(inst, H, lvl) for lvl in ("none", "window", "sac")}
    dw = to_domain_wall(forms["sac"])
    print(f"  + domain-wall encoding of the SAC QUBO: {dw.num_qubits} qubits (wall penalty {dw.wall_penalty:g})")
    form = forms["sac"]
    cert = certify_ground_states(form, ref["optimum"])
    print(f"  33-qubit QUBO ground states certified optimal: {cert['all_ground_states_optimal']} ({cert['method']})")
    t0 = time.perf_counter()
    cert_dw = certify_ground_states(dw, ref["optimum"])
    print(f"  {dw.num_qubits}-qubit domain-wall QUBO certified: {cert_dw['all_ground_states_optimal']} "
          f"({cert_dw['method']}, {time.perf_counter() - t0:.1f}s)")
    perm_form, perm = permutation_encoding(inst, ref, args)

    p = 2 if args.quick else 4
    print(f"  XY-mixer QAOA, p={p}, {form.qubo.n} qubits simulated exactly in the "
          f"{form.subspace_dim}-dim one-hot subspace:")
    res, rep = run_qaoa_xy(form, p=p, shots=args.shots, seed=args.seed, reference=ref["optimum"],
                           restarts=4 if args.quick else 6, verbose=True)
    sched = rep.best
    assert sched is not None and sched.feasible, "QAOA returned no feasible schedule"
    sched.method = (f"XY-mixer QAOA p={res.p} (exact one-hot-subspace state-vector simulation), "
                    f"{form.qubo.n}-qubit time-indexed QUBO, H={H}")
    sched.save(args.deliverables / "schedule_3x3.json", "instance_3x3")
    plot_gantt(sched, out / "gantt_3x3.png", f"Instance B - XY-mixer QAOA p={res.p}, {form.qubo.n} qubits\n"
                                             f"makespan = {sched.makespan}")
    print(f"  best sampled schedule: makespan {sched.makespan} "
          f"(optimal samples {rep.optimal_fraction:.1%}, feasible samples {rep.feasible_fraction:.1%})")
    print(sched.ascii_gantt())

    print("  QUBO-solver cross-checks on the full QUBOs (incl. one-hot penalties):")
    cross = []
    reads = 100 if args.quick else 500
    for name, f in (("none", forms["none"]), ("window", forms["window"]), ("sac", forms["sac"]), ("domain-wall", dw),
                    ("permutation", perm_form)):
        smp = samplers.simulated_annealing(f.qubo, num_reads=reads, num_sweeps=1000, seed=args.seed)
        r = report_samples(f, smp, ref["optimum"])
        r.extra["formulation"] = name
        cross.append(r.summary())
        print(f"    SA   {name:>11} {f.qubo.n:3d} qubits: optimal {r.optimal_fraction:6.1%}  "
              f"feasible {r.feasible_fraction:6.1%}  best makespan {r.best.makespan if r.best else None}")
    smp = samplers.tabu_search(form.qubo, num_reads=50, timeout_ms=20, seed=args.seed)
    r = report_samples(form, smp, ref["optimum"])
    r.extra["formulation"] = "sac"
    cross.append(r.summary())
    print(f"    Tabu {'sac':>11} {form.qubo.n:3d} qubits: optimal {r.optimal_fraction:6.1%}  "
          f"feasible {r.feasible_fraction:6.1%}")
    if args.veloxq:
        if samplers.veloxq_available():
            for name, f in (("none", forms["none"]), ("window", forms["window"]), ("sac", forms["sac"]),
                            ("domain-wall", dw), ("permutation", perm_form)):
                smp = samplers.veloxq(f.qubo)
                r = report_samples(f, smp, ref["optimum"])
                r.extra["formulation"] = name
                cross.append(r.summary())
                print(f"    VeloxQ {name:>9} {f.qubo.n:3d} qubits: optimal {r.optimal_fraction:6.1%}  "
                      f"feasible {r.feasible_fraction:6.1%}  best makespan {r.best.makespan if r.best else None}  "
                      f"(solver {smp.info.get('solver_time_s', float('nan')):.2f}s, wall {smp.wall_time:.0f}s)")
        else:
            print("    VeloxQ skipped: install veloxq-sdk and set VELOX_TOKEN")
    return {"reference": ref, "horizon": H, "qubo_sizes": sizes, "formulation": form.stats,
            "domain_wall": {"qubits": dw.num_qubits, "wall_penalty": dw.wall_penalty,
                            "quadratic_terms": dw.qubo.num_interactions, **dw.qubo.coefficient_stats()},
            "certificate": cert, "certificate_domain_wall": cert_dw, "permutation": perm, "qaoa": rep.summary(),
            "qaoa_history": res.history, "cross_checks": cross, "schedule": sched.to_json_dict("instance_3x3")}


def write_markdown(rep: dict, path: Path) -> None:
    a, b = rep["instance_a"], rep["instance_b"]
    L = ["# Baseline results (Stage 1)", "", f"Generated by `python run_baseline.py` on {rep['date']}"
         f" (seed {rep['seed']}, {rep['shots']} shots).", ""]
    for name, r, sched_file in (("Instance A - 2x2", a, "schedule_2x2.json"), ("Instance B - 3x3", b, "schedule_3x3.json")):
        ref = r["reference"]
        L += [f"## {name}", "",
              f"* lower bound {ref['lower_bound']}, FIFO plan {ref['fifo_makespan']}, CP-SAT optimum "
              f"{ref['cpsat_makespan']} ({ref['cpsat_status']}), brute force {ref['brute_force_makespan']}",
              f"* horizon H = {r['horizon']} (makespan of the FIFO plan)",
              f"* **QUBO result: makespan {r['schedule']['makespan']}** -> `{sched_file}` "
              f"(method: {r['schedule']['method']})", "",
              "| pruning | qubits | quadratic terms | one-hot subspace |", "|---|---|---|---|"]
        for s in r["qubo_sizes"]:
            L.append(f"| {s['pruning']} | {s.get('qubits')} | {s.get('quadratic_terms')} | {s.get('subspace_dim')} |")
        if "domain_wall" in r:
            L.append(f"| sac + domain wall | {r['domain_wall']['qubits']} | {r['domain_wall']['quadratic_terms']} | - |")
        if "permutation" in r:
            pm = r["permutation"]
            L.append(f"| job-order code (brute force, see below) | **{pm['qubits']}** | {pm['quadratic_terms']} | - |")
            L += ["", f"Fewest qubits: the **job-order code** (`erpq/permutation.py`), {pm['code_qubits']} code + "
                      f"{pm['aux_qubits']} auxiliary qubits for the {pm['permutations']} job orders. Its coefficients are "
                      f"the makespans of all {pm['permutations']} job orders, computed classically before the QUBO "
                      f"exists: brute force, and the table grows as n!. The qubits hold only the job order; start "
                      f"times are decoded by list scheduling. Exact only for same-route flow shops with <= 3 machines "
                      f"and pure makespan. Certificate ({pm['certificate']['method']}): "
                      f"{pm['certificate']['ground_states']} ground states, all optimal = "
                      f"**{pm['certificate']['all_ground_states_optimal']}**. {pm['qaoa']['solver']}: exact "
                      f"P(optimal) = {pm['qaoa']['p_optimal_exact']:.4f} (uniform sampling: "
                      f"{pm['qaoa']['uniform_p_optimal']:.4f}). Reported for comparison only; the delivered "
                      f"schedule comes from the time-indexed QUBO."]
        c = r["certificate"]
        L += ["", f"Ground-state certificate ({c['method']}): {c['ground_states']} ground states, all optimal = "
                  f"**{c['all_ground_states_optimal']}**.", ""]
        q = r["qaoa"]
        L += [f"QAOA: {q['solver']}, exact P(optimal) = {q['p_optimal_exact']:.4f} "
              f"(uniform sampling: {q['uniform_p_optimal']:.2e}), sampled optimal fraction "
              f"{q['optimal_fraction']:.3f}, feasible {q['feasible_fraction']:.3f}.", ""]
        L += ["| p | <E> | P(optimal) | P(feasible) |", "|---|---|---|---|"]
        for h in r["qaoa_history"]:
            pf = "-" if h["p_feasible"] is None else f"{h['p_feasible']:.4f}"
            L.append(f"| {h['p']} | {h['expectation']:.3f} | {h['p_ground']:.4f} | {pf} |")
        L.append("")
        if "qiskit_max_prob_diff" in r:
            L += [f"Qiskit gate-level circuit with the same angles: max |p_numpy - p_qiskit| = "
                  f"{r['qiskit_max_prob_diff']:.1e}.", ""]
        if "certificate_domain_wall" in r:
            c = r["certificate_domain_wall"]
            L += [f"Domain-wall QUBO certificate ({c['method']}): all ground states optimal = "
                  f"**{c['all_ground_states_optimal']}**.", ""]
        if "cross_checks" in r:
            L += ["| solver | formulation | qubits | optimal samples | feasible samples | best makespan |",
                  "|---|---|---|---|---|---|"]
            for x in r["cross_checks"]:
                L.append(f"| {x['solver']} | {x['formulation']} | {x['qubits']} | {x['optimal_fraction']:.3f} | "
                         f"{x['feasible_fraction']:.3f} | {x['best_makespan']} |")
            L.append("")
        L += [f"![{name}](gantt_{'2x2' if 'A' in name else '3x3'}.png)", ""]
    path.write_text("\n".join(L), newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="smaller QAOA depth / fewer reads")
    ap.add_argument("--veloxq", action="store_true", help="also solve the 3x3 QUBOs on VeloxQ")
    ap.add_argument("--shots", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "results" / "baseline"),
                    help="report directory; if changed, the schedule files are written there too (not to the repo root)")
    args = ap.parse_args()
    out = Path(args.out)
    args.deliverables = ROOT if out.resolve() == (ROOT / "results" / "baseline").resolve() else out
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    rep = {"date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "seed": args.seed, "shots": args.shots,
           "instance_a": solve_instance_a(args, out), "instance_b": solve_instance_b(args, out)}
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str) + "\n", newline="\n")
    write_markdown(rep, out / "report.md")
    from erpq.schedule import Schedule

    for inst_file, sched_file in (("instance_2x2.json", "schedule_2x2.json"), ("instance_3x3.json", "schedule_3x3.json")):
        inst = Instance.load(ROOT / "instances" / inst_file)
        s = Schedule.load(inst, args.deliverables / sched_file)
        v = s.violations()
        print(f"\n{sched_file}: makespan {s.makespan}, feasible = {not v}" + (f" {v}" if v else ""))
        assert not v
    print(f"\nreport: {out / 'report.md'}   total time {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()

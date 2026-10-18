#!/usr/bin/env python
"""Live demo (~1 minute): the whole story in one run.

1. Instance B: QUBO sizes 72 -> 39 -> 33 -> 24 qubits, all exact; fewest:
   3 qubits with the job-order code (its coefficients come from brute force)
2. XY-mixer QAOA on the 33-qubit QUBO -> optimal schedule (makespan 8)
3. Stage 2: metaltech_monday - horizon ascent, QUBO optimum = CP-SAT
4. Disruption: milling breaks down at t=2 for 2 h -> rolling QUBO re-plan
   (XY-QAOA with transferred angles; SA when the subspace is too large to
   simulate) vs the ERP's right-shift repair
5. (only with --veloxq and VELOX_TOKEN) the same re-plan live on VeloxQ

    python demo.py
    python demo.py --veloxq
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from erpq.classical import solve_cpsat
from erpq.domainwall import to_domain_wall
from erpq.experiments import exact_qubo_solve, qaoa_or_sa_solve, veloxq_solve
from erpq.horizon import horizon_ascent
from erpq.model import Instance
from erpq.permutation import PermutationQUBO
from erpq.pipeline import run_qaoa_xy
from erpq.rolling import residual_instance, right_shift_repair
from erpq.timeindexed import build_time_indexed_qubo

ROOT = Path(__file__).resolve().parent


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--veloxq", action="store_true", help="add step 5, the re-plan on VeloxQ (needs VELOX_TOKEN)")
    args = ap.parse_args()
    t0 = time.perf_counter()
    banner("1) Instance B (3 jobs x 3 machines): how many qubits does the QUBO need?")
    inst = Instance.load(ROOT / "instances/instance_3x3.json")
    for level in ("none", "window", "sac"):
        m = build_time_indexed_qubo(inst, 8, level)
        print(f"   {level:>7}: {m.qubo.n:2d} qubits, {m.qubo.num_interactions:3d} couplings")
    sac = build_time_indexed_qubo(inst, 8, "sac")
    print(f"   domain wall: {to_domain_wall(sac).num_qubits} qubits   (every one of them exact)")
    perm = PermutationQUBO(inst)
    print(f"   job-order code: {perm.qubo.n} qubits, {perm.qubo.num_interactions} couplings   (fewest, but its "
          f"coefficients are the makespans of all {len(perm.perms)} job orders = brute force)")

    banner("2) XY-mixer QAOA on the 33-qubit QUBO (exact simulation in the 103,680-dim one-hot subspace)")
    res, rep = run_qaoa_xy(sac, p=3, shots=1024, seed=7, reference=8, restarts=3, verbose=True)
    print(f"   P(optimal) per shot: {res.p_ground:.3f}  (uniform sampling: {rep.extra['uniform_p_optimal']:.1e})")
    print(f"   best of 1024 shots: makespan {rep.best.makespan}, feasible = {rep.best.feasible}")
    print(rep.best.ascii_gantt())

    banner("3) Stage 2 - metaltech_monday: setups, maintenance, due dates, a job with its own route")
    mon = Instance.load(ROOT / "instances/extension/metaltech_monday.json")
    asc = horizon_ascent(mon, exact_qubo_solve, verbose=True)
    plan = asc.best.best
    print(f"   QUBO optimum {asc.best.best_objective:g} (makespan {plan.makespan}, weighted tardiness "
          f"{plan.weighted_tardiness():g}) - CP-SAT says {solve_cpsat(mon).objective:g}")
    print(plan.ascii_gantt())

    banner("4) Monday, t=2: the milling machine F breaks down for 2 hours")
    resid, imap = residual_instance(mon, plan, 2, "F", 2)
    rs = right_shift_repair(resid, plan, imap)
    angles = np.concatenate([res.gammas, res.betas])
    rep2 = horizon_ascent(resid, lambda f: qaoa_or_sa_solve(f, angles), verbose=True)
    q = rep2.best.best
    print(f"   residual problem: {len(resid.operations)} operations left; best found with {rep2.form.qubo.n} qubits "
          f"(H={rep2.horizon}, solver: {rep2.best.solver})")
    print(f"   ERP right-shift repair: objective {rs.objective():g} (makespan {rs.makespan})")
    print(f"   rolling QUBO re-plan: objective {q.objective():g} "
          f"(makespan {q.makespan}); CP-SAT {solve_cpsat(resid).objective:g}")
    print(q.ascii_gantt())

    if args.veloxq:
        from erpq.solvers import samplers

        banner("5) The same re-plan live on VeloxQ (Quantumz.io's GPU QUBO solver, cloud)")
        if not samplers.veloxq_available():
            print("   skipped: install veloxq-sdk and set VELOX_TOKEN")
        else:
            log: list = []
            rep3 = horizon_ascent(resid, lambda f: veloxq_solve(f, log=log), verbose=True)
            v = rep3.best.best
            print(f"   VeloxQ re-plan: objective {v.objective():g} (makespan {v.makespan}), feasible = {v.feasible}; "
                  f"{len(log)} live calls, {sum(log):.2f} s of solver time reported by the service")
            print(v.ascii_gantt())
    print(f"\n(done in {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()

from __future__ import annotations

import math
import time

import numpy as np

from .heuristics import makespan_lower_bound
from .model import Instance
from .pipeline import RunReport, evaluate_states, report_samples
from .solvers import samplers
from .timeindexed import TimeIndexedQUBO, compute_domains


def exact_qubo_solve(form: TimeIndexedQUBO, max_states: int = 30_000_000) -> RunReport:
    t0 = time.perf_counter()
    T = form.register_energy_tensor(max_states=max_states)
    flat = T.ravel()
    emin = flat.min()
    idx = np.flatnonzero(np.isclose(flat, emin, atol=1e-9))[:256]
    states = np.array([form.subspace_to_bits(np.unravel_index(i, T.shape)) for i in idx], dtype=np.int8)
    rep = evaluate_states(form, states, flat[idx], "exact (subspace enumeration)", None, time.perf_counter() - t0,
                          {"states_enumerated": int(flat.size), "ground_energy": float(emin),
                           "ground_states": int(np.isclose(flat, emin, atol=1e-9).sum())})
    return rep


def exact_or_sa_solve(form: TimeIndexedQUBO, max_states: float = 3e7, reads: int = 300) -> RunReport:
    if form.subspace_dim <= max_states or form.qubo.n == 0:
        return exact_qubo_solve(form)
    return report_samples(form, samplers.simulated_annealing(form.qubo, num_reads=reads, num_sweeps=2000, seed=0))


def qaoa_or_sa_solve(form: TimeIndexedQUBO, angles: np.ndarray, shots: int = 1024, max_subspace: float = 2e6,
                     reads: int = 200, seed: int = 5) -> RunReport:
    from .pipeline import run_qaoa_xy

    if form.qubo.n == 0:
        return exact_qubo_solve(form)
    if form.subspace_dim <= max_subspace:
        return run_qaoa_xy(form, shots=shots, seed=seed, fixed_angles=angles)[1]
    return report_samples(form, samplers.simulated_annealing(form.qubo, num_reads=reads, num_sweeps=1000, seed=3))


def veloxq_solve(form: TimeIndexedQUBO, num_rep: int = 1024, num_steps: int = 5000, log: list | None = None) -> RunReport:
    if form.qubo.n == 0:
        return exact_qubo_solve(form)
    smp = samplers.veloxq(form.qubo, num_rep=num_rep, num_steps=num_steps)
    if log is not None:
        log.append(smp.info.get("solver_time_s", smp.wall_time))
    return report_samples(form, smp)


def shift_horizon(inst: Instance, solve_cpsat, slack: int = 1) -> int:
    d = inst.to_dict()
    d["objective"] = {"makespan": 1, "weighted_tardiness": 0}
    mk = Instance.from_dict(d, inst.name)
    return int(solve_cpsat(mk, time_limit=20).objective) + slack


def certified_horizon_cpsat(inst: Instance, solve_cpsat, max_extra: int = 8) -> tuple[int, float]:
    from .horizon import certificate_bound

    lb = makespan_lower_bound(inst)
    for H in range(lb, lb + max_extra + 1):
        if compute_domains(inst, H, "sac") is None:
            continue
        r = solve_cpsat(inst, horizon=H, time_limit=20)
        if r.objective is not None and r.objective <= certificate_bound(inst, H) + 1e-9:
            return H, r.objective
    raise RuntimeError("no certified horizon found")


def sampler_trials(form, solver: str, reference: float, seeds: int, **kw) -> dict:
    rates, feas, times, best = [], [], [], []
    per_read = None
    for s in range(seeds):
        if solver == "sa":
            smp = samplers.simulated_annealing(form.qubo, seed=s, **kw)
        elif solver == "tabu":
            smp = samplers.tabu_search(form.qubo, seed=s, **kw)
        elif solver == "veloxq":
            smp = samplers.veloxq(form.qubo, **kw)
        else:
            raise ValueError(solver)
        r = report_samples(form, smp, reference)
        rates.append(r.optimal_fraction)
        feas.append(r.feasible_fraction)
        times.append(smp.wall_time)
        best.append(r.best_objective)
        per_read = smp.info.get("solver_time_s", smp.wall_time) / max(1, len(smp.states))
    rates = np.array(rates)
    mean = float(rates.mean())
    return {
        "solver": solver,
        "qubits": form.qubo.n,
        "seeds": seeds,
        "p_success_mean": mean,
        "p_success_ci95": ci95(rates),
        "p_feasible_mean": float(np.mean(feas)),
        "best_objective_min": min(b for b in best if b is not None) if any(b is not None for b in best) else None,
        "runs_hitting_optimum": int(sum(1 for b in best if b is not None and abs(b - reference) < 1e-9)),
        "seconds_per_sample": per_read,
        "time_basis": "solver-reported" if "solver_time_s" in smp.info else "wall clock",
        "wall_seconds_per_run": float(np.mean(times)),
        "tts99_samples": tts99(mean),
        "tts99_seconds": None if tts99(mean) is None else tts99(mean) * per_read,
    }


def ci95(x: np.ndarray, n_boot: int = 2000, seed: int = 0) -> list[float]:
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return [float(x.mean()), float(x.mean())]
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def tts99(p: float) -> float | None:
    if p <= 0:
        return None
    if p >= 0.99:
        return 1.0
    return math.log(0.01) / math.log(1 - p)

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .domainwall import DomainWallQUBO
from .schedule import Schedule
from .solvers.qaoa import QAOAResult, XMixerQAOA, XYMixerQAOA
from .solvers.samplers import Samples
from .timeindexed import TimeIndexedQUBO

Formulation = TimeIndexedQUBO | DomainWallQUBO


@dataclass
class RunReport:
    solver: str
    qubits: int
    samples: int
    feasible_fraction: float
    optimal_fraction: float | None
    best: Schedule | None
    best_objective: float | None
    best_energy: float
    wall_time: float
    extra: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "solver": self.solver,
            "qubits": self.qubits,
            "samples": self.samples,
            "feasible_fraction": round(self.feasible_fraction, 6),
            "optimal_fraction": None if self.optimal_fraction is None else round(self.optimal_fraction, 6),
            "best_objective": self.best_objective,
            "best_makespan": None if self.best is None else self.best.makespan,
            "best_energy": self.best_energy,
            "wall_time_s": round(self.wall_time, 3),
            **self.extra,
        }


def evaluate_states(
    form: Formulation,
    states: np.ndarray,
    energies: np.ndarray,
    solver: str,
    reference: float | None = None,
    wall_time: float = 0.0,
    extra: dict | None = None,
) -> RunReport:
    states = np.asarray(states).astype(np.int8)
    uniq, inverse, counts = np.unique(states, axis=0, return_inverse=True, return_counts=True)
    inverse = np.asarray(inverse).ravel()
    feas_count = 0
    opt_count = 0
    best: tuple | None = None
    for k, s in enumerate(uniq):
        sched, _ = form.decode(s)
        if sched is None or sched.violations():
            continue
        obj = sched.objective()
        feas_count += counts[k]
        if reference is not None and abs(obj - reference) < 1e-9:
            opt_count += counts[k]
        energy = float(energies[np.flatnonzero(inverse == k)[0]])
        key = (obj, sum(e.end for e in sched.entries), energy)
        if best is None or key < best[0]:
            best = (key, sched)
    n = len(states)
    return RunReport(
        solver=solver,
        qubits=form.qubo.n,
        samples=n,
        feasible_fraction=feas_count / n if n else 0.0,
        optimal_fraction=None if reference is None else opt_count / n,
        best=None if best is None else best[1],
        best_objective=None if best is None else best[0][0],
        best_energy=float(np.min(energies)) if len(energies) else float("nan"),
        wall_time=wall_time,
        extra=extra or {},
    )


def report_samples(form: Formulation, smp: Samples, reference: float | None = None) -> RunReport:
    return evaluate_states(form, smp.states, smp.energies, smp.solver, reference, smp.wall_time, dict(smp.info))


def ising_scale(form: Formulation) -> float:
    h, J, _ = form.qubo.to_ising()
    return float(max(np.abs(h).max(initial=0.0), max((abs(v) for v in J.values()), default=0.0), 1e-12))


def run_qaoa_x(
    form: Formulation,
    p: int = 4,
    shots: int = 4096,
    seed: int = 0,
    reference: float | None = None,
    restarts: int = 8,
    cvar: float = 1.0,
    verbose: bool = False,
    constraint_energies: np.ndarray | None = None,
) -> tuple[QAOAResult, RunReport]:
    t0 = time.perf_counter()
    E = form.qubo.all_energies()
    if constraint_energies is None and isinstance(form, TimeIndexedQUBO):
        constraint_energies = form.constraint_qubo.all_energies()
    elif constraint_energies is None and isinstance(form, DomainWallQUBO):
        constraint_energies = domain_wall_constraint_energies(form)
    feasible = None if constraint_energies is None else np.isclose(constraint_energies, 0.0)
    qa = XMixerQAOA(E, form.qubo.n, scale=ising_scale(form), feasible=feasible)
    res = qa.optimize(p_max=p, restarts=restarts, cvar=cvar, seed=seed, verbose=verbose)
    idx = qa.sample(res.probabilities, shots, seed)
    states = ((idx[:, None] >> np.arange(form.qubo.n)[None, :]) & 1).astype(np.int8)
    extra = {
        "p": res.p,
        "p_optimal_exact": res.p_ground,
        "p_feasible_exact": res.p_feasible,
        "uniform_p_optimal": float(qa.ground.mean()),
        "evaluations": res.evaluations,
        "gammas": res.gammas.round(6).tolist(),
        "betas": res.betas.round(6).tolist(),
        "cvar_alpha": cvar,
        "simulated_dimension": int(E.size),
    }
    rep = evaluate_states(form, states, E[idx], f"QAOA X-mixer p={res.p}", reference, time.perf_counter() - t0, extra)
    return res, rep


def run_qaoa_xy(
    form: TimeIndexedQUBO,
    p: int = 4,
    shots: int = 4096,
    seed: int = 0,
    reference: float | None = None,
    mixer: str = "ring",
    restarts: int = 6,
    cvar: float = 1.0,
    verbose: bool = False,
    init: np.ndarray | None = None,
    fixed_angles: np.ndarray | None = None,
) -> tuple[QAOAResult, RunReport]:
    t0 = time.perf_counter()
    T = form.register_energy_tensor()
    feasible = np.isclose(form.register_energy_tensor(form.constraint_qubo), 0.0)
    qa = XYMixerQAOA(T, [r.kind for r in form.registers], mixer, scale=ising_scale(form), feasible=feasible)
    if fixed_angles is not None:
        k = len(fixed_angles) // 2
        res = qa.evaluate(fixed_angles[:k], fixed_angles[k:])
    else:
        res = qa.optimize(p_max=p, restarts=restarts, cvar=cvar, seed=seed, verbose=verbose, init=init)
    idx = qa.sample(res.probabilities, shots, seed)
    multi = np.array(np.unravel_index(idx, T.shape)).T
    states = np.array([form.subspace_to_bits(mi) for mi in multi], dtype=np.int8)
    extra = {
        "p": res.p,
        "mixer": mixer,
        "p_optimal_exact": res.p_ground,
        "p_feasible_exact": res.p_feasible,
        "uniform_p_optimal": float(qa.ground.mean()),
        "evaluations": res.evaluations,
        "gammas": res.gammas.round(6).tolist(),
        "betas": res.betas.round(6).tolist(),
        "cvar_alpha": cvar,
        "simulated_dimension": int(T.size),
        "full_hilbert_dimension": f"2^{form.qubo.n}",
    }
    rep = evaluate_states(
        form, states, T.ravel()[idx], f"XY-mixer QAOA p={res.p} ({mixer})", reference, time.perf_counter() - t0, extra
    )
    return res, rep


def domain_wall_constraint_energies(dw: DomainWallQUBO) -> np.ndarray:
    n = dw.qubo.n
    idx = np.arange(2**n)
    S = ((idx[:, None] >> np.arange(n)[None, :]) & 1).astype(float)
    A = np.zeros((n, dw.base.qubo.n))
    c = np.zeros(dw.base.qubo.n)
    for v, (const, terms) in enumerate(dw.affine):
        c[v] = const
        for i, k in terms.items():
            A[i, v] = k
    X = S @ A + c
    valid = np.all((X == 0) | (X == 1), axis=1)
    out = np.ones(2**n)
    out[valid] = dw.base.constraint_qubo.energies(X[valid])
    return out

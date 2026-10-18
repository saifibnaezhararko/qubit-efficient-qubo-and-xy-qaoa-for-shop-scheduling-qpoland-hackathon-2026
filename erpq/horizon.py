from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .heuristics import best_heuristic, makespan_lower_bound
from .model import Instance
from .pipeline import RunReport
from .timeindexed import InfeasibleHorizon, TimeIndexedQUBO, build_time_indexed_qubo


def certificate_bound(inst: Instance, H: int) -> float:
    obj = inst.objective
    bound = obj.makespan * (H + 1)
    if obj.tardiness:
        lb = {j.id: max(j.release, inst.time_origin) + j.total_duration for j in inst.jobs}
        late = {j.id: j.weight * max(0, lb[j.id] - j.due_date) for j in inst.jobs}
        base = sum(late.values())
        bound += obj.tardiness * min(base - late[j.id] + j.weight * max(0, max(H + 1, lb[j.id]) - j.due_date)
                                     for j in inst.jobs)
    return bound


@dataclass
class AscentStep:
    horizon: int
    status: str
    qubits: int | None = None
    subspace_dim: int | None = None
    objective: float | None = None
    bound: float | None = None
    certified: bool = False
    report: dict | None = None


@dataclass
class AscentResult:
    best: RunReport | None
    steps: list[AscentStep] = field(default_factory=list)
    form: TimeIndexedQUBO | None = None

    @property
    def certified(self) -> bool:
        return any(s.certified for s in self.steps)

    @property
    def horizon(self) -> int | None:
        return self.form.horizon if self.form else None


def horizon_ascent(
    inst: Instance,
    solve: Callable[[TimeIndexedQUBO], RunReport],
    pruning: str = "sac",
    max_horizon: int | None = None,
    patience: int = 2,
    verbose: bool = False,
    **build_kwargs,
) -> AscentResult:
    lb = makespan_lower_bound(inst)
    if max_horizon is None:
        h = best_heuristic(inst)
        max_horizon = h.makespan if inst.objective.pure_makespan else int(h.objective() // inst.objective.makespan)
    res = AscentResult(None)
    first_found = None
    for H in range(lb, max_horizon + 1):
        if first_found is not None and H > first_found + patience:
            break
        try:
            form = build_time_indexed_qubo(inst, H, pruning, **build_kwargs)
        except InfeasibleHorizon:
            res.steps.append(AscentStep(H, "infeasible (propagation proof)"))
            if verbose:
                print(f"    H={H}: no schedule fits (proved by {pruning} propagation)")
            continue
        rep = solve(form)
        step = AscentStep(H, "solved" if rep.best else "no feasible sample", form.qubo.n, form.subspace_dim,
                          rep.best_objective, certificate_bound(inst, H), report=rep.summary())
        if rep.best is not None and (res.best is None or rep.best_objective < res.best.best_objective):
            res.best, res.form = rep, form
        if rep.best is not None and first_found is None:
            first_found = H
        if res.best is not None and res.best.best_objective <= step.bound + 1e-9:
            step.certified = True
        res.steps.append(step)
        if verbose:
            print(f"    H={H}: {form.qubo.n} qubits, {step.status}, objective {rep.best_objective}, "
                  f"bound {step.bound:g} -> {'certified' if step.certified else 'continue'}")
        if step.certified:
            break
    return res

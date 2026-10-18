from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .experiments import exact_qubo_solve
from .model import FixedEntry, Instance, Job, Operation
from .pipeline import RunReport, report_samples
from .qubo import QUBO
from .schedule import Entry, Schedule
from .solvers import samplers
from .timeindexed import TimeIndexedQUBO, build_time_indexed_qubo

BatchSolver = Callable[[list[TimeIndexedQUBO], int], tuple[list[RunReport], float]]


@dataclass
class LNSStep:
    iteration: int
    neighbourhoods: list[list[str]]
    qubits: int
    candidate: float | None
    objective: float
    accepted_moves: int
    improved: bool
    solver_time_s: float
    wall_time_s: float


def neighbourhood_instance(inst: Instance, plan: Schedule, free: set[str]) -> Instance:
    sub = copy.deepcopy(inst)
    sub.name = f"{inst.name}_lns"
    jobs, uid = [], 0
    for job in inst.jobs:
        if job.id not in free:
            continue
        ops = []
        for op in job.operations:
            ops.append(Operation(uid, job.id, op.index, op.machine, op.duration))
            uid += 1
        jobs.append(Job(job.id, ops, job.release, job.due_date, job.weight, job.family))
    sub.jobs = jobs
    sub.fixed = list(inst.fixed) + [FixedEntry(e.job, e.index, e.machine, e.start, e.end)
                                     for e in plan.entries if e.job not in free]
    return sub


def merge_plan(inst: Instance, plan: Schedule, part: Schedule, free: set[str], method: str = "") -> Schedule:
    entries = [e for e in plan.entries if e.job not in free]
    entries += [Entry(e.job, e.index, e.machine, e.start, e.end) for e in part.entries]
    return Schedule(inst, sorted(entries, key=lambda e: (e.start, e.machine)), method or plan.method)


def stack_qubos(qubos: list[QUBO]) -> tuple[QUBO, list[int]]:
    starts, n = [], 0
    for q in qubos:
        starts.append(n)
        n += q.n
    big = QUBO([f"b{b}_{lab}" for b, q in enumerate(qubos) for lab in q.labels])
    for s, q in zip(starts, qubos):
        big.linear[s:s + q.n] = q.linear
        for (i, j), v in q.quadratic.items():
            big.quadratic[(s + i, s + j)] = v
        big.offset += q.offset
    return big, starts


def veloxq_batch(num_rep: int = 256, num_steps: int = 5000) -> BatchSolver:
    def solve(forms: list[TimeIndexedQUBO], it: int) -> tuple[list[RunReport], float]:
        big, starts = stack_qubos([f.qubo for f in forms])
        smp = samplers.veloxq(big, num_rep=num_rep, num_steps=num_steps)
        reps = []
        for s, f in zip(starts, forms):
            states = smp.states[:, s:s + f.qubo.n]
            reps.append(report_samples(f, samplers.Samples(smp.solver, states, f.qubo.energies(states),
                                                           smp.wall_time, dict(smp.info))))
        return reps, smp.info.get("solver_time_s", smp.wall_time)
    return solve


def sa_batch(num_reads: int = 100, num_sweeps: int = 1000) -> BatchSolver:
    def solve(forms: list[TimeIndexedQUBO], it: int) -> tuple[list[RunReport], float]:
        reps, t = [], 0.0
        for b, f in enumerate(forms):
            smp = samplers.simulated_annealing(f.qubo, num_reads=num_reads, num_sweeps=num_sweeps, seed=1000 * it + b)
            reps.append(report_samples(f, smp))
            t += smp.wall_time
        return reps, t
    return solve


def lns(
    inst: Instance,
    horizon: int,
    start: Schedule,
    solve: BatchSolver,
    k: int = 6,
    iterations: int = 20,
    batch: int = 1,
    seed: int = 0,
    target: float | None = None,
) -> tuple[Schedule, list[LNSStep]]:
    if start.violations():
        raise ValueError("the start plan must be feasible")
    rng = np.random.default_rng(seed)
    ids = [j.id for j in inst.jobs]
    plan, cur = start, start.objective()
    steps: list[LNSStep] = []
    for it in range(iterations):
        if target is not None and cur <= target + 1e-9:
            break
        t0 = time.perf_counter()
        frees = [set(rng.choice(ids, size=min(k, len(ids)), replace=False).tolist()) for _ in range(batch)]
        forms = [build_time_indexed_qubo(neighbourhood_instance(inst, plan, f), horizon, "sac") for f in frees]
        reps: list[RunReport | None] = [exact_qubo_solve(f) if f.qubo.n == 0 else None for f in forms]
        todo = [b for b, r in enumerate(reps) if r is None]
        solver_time = 0.0
        if todo:
            solved, solver_time = solve([forms[b] for b in todo], it)
            for b, r in zip(todo, solved):
                reps[b] = r
        cands = []
        for b, r in enumerate(reps):
            if r is not None and r.best is not None:
                new = merge_plan(inst, plan, r.best, frees[b])
                if not new.violations():
                    cands.append((new.objective(), b))
        best_cand = min(c for c, _ in cands) if cands else None
        before, moves = cur, 0
        for _, b in sorted(cands):
            new = merge_plan(inst, plan, reps[b].best, frees[b])
            if not new.violations() and new.objective() <= cur + 1e-9:
                plan, cur, moves = new, new.objective(), moves + 1
        steps.append(LNSStep(it, [sorted(f) for f in frees], int(sum(forms[b].qubo.n for b in todo)), best_cand, cur,
                             moves, cur < before - 1e-9, solver_time, time.perf_counter() - t0))
    return plan, steps

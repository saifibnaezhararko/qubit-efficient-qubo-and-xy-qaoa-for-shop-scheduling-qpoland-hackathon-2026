from __future__ import annotations

import time
from dataclasses import dataclass

from .model import Instance
from .schedule import Entry, Schedule


@dataclass
class CPSATResult:
    schedule: Schedule | None
    status: str
    objective: float | None
    wall_time: float


def _scale(weights: list[float]) -> int:
    for k in range(7):
        if all(abs(w * 10**k - round(w * 10**k)) < 1e-9 for w in weights):
            return 10**k
    return 10**6


def solve_cpsat(
    inst: Instance,
    horizon: int | None = None,
    time_limit: float = 30.0,
    workers: int = 4,
    seed: int = 0,
) -> CPSATResult:
    from ortools.sat.python import cp_model

    t0 = time.perf_counter()
    m = cp_model.CpModel()
    if horizon is None:
        horizon = (
            max([inst.time_origin] + [j.release for j in inst.jobs] + list(inst.machine_ready.values()))
            + sum(op.duration for op in inst.operations)
            + sum(b - a for ws in inst.unavailability.values() for a, b in ws)
            + sum(max(t.values(), default=0) for t in inst.setup_times.values()) * len(inst.operations)
            + max([f.end for f in inst.fixed], default=0)
        )

    start, end, presence, intervals = {}, {}, {}, {}
    for op in inst.operations:
        lo, hi = inst.head(op), horizon - inst.tail(op)
        if hi < lo:
            return CPSATResult(None, "INFEASIBLE", None, time.perf_counter() - t0)
        s = m.NewIntVar(lo, hi, f"s_{op.uid}")
        start[op.uid], end[op.uid] = s, s + op.duration
        lits = []
        for u in inst.units[op.machine]:
            p = m.NewBoolVar(f"p_{op.uid}_{u}")
            presence[op.uid, u] = p
            intervals[op.uid, u] = m.NewOptionalFixedSizeIntervalVar(s, op.duration, p, f"i_{op.uid}_{u}")
            m.Add(s >= inst.machine_ready.get(u, 0)).OnlyEnforceIf(p)
            for f in inst.fixed:
                if f.machine == u and f.job != op.job:
                    gap = inst.setup(op.machine, f.job, op.job)
                    if gap:
                        m.Add(s >= f.end + gap).OnlyEnforceIf(p)
            lits.append(p)
        m.AddExactlyOne(lits)

    for job in inst.jobs:
        for a, b in zip(job.operations, job.operations[1:]):
            m.Add(start[b.uid] >= end[a.uid])

    for mtype, units in inst.units.items():
        ops = [op for op in inst.operations if op.machine == mtype]
        for u in units:
            ivs = [intervals[op.uid, u] for op in ops]
            for k, (a, b) in enumerate(inst.unavailability.get(u, [])):
                ivs.append(m.NewIntervalVar(a, b - a, b, f"out_{u}_{k}"))
            for k, f in enumerate(inst.fixed):
                if f.machine == u:
                    ivs.append(m.NewIntervalVar(f.start, f.end - f.start, f.end, f"fix_{u}_{k}"))
            m.AddNoOverlap(ivs)
            if not inst.setup_times.get(mtype):
                continue
            for i, a in enumerate(ops):
                for b in ops[i + 1 :]:
                    if a.job == b.job:
                        continue
                    sab, sba = inst.setup(mtype, a.job, b.job), inst.setup(mtype, b.job, a.job)
                    if not sab and not sba:
                        continue
                    pa, pb = presence[a.uid, u], presence[b.uid, u]
                    before = m.NewBoolVar(f"o_{a.uid}_{b.uid}_{u}")
                    m.Add(start[b.uid] >= end[a.uid] + sab).OnlyEnforceIf([before, pa, pb])
                    m.Add(start[a.uid] >= end[b.uid] + sba).OnlyEnforceIf([before.Not(), pa, pb])

    cmax = m.NewIntVar(0, horizon, "cmax")
    for job in inst.jobs:
        m.Add(cmax >= end[job.operations[-1].uid])
    for f in inst.fixed:
        m.Add(cmax >= f.end)
    obj = inst.objective
    scale = _scale([obj.makespan, obj.tardiness] + [j.weight for j in inst.jobs])
    terms = [round(obj.makespan * scale) * cmax]
    if obj.tardiness:
        for job in inst.jobs:
            tj = m.NewIntVar(0, horizon, f"T_{job.id}")
            m.Add(tj >= end[job.operations[-1].uid] - job.due_date)
            terms.append(round(obj.tardiness * job.weight * scale) * tj)
    m.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    status = solver.Solve(m)
    name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return CPSATResult(None, name, None, time.perf_counter() - t0)
    entries = []
    for op in inst.operations:
        unit = next(u for u in inst.units[op.machine] if solver.Value(presence[op.uid, u]))
        s = solver.Value(start[op.uid])
        entries.append(Entry(op.job, op.index, unit, s, s + op.duration))
    sched = Schedule(inst, entries, f"CP-SAT ({name.lower()})")
    return CPSATResult(sched, name, sched.objective(), time.perf_counter() - t0)

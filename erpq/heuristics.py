from __future__ import annotations

import itertools
import math

from .model import Instance, Operation
from .schedule import Entry, Schedule


def makespan_lower_bound(inst: Instance) -> int:
    lb = inst.time_origin
    for f in inst.fixed:
        lb = max(lb, f.end)
    for job in inst.jobs:
        lb = max(lb, max(job.release, inst.time_origin) + job.total_duration)
    for mtype, units in inst.units.items():
        ops = [op for op in inst.operations if op.machine == mtype]
        if not ops:
            continue
        load = sum(op.duration for op in ops)
        min_head = min(inst.head(op) for op in ops)
        min_ready = min(max(inst.machine_ready.get(u, 0), inst.time_origin) for u in units)
        min_tail = min(inst.tail(op) - op.duration for op in ops)
        lb = max(lb, max(min_head, min_ready) + math.ceil(load / len(units)) + min_tail)
    return lb


def _earliest_start(inst: Instance, unit: str, t0: int, duration: int) -> int:
    t = max(t0, inst.machine_ready.get(unit, 0), inst.time_origin)
    while not inst.unit_available(unit, t, t + duration):
        t += 1
    return t


def list_schedule(inst: Instance, job_order: list[str], method: str = "") -> Schedule:
    unit_free = {u: inst.time_origin for u in inst.all_units}
    unit_last: dict[str, str | None] = {u: None for u in inst.all_units}
    for f in inst.fixed:
        unit_free[f.machine] = max(unit_free[f.machine], f.end)
        unit_last[f.machine] = f.job
    entries: list[Entry] = []
    for job_id in job_order:
        job = inst.job(job_id)
        t_job = max(job.release, inst.time_origin)
        for op in job.operations:
            best = None
            for unit in inst.units[op.machine]:
                prev = unit_last[unit]
                gap = inst.setup(op.machine, prev, job_id) if prev and prev != job_id else 0
                start = _earliest_start(inst, unit, max(t_job, unit_free[unit] + gap), op.duration)
                if best is None or start < best[0]:
                    best = (start, unit)
            start, unit = best
            entries.append(Entry(job_id, op.index, unit, start, start + op.duration))
            unit_free[unit] = start + op.duration
            unit_last[unit] = job_id
            t_job = start + op.duration
    return Schedule(inst, entries, method or f"list schedule {'-'.join(job_order)}")


def fifo_schedule(inst: Instance) -> Schedule:
    return list_schedule(inst, [j.id for j in inst.jobs], "FIFO (order of arrival)")


def neh_schedule(inst: Instance) -> Schedule:
    jobs = sorted(inst.jobs, key=lambda j: -j.total_duration)
    seq: list[str] = []
    for job in jobs:
        best = None
        for pos in range(len(seq) + 1):
            cand = seq[:pos] + [job.id] + seq[pos:]
            val = list_schedule(inst, cand).objective()
            if best is None or val < best[0]:
                best = (val, cand)
        seq = best[1]
    return list_schedule(inst, seq, "NEH insertion heuristic")


def best_heuristic(inst: Instance) -> Schedule:
    cands = [fifo_schedule(inst), neh_schedule(inst)]
    if all(j.due_date is not None for j in inst.jobs):
        edd = sorted(inst.jobs, key=lambda j: (j.due_date, -j.weight))
        cands.append(list_schedule(inst, [j.id for j in edd], "EDD (earliest due date)"))
    return min(cands, key=lambda s: (s.objective(), s.makespan))


def brute_force_permutations(inst: Instance) -> Schedule:
    best = None
    for perm in itertools.permutations([j.id for j in inst.jobs]):
        s = list_schedule(inst, list(perm))
        key = (s.objective(), s.makespan)
        if best is None or key < best[0]:
            best = (key, s)
    sched = best[1]
    sched.method = "brute force over all job permutations"
    return sched


def operation_window(inst: Instance, op: Operation, horizon: int) -> tuple[int, int]:
    return inst.head(op), horizon - inst.tail(op)


def serial_schedule(inst: Instance, op_order: list[tuple[str, int]], method: str = "") -> Schedule:
    unit_free = {u: inst.time_origin for u in inst.all_units}
    unit_last: dict[str, str | None] = {u: None for u in inst.all_units}
    for f in inst.fixed:
        unit_free[f.machine] = max(unit_free[f.machine], f.end)
        unit_last[f.machine] = f.job
    job_ready = {j.id: max(j.release, inst.time_origin) for j in inst.jobs}
    next_index = {j.id: 0 for j in inst.jobs}
    pending = list(op_order)
    entries: list[Entry] = []
    while pending:
        k = next(i for i, (job_id, idx) in enumerate(pending) if next_index[job_id] == idx)
        job_id, idx = pending.pop(k)
        op = inst.job(job_id).operations[idx]
        best = None
        for unit in inst.units[op.machine]:
            prev = unit_last[unit]
            gap = inst.setup(op.machine, prev, job_id) if prev and prev != job_id else 0
            start = _earliest_start(inst, unit, max(job_ready[job_id], unit_free[unit] + gap), op.duration)
            if best is None or start < best[0]:
                best = (start, unit)
        start, unit = best
        entries.append(Entry(job_id, idx, unit, start, start + op.duration))
        unit_free[unit], unit_last[unit] = start + op.duration, job_id
        job_ready[job_id] = start + op.duration
        next_index[job_id] += 1
    return Schedule(inst, entries, method or "serial schedule")

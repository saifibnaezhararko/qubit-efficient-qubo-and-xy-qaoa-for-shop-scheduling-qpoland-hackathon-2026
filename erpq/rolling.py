from __future__ import annotations

import copy

from .heuristics import serial_schedule
from .model import FixedEntry, Instance, Job, Operation, merge_windows
from .schedule import Entry, Schedule


def residual_instance(inst: Instance, plan: Schedule, now: int, machine: str, duration: int) -> tuple[Instance, dict]:
    entry = {(e.job, e.index): e for e in plan.entries}
    jobs, fixed, index_map = [], list(inst.fixed), {}
    machine_ready = dict(inst.machine_ready)
    uid = 0
    for job in inst.jobs:
        remaining, release = [], max(job.release, now)
        for op in job.operations:
            e = entry[(job.id, op.index)]
            if e.end <= now:
                continue
            if e.start < now and e.machine != machine:
                fixed.append(FixedEntry(job.id, op.index, e.machine, e.start, e.end))
                machine_ready[e.machine] = max(machine_ready.get(e.machine, 0), e.end)
                release = max(release, e.end)
                continue
            remaining.append(op)
        if not remaining:
            continue
        ops = []
        for k, op in enumerate(remaining):
            index_map[(job.id, k)] = op.index
            ops.append(Operation(uid, job.id, k, op.machine, op.duration))
            uid += 1
        jobs.append(Job(job.id, ops, release, job.due_date, job.weight, job.family))
    res = copy.deepcopy(inst)
    res.name = f"{inst.name}_replan_t{now}_{machine}{duration}"
    res.jobs = jobs
    res.fixed = fixed
    res.time_origin = now
    res.machine_ready = {u: max(r, now) for u, r in machine_ready.items() if r > now}
    res.unavailability = {u: list(ws) for u, ws in inst.unavailability.items()}
    res.unavailability.setdefault(machine, []).append((now, now + duration))
    res.unavailability = merge_windows(res.unavailability)
    return res, index_map


def right_shift_repair(res: Instance, plan: Schedule, index_map: dict) -> Schedule:
    inv = {(job, orig): k for (job, k), orig in index_map.items()}
    order = [(e.job, inv[(e.job, e.index)]) for e in sorted(plan.entries, key=lambda e: (e.start, e.machine))
             if (e.job, e.index) in inv]
    return serial_schedule(res, order, "right-shift repair of the original plan")


def merge(original: Instance, plan: Schedule, res: Instance, replan: Schedule, index_map: dict, now: int) -> list[dict]:
    rows = []
    replanned = {(job, orig) for (job, _), orig in index_map.items()}
    fixed = {(f.job, f.index) for f in res.fixed}
    for e in plan.entries:
        key = (e.job, e.index)
        if key not in replanned and key not in fixed and e.end <= now:
            rows.append({"job": e.job, "operation": e.index, "machine": e.machine, "start": e.start, "end": e.end,
                         "status": "done"})
    for f in res.fixed:
        rows.append({"job": f.job, "operation": f.index, "machine": f.machine, "start": f.start, "end": f.end,
                     "status": "running"})
    for e in replan.entries:
        rows.append({"job": e.job, "operation": index_map[(e.job, e.index)], "machine": e.machine,
                     "start": e.start, "end": e.end, "status": "re-planned"})
    return sorted(rows, key=lambda r: (r["start"], r["machine"]))


__all__ = ["residual_instance", "right_shift_repair", "merge", "Entry"]

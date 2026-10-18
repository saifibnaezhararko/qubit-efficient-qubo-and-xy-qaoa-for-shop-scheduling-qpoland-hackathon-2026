from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .model import Instance


@dataclass(frozen=True)
class Entry:
    job: str
    index: int
    machine: str
    start: int
    end: int


class Schedule:
    def __init__(self, instance: Instance, entries: list[Entry], method: str = ""):
        self.instance = instance
        self.entries = sorted(entries, key=lambda e: (e.start, e.machine, e.job))
        self.method = method

    @property
    def makespan(self) -> int:
        ends = [e.end for e in self.entries] + [f.end for f in self.instance.fixed]
        return max(ends) if ends else 0

    def completion(self, job_id: str) -> int | None:
        job = self.instance.job(job_id)
        last = job.operations[-1].index
        ends = [e.end for e in self.entries if e.job == job_id and e.index == last]
        return max(ends) if ends else None

    def weighted_tardiness(self) -> float:
        total = 0.0
        for job in self.instance.jobs:
            c = self.completion(job.id)
            if job.due_date is not None and c is not None:
                total += job.weight * max(0, c - job.due_date)
        return total

    def tardiness_by_job(self) -> dict[str, int]:
        return {
            j.id: max(0, self.completion(j.id) - j.due_date) for j in self.instance.jobs if j.due_date is not None
        }

    def objective(self) -> float:
        obj = self.instance.objective
        return obj.makespan * self.makespan + obj.tardiness * self.weighted_tardiness()

    def violations(self) -> list[str]:
        inst = self.instance
        errs: list[str] = []
        by_op: dict[tuple[str, int], list[Entry]] = {}
        for e in self.entries:
            by_op.setdefault((e.job, e.index), []).append(e)

        for job in inst.jobs:
            for op in job.operations:
                got = by_op.get((job.id, op.index), [])
                if len(got) != 1:
                    errs.append(f"{op.name}: scheduled {len(got)} times (must be exactly once)")
                    continue
                e = got[0]
                if e.machine not in inst.units.get(op.machine, []):
                    errs.append(f"{op.name}: unit {e.machine} cannot process machine type {op.machine}")
                if e.end - e.start != op.duration:
                    errs.append(f"{op.name}: end-start={e.end - e.start} but duration={op.duration}")
                if e.start < inst.time_origin or e.start < 0:
                    errs.append(f"{op.name}: starts at {e.start} before time origin {inst.time_origin}")
                if op.index == 0 and e.start < job.release:
                    errs.append(f"{op.name}: starts at {e.start} before release {job.release}")
                if e.start < inst.machine_ready.get(e.machine, 0):
                    errs.append(f"{op.name}: unit {e.machine} is busy until {inst.machine_ready[e.machine]}")
                for a, b in inst.unavailability.get(e.machine, []):
                    if e.start < b and a < e.end:
                        errs.append(f"{op.name}: [{e.start},{e.end}) overlaps outage of {e.machine} [{a},{b})")
        extra = set(by_op) - {(j.id, op.index) for j in inst.jobs for op in j.operations}
        for key in sorted(extra):
            errs.append(f"unknown operation {key}")
        if errs:
            return errs

        for job in inst.jobs:
            for a, b in zip(job.operations, job.operations[1:]):
                ea, eb = by_op[(job.id, a.index)][0], by_op[(job.id, b.index)][0]
                if eb.start < ea.end:
                    errs.append(f"{job.id}: {b.machine} starts at {eb.start} before {a.machine} ends at {ea.end}")

        per_unit: dict[str, list[Entry]] = {}
        for e in self.entries:
            per_unit.setdefault(e.machine, []).append(e)
        for unit, es in per_unit.items():
            mtype = inst.unit_type(unit)
            es = sorted(es, key=lambda e: e.start)
            for i, a in enumerate(es):
                for b in es[i + 1 :]:
                    gap = inst.setup(mtype, a.job, b.job) if a.job != b.job else 0
                    if b.start < a.end + gap:
                        what = "overlaps" if b.start < a.end else f"violates setup gap {gap} after"
                        errs.append(
                            f"unit {unit}: {b.job}[{b.start},{b.end}) {what} {a.job}[{a.start},{a.end})"
                        )
            for b in es:
                if inst.fixed_conflict(b.job, unit, b.start, b.end):
                    errs.append(f"unit {unit}: {b.job}[{b.start},{b.end}) clashes with a running operation")
        return errs

    @property
    def feasible(self) -> bool:
        return not self.violations()

    def to_json_dict(self, instance_name: str | None = None, extended: bool | None = None) -> dict:
        inst = self.instance
        if extended is None:
            extended = not inst.is_baseline_like
        out: dict = {
            "instance": instance_name or inst.name,
            "method": self.method,
            "makespan": self.makespan,
            "schedule": [],
        }
        for e in self.entries:
            row: dict = {"job": e.job, "machine": e.machine, "start": e.start, "end": e.end}
            if extended:
                row["operation"] = e.index
            out["schedule"].append(row)
        if extended:
            out["fixed"] = [
                {"job": f.job, "operation": f.index, "machine": f.machine, "start": f.start, "end": f.end}
                for f in inst.fixed
            ]
            out["objective"] = {
                "weights": inst.objective.to_dict(),
                "makespan": self.makespan,
                "weighted_tardiness": self.weighted_tardiness(),
                "value": self.objective(),
            }
        return out

    def save(self, path: str | Path, instance_name: str | None = None, extended: bool | None = None) -> None:
        Path(path).write_text(json.dumps(self.to_json_dict(instance_name, extended), indent=2) + "\n", newline="\n")

    @classmethod
    def from_json_dict(cls, instance: Instance, data: dict) -> "Schedule":
        entries = []
        for row in data["schedule"]:
            job = instance.job(row["job"])
            if "operation" in row:
                index = int(row["operation"])
            else:
                mtype = instance.unit_type(row["machine"])
                matches = [op.index for op in job.operations if op.machine == mtype]
                if len(matches) != 1:
                    raise ValueError(f"cannot identify operation of {row} without an 'operation' index")
                index = matches[0]
            entries.append(Entry(job.id, index, str(row["machine"]), int(row["start"]), int(row["end"])))
        return cls(instance, entries, data.get("method", ""))

    @classmethod
    def load(cls, instance: Instance, path: str | Path) -> "Schedule":
        return cls.from_json_dict(instance, json.loads(Path(path).read_text()))

    def ascii_gantt(self) -> str:
        inst = self.instance
        span = self.makespan
        lines = ["      " + "".join(f"{t % 10}" for t in range(span))]
        for unit in inst.all_units:
            row = ["."] * span
            for a, b in inst.unavailability.get(unit, []):
                for t in range(max(a, 0), min(b, span)):
                    row[t] = "#"
            for f in inst.fixed:
                if f.machine == unit:
                    for t in range(f.start, min(f.end, span)):
                        row[t] = "="
            for e in self.entries:
                if e.machine == unit:
                    label = e.job[-1] if e.job else "?"
                    for t in range(e.start, e.end):
                        row[t] = label
            lines.append(f"{unit:>5} " + "".join(row))
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"Schedule(makespan={self.makespan}, entries={len(self.entries)}, method={self.method!r})"

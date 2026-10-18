from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_MACHINE_ORDER = ("T", "F", "S")


@dataclass(frozen=True)
class Operation:
    uid: int
    job: str
    index: int
    machine: str
    duration: int

    @property
    def name(self) -> str:
        return f"{self.job}/{self.index}:{self.machine}"


@dataclass
class Job:
    id: str
    operations: list[Operation]
    release: int = 0
    due_date: int | None = None
    weight: float = 1.0
    family: str | None = None

    @property
    def total_duration(self) -> int:
        return sum(op.duration for op in self.operations)


@dataclass(frozen=True)
class Objective:
    makespan: float = 1.0
    tardiness: float = 0.0

    @property
    def pure_makespan(self) -> bool:
        return self.tardiness == 0

    def to_dict(self) -> dict:
        return {"makespan": self.makespan, "weighted_tardiness": self.tardiness}


@dataclass(frozen=True)
class FixedEntry:
    job: str
    index: int
    machine: str
    start: int
    end: int


@dataclass
class Instance:
    name: str
    jobs: list[Job]
    units: dict[str, list[str]]
    setup_times: dict[str, dict[tuple[str, str], int]] = field(default_factory=dict)
    unavailability: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    machine_ready: dict[str, int] = field(default_factory=dict)
    objective: Objective = field(default_factory=Objective)
    time_origin: int = 0
    fixed: list[FixedEntry] = field(default_factory=list)
    description: str = ""
    families: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for job in self.jobs:
            if job.family is not None:
                self.families.setdefault(job.id, job.family)
        self.unavailability = merge_windows(self.unavailability)

    @property
    def operations(self) -> list[Operation]:
        return [op for job in self.jobs for op in job.operations]

    @property
    def machine_types(self) -> list[str]:
        return list(self.units)

    @property
    def all_units(self) -> list[str]:
        return [u for units in self.units.values() for u in units]

    def job(self, job_id: str) -> Job:
        for job in self.jobs:
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def unit_type(self, unit: str) -> str:
        for mtype, units in self.units.items():
            if unit in units:
                return mtype
        raise KeyError(unit)

    def setup(self, machine_type: str, job_from: str, job_to: str) -> int:
        table = self.setup_times.get(machine_type)
        if not table:
            return 0
        fa, fb = self.families.get(job_from), self.families.get(job_to)
        if fa is None or fb is None or fa == fb:
            return 0
        return table.get((fa, fb), 0)

    @property
    def has_setups(self) -> bool:
        return any(v for table in self.setup_times.values() for v in table.values())

    @property
    def is_baseline_like(self) -> bool:
        return (
            not self.has_setups
            and not any(self.unavailability.values())
            and not any(self.machine_ready.values())
            and all(len(u) == 1 for u in self.units.values())
            and all(j.release == 0 for j in self.jobs)
            and self.objective.pure_makespan
            and not self.fixed
            and self.time_origin == 0
        )

    def features(self) -> list[str]:
        feats = []
        routes = {tuple(op.machine for op in j.operations) for j in self.jobs}
        if len(routes) > 1:
            feats.append("per-job routes")
        if any(len(u) > 1 for u in self.units.values()):
            feats.append("parallel machines")
        if self.has_setups:
            feats.append("setup times")
        if any(self.unavailability.values()):
            feats.append("machine outages")
        if any(j.release for j in self.jobs) or any(self.machine_ready.values()) or self.fixed:
            feats.append("rolling state")
        if self.objective.tardiness:
            feats.append("due dates")
        return feats or ["baseline"]

    def check_setup_triangle(self) -> list[str]:
        problems = []
        for mtype in self.setup_times:
            ops = [op for op in self.operations if op.machine == mtype]
            for a in ops:
                for b in ops:
                    for c in ops:
                        if len({a.job, b.job, c.job}) < 3:
                            continue
                        lhs = self.setup(mtype, a.job, c.job)
                        rhs = self.setup(mtype, a.job, b.job) + b.duration + self.setup(mtype, b.job, c.job)
                        if lhs > rhs:
                            problems.append(f"{mtype}: {a.job}->{c.job} ({lhs}) > via {b.job} ({rhs})")
        return problems

    @classmethod
    def from_dict(cls, data: dict, name: str = "instance") -> "Instance":
        if data.get("problem", "erp_scheduling") != "erp_scheduling":
            raise ValueError(f"unsupported problem type {data.get('problem')!r}")
        name = data.get("name", name)

        jobs: list[Job] = []
        uid = 0
        for jd in data["jobs"]:
            ops = []
            for k, od in enumerate(jd["operations"]):
                dur = int(od["duration"])
                if dur <= 0:
                    raise ValueError(f"job {jd['id']} op {k}: duration must be positive")
                ops.append(Operation(uid, str(jd["id"]), k, str(od["machine"]), dur))
                uid += 1
            jobs.append(
                Job(
                    id=str(jd["id"]),
                    operations=ops,
                    release=int(jd.get("release", 0)),
                    due_date=None if jd.get("due_date") is None else int(jd["due_date"]),
                    weight=float(jd.get("weight", 1.0)),
                    family=jd.get("family"),
                )
            )
        if len({j.id for j in jobs}) != len(jobs):
            raise ValueError("job ids must be unique")

        used_types = []
        for j in jobs:
            for op in j.operations:
                if op.machine not in used_types:
                    used_types.append(op.machine)
        units: dict[str, list[str]] = {}
        if "machines" in data:
            for md in data["machines"]:
                if isinstance(md, str):
                    units.setdefault(md, []).append(md)
                else:
                    units.setdefault(str(md.get("type", md["id"])), []).append(str(md["id"]))
        ordered = [t for t in DEFAULT_MACHINE_ORDER if t in used_types] + [
            t for t in used_types if t not in DEFAULT_MACHINE_ORDER
        ]
        for t in ordered:
            units.setdefault(t, [t])
        missing = [t for t in used_types if t not in units]
        if missing:
            raise ValueError(f"no machine units for types {missing}")
        units = {t: units[t] for t in sorted(units, key=lambda t: ordered.index(t) if t in ordered else 99)}

        setup_times: dict[str, dict[tuple[str, str], int]] = {}
        for mtype, table in data.get("setup_times", {}).items():
            setup_times[mtype] = {
                (fa, fb): int(v) for fa, row in table.items() for fb, v in row.items() if fa != fb
            }

        unavailability: dict[str, list[tuple[int, int]]] = {}
        for w in data.get("unavailability", []):
            if int(w["end"]) <= int(w["start"]):
                raise ValueError(f"empty unavailability window {w}")
            unavailability.setdefault(str(w["machine"]), []).append((int(w["start"]), int(w["end"])))

        obj = data.get("objective", {})
        objective = Objective(
            makespan=float(obj.get("makespan", 1.0)),
            tardiness=float(obj.get("weighted_tardiness", 0.0)),
        )
        if objective.makespan < 0 or objective.tardiness < 0 or (objective.makespan == 0 and objective.tardiness == 0):
            raise ValueError("objective weights must be non-negative and not both zero")
        if objective.tardiness and any(j.due_date is None for j in jobs):
            raise ValueError("weighted tardiness objective needs a due_date for every job")

        fixed = [
            FixedEntry(str(f["job"]), int(f.get("operation", -1)), str(f["machine"]), int(f["start"]), int(f["end"]))
            for f in data.get("fixed", [])
        ]

        inst = cls(
            name=name,
            jobs=jobs,
            units=units,
            setup_times=setup_times,
            unavailability=unavailability,
            machine_ready={str(k): int(v) for k, v in data.get("machine_ready", {}).items()},
            objective=objective,
            time_origin=int(data.get("time_origin", 0)),
            fixed=fixed,
            description=data.get("description", ""),
        )
        for unit in list(inst.unavailability) + list(inst.machine_ready):
            inst.unit_type(unit)
        return inst

    @classmethod
    def load(cls, path: str | Path) -> "Instance":
        path = Path(path)
        with path.open() as fh:
            data = json.load(fh)
        return cls.from_dict(data, name=path.stem)

    def to_dict(self) -> dict:
        out: dict = {"problem": "erp_scheduling", "name": self.name}
        if self.description:
            out["description"] = self.description
        if any(len(u) > 1 or u[0] != t for t, u in self.units.items()):
            out["machines"] = [{"id": u, "type": t} for t, us in self.units.items() for u in us]
        jobs = []
        for j in self.jobs:
            jd: dict = {"id": j.id, "operations": [{"machine": op.machine, "duration": op.duration} for op in j.operations]}
            if j.release:
                jd["release"] = j.release
            if j.due_date is not None:
                jd["due_date"] = j.due_date
            if j.weight != 1.0:
                jd["weight"] = j.weight
            if j.family is not None:
                jd["family"] = j.family
            jobs.append(jd)
        out["jobs"] = jobs
        if self.setup_times:
            st: dict = {}
            for mtype, table in self.setup_times.items():
                for (fa, fb), v in table.items():
                    st.setdefault(mtype, {}).setdefault(fa, {})[fb] = v
            out["setup_times"] = st
        if any(self.unavailability.values()):
            out["unavailability"] = [
                {"machine": u, "start": a, "end": b} for u, ws in self.unavailability.items() for a, b in ws
            ]
        if any(self.machine_ready.values()):
            out["machine_ready"] = dict(self.machine_ready)
        if self.time_origin:
            out["time_origin"] = self.time_origin
        if self.fixed:
            out["fixed"] = [
                {"job": f.job, "operation": f.index, "machine": f.machine, "start": f.start, "end": f.end}
                for f in self.fixed
            ]
        if not self.objective.pure_makespan or self.objective.makespan != 1.0:
            out["objective"] = self.objective.to_dict()
        return out

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", newline="\n")

    def head(self, op: Operation) -> int:
        job = self.job(op.job)
        return max(job.release, self.time_origin) + sum(o.duration for o in job.operations[: op.index])

    def tail(self, op: Operation) -> int:
        return sum(o.duration for o in self.job(op.job).operations[op.index :])

    def successor(self, op: Operation) -> Operation | None:
        ops = self.job(op.job).operations
        return ops[op.index + 1] if op.index + 1 < len(ops) else None

    def is_last(self, op: Operation) -> bool:
        return op.index == len(self.job(op.job).operations) - 1

    def unit_available(self, unit: str, start: int, end: int) -> bool:
        if start < self.machine_ready.get(unit, 0):
            return False
        return all(end <= a or start >= b for a, b in self.unavailability.get(unit, []))

    def fixed_conflict(self, job_id: str, unit: str, start: int, end: int) -> bool:
        mtype = self.unit_type(unit)
        for f in self.fixed:
            if f.machine != unit:
                continue
            gap_after = self.setup(mtype, f.job, job_id) if f.job != job_id else 0
            gap_before = self.setup(mtype, job_id, f.job) if f.job != job_id else 0
            if not (start >= f.end + gap_after or end + gap_before <= f.start):
                return True
        return False


def merge_windows(windows: dict[str, list[tuple[int, int]]]) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for unit, ws in windows.items():
        merged: list[tuple[int, int]] = []
        for a, b in sorted(ws):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        out[unit] = merged
    return out


def load_instances(paths: Iterable[str | Path]) -> list[Instance]:
    return [Instance.load(p) for p in paths]

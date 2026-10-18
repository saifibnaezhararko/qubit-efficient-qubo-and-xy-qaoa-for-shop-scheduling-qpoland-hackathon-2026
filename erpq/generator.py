from __future__ import annotations

import numpy as np

from .heuristics import makespan_lower_bound
from .model import Instance

FEATURES = ("due_dates", "setups", "outage", "routes", "release", "parallel")


def random_instance(
    n_jobs: int,
    seed: int,
    features: tuple[str, ...] = (),
    durations: tuple[int, int] | dict[str, tuple[int, int]] = (1, 3),
    machines: tuple[str, ...] = ("T", "F", "S"),
    name: str | None = None,
) -> Instance:
    rng = np.random.default_rng(seed)
    jobs = []
    for k in range(n_jobs):
        route = list(machines)
        if "routes" in features and rng.random() < 0.5:
            if rng.random() < 0.5:
                route.pop(int(rng.integers(len(route))))
            else:
                i = int(rng.integers(len(route) - 1))
                route[i], route[i + 1] = route[i + 1], route[i]
        rng_d = (lambda m: durations[m]) if isinstance(durations, dict) else (lambda m: durations)
        ops = [{"machine": m, "duration": int(rng.integers(rng_d(m)[0], rng_d(m)[1] + 1))} for m in route]
        job = {"id": f"Z{k + 1}", "operations": ops}
        if "release" in features:
            job["release"] = int(rng.integers(0, 3))
        if "setups" in features:
            job["family"] = "AB"[int(rng.integers(2))]
        jobs.append(job)
    data: dict = {"problem": "erp_scheduling", "name": name or f"rand_n{n_jobs}_s{seed}", "jobs": jobs}
    if "parallel" in features:
        data["machines"] = [{"id": "T", "type": "T"}, {"id": "F1", "type": "F"}, {"id": "F2", "type": "F"},
                            {"id": "S", "type": "S"}]
    if "setups" in features:
        data["setup_times"] = {m: {"A": {"B": 1}, "B": {"A": 1}} for m in ("F", "S")}
    if "due_dates" in features:
        for job in jobs:
            work = sum(o["duration"] for o in job["operations"])
            job["due_date"] = int(job.get("release", 0) + work + rng.integers(0, max(2, n_jobs * 2)))
            job["weight"] = int(rng.integers(1, 4))
        data["objective"] = {"makespan": 2, "weighted_tardiness": 1}
    inst = Instance.from_dict(data, data["name"])
    if "outage" in features:
        lb = makespan_lower_bound(inst)
        unit = str(rng.choice(inst.all_units))
        start = int(rng.integers(1, max(2, lb - 1)))
        data["unavailability"] = [{"machine": unit, "start": start, "end": start + int(rng.integers(1, 3))}]
        inst = Instance.from_dict(data, data["name"])
    return inst

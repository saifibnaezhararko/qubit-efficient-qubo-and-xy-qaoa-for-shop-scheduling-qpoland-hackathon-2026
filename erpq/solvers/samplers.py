from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np

from ..qubo import QUBO


@dataclass
class Samples:
    solver: str
    states: np.ndarray
    energies: np.ndarray
    wall_time: float
    info: dict = field(default_factory=dict)

    @property
    def best_energy(self) -> float:
        return float(self.energies.min())


def _from_sampleset(name: str, ss, n: int, t: float, info=None) -> Samples:
    import dimod

    if ss.vartype is dimod.SPIN:
        ss = ss.change_vartype(dimod.BINARY, inplace=False)
    labels = [int(v) for v in ss.variables]
    raw = ss.record.sample
    states = np.zeros((raw.shape[0], n), dtype=np.int8)
    states[:, labels] = raw
    reps = ss.record.num_occurrences
    states = np.repeat(states, reps, axis=0)
    energies = np.repeat(ss.record.energy, reps)
    return Samples(name, states, energies.astype(float), t, info or {})


def simulated_annealing(q: QUBO, num_reads: int = 200, num_sweeps: int = 1000, seed: int = 0) -> Samples:
    from dwave.samplers import SimulatedAnnealingSampler

    t0 = time.perf_counter()
    ss = SimulatedAnnealingSampler().sample(q.to_bqm(), num_reads=num_reads, num_sweeps=num_sweeps, seed=seed)
    return _from_sampleset(
        "simulated annealing", ss, q.n, time.perf_counter() - t0, {"num_reads": num_reads, "num_sweeps": num_sweeps}
    )


def tabu_search(q: QUBO, num_reads: int = 20, timeout_ms: int = 50, seed: int = 0) -> Samples:
    from dwave.samplers import TabuSampler

    t0 = time.perf_counter()
    ss = TabuSampler().sample(q.to_bqm(), num_reads=num_reads, timeout=timeout_ms, seed=seed)
    return _from_sampleset("tabu search", ss, q.n, time.perf_counter() - t0, {"num_reads": num_reads, "timeout_ms": timeout_ms})


def exhaustive(q: QUBO) -> Samples:
    t0 = time.perf_counter()
    E = q.all_energies()
    emin = E.min()
    idx = np.flatnonzero(np.isclose(E, emin, atol=1e-9))
    states = ((idx[:, None] >> np.arange(q.n)[None, :]) & 1).astype(np.int8)
    return Samples("exhaustive enumeration", states, E[idx], time.perf_counter() - t0, {"states_checked": int(E.size)})


class VeloxQUnavailable(RuntimeError):
    pass


def veloxq_available() -> bool:
    try:
        import veloxq_sdk
    except ImportError:
        return False
    return bool(os.environ.get("VELOX_TOKEN"))


def veloxq(q: QUBO, num_rep: int = 1024, num_steps: int = 5000, solver: str = "veloxq") -> Samples:
    try:
        from veloxq_sdk import SBMParameters, SBMSolver, VeloxQParameters, VeloxQSolver
        from veloxq_sdk.config import load_config
    except ImportError as exc:
        raise VeloxQUnavailable("pip install veloxq-sdk") from exc
    if not os.environ.get("VELOX_TOKEN"):
        raise VeloxQUnavailable("set the VELOX_TOKEN environment variable to your VeloxQ API token")
    load_config()
    if solver == "sbm":
        sv = SBMSolver(parameters=SBMParameters(num_rep=num_rep, num_steps=num_steps))
    else:
        sv = VeloxQSolver(parameters=VeloxQParameters(num_rep=num_rep, num_steps=num_steps))
    t0 = time.perf_counter()
    ss = sv.sample(q.to_bqm(), vartype="BINARY")
    t = time.perf_counter() - t0
    info = {"num_rep": num_rep, "num_steps": num_steps}
    if "total_time" in ss.info:
        info["solver_time_s"] = float(ss.info["total_time"])
    res = _from_sampleset(f"VeloxQ ({solver})", ss, q.n, t, info)
    res.energies = q.energies(res.states)
    return res

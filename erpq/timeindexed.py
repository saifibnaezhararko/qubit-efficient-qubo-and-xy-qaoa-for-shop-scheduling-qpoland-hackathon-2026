from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .heuristics import best_heuristic, fifo_schedule, makespan_lower_bound
from .model import Instance, Operation
from .qubo import QUBO
from .schedule import Entry, Schedule

PRUNING_LEVELS = ("none", "horizon", "window", "ac3", "sac")
MAKESPAN_ENCODINGS = ("auto", "exp", "thermometer", "none")


class InfeasibleHorizon(ValueError):
    pass


def unary_feasible(inst: Instance, op: Operation, unit: str, t: int) -> bool:
    if op.index == 0 and t < inst.job(op.job).release:
        return False
    return inst.unit_available(unit, t, t + op.duration) and not inst.fixed_conflict(op.job, unit, t, t + op.duration)


def _initial_values(inst: Instance, op: Operation, horizon: int, level: str) -> list[tuple[str, int]]:
    vals = []
    origin = inst.time_origin
    for unit in inst.units[op.machine]:
        if level == "none":
            ts = range(origin, horizon)
        elif level == "horizon":
            ts = range(origin, horizon - op.duration + 1)
        else:
            lo = max(inst.head(op), inst.machine_ready.get(unit, 0))
            hi = horizon - inst.tail(op)
            ts = [t for t in range(lo, hi + 1) if unary_feasible(inst, op, unit, t)]
        vals.extend((unit, t) for t in ts)
    return vals


def compatible(inst: Instance, a: Operation, va: tuple[str, int], b: Operation, vb: tuple[str, int]) -> bool:
    (ua, ta), (ub, tb) = va, vb
    if a.job == b.job:
        if b.index == a.index + 1:
            return tb >= ta + a.duration
        if a.index == b.index + 1:
            return ta >= tb + b.duration
        return True
    if a.machine != b.machine or ua != ub:
        return True
    sab = inst.setup(a.machine, a.job, b.job)
    sba = inst.setup(a.machine, b.job, a.job)
    return tb >= ta + a.duration + sab or ta >= tb + b.duration + sba


def constraint_pairs(inst: Instance) -> list[tuple[Operation, Operation, str]]:
    pairs = []
    ops = inst.operations
    for a, b in itertools.combinations(ops, 2):
        if a.job == b.job:
            if abs(a.index - b.index) == 1:
                pairs.append((a, b, "prec") if a.index < b.index else (b, a, "prec"))
        elif a.machine == b.machine:
            pairs.append((a, b, "cap"))
    return pairs


class DomainPropagator:
    def __init__(self, inst: Instance, values: dict[int, list[tuple[str, int]]]):
        self.inst = inst
        self.values = values
        self.ops = {op.uid: op for op in inst.operations}
        self.neighbours: dict[int, list[int]] = {uid: [] for uid in values}
        self.compat: dict[tuple[int, int], np.ndarray] = {}
        for a, b, _ in constraint_pairs(inst):
            M = np.array(
                [[compatible(inst, a, va, b, vb) for vb in values[b.uid]] for va in values[a.uid]], dtype=bool
            ).reshape(len(values[a.uid]), len(values[b.uid]))
            self.compat[a.uid, b.uid] = M
            self.compat[b.uid, a.uid] = M.T
            self.neighbours[a.uid].append(b.uid)
            self.neighbours[b.uid].append(a.uid)

    def ac3(self, alive: dict[int, np.ndarray], queue=None) -> bool:
        if queue is None:
            queue = deque((a, b) for a in alive for b in self.neighbours[a])
        queued = set(queue)
        while queue:
            a, b = queue.popleft()
            queued.discard((a, b))
            M = self.compat[a, b]
            supported = M[:, alive[b]].any(axis=1)
            new = alive[a] & supported
            if new.sum() != alive[a].sum():
                alive[a] = new
                if not new.any():
                    return False
                for c in self.neighbours[a]:
                    if c != b and (c, a) not in queued:
                        queue.append((c, a))
                        queued.add((c, a))
        return True

    def sac(self, alive: dict[int, np.ndarray]) -> bool:
        if not self.ac3(alive):
            return False
        changed = True
        while changed:
            changed = False
            for a in alive:
                for i in np.flatnonzero(alive[a]):
                    trial = {k: v.copy() for k, v in alive.items()}
                    trial[a][:] = False
                    trial[a][i] = True
                    if not self.ac3(trial, deque((c, a) for c in self.neighbours[a])):
                        alive[a][i] = False
                        changed = True
                        if not alive[a].any() or not self.ac3(alive):
                            return False
        return True


def compute_domains(inst: Instance, horizon: int, level: str = "sac") -> dict[int, list[tuple[str, int]]] | None:
    if level not in PRUNING_LEVELS:
        raise ValueError(f"pruning level must be one of {PRUNING_LEVELS}")
    values = {op.uid: _initial_values(inst, op, horizon, level) for op in inst.operations}
    if any(not v for v in values.values()):
        return None
    if level in ("none", "horizon", "window"):
        return values
    prop = DomainPropagator(inst, values)
    alive = {uid: np.ones(len(v), dtype=bool) for uid, v in values.items()}
    ok = prop.ac3(alive) if level == "ac3" else prop.sac(alive)
    if not ok:
        return None
    return {uid: [v for v, keep in zip(values[uid], alive[uid]) if keep] for uid in values}


@dataclass(frozen=True)
class Var:
    kind: str
    op: int
    unit: str
    t: int


@dataclass
class Register:
    kind: str
    vars: list[int]
    op: int = -1

    @property
    def dim(self) -> int:
        return len(self.vars) if self.kind == "onehot" else 2


@dataclass
class Penalties:
    onehot: float
    precedence: float
    capacity: float
    makespan_link: float

    def scaled(self, k: float) -> "Penalties":
        return Penalties(self.onehot * k, self.precedence * k, self.capacity * k, self.makespan_link * k)


@dataclass
class TimeIndexedQUBO:
    inst: Instance
    horizon: int
    pruning: str
    makespan_encoding: str
    lower_bound: int
    domains: dict[int, list[tuple[str, int]]]
    vars: list[Var]
    registers: list[Register]
    qubo: QUBO
    penalties: Penalties
    objective_bound: float
    constraint_qubo: QUBO | None = None
    stats: dict = field(default_factory=dict)

    def decode(self, x) -> tuple[Schedule | None, str]:
        x = np.asarray(x).astype(int)
        ops = {op.uid: op for op in self.inst.operations}
        entries = []
        for reg in self.registers:
            if reg.kind != "onehot":
                continue
            on = [v for v in reg.vars if x[v]]
            op = ops[reg.op]
            if len(on) != 1:
                return None, f"{op.name} started {len(on)} times"
            var = self.vars[on[0]]
            entries.append(Entry(op.job, op.index, var.unit, var.t, var.t + op.duration))
        for uid, dom in self.domains.items():
            if len(dom) == 1 and not any(r.op == uid for r in self.registers):
                op = ops[uid]
                unit, t = dom[0]
                entries.append(Entry(op.job, op.index, unit, t, t + op.duration))
        return Schedule(self.inst, entries), ""

    def encode(self, sched: Schedule) -> np.ndarray | None:
        index = {(v.op, v.unit, v.t): i for i, v in enumerate(self.vars) if v.kind == "x"}
        uid = {(op.job, op.index): op.uid for op in self.inst.operations}
        x = np.zeros(len(self.vars), dtype=int)
        for e in sched.entries:
            key = (uid[e.job, e.index], e.machine, e.start)
            if key in index:
                x[index[key]] = 1
            elif self.domains[key[0]] != [(e.machine, e.start)]:
                return None
        for i, v in enumerate(self.vars):
            if v.kind == "z":
                x[i] = int(sched.makespan > v.t)
        return x

    def objective_offset(self) -> float:
        if self.makespan_encoding in ("thermometer", "none"):
            return self.inst.objective.makespan * self.lower_bound
        return 0.0

    @property
    def num_qubits(self) -> int:
        return self.qubo.n

    @property
    def subspace_dim(self) -> int:
        return int(np.prod([r.dim for r in self.registers], dtype=float)) if self.registers else 1

    def register_energy_tensor(self, qubo: QUBO | None = None, max_states: int = 50_000_000) -> np.ndarray:
        dims = [r.dim for r in self.registers]
        if np.prod(dims, dtype=float) > max_states:
            raise ValueError(f"subspace has {np.prod(dims, dtype=float):.3g} states")
        q = qubo if qubo is not None else self.qubo
        local: list[list[list[int]]] = []
        for r in self.registers:
            local.append([[v] for v in r.vars] if r.kind == "onehot" else [[], r.vars])
        owner = {}
        for g, r in enumerate(self.registers):
            for v in r.vars:
                owner[v] = g
        E = np.full(dims, q.offset, dtype=float)
        G = len(dims)
        for g in range(G):
            L = np.array([sum(q.linear[v] for v in act) for act in local[g]])
            shape = [1] * G
            shape[g] = dims[g]
            E += L.reshape(shape)
        pair_terms: dict[tuple[int, int], np.ndarray] = {}
        for (i, j), val in q.quadratic.items():
            gi, gj = owner[i], owner[j]
            if gi == gj:
                continue
            if gi > gj:
                gi, gj, i, j = gj, gi, j, i
            P = pair_terms.setdefault((gi, gj), np.zeros((dims[gi], dims[gj])))
            li = [k for k, act in enumerate(local[gi]) if i in act]
            lj = [k for k, act in enumerate(local[gj]) if j in act]
            for a in li:
                for b in lj:
                    P[a, b] += val
        for (gi, gj), P in pair_terms.items():
            shape = [1] * G
            shape[gi], shape[gj] = dims[gi], dims[gj]
            E += P.reshape(shape)
        return E

    def subspace_to_bits(self, multi_index) -> np.ndarray:
        x = np.zeros(self.qubo.n, dtype=int)
        for r, k in zip(self.registers, multi_index):
            if r.kind == "onehot":
                x[r.vars[k]] = 1
            elif k == 1:
                x[r.vars[0]] = 1
        return x


def build_time_indexed_qubo(
    inst: Instance,
    horizon: int | None = None,
    pruning: str = "sac",
    makespan_encoding: str = "auto",
    penalty: float | Penalties | None = None,
    penalty_scale: float = 1.0,
) -> TimeIndexedQUBO:
    if pruning not in PRUNING_LEVELS:
        raise ValueError(f"pruning must be one of {PRUNING_LEVELS}, got {pruning!r}")
    if makespan_encoding not in MAKESPAN_ENCODINGS:
        raise ValueError(f"makespan_encoding must be one of {MAKESPAN_ENCODINGS}, got {makespan_encoding!r}")
    if makespan_encoding == "exp" and inst.objective.tardiness:
        raise ValueError("the exponential makespan encoding is only exact for a pure makespan objective")
    if horizon is None:
        horizon = fifo_schedule(inst).makespan
    lb = makespan_lower_bound(inst)
    domains = compute_domains(inst, horizon, pruning)
    if domains is None:
        raise InfeasibleHorizon(f"no schedule of {inst.name} can finish by H={horizon} (proved by {pruning} pruning)")

    obj = inst.objective
    ops = inst.operations
    sinks = [op for op in ops if inst.is_last(op)]
    max_end = max(t + op.duration for op in sinks for _, t in domains[op.uid])
    if makespan_encoding == "auto":
        makespan_encoding = "exp" if obj.tardiness == 0 else "thermometer"
    if obj.makespan == 0 or max_end <= lb:
        makespan_encoding = "none"

    vars_: list[Var] = []
    registers: list[Register] = []
    for op in ops:
        dom = domains[op.uid]
        if len(dom) == 1 and pruning in ("ac3", "sac"):
            continue
        reg = Register("onehot", [], op.uid)
        for unit, t in dom:
            reg.vars.append(len(vars_))
            vars_.append(Var("x", op.uid, unit, t))
        registers.append(reg)
    z_index: dict[int, int] = {}
    if makespan_encoding == "thermometer":
        for T in range(lb, max_end):
            z_index[T] = len(vars_)
            registers.append(Register("bit", [len(vars_)]))
            vars_.append(Var("z", -1, "", T))

    n_sinks = len(sinks)

    def sink_cost(op: Operation, end: int) -> float:
        c = 0.0
        job = inst.job(op.job)
        if obj.tardiness and job.due_date is not None:
            c += obj.tardiness * job.weight * max(0, end - job.due_date)
        if makespan_encoding == "exp" and end > lb:
            c += obj.makespan * float(n_sinks + 1) ** (end - lb - 1)
        return c

    def objective_energy(sched: Schedule) -> float:
        e = 0.0
        for en in sched.entries:
            op = next(o for o in ops if o.job == en.job and o.index == en.index)
            if inst.is_last(op):
                e += sink_cost(op, en.end)
        if makespan_encoding == "thermometer":
            e += obj.makespan * max(0, sched.makespan - lb)
        return e

    U = None
    for cand in (fifo_schedule(inst), best_heuristic(inst)):
        if cand.makespan <= horizon and cand.feasible:
            fits = all(
                (en.machine, en.start) in domains[next(o.uid for o in ops if o.job == en.job and o.index == en.index)]
                for en in cand.entries
            )
            if fits:
                U = objective_energy(cand)
                break
    if U is None:
        U = sum(max(sink_cost(op, t + op.duration) for _, t in domains[op.uid]) for op in sinks)
        U += obj.makespan * len(z_index)

    if penalty is None:
        p = (U + 1.0) * penalty_scale
        pen = Penalties(p, p, p, p)
    elif isinstance(penalty, Penalties):
        pen = penalty
    else:
        pen = Penalties(penalty, penalty, penalty, penalty)

    labels = []
    opn = {op.uid: op for op in ops}
    for v in vars_:
        labels.append(f"x[{opn[v.op].job}.{opn[v.op].machine}{v.op}@{v.unit},{v.t}]" if v.kind == "x" else f"z[{v.t}]")
    q = QUBO(labels)
    cq = QUBO(labels)

    for reg in registers:
        if reg.kind != "onehot":
            continue
        for qq, w in ((q, pen.onehot), (cq, 1.0)):
            qq.offset += w
            for i in reg.vars:
                qq.add_linear(i, -w)
            for i, j in itertools.combinations(reg.vars, 2):
                qq.add_quadratic(i, j, 2 * w, "onehot")

    opn_by_uid = {op.uid: op for op in ops}
    for i, v in enumerate(vars_):
        if v.kind == "x" and not unary_feasible(inst, opn_by_uid[v.op], v.unit, v.t):
            q.add_linear(i, pen.capacity)
            cq.add_linear(i, 1.0)
            q.term_kinds["unary"] += 1

    reg_of = {r.op: r for r in registers if r.kind == "onehot"}
    for a, b, kind in constraint_pairs(inst):
        ra, rb = reg_of.get(a.uid), reg_of.get(b.uid)
        if ra is None or rb is None:
            continue
        weight = pen.precedence if kind == "prec" else pen.capacity
        for i in ra.vars:
            for j in rb.vars:
                va, vb = vars_[i], vars_[j]
                if not compatible(inst, a, (va.unit, va.t), b, (vb.unit, vb.t)):
                    q.add_quadratic(i, j, weight, kind)
                    cq.add_quadratic(i, j, 1.0, kind)

    for op in sinks:
        reg = reg_of.get(op.uid)
        if reg is None:
            continue
        for i in reg.vars:
            end = vars_[i].t + op.duration
            c = sink_cost(op, end)
            if c:
                q.add_linear(i, c)
            for T, zi in z_index.items():
                if end > T:
                    q.add_linear(i, pen.makespan_link)
                    q.add_quadratic(i, zi, -pen.makespan_link, "makespan")
    for T, zi in z_index.items():
        q.add_linear(zi, obj.makespan)
    for op in sinks:
        if op.uid not in reg_of:
            end = domains[op.uid][0][1] + op.duration
            q.offset += sink_cost(op, end)
            for T, zi in z_index.items():
                if end > T:
                    q.offset += pen.makespan_link
                    q.add_linear(zi, -pen.makespan_link)

    model = TimeIndexedQUBO(
        constraint_qubo=cq,
        inst=inst,
        horizon=horizon,
        pruning=pruning,
        makespan_encoding=makespan_encoding,
        lower_bound=lb,
        domains=domains,
        vars=vars_,
        registers=registers,
        qubo=q,
        penalties=pen,
        objective_bound=U,
    )
    model.stats = {
        "horizon": horizon,
        "lower_bound": lb,
        "pruning": pruning,
        "makespan_encoding": makespan_encoding,
        "start_variables": sum(len(r.vars) for r in registers if r.kind == "onehot"),
        "aux_variables": len(z_index),
        "qubits": q.n,
        "fixed_operations": sum(1 for op in ops if op.uid not in reg_of),
        "quadratic_terms": q.num_interactions,
        "terms_by_kind": dict(q.term_kinds),
        "subspace_dim": model.subspace_dim,
        "penalty": pen.onehot,
        "objective_bound_U": U,
        **q.coefficient_stats(),
    }
    return model


def pruning_report(inst: Instance, horizon: int, encoding: str = "auto") -> list[dict]:
    rows = []
    for level in PRUNING_LEVELS:
        try:
            m = build_time_indexed_qubo(inst, horizon, level, encoding)
            rows.append(m.stats)
        except InfeasibleHorizon as exc:
            rows.append({"pruning": level, "horizon": horizon, "error": str(exc)})
    return rows

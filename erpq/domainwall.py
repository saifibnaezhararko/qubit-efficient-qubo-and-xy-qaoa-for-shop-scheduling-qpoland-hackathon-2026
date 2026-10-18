from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .qubo import QUBO
from .schedule import Schedule
from .timeindexed import TimeIndexedQUBO


@dataclass
class DomainWallQUBO:
    base: TimeIndexedQUBO
    qubo: QUBO
    affine: list[tuple[float, dict[int, float]]]
    wall_penalty: float
    groups: list[list[int]]

    @property
    def num_qubits(self) -> int:
        return self.qubo.n

    def to_onehot(self, s) -> np.ndarray | None:
        s = np.asarray(s).astype(int)
        x = np.zeros(self.base.qubo.n, dtype=int)
        for v, (c, terms) in enumerate(self.affine):
            val = c + sum(k * s[i] for i, k in terms.items())
            if val not in (0, 1):
                return None
            x[v] = int(val)
        return x

    def decode(self, s) -> tuple[Schedule | None, str]:
        x = self.to_onehot(s)
        if x is None:
            return None, "broken domain wall"
        return self.base.decode(x)

    def from_onehot(self, x) -> np.ndarray:
        x = np.asarray(x).astype(int)
        s = np.zeros(self.qubo.n, dtype=int)
        for reg, bits in zip([r for r in self.base.registers if r.kind == "onehot"], self.groups):
            k = int(np.flatnonzero(x[reg.vars])[0])
            s[bits[:k]] = 1
        for v, (c, terms) in enumerate(self.affine):
            if len(terms) == 1 and c == 0 and self.base.vars[v].kind == "z":
                s[next(iter(terms))] = x[v]
        return s


def to_domain_wall(model: TimeIndexedQUBO, wall_penalty: float | None = None) -> DomainWallQUBO:
    base = model.qubo
    labels: list[str] = []
    affine: list[tuple[float, dict[int, float]] | None] = [None] * base.n
    groups: list[list[int]] = []
    onehot_regs = [r for r in model.registers if r.kind == "onehot"]
    for reg in onehot_regs:
        d = len(reg.vars)
        bits = list(range(len(labels), len(labels) + d - 1))
        labels += [f"s[{base.labels[reg.vars[0]].split('@')[0]}#{k}]" for k in range(1, d)]
        groups.append(bits)
        for k, v in enumerate(reg.vars):
            const, terms = 0.0, {}
            if k == 0:
                const += 1.0
            else:
                terms[bits[k - 1]] = terms.get(bits[k - 1], 0.0) + 1.0
            if k + 1 <= d - 1:
                terms[bits[k]] = terms.get(bits[k], 0.0) - 1.0
            affine[v] = (const, terms)
    for reg in model.registers:
        if reg.kind == "bit":
            v = reg.vars[0]
            affine[v] = (0.0, {len(labels): 1.0})
            labels.append(base.labels[v])
    assert all(a is not None for a in affine)

    q = QUBO(labels)
    q.offset = base.offset
    for v, a in enumerate(base.linear):
        c, terms = affine[v]
        q.offset += a * c
        for i, k in terms.items():
            q.add_linear(i, a * k)
    for (u, v), val in base.quadratic.items():
        cu, tu = affine[u]
        cv, tv = affine[v]
        q.offset += val * cu * cv
        for i, k in tu.items():
            q.add_linear(i, val * k * cv)
        for j, k in tv.items():
            q.add_linear(j, val * k * cu)
        for i, ki in tu.items():
            for j, kj in tv.items():
                q.add_quadratic(i, j, val * ki * kj, "mapped")
    q.quadratic = {k: v for k, v in q.quadratic.items() if abs(v) > 1e-12}
    q.linear[np.abs(q.linear) < 1e-12] = 0.0

    if wall_penalty is None:
        wall_penalty = model.objective_bound + 1.0 + _gain_bound(model)
    for bits in groups:
        for k in range(len(bits) - 1):
            q.add_linear(bits[k + 1], wall_penalty)
            q.add_quadratic(bits[k], bits[k + 1], -wall_penalty, "wall")
    return DomainWallQUBO(model, q, affine, wall_penalty, groups)


def _gain_bound(model: TimeIndexedQUBO) -> float:
    base = model.qubo
    group_of: dict[int, int] = {}
    sizes: dict[int, int] = {}
    for g, r in enumerate(model.registers):
        for v in r.vars:
            group_of[v] = g
        sizes[g] = len(r.vars) if r.kind == "onehot" else 1
    onehot_lin = {v: -model.penalties.onehot for r in model.registers if r.kind == "onehot" for v in r.vars}
    worst = 0.0
    for r in model.registers:
        if r.kind != "onehot":
            continue
        for i in r.vars:
            gain = abs(base.linear[i] - onehot_lin.get(i, 0.0))
            per_group: dict[int, float] = {}
            for (a, b), val in base.quadratic.items():
                if i not in (a, b):
                    continue
                j = b if a == i else a
                h = group_of[j]
                if h == group_of[i]:
                    continue
                per_group[h] = max(per_group.get(h, 0.0), abs(val))
            for h, qmax in per_group.items():
                gain += ((sizes[h] - 1) // 2 + 1) * qmax
            worst = max(worst, gain)
    return worst

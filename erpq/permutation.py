from __future__ import annotations

import itertools
import math
from collections import Counter

import numpy as np

from .heuristics import list_schedule
from .model import Instance
from .qubo import QUBO
from .schedule import Schedule


def permutation_applicable(inst: Instance) -> bool:
    routes = {tuple(op.machine for op in j.operations) for j in inst.jobs}
    return inst.is_baseline_like and len(routes) == 1 and len(inst.machine_types) <= 3


def moebius(f: np.ndarray) -> np.ndarray:
    c = np.array(f, dtype=float)
    b = int(round(math.log2(c.size)))
    for i in range(b):
        bit = 1 << i
        for mask in range(c.size):
            if mask & bit:
                c[mask] -= c[mask ^ bit]
    return c


class PermutationQUBO:
    def __init__(self, inst: Instance):
        if not permutation_applicable(inst):
            raise ValueError("permutation encoding is exact only for baseline-like flow shops with <= 3 machines")
        self.instance = inst
        self.perms = [list(p) for p in itertools.permutations([j.id for j in inst.jobs])]
        self.code_bits = max(1, math.ceil(math.log2(len(self.perms))))
        costs = [list_schedule(inst, p).objective() for p in self.perms]
        self.invalid_penalty = max(costs) + 1
        table = np.full(1 << self.code_bits, float(self.invalid_penalty))
        table[: len(costs)] = costs
        self.cost_table = table
        c = moebius(table)
        terms: dict[tuple[int, ...], float] = {}
        for mask, v in enumerate(c):
            if abs(v) > 1e-9:
                terms[tuple(i for i in range(self.code_bits) if mask >> i & 1)] = float(v)
        self.hubo_degree = max((len(t) for t in terms), default=0)
        self.aux: list[tuple[int, int]] = []
        n_vars = self.code_bits
        while any(len(t) > 2 for t in terms):
            pairs = Counter(p for t in terms if len(t) > 2 for p in itertools.combinations(t, 2))
            a, b = min(pairs, key=lambda p: (-pairs[p], p))
            y = n_vars
            n_vars += 1
            self.aux.append((a, b))
            new: dict[tuple[int, ...], float] = {}
            for t, v in terms.items():
                if len(t) > 2 and a in t and b in t:
                    t = tuple(sorted([i for i in t if i not in (a, b)] + [y]))
                new[t] = new.get(t, 0.0) + v
            terms = new
        self.terms = terms
        self.aux_penalty = [0.0] * len(self.aux)
        for k in reversed(range(len(self.aux))):
            y = self.code_bits + k
            m = 1.0 + sum(abs(v) for t, v in terms.items() if y in t)
            m += sum(2 * self.aux_penalty[z] for z in range(k + 1, len(self.aux)) if y in self.aux[z])
            self.aux_penalty[k] = m
        labels = [f"code[{i}]" for i in range(self.code_bits)] + [f"aux[{a},{b}]" for a, b in self.aux]
        q = QUBO(labels)
        for t, v in terms.items():
            if len(t) == 0:
                q.offset += v
            elif len(t) == 1:
                q.add_linear(t[0], v)
            else:
                q.add_quadratic(t[0], t[1], v, kind="objective")
        for k, (a, b) in enumerate(self.aux):
            y, m = self.code_bits + k, self.aux_penalty[k]
            q.add_quadratic(a, b, m, kind="aux")
            q.add_quadratic(a, y, -2 * m, kind="aux")
            q.add_quadratic(b, y, -2 * m, kind="aux")
            q.add_linear(y, 3 * m)
        self.qubo = q

    def _aux_consistent(self, x) -> bool:
        return all(x[self.code_bits + k] == x[a] * x[b] for k, (a, b) in enumerate(self.aux))

    def decode(self, state) -> tuple[Schedule | None, dict]:
        x = [int(v) for v in state]
        k = sum(x[i] << i for i in range(self.code_bits))
        if k >= len(self.perms) or not self._aux_consistent(x):
            return None, {"code": k}
        perm = self.perms[k]
        return list_schedule(self.instance, perm, f"permutation {'-'.join(perm)}"), {"code": k, "permutation": perm}

    def constraint_energies(self) -> np.ndarray:
        n = self.qubo.n
        idx = np.arange(1 << n)
        bits = (idx[:, None] >> np.arange(n)[None, :]) & 1
        valid = (idx & ((1 << self.code_bits) - 1)) < len(self.perms)
        for k, (a, b) in enumerate(self.aux):
            valid &= bits[:, self.code_bits + k] == bits[:, a] * bits[:, b]
        return (~valid).astype(float)

    def summary(self) -> dict:
        return {
            "jobs": len(self.instance.jobs),
            "permutations": len(self.perms),
            "code_qubits": self.code_bits,
            "aux_qubits": len(self.aux),
            "qubits": self.qubo.n,
            "hubo_degree": self.hubo_degree,
            "quadratic_terms": self.qubo.num_interactions,
            "invalid_code_penalty": self.invalid_penalty,
            "aux_penalties": self.aux_penalty,
            "cost_table_evaluations": len(self.perms),
        }

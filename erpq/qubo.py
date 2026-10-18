from __future__ import annotations

from collections import Counter

import numpy as np


class QUBO:
    def __init__(self, labels: list[str]):
        self.labels = list(labels)
        self.n = len(self.labels)
        self.linear = np.zeros(self.n)
        self.quadratic: dict[tuple[int, int], float] = {}
        self.offset = 0.0
        self.term_kinds: Counter = Counter()

    def add_linear(self, i: int, value: float) -> None:
        self.linear[i] += value

    def add_quadratic(self, i: int, j: int, value: float, kind: str = "") -> None:
        if i == j:
            self.linear[i] += value
            return
        key = (i, j) if i < j else (j, i)
        if key not in self.quadratic and kind:
            self.term_kinds[kind] += 1
        self.quadratic[key] = self.quadratic.get(key, 0.0) + value

    def energy(self, x) -> float:
        x = np.asarray(x, dtype=float)
        e = self.offset + float(self.linear @ x)
        for (i, j), v in self.quadratic.items():
            e += v * x[i] * x[j]
        return e

    def energies(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        e = self.offset + X @ self.linear
        if self.quadratic:
            idx = np.array(list(self.quadratic.keys()))
            val = np.array(list(self.quadratic.values()))
            e += (X[:, idx[:, 0]] * X[:, idx[:, 1]]) @ val
        return e

    def all_energies(self) -> np.ndarray:
        if self.n > 26:
            raise ValueError(f"refusing to enumerate 2^{self.n} states")
        neighbours: list[list[tuple[int, float]]] = [[] for _ in range(self.n)]
        for (i, j), v in self.quadratic.items():
            neighbours[j].append((i, v))
        energies = np.array([self.offset])
        for q in range(self.n):
            idx = np.arange(energies.size)
            delta = np.full(energies.size, self.linear[q])
            for i, v in neighbours[q]:
                delta += v * ((idx >> i) & 1)
            energies = np.concatenate([energies, energies + delta])
        return energies

    def to_upper_matrix(self) -> np.ndarray:
        Q = np.diag(self.linear.copy())
        for (i, j), v in self.quadratic.items():
            Q[i, j] += v
        return Q

    def to_bqm(self):
        import dimod

        return dimod.BinaryQuadraticModel(
            {i: float(v) for i, v in enumerate(self.linear)},
            {k: float(v) for k, v in self.quadratic.items()},
            float(self.offset),
            dimod.BINARY,
        )

    def to_ising(self) -> tuple[np.ndarray, dict[tuple[int, int], float], float]:
        h = np.zeros(self.n)
        J: dict[tuple[int, int], float] = {}
        c = self.offset
        for i, a in enumerate(self.linear):
            c += a / 2
            h[i] -= a / 2
        for (i, j), v in self.quadratic.items():
            c += v / 4
            h[i] -= v / 4
            h[j] -= v / 4
            J[i, j] = J.get((i, j), 0.0) + v / 4
        return h, J, c

    @property
    def num_interactions(self) -> int:
        return sum(1 for v in self.quadratic.values() if v != 0)

    def coefficient_stats(self) -> dict:
        coeffs = np.concatenate([self.linear, np.array(list(self.quadratic.values()) or [0.0])])
        nz = np.abs(coeffs[coeffs != 0])
        return {
            "max_abs": float(nz.max()) if nz.size else 0.0,
            "min_abs": float(nz.min()) if nz.size else 0.0,
            "dynamic_range": float(nz.max() / nz.min()) if nz.size else 0.0,
        }

    def __repr__(self) -> str:
        return f"QUBO(n={self.n}, interactions={self.num_interactions})"

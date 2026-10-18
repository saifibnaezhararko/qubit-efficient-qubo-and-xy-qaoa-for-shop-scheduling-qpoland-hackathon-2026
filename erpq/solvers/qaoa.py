from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize


@dataclass
class QAOAResult:
    p: int
    gammas: np.ndarray
    betas: np.ndarray
    expectation: float
    objective_value: float
    probabilities: np.ndarray
    p_ground: float
    p_feasible: float | None
    history: list[dict] = field(default_factory=list)
    wall_time: float = 0.0
    evaluations: int = 0


class _QAOABase:
    exact_gradient = True

    def __init__(self, energies: np.ndarray, scale: float | None = None, feasible: np.ndarray | None = None):
        self.energies = np.asarray(energies, dtype=float).ravel()
        self.shape = np.shape(energies)
        self.scale = scale or max(1e-12, float(np.max(np.abs(self.energies - self.energies.mean()))))
        self.cost = (self.energies / self.scale).reshape(self.shape)
        self.feasible = None if feasible is None else np.asarray(feasible, dtype=bool).ravel()
        self.e_min = float(self.energies.min())
        self.ground = np.isclose(self.energies, self.e_min, atol=1e-9)
        self._order = np.argsort(self.cost.ravel(), kind="stable")
        self.evaluations = 0

    def initial_state(self) -> np.ndarray:
        raise NotImplementedError

    def apply_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        raise NotImplementedError

    def mixer_generator(self, psi: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def evolve(self, gammas, betas) -> np.ndarray:
        psi = self.initial_state()
        for g, b in zip(gammas, betas):
            psi = psi * np.exp(-1j * g * self.cost)
            psi = self.apply_mixer(psi, b)
        return psi

    def probabilities(self, gammas, betas) -> np.ndarray:
        psi = self.evolve(np.asarray(gammas, float), np.asarray(betas, float))
        return np.abs(psi.ravel()) ** 2

    def _loss_weights(self, probs: np.ndarray, cvar: float) -> tuple[float, np.ndarray]:
        c = self.cost.ravel()
        if cvar >= 1.0:
            return float(probs @ c), c
        order = self._order
        pr = probs[order]
        cum = np.cumsum(pr)
        k = min(int(np.searchsorted(cum, cvar)), len(pr) - 1)
        partial = pr[:k] @ c[order[:k]]
        rest = cvar - (cum[k - 1] if k else 0.0)
        loss = float((partial + rest * c[order[k]]) / cvar)
        w = np.zeros_like(c)
        w[order[:k]] = (c[order[:k]] - c[order[k]]) / cvar
        return loss, w

    def loss_and_grad(self, theta: np.ndarray, p: int, cvar: float):
        self.evaluations += 1
        g, b = theta[:p], theta[p:]
        psi = self.evolve(g, b)
        probs = np.abs(psi.ravel()) ** 2
        loss, w = self._loss_weights(probs, cvar)
        lam = w.reshape(self.shape) * psi
        grad = np.zeros(2 * p)
        for l in reversed(range(p)):
            grad[p + l] = 2 * np.real(np.vdot(lam, -1j * self.mixer_generator(psi)))
            psi = self.apply_mixer(psi, -b[l])
            lam = self.apply_mixer(lam, -b[l])
            grad[l] = 2 * np.real(np.vdot(lam, -1j * self.cost * psi))
            phase = np.exp(1j * g[l] * self.cost)
            psi, lam = psi * phase, lam * phase
        return loss, grad

    def loss(self, theta: np.ndarray, p: int, cvar: float) -> float:
        self.evaluations += 1
        probs = self.probabilities(theta[:p], theta[p:])
        return self._loss_weights(probs, cvar)[0]

    def optimize(
        self,
        p_max: int = 3,
        restarts: int = 8,
        cvar: float = 1.0,
        seed: int = 0,
        maxiter: int = 200,
        verbose: bool = False,
        init: np.ndarray | None = None,
    ) -> QAOAResult:
        rng = np.random.default_rng(seed)
        t0 = time.perf_counter()
        self.evaluations = 0
        history = []
        best = None
        fun = self.loss_and_grad if self.exact_gradient else self.loss
        jac = True if self.exact_gradient else None
        layers = [p_max] if init is not None else range(1, p_max + 1)
        for p in layers:
            if init is not None:
                starts = [np.asarray(init, float)]
            elif p == 1:
                starts = [np.array([g, b]) for g in np.linspace(0.1, 1.5, 4) for b in np.linspace(0.1, 0.7, 3)]
                starts += [np.array([rng.uniform(0, 2), rng.uniform(0, np.pi / 2)]) for _ in range(restarts)]
                starts = sorted(starts, key=lambda th: self.loss(th, 1, cvar))[: max(3, restarts // 2)]
            else:
                starts = [np.concatenate([_interp(best[: p - 1]), _interp(best[p - 1 :])])]
                ramp = (np.arange(p) + 0.5) / p
                for dt in (0.5, 0.8):
                    starts.append(np.concatenate([ramp * dt * 2, (1 - ramp) * dt]))
                for _ in range(max(1, restarts // 4)):
                    starts.append(starts[0] + rng.normal(0, 0.05, 2 * p))
            best_val = np.inf
            for th0 in starts:
                res = minimize(fun, th0, args=(p, cvar), jac=jac, method="L-BFGS-B", options={"maxiter": maxiter})
                if res.fun < best_val:
                    best_val, best = float(res.fun), res.x
            probs = self.probabilities(best[:p], best[p:])
            row = {
                "p": p,
                "loss": best_val,
                "expectation": float(probs @ self.energies),
                "p_ground": float(probs[self.ground].sum()),
                "p_feasible": None if self.feasible is None else float(probs[self.feasible].sum()),
                "evaluations": self.evaluations,
                "seconds": time.perf_counter() - t0,
                "gammas": best[:p].tolist(),
                "betas": best[p:].tolist(),
            }
            history.append(row)
            if verbose:
                pf = "-" if row["p_feasible"] is None else f"{row['p_feasible']:.4f}"
                print(f"    p={p}: <E>={row['expectation']:.3f}  P(optimal)={row['p_ground']:.4f}  P(feasible)={pf}")
        p = len(best) // 2
        probs = self.probabilities(best[:p], best[p:])
        return QAOAResult(
            p=p,
            gammas=best[:p].copy(),
            betas=best[p:].copy(),
            expectation=float(probs @ self.energies),
            objective_value=history[-1]["loss"],
            probabilities=probs,
            p_ground=float(probs[self.ground].sum()),
            p_feasible=None if self.feasible is None else float(probs[self.feasible].sum()),
            history=history,
            wall_time=time.perf_counter() - t0,
            evaluations=self.evaluations,
        )

    def evaluate(self, gammas, betas) -> QAOAResult:
        t0 = time.perf_counter()
        gammas, betas = np.asarray(gammas, float), np.asarray(betas, float)
        probs = self.probabilities(gammas, betas)
        return QAOAResult(
            p=len(gammas), gammas=gammas, betas=betas, expectation=float(probs @ self.energies),
            objective_value=float(probs @ self.cost.ravel()), probabilities=probs,
            p_ground=float(probs[self.ground].sum()),
            p_feasible=None if self.feasible is None else float(probs[self.feasible].sum()),
            wall_time=time.perf_counter() - t0, evaluations=1,
        )

    @staticmethod
    def sample(probs: np.ndarray, shots: int, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        probs = np.clip(probs, 0, None)
        return rng.choice(probs.size, size=shots, p=probs / probs.sum())


def _interp(v: np.ndarray) -> np.ndarray:
    p = len(v)
    out = np.zeros(p + 1)
    for i in range(p + 1):
        left = v[i - 1] if i - 1 >= 0 else 0.0
        right = v[i] if i < p else 0.0
        out[i] = (i / p) * left + ((p - i) / p) * right
    return out


class XMixerQAOA(_QAOABase):
    def __init__(self, energies: np.ndarray, n_qubits: int, scale: float | None = None, feasible=None):
        super().__init__(np.asarray(energies).ravel(), scale, feasible)
        self.n = n_qubits
        assert self.energies.size == 2**n_qubits

    def initial_state(self) -> np.ndarray:
        return np.full(2**self.n, 2 ** (-self.n / 2), dtype=complex)

    def apply_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        psi = psi.copy()
        c, s = np.cos(beta), -1j * np.sin(beta)
        for q in range(self.n):
            v = psi.reshape(-1, 2, 2**q)
            a0, a1 = v[:, 0, :].copy(), v[:, 1, :].copy()
            v[:, 0, :] = c * a0 + s * a1
            v[:, 1, :] = s * a0 + c * a1
        return psi

    def mixer_generator(self, psi: np.ndarray) -> np.ndarray:
        out = np.zeros_like(psi)
        for q in range(self.n):
            v = psi.reshape(-1, 2, 2**q)
            o = out.reshape(-1, 2, 2**q)
            o[:, 0, :] += v[:, 1, :]
            o[:, 1, :] += v[:, 0, :]
        return out


class XYMixerQAOA(_QAOABase):
    def __init__(self, energy_tensor: np.ndarray, kinds: list[str], mixer: str = "ring", scale=None, feasible=None,
                 fuse_limit: int = 24):
        super().__init__(energy_tensor, scale, feasible)
        self.dims = energy_tensor.shape
        self.kinds = kinds
        self.mixer = mixer
        self.exact_gradient = mixer != "parity"
        self._gen: list[np.ndarray | None] = []
        self._factors: list[list[tuple[np.ndarray, np.ndarray]]] = []
        for d, kind in zip(self.dims, kinds):
            if kind == "bit":
                mats = [np.array([[0.0, 1.0], [1.0, 0.0]])]
            elif mixer == "parity":
                mats = _parity_matchings(d)
            else:
                mats = [_xy_adjacency(d, mixer)]
            mats = [A for A in mats if A.any()]
            self._factors.append([np.linalg.eigh(A) for A in mats])
            self._gen.append(sum(mats) if mats else None)
        self._groups: list[list[int]] = [[]]
        for axis, d in enumerate(self.dims):
            if self._groups[-1] and np.prod([self.dims[a] for a in self._groups[-1]]) * d > fuse_limit:
                self._groups.append([])
            self._groups[-1].append(axis)
        self._fused_dims = tuple(int(np.prod([self.dims[a] for a in g])) for g in self._groups)

    def initial_state(self) -> np.ndarray:
        return np.full(self.dims, 1 / np.sqrt(np.prod(self.dims, dtype=float)), dtype=complex)

    def _register_unitary(self, axis: int, beta: float) -> np.ndarray:
        U = np.eye(self.dims[axis], dtype=complex)
        for w, V in self._factors[axis]:
            U = ((V * np.exp(-1j * beta * w)) @ V.conj().T) @ U
        return U

    def _apply_fused(self, M: np.ndarray, psi: np.ndarray, k: int) -> np.ndarray:
        pre = int(np.prod(self._fused_dims[:k], dtype=np.int64))
        return (M @ psi.reshape(pre, self._fused_dims[k], -1)).reshape(self.dims)

    def apply_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        for k, group in enumerate(self._groups):
            U = np.ones((1, 1), dtype=complex)
            for axis in group:
                U = np.kron(U, self._register_unitary(axis, beta))
            psi = self._apply_fused(U, psi, k)
        return psi

    def mixer_generator(self, psi: np.ndarray) -> np.ndarray:
        out = np.zeros_like(psi)
        for k, group in enumerate(self._groups):
            dims = [self.dims[a] for a in group]
            Hf = np.zeros((self._fused_dims[k],) * 2, dtype=complex)
            for i, axis in enumerate(group):
                if self._gen[axis] is None:
                    continue
                term = np.ones((1, 1))
                for j, d in enumerate(dims):
                    term = np.kron(term, self._gen[axis] if j == i else np.eye(d))
                Hf += term
            out += self._apply_fused(Hf, psi, k)
        return out


def _xy_adjacency(d: int, mixer: str) -> np.ndarray:
    A = np.zeros((d, d))
    if d == 1:
        return A
    if mixer == "clique":
        A[:] = 1.0
        np.fill_diagonal(A, 0.0)
    elif mixer == "ring":
        for k in range(d):
            l = (k + 1) % d
            A[k, l] = A[l, k] = 1.0
    else:
        raise ValueError(mixer)
    return A


def _parity_matchings(d: int) -> list[np.ndarray]:
    if d < 2:
        return []
    edges = [(k, (k + 1) % d) for k in range(d if d > 2 else 1)]
    layers = [
        [e for e in edges if e[0] % 2 == 0 and e[1] != 0],
        [e for e in edges if e[0] % 2 == 1 and e[1] != 0],
        [e for e in edges if e[1] == 0 and d > 2],
    ]
    mats = []
    for layer in layers:
        A = np.zeros((d, d))
        for k, l in layer:
            A[k, l] = A[l, k] = 1.0
        mats.append(A)
    return mats

"""Pauli correlation encoding (PCE): a QUBO with m binary variables on n << m qubits.

Sciorilli et al., "Towards large-scale quantum optimization solvers with few qubits", arXiv:2401.09421.
Variable i is the sign of the expectation value of a Pauli string Pi_i on ONE n-qubit state,
x_i = (1 - sgn<Pi_i>) / 2 (the spin convention of `QUBO.to_ising`). The strings are the weight-2 and
weight-1 strings of the three commuting families Z..Z, X..X and Y..Y, 3 * (C(n, 2) + n) of them: 4 qubits
hold up to 30 variables, and one evaluation needs only 3 measurement settings.

The state comes from a hardware-efficient ansatz (RY, RZ on every qubit, then `layers` x (CNOT ring,
RY, RZ)), simulated exactly. Training minimises the paper's relaxed loss
    L = c + sum_i h_i t_i + sum_ij J_ij t_i t_j + beta * nu * (mean_i t_i^2)^2,   t_i = tanh(alpha <Pi_i>)
with exact parameter-shift gradients and L-BFGS-B. alpha = n^floor(k/2) = 4 (k = 2) and beta = 1/2 are
the paper's choices; nu = (sum |h| + sum |J|) / 2 stands in for its MaxCut bound. This is a variational
heuristic: nothing guarantees that a restart ends in a ground state, so every read-out is decoded and
validated by the caller, and results are reported per restart, raw and after the paper's single
bit-swap pass (classical post-processing).
"""

from __future__ import annotations

import itertools
import time

import numpy as np
from scipy.optimize import minimize

from ..qubo import QUBO
from .samplers import Samples

FAMILIES = "ZXY"
_H = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
# measurement-basis change per family: U^dag Z U = X (U = H) and = Y (U = H S^dag)
_BASIS = {"Z": np.eye(2), "X": _H, "Y": _H @ np.diag([1, -1j])}


def pauli_strings(n: int, m: int | None = None) -> list[tuple[str, tuple[int, ...]]]:
    """Weight-2 strings of the Z, X, Y families first, then the weight-1 strings; the first m are used."""
    out = [(f, s) for k in (2, 1) for f in FAMILIES for s in itertools.combinations(range(n), k)]
    if m is not None and m > len(out):
        raise ValueError(f"{n} qubits hold at most {len(out)} variables with weight <= 2 strings, need {m}")
    return out if m is None else out[:m]


def qiskit_label(n: int, string: tuple[str, tuple[int, ...]]) -> str:
    fam, sub = string
    return "".join(fam if q in sub else "I" for q in reversed(range(n)))


class PCE:
    def __init__(self, qubo: QUBO, n_qubits: int = 4, layers: int = 4, alpha: float = 4.0, beta: float = 0.5):
        self.qubo = qubo
        self.n, self.layers, self.alpha, self.beta = n_qubits, layers, alpha, beta
        self.strings = pauli_strings(n_qubits, qubo.n)
        self.num_params = (layers + 1) * n_qubits * 2
        h, J, c = qubo.to_ising()
        self.h, self.c = h, c
        self.J = np.zeros((qubo.n, qubo.n))
        for (i, j), v in J.items():
            self.J[i, j] += v
        self.Js = self.J + self.J.T
        self.nu = 0.5 * (np.abs(h).sum() + np.abs(self.J).sum())
        dim = 2**n_qubits
        idx = np.arange(dim)
        self._sign = 1 - 2 * ((idx[None, :] >> np.arange(n_qubits)[:, None]) & 1)     # (n, dim), qubit k = bit k
        self._cnots = [idx ^ (((idx >> a) & 1) << ((a + 1) % n_qubits)) for a in range(n_qubits)]
        self._rot = {}
        for f in FAMILIES:
            U = np.array([[1.0]])
            for _ in range(n_qubits):
                U = np.kron(U, _BASIS[f])
            self._rot[f] = U.T
        self._chi = {f: np.array([np.prod(self._sign[list(s)], axis=0) for g, s in self.strings if g == f])
                     for f in FAMILIES}
        self._order = np.argsort([FAMILIES.index(g) for g, _ in self.strings], kind="stable")
        self._inverse = np.argsort(self._order)

    def states(self, theta: np.ndarray) -> np.ndarray:
        """theta (B, num_params) -> state vectors (B, 2^n), little-endian like Qiskit."""
        B, n = theta.shape[0], self.n
        th = theta.reshape(B, self.layers + 1, n, 2)
        psi = np.zeros((B, 2**n), dtype=complex)
        psi[:, 0] = 1.0
        for layer in range(self.layers + 1):
            if layer:
                for perm in self._cnots:
                    psi = psi[:, perm]
            for k in range(n):
                t = psi.reshape(B, 2 ** (n - 1 - k), 2, 2**k)
                c = np.cos(th[:, layer, k, 0] / 2)[:, None, None]
                s = np.sin(th[:, layer, k, 0] / 2)[:, None, None]
                psi = np.stack([c * t[:, :, 0] - s * t[:, :, 1], s * t[:, :, 0] + c * t[:, :, 1]], axis=2)
                psi = psi.reshape(B, -1) * np.exp(-0.5j * th[:, layer, k, 1][:, None] * self._sign[k][None, :])
        return psi

    def setting_probabilities(self, theta: np.ndarray) -> dict[str, np.ndarray]:
        """Outcome probabilities of the 3 measurement settings, (B, 2^n) each."""
        psi = self.states(np.atleast_2d(theta))
        return {f: np.abs(psi @ self._rot[f]) ** 2 for f in FAMILIES}

    def correlators(self, theta: np.ndarray) -> np.ndarray:
        """<Pi_i> for every variable, (B, m)."""
        p = self.setting_probabilities(theta)
        return np.concatenate([p[f] @ self._chi[f].T for f in FAMILIES], axis=1)[:, self._inverse]

    def loss_grad(self, theta: np.ndarray) -> tuple[float, np.ndarray]:
        P = self.num_params
        E = self.correlators(np.vstack([theta, theta + np.pi / 2 * np.eye(P), theta - np.pi / 2 * np.eye(P)]))
        e0, dE = E[0], (E[1:P + 1] - E[P + 1:]) / 2                                  # parameter-shift rule
        t = np.tanh(self.alpha * e0)
        mean_sq = float(np.mean(t**2))
        loss = self.c + self.h @ t + t @ self.J @ t + self.beta * self.nu * mean_sq**2
        dt = self.h + self.Js @ t + 4 * self.beta * self.nu * mean_sq * t / len(t)
        return float(loss), dE @ (dt * self.alpha * (1 - t**2))

    @staticmethod
    def bits(corr: np.ndarray) -> np.ndarray:
        return (corr < 0).astype(np.int8)

    def shot_readout(self, theta: np.ndarray, shots: int, rng: np.random.Generator) -> np.ndarray:
        """Correlators estimated from `shots` samples in each of the 3 measurement settings."""
        est = []
        for f, p in self.setting_probabilities(theta).items():
            counts = np.bincount(rng.choice(p.shape[1], size=shots, p=p[0] / p[0].sum()), minlength=p.shape[1])
            est.append(self._chi[f] @ counts / shots)
        return np.concatenate(est)[self._inverse]


def bitswap(q: QUBO, x: np.ndarray) -> np.ndarray:
    """The paper's post-processing: one pass that flips each bit in turn and keeps it if the energy drops."""
    x = np.array(x, dtype=np.int8)
    e = q.energy(x)
    for i in range(q.n):
        x[i] ^= 1
        e2 = q.energy(x)
        if e2 < e - 1e-12:
            e = e2
        else:
            x[i] ^= 1
    return x


def pce_solve(q: QUBO, n_qubits: int = 4, layers: int = 4, alpha: float = 4.0, beta: float = 0.5,
              restarts: int = 100, seed: int = 7, maxiter: int = 2000) -> tuple[Samples, Samples, PCE]:
    """Independent random restarts; returns the raw read-outs, the bit-swapped read-outs and the model.

    `info["thetas"]` keeps the trained angles of every restart (row k belongs to read-out k).
    """
    pce = PCE(q, n_qubits, layers, alpha, beta)
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    raw, swapped, losses, margins, thetas, evals = [], [], [], [], [], 0
    for _ in range(restarts):
        res = minimize(pce.loss_grad, rng.uniform(0, 2 * np.pi, pce.num_params), jac=True, method="L-BFGS-B",
                       options={"maxiter": maxiter})
        corr = pce.correlators(res.x)[0]
        x = pce.bits(corr)
        raw.append(x)
        swapped.append(bitswap(q, x))
        losses.append(float(res.fun))
        margins.append(float(np.abs(corr).min()))
        thetas.append(res.x)
        evals += int(res.nfev)
    wall = time.perf_counter() - t0
    info = {"n_qubits": n_qubits, "variables": q.n, "layers": layers, "parameters": pce.num_params, "alpha": alpha,
            "beta": beta, "nu": pce.nu, "restarts": restarts, "seed": seed, "loss_evaluations": evals,
            "losses": losses, "min_abs_correlator": margins, "thetas": np.array(thetas)}
    raw_s = np.array(raw, dtype=np.int8)
    sw_s = np.array(swapped, dtype=np.int8)
    return (Samples("pce", raw_s, q.energies(raw_s), wall, info),
            Samples("pce+bitswap", sw_s, q.energies(sw_s), wall, {"post_processing": "one bit-swap pass"}), pce)


def relaxation_control(q: QUBO, alpha: float = 4.0, beta: float = 0.5, restarts: int = 100, seed: int = 7) -> Samples:
    """Classical control: the same relaxed loss over m free parameters (t_i = tanh(alpha z_i)), no quantum state."""
    pce = PCE(q, 4, 0, alpha, beta)
    rng = np.random.default_rng(seed)

    def loss_grad(z):
        t = np.tanh(alpha * z)
        mean_sq = float(np.mean(t**2))
        loss = pce.c + pce.h @ t + t @ pce.J @ t + beta * pce.nu * mean_sq**2
        dt = pce.h + pce.Js @ t + 4 * beta * pce.nu * mean_sq * t / len(t)
        return float(loss), dt * alpha * (1 - t**2)

    t0 = time.perf_counter()
    out = []
    for _ in range(restarts):
        res = minimize(loss_grad, rng.uniform(-1, 1, q.n), jac=True, method="L-BFGS-B", options={"maxiter": 2000})
        out.append((res.x < 0).astype(np.int8))
    states = np.array(out, dtype=np.int8)
    return Samples("relaxation (no quantum state)", states, q.energies(states), time.perf_counter() - t0, {})

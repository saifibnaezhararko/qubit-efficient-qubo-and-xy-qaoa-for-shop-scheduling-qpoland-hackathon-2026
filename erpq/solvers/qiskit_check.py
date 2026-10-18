from __future__ import annotations

import numpy as np

from ..qubo import QUBO


def _cost_layer(qc, qubo: QUBO, gamma: float) -> None:
    h, J, _ = qubo.to_ising()
    for i, hi in enumerate(h):
        if hi:
            qc.rz(2 * gamma * hi, i)
    for (i, j), v in J.items():
        if v:
            qc.rzz(2 * gamma * v, i, j)


def x_qaoa_circuit(qubo: QUBO, gammas, betas, scale: float):
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(qubo.n)
    qc.h(range(qubo.n))
    for g, b in zip(gammas, betas):
        _cost_layer(qc, qubo, g / scale)
        for q in range(qubo.n):
            qc.rx(2 * b, q)
    return qc


def xy_qaoa_circuit(form, gammas, betas, scale: float):
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import StatePreparation, XXPlusYYGate

    from .qaoa import _parity_matchings

    n = form.qubo.n
    qc = QuantumCircuit(n)
    for reg in form.registers:
        if reg.kind == "onehot":
            d = len(reg.vars)
            w = np.zeros(2**d)
            w[[1 << k for k in range(d)]] = 1 / np.sqrt(d)
            qc.append(StatePreparation(w), reg.vars)
        else:
            qc.h(reg.vars[0])
    for g, b in zip(gammas, betas):
        _cost_layer(qc, form.qubo, g / scale)
        for reg in form.registers:
            if reg.kind == "bit":
                qc.rx(2 * b, reg.vars[0])
                continue
            for A in _parity_matchings(len(reg.vars)):
                for k, l in zip(*np.nonzero(np.triu(A))):
                    qc.append(XXPlusYYGate(2 * b), [reg.vars[k], reg.vars[l]])
    return qc


def statevector_probabilities(qc) -> np.ndarray:
    from qiskit.quantum_info import Statevector

    return Statevector.from_instruction(qc).probabilities()


def compare_x_qaoa(qubo: QUBO, gammas, betas, scale: float, probs_numpy: np.ndarray) -> float:
    p = statevector_probabilities(x_qaoa_circuit(qubo, gammas, betas, scale))
    return float(np.max(np.abs(p - probs_numpy)))


def pce_circuit(pce, theta):
    from qiskit import QuantumCircuit

    n = pce.n
    th = np.asarray(theta).reshape(pce.layers + 1, n, 2)
    qc = QuantumCircuit(n)
    for layer in range(pce.layers + 1):
        if layer:
            for a in range(n):
                qc.cx(a, (a + 1) % n)
        for k in range(n):
            qc.ry(th[layer, k, 0], k)
            qc.rz(th[layer, k, 1], k)
    return qc


def compare_pce(pce, theta) -> float:
    """Max |<Pi_i>_numpy - <Pi_i>_qiskit| over all encoded variables, gate-level circuit."""
    from qiskit.quantum_info import SparsePauliOp, Statevector

    from .pce import qiskit_label

    sv = Statevector.from_instruction(pce_circuit(pce, theta))
    ref = np.array([sv.expectation_value(SparsePauliOp(qiskit_label(pce.n, s))).real for s in pce.strings])
    return float(np.max(np.abs(ref - pce.correlators(theta)[0])))


def compare_xy_qaoa(form, gammas, betas, scale: float, probs_subspace: np.ndarray) -> float:
    p_full = statevector_probabilities(xy_qaoa_circuit(form, gammas, betas, scale))
    dims = [r.dim for r in form.registers]
    embedded = np.zeros_like(p_full)
    for flat, multi in enumerate(np.ndindex(*dims)):
        x = form.subspace_to_bits(multi)
        embedded[int((x << np.arange(len(x))).sum())] += probs_subspace[flat]
    return float(np.max(np.abs(p_full - embedded)))

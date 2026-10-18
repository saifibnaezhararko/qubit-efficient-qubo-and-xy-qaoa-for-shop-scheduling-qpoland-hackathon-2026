from pathlib import Path

import numpy as np
import pytest

from erpq.domainwall import to_domain_wall
from erpq.model import Instance
from erpq.solvers.pce import PCE, pauli_strings, pce_solve
from erpq.timeindexed import build_time_indexed_qubo

ROOT = Path(__file__).resolve().parents[1]
_PAULI = {"I": np.eye(2), "X": np.array([[0, 1], [1, 0]]), "Y": np.array([[0, -1j], [1j, 0]]),
          "Z": np.diag([1.0, -1.0])}


def _instance_b_domain_wall():
    inst = Instance.load(ROOT / "instances/instance_3x3.json")
    return to_domain_wall(build_time_indexed_qubo(inst, 8, "sac"))


def test_correlators_match_dense_pauli_matrices():
    dw = _instance_b_domain_wall()
    pce = PCE(dw.qubo)
    assert pce.n == 4 and len(pce.strings) == dw.qubo.n == 24 and len(pauli_strings(4)) == 30
    theta = np.random.default_rng(0).uniform(0, 2 * np.pi, pce.num_params)
    psi = pce.states(theta[None, :])[0]
    for (fam, sub), value in zip(pce.strings, pce.correlators(theta)[0]):
        op = np.array([[1.0]])
        for q in reversed(range(pce.n)):          # little endian: qubit 0 is the last Kronecker factor
            op = np.kron(op, _PAULI[fam if q in sub else "I"])
        assert value == pytest.approx(float(np.real(psi.conj() @ op @ psi)), abs=1e-12)


def test_parameter_shift_gradient_matches_finite_differences():
    pce = PCE(_instance_b_domain_wall().qubo)
    theta = np.random.default_rng(1).uniform(0, 2 * np.pi, pce.num_params)
    _, grad = pce.loss_grad(theta)
    eps = 1e-6
    for k in range(0, pce.num_params, 7):
        d = np.zeros(pce.num_params)
        d[k] = eps
        num = (pce.loss_grad(theta + d)[0] - pce.loss_grad(theta - d)[0]) / (2 * eps)
        assert grad[k] == pytest.approx(num, abs=1e-5)


def test_instance_b_on_four_qubits_finds_an_optimal_schedule():
    dw = _instance_b_domain_wall()
    raw, swapped, pce = pce_solve(dw.qubo, restarts=16, seed=7)
    assert pce.n == 4 and raw.states.shape == (16, 24)
    makespans = []
    for x in raw.states:
        sched, _ = dw.decode(x)
        if sched is not None and not sched.violations():
            makespans.append(sched.makespan)
    assert makespans and min(makespans) == 8
    assert np.all(dw.qubo.energies(swapped.states) <= dw.qubo.energies(raw.states) + 1e-12)

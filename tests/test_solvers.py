from pathlib import Path

import numpy as np

from erpq.model import Instance
from erpq.pipeline import ising_scale, run_qaoa_x, run_qaoa_xy
from erpq.solvers.qaoa import XMixerQAOA, XYMixerQAOA
from erpq.solvers.qiskit_check import compare_x_qaoa, compare_xy_qaoa
from erpq.solvers.samplers import _from_sampleset, simulated_annealing
from erpq.pipeline import report_samples
from erpq.timeindexed import build_time_indexed_qubo

ROOT = Path(__file__).resolve().parents[1]
A = Instance.load(ROOT / "instances/instance_2x2.json")


def _fd(qa, th, p, cvar):
    return np.array([(qa.loss(th + 1e-6 * e, p, cvar) - qa.loss(th - 1e-6 * e, p, cvar)) / 2e-6 for e in np.eye(2 * p)])


def test_adjoint_gradients():
    m = build_time_indexed_qubo(A, 5, "window")
    rng = np.random.default_rng(0)
    qa = XMixerQAOA(m.qubo.all_energies(), m.qubo.n, scale=ising_scale(m))
    for cvar in (1.0, 0.3):
        th = rng.uniform(0, 1, 4)
        assert np.allclose(qa.loss_and_grad(th, 2, cvar)[1], _fd(qa, th, 2, cvar), atol=1e-6)
    xy = XYMixerQAOA(m.register_energy_tensor(), [r.kind for r in m.registers], "ring", scale=ising_scale(m))
    th = rng.uniform(0, 1, 4)
    assert np.allclose(xy.loss_and_grad(th, 2, 1.0)[1], _fd(xy, th, 2, 1.0), atol=1e-6)


def test_simulators_match_qiskit_circuits():
    m = build_time_indexed_qubo(A, 5, "window")
    g, b = np.array([0.4, 0.9]), np.array([0.3, 0.2])
    sc = ising_scale(m)
    qa = XMixerQAOA(m.qubo.all_energies(), m.qubo.n, scale=sc)
    assert compare_x_qaoa(m.qubo, g, b, sc, qa.probabilities(g, b)) < 1e-10
    mt = build_time_indexed_qubo(A, 5, "window", makespan_encoding="thermometer")
    sc = ising_scale(mt)
    xy = XYMixerQAOA(mt.register_energy_tensor(), [r.kind for r in mt.registers], "parity", scale=sc)
    assert compare_xy_qaoa(mt, g, b, sc, xy.probabilities(g, b)) < 1e-10


def test_xy_mixer_stays_in_subspace_and_qaoa_finds_optimum():
    m = build_time_indexed_qubo(A, 5, "window")
    res, rep = run_qaoa_xy(m, p=2, shots=512, seed=0, reference=4, restarts=2)
    assert abs(res.probabilities.sum() - 1) < 1e-9
    assert rep.best.makespan == 4 and rep.best.feasible
    res, rep = run_qaoa_x(m, p=2, shots=2048, seed=0, reference=4, restarts=2)
    assert rep.best.makespan == 4
    assert res.p_ground > 1 / 4096


def test_simulated_annealing_on_3x3():
    m = build_time_indexed_qubo(Instance.load(ROOT / "instances/instance_3x3.json"), 8, "sac")
    rep = report_samples(m, simulated_annealing(m.qubo, num_reads=50, seed=0), 8)
    assert rep.best.makespan == 8 and rep.optimal_fraction > 0.5


def test_sampleset_maps_back_by_label_and_from_spins():
    import dimod

    n = 7
    x = np.random.default_rng(0).integers(0, 2, (5, n), dtype=np.int8)
    order = np.random.default_rng(1).permutation(n)
    for vartype, vals in ((dimod.BINARY, x), (dimod.SPIN, 2 * x.astype(int) - 1)):
        ss = dimod.SampleSet.from_samples((vals[:, order], [str(i) for i in order]), vartype, energy=np.zeros(len(x)))
        assert np.array_equal(_from_sampleset("test", ss, n, 0.0).states, x)

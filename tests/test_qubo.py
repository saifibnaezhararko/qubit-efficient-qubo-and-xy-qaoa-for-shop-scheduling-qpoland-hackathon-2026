import itertools
from pathlib import Path

import numpy as np
import pytest

from erpq.classical import solve_cpsat
from erpq.domainwall import to_domain_wall
from erpq.experiments import shift_horizon
from erpq.generator import random_instance
from erpq.heuristics import fifo_schedule
from erpq.model import Instance
from erpq.qubo import QUBO
from erpq.solvers.samplers import exhaustive
from erpq.timeindexed import InfeasibleHorizon, build_time_indexed_qubo, compute_domains

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "instances/instance_2x2.json"
B = ROOT / "instances/instance_3x3.json"


def test_qubo_energy_paths_agree():
    rng = np.random.default_rng(0)
    q = QUBO([str(i) for i in range(7)])
    q.linear = rng.normal(size=7)
    for i, j in itertools.combinations(range(7), 2):
        if rng.random() < 0.5:
            q.add_quadratic(i, j, rng.normal())
    q.offset = 1.5
    E = q.all_energies()
    X = ((np.arange(128)[:, None] >> np.arange(7)) & 1)
    assert np.allclose(E, q.energies(X))
    assert np.allclose(E[:5], [q.energy(x) for x in X[:5]])
    h, J, c = q.to_ising()
    Z = 1 - 2 * X
    ising = c + Z @ h + sum(v * Z[:, i] * Z[:, j] for (i, j), v in J.items())
    assert np.allclose(E, ising)


def test_reference_variable_counts():
    inst = Instance.load(B)
    assert build_time_indexed_qubo(inst, 8, "none").qubo.n == 72
    assert build_time_indexed_qubo(inst, 8, "window").qubo.n == 39
    assert build_time_indexed_qubo(inst, 8, "sac").qubo.n == 33
    assert to_domain_wall(build_time_indexed_qubo(inst, 8, "sac")).num_qubits == 24


@pytest.mark.parametrize("level", ["none", "horizon", "window", "ac3", "sac"])
def test_ground_states_are_optimal_2x2(level):
    inst = Instance.load(A)
    m = build_time_indexed_qubo(inst, 5, level)
    if m.qubo.n > 22:
        pytest.skip("too many qubits for brute force")
    ex = exhaustive(m.qubo)
    for s in ex.states:
        sched, _ = m.decode(s)
        assert sched is not None and sched.feasible and sched.makespan == 4


def test_pruning_keeps_every_feasible_schedule():
    inst = Instance.load(B)
    win = build_time_indexed_qubo(inst, 8, "window")
    sac = build_time_indexed_qubo(inst, 8, "sac")
    Tw = win.register_energy_tensor(win.constraint_qubo)
    feas_w = set()
    for i in np.flatnonzero(np.isclose(Tw.ravel(), 0)):
        s, _ = win.decode(win.subspace_to_bits(np.unravel_index(i, Tw.shape)))
        feas_w.add(tuple(sorted((e.job, e.index, e.start) for e in s.entries)))
    Ts = sac.register_energy_tensor(sac.constraint_qubo)
    feas_s = set()
    for i in np.flatnonzero(np.isclose(Ts.ravel(), 0)):
        s, _ = sac.decode(sac.subspace_to_bits(np.unravel_index(i, Ts.shape)))
        feas_s.add(tuple(sorted((e.job, e.index, e.start) for e in s.entries)))
    assert feas_w == feas_s and len(feas_w) == 13


def test_encode_decode_roundtrip_and_energy():
    inst = Instance.load(B)
    m = build_time_indexed_qubo(inst, 8, "window")
    s = fifo_schedule(inst)
    x = m.encode(s)
    back, _ = m.decode(x)
    assert sorted((e.job, e.index, e.start) for e in back.entries) == sorted((e.job, e.index, e.start) for e in s.entries)
    assert m.qubo.energy(x) == 0
    assert m.constraint_qubo.energy(x) == 0


@pytest.mark.parametrize("n_jobs,seed", [(2, s) for s in range(6)] + [(3, s) for s in (1, 2, 4, 5)])
def test_random_extended_instances_exact(n_jobs, seed):
    feats = [("due_dates", "setups"), ("outage", "routes"), ("release", "due_dates"), ("parallel",),
             ("setups", "outage"), ("due_dates", "routes", "release")][seed]
    inst = random_instance(n_jobs, seed=seed, features=feats, durations=(1, 2))
    H = shift_horizon(inst, solve_cpsat)
    m = build_time_indexed_qubo(inst, H, "sac")
    assert m.subspace_dim <= 5_000_000
    T = m.register_energy_tensor()
    best = None
    for i in np.flatnonzero(np.isclose(T.ravel(), T.min())):
        s, _ = m.decode(m.subspace_to_bits(np.unravel_index(i, T.shape)))
        assert s is not None and s.feasible, s.violations()
        best = s.objective() if best is None else best
        assert s.objective() == best
    assert best == pytest.approx(solve_cpsat(inst, horizon=H).objective)


def test_domain_wall_preserves_energies_of_valid_states():
    inst = Instance.load(A)
    m = build_time_indexed_qubo(inst, 5, "window")
    dw = to_domain_wall(m)
    T = m.register_energy_tensor()
    for multi in np.ndindex(*T.shape):
        x = m.subspace_to_bits(multi)
        s = dw.from_onehot(x)
        assert np.array_equal(dw.to_onehot(s), x)
        assert dw.qubo.energy(s) == pytest.approx(T[multi])
    ex = exhaustive(dw.qubo)
    assert all(dw.decode(s)[0].makespan == 4 for s in ex.states)


def test_infeasible_horizon_detected():
    inst = Instance.load(B)
    assert compute_domains(inst, 7, "window") is not None
    assert compute_domains(inst, 7, "sac") is None
    with pytest.raises(InfeasibleHorizon):
        build_time_indexed_qubo(inst, 7, "sac")


def test_bad_arguments_are_not_mistaken_for_infeasibility():
    from erpq.experiments import exact_qubo_solve
    from erpq.horizon import horizon_ascent

    inst = Instance.load(ROOT / "instances/extension/metaltech_monday.json")
    with pytest.raises(ValueError) as exc:
        horizon_ascent(inst, exact_qubo_solve, pruning="SAC")
    assert not isinstance(exc.value, InfeasibleHorizon)
    with pytest.raises(ValueError):
        build_time_indexed_qubo(inst, 9, "sac", makespan_encoding="exp")


@pytest.mark.parametrize("seed,feats", [(10, ("outage", "release")), (12, ("release", "routes"))])
@pytest.mark.parametrize("level", ["none", "horizon"])
def test_unpruned_levels_exact_with_unary_constraints(seed, feats, level):
    inst = random_instance(2, seed=seed, features=feats, durations=(1, 2))
    H = solve_cpsat(inst).schedule.makespan + 1
    ref = solve_cpsat(inst, horizon=H).objective
    m = build_time_indexed_qubo(inst, H, level)
    assert m.qubo.term_kinds["unary"] > 0
    T = m.register_energy_tensor()
    for i in np.flatnonzero(np.isclose(T.ravel(), T.min())):
        s, _ = m.decode(m.subspace_to_bits(np.unravel_index(i, T.shape)))
        assert s.feasible, s.violations()
        assert s.objective() == pytest.approx(ref)


def test_outage_violation_is_penalised_in_naive_qubo():
    inst = Instance.load(ROOT / "instances/extension/metaltech_monday.json")
    d = inst.to_dict()
    d.pop("unavailability")
    s = solve_cpsat(Instance.from_dict(d), horizon=9).schedule
    s.instance = inst
    assert s.violations()
    for level in ("none", "horizon"):
        m = build_time_indexed_qubo(inst, 9, level)
        assert m.constraint_qubo.energy(m.encode(s)) > 0

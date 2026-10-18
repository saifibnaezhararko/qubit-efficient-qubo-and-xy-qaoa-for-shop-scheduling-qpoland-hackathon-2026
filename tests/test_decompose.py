import numpy as np

from erpq.classical import solve_cpsat
from erpq.decompose import lns, merge_plan, neighbourhood_instance, sa_batch, stack_qubos
from erpq.experiments import exact_qubo_solve, shift_horizon
from erpq.generator import random_instance
from erpq.pipeline import report_samples
from erpq.solvers import samplers
from erpq.timeindexed import build_time_indexed_qubo

FEATS = ("due_dates", "setups", "routes", "outage")


def test_stacked_qubo_is_the_sum_of_its_blocks():
    inst = random_instance(3, seed=3000, features=FEATS)
    H = shift_horizon(inst, solve_cpsat)
    a = build_time_indexed_qubo(inst, H, "window").qubo
    b = build_time_indexed_qubo(inst, H + 1, "sac").qubo
    big, starts = stack_qubos([a, b])
    assert starts == [0, a.n] and big.n == a.n + b.n
    rng = np.random.default_rng(0)
    X = rng.integers(0, 2, size=(50, big.n))
    assert np.allclose(big.energies(X), a.energies(X[:, :a.n]) + b.energies(X[:, a.n:]))


def test_sub_qubo_objective_is_the_full_objective_up_to_a_constant():
    inst = random_instance(5, seed=5000, features=FEATS)
    H = shift_horizon(inst, solve_cpsat)
    cp = solve_cpsat(inst, horizon=H)
    plan = cp.schedule
    free = {inst.jobs[0].id, inst.jobs[2].id}
    sub = neighbourhood_instance(inst, plan, free)
    rep = exact_qubo_solve(build_time_indexed_qubo(sub, H, "sac"))
    merged = merge_plan(inst, plan, rep.best, free)
    assert not merged.violations()
    assert abs(merged.objective() - cp.objective) < 1e-9
    tard_fixed = sum(j.weight * max(0, plan.completion(j.id) - j.due_date) for j in inst.jobs if j.id not in free)
    assert abs(merged.objective() - (rep.best.objective() + inst.objective.tardiness * tard_fixed)) < 1e-9


def test_lns_stays_feasible_and_never_gets_worse():
    inst = random_instance(6, seed=6001, features=FEATS)
    H = shift_horizon(inst, solve_cpsat)
    ref = solve_cpsat(inst, horizon=H).objective
    full = build_time_indexed_qubo(inst, H, "sac")
    start = report_samples(full, samplers.simulated_annealing(full.qubo, num_reads=50, num_sweeps=500, seed=0)).best
    assert start is not None
    plan, steps = lns(inst, H, start, sa_batch(num_reads=30, num_sweeps=300), k=3, iterations=4, batch=2, seed=0)
    assert not plan.violations() and plan.makespan <= H
    objs = [start.objective()] + [s.objective for s in steps]
    assert all(b <= a + 1e-9 for a, b in zip(objs, objs[1:]))
    assert ref - 1e-9 <= plan.objective() <= start.objective() + 1e-9

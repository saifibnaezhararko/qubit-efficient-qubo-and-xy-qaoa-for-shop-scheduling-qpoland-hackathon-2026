from pathlib import Path

from erpq.classical import solve_cpsat
from erpq.experiments import exact_or_sa_solve, exact_qubo_solve
from erpq.horizon import horizon_ascent
from erpq.model import Instance
from erpq.rolling import merge, residual_instance, right_shift_repair

ROOT = Path(__file__).resolve().parents[1]
MONDAY = ROOT / "instances/extension/metaltech_monday.json"


def test_horizon_ascent_certifies_metaltech_monday():
    inst = Instance.load(MONDAY)
    asc = horizon_ascent(inst, exact_qubo_solve)
    assert asc.certified
    assert asc.horizon == 9 and asc.form.qubo.n == 35
    assert [s.status for s in asc.steps[:2]] == ["infeasible (propagation proof)"] * 2
    assert asc.best.best_objective == solve_cpsat(inst).objective == 21


def test_rolling_replan_is_feasible_and_never_worse_than_right_shift():
    inst = Instance.load(MONDAY)
    plan = horizon_ascent(inst, exact_qubo_solve).best.best
    for now, machine, dur in ((2, "F", 2), (3, "S", 1), (1, "T", 3)):
        res, imap = residual_instance(inst, plan, now, machine, dur)
        rs = right_shift_repair(res, plan, imap)
        assert rs.feasible, rs.violations()
        asc = horizon_ascent(res, exact_or_sa_solve)
        q = asc.best.best
        assert q.feasible, q.violations()
        cp = solve_cpsat(res)
        assert abs(q.objective() - cp.objective) < 1e-9
        assert q.objective() <= rs.objective() + 1e-9
        rows = merge(inst, plan, res, q, imap, now)
        assert len(rows) == len(inst.operations)

import json
from pathlib import Path

import pytest

from erpq.classical import solve_cpsat
from erpq.heuristics import brute_force_permutations, fifo_schedule, makespan_lower_bound
from erpq.model import Instance
from erpq.schedule import Entry, Schedule

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "instances/instance_2x2.json"
B = ROOT / "instances/instance_3x3.json"


def test_reference_makespans():
    for path, opt in ((A, 4), (B, 8)):
        inst = Instance.load(path)
        assert makespan_lower_bound(inst) == opt
        assert brute_force_permutations(inst).makespan == opt
        assert solve_cpsat(inst).objective == opt


def test_validator_catches_violations():
    inst = Instance.load(A)
    good = Schedule(inst, [Entry("Z2", 0, "T", 0, 1), Entry("Z2", 1, "F", 1, 3),
                           Entry("Z1", 0, "T", 1, 3), Entry("Z1", 1, "F", 3, 4)])
    assert good.feasible and good.makespan == 4
    overlap = Schedule(inst, [Entry("Z2", 0, "T", 0, 1), Entry("Z2", 1, "F", 1, 3),
                              Entry("Z1", 0, "T", 0, 2), Entry("Z1", 1, "F", 3, 4)])
    assert any("overlaps" in v for v in overlap.violations())
    order = Schedule(inst, [Entry("Z2", 0, "T", 0, 1), Entry("Z2", 1, "F", 0, 2),
                            Entry("Z1", 0, "T", 1, 3), Entry("Z1", 1, "F", 3, 4)])
    assert any("before" in v for v in order.violations())
    missing = Schedule(inst, good.entries[:3])
    assert not missing.feasible


def test_schedule_files_are_feasible_and_optimal():
    for inst_path, sched, opt in ((A, "schedule_2x2.json", 4), (B, "schedule_3x3.json", 8)):
        inst = Instance.load(inst_path)
        s = Schedule.load(inst, ROOT / sched)
        assert s.violations() == []
        assert s.makespan == opt
        for data in (json.loads((ROOT / sched).read_text()), s.to_json_dict(inst_path.stem)):
            assert set(data) == {"instance", "method", "makespan", "schedule"}
            assert all(set(r) == {"job", "machine", "start", "end"} for r in data["schedule"])
            assert all(isinstance(r[k], int) for r in data["schedule"] for k in ("start", "end"))
            assert data["makespan"] == max(r["end"] for r in data["schedule"])


def test_extended_features_respected_by_heuristic_and_cpsat():
    for p in sorted((ROOT / "instances/extension").glob("*.json")):
        inst = Instance.load(p)
        assert inst.check_setup_triangle() == []
        assert fifo_schedule(inst).feasible
        r = solve_cpsat(inst)
        assert r.schedule.feasible, r.schedule.violations()


def test_invalid_instances_rejected():
    with pytest.raises(ValueError):
        Instance.from_dict({"problem": "erp_scheduling", "jobs": [{"id": "Z1", "operations": [
            {"machine": "T", "duration": 0}]}]})
    with pytest.raises(ValueError):
        Instance.from_dict({"problem": "erp_scheduling", "objective": {"weighted_tardiness": 1},
                            "jobs": [{"id": "Z1", "operations": [{"machine": "T", "duration": 1}]}]})

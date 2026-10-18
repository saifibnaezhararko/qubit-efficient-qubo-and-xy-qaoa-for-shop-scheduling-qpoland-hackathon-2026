from pathlib import Path

import numpy as np
import pytest

from erpq.generator import random_instance
from erpq.heuristics import brute_force_permutations
from erpq.model import Instance
from erpq.permutation import PermutationQUBO

ROOT = Path(__file__).resolve().parents[1]


def _certify(form: PermutationQUBO, optimum: float) -> int:
    E = form.qubo.all_energies()
    n = form.qubo.n
    ground = np.flatnonzero(np.isclose(E, E.min()))
    for g in ground:
        sched, _ = form.decode((g >> np.arange(n)) & 1)
        assert sched is not None and not sched.violations()
        assert sched.objective() == pytest.approx(optimum)
    codes = np.arange(E.size) & ((1 << form.code_bits) - 1)
    mins = np.full(1 << form.code_bits, np.inf)
    np.minimum.at(mins, codes, E)
    assert np.allclose(mins, form.cost_table)
    return len(ground)


def test_instance_b_permutation_encoding():
    inst = Instance.load(ROOT / "instances/instance_3x3.json")
    form = PermutationQUBO(inst)
    assert form.qubo.n == 3 and not form.aux
    assert _certify(form, 8) == 4


@pytest.mark.parametrize("n_jobs,seeds", [(3, range(10)), (4, range(3))])
def test_random_flow_shops_exact(n_jobs, seeds):
    aux_used = 0
    for seed in seeds:
        inst = random_instance(n_jobs, seed, durations=(1, 4))
        form = PermutationQUBO(inst)
        if n_jobs == 3:
            assert form.qubo.n <= 4
        aux_used += len(form.aux)
        _certify(form, brute_force_permutations(inst).objective())
    assert aux_used > 0


def test_extended_instance_rejected():
    inst = Instance.load(ROOT / "instances/extension/metaltech_monday.json")
    with pytest.raises(ValueError):
        PermutationQUBO(inst)

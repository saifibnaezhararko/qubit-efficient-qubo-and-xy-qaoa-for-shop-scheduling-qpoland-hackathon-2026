# Part 7 - the baseline instances on 2 and 4 qubits: Pauli correlation encoding

The time-indexed QUBOs of both baseline instances (SAC-pruned at the baseline horizon, as behind `schedule_2x2.json` and `schedule_3x3.json`, then domain-wall encoded) are solved with Pauli correlation encoding (PCE; Sciorilli et al., arXiv:2401.09421) on the fewest qubits the encoding allows. Variable i is the sign of the expectation value of one Pauli string on a single n-qubit state, x_i = (1 - sgn<P_i>) / 2. The strings are the weight-2 and weight-1 strings of the Z..Z, X..X and Y..Y families, 3 x (C(n, 2) + n) of them, so one evaluation needs only 3 measurement settings. The QUBOs themselves are unchanged: no coefficient comes from brute force, and every read-out is decoded and checked by the validator.

The protocol is the same for both instances. Ansatz: RY, RZ on every qubit, then 4 x (CNOT ring, RY, RZ). Loss: the paper's tanh relaxation of the Ising energy plus its regulariser, with alpha = n (= n^floor(k/2), k = 2), beta = 0.5 and nu = (sum |h| + sum |J|) / 2 in place of the paper's MaxCut bound. L-BFGS-B with exact parameter-shift gradients, 100 independent random restarts (seed 7). Each QUBO is certified by enumerating all 2^m states.

| instance | horizon | QUBO variables | couplings | qubits | Pauli strings available | angles | alpha | nu | ground states | all ground states optimal | PCE time [s] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A (2x2) | 5 | 8 | 18 | **2** | 9 | 20 | 2 | 12 | 1 | True | 4 |
| B (3x3) | 8 | 24 | 87 | **4** | 30 | 40 | 4 | 45.125 | 13 | True | 100 |

## Instance A (2x2): 8 variables on 2 qubits

| method | qubits | runs | P(optimal) per run | P(feasible) | best makespan |
|---|---|---|---|---|---|
| PCE, raw read-out | 2 | 100 restarts | **0.000** | 0.730 | 5 |
| PCE + one bit-swap pass (classical post-processing) | 2 | 100 restarts | 0.000 | 0.730 | 5 |
| the same circuit at random angles (no training) | 2 | 100000 angle vectors | 1.2e-03 | 0.030 | 4 |
| control: same loss, 8 free parameters, no quantum state | - | 100 restarts | 0.130 | 0.990 | 4 |
| simulated annealing on the same QUBO | 8 | 100 reads | 0.880 | 1.000 | 4 |

A uniformly random 8-bit string is optimal with probability 3.9e-03 (1 optimal schedule).

No restart returns an optimal schedule: 73% of the read-outs are feasible, at best makespan 5, the rest infeasible. The bit-swap pass does not repair them. The optimal sign pattern is reachable on 2 qubits: the untrained circuit produces it for 0.12% of the random angle vectors. It is the training on the relaxed loss, not the encoding, that misses it.

Best read-out: restart 41, QUBO energy 1 (makespan 5, not optimal), the lowest of all restarts, with the largest margin among them, min |<P_i>| = 0.088. Qiskit gate-level circuit with the same angles: max |<P_i>_numpy - <P_i>_qiskit| = 5.8e-16. Estimating the 8 correlators from 4096 shots in each of the 3 settings gives the same bit string: True (makespan 5). The smallest margin is 5.6 shot-noise standard deviations at 4096 shots.

```
      01234
    T 2.11.
    F .22.1
```

## Instance B (3x3): 24 variables on 4 qubits

| method | qubits | runs | P(optimal) per run | P(feasible) | best makespan |
|---|---|---|---|---|---|
| PCE, raw read-out | 4 | 100 restarts | **0.190** | 0.190 | 8 |
| PCE + one bit-swap pass (classical post-processing) | 4 | 100 restarts | 0.440 | 0.440 | 8 |
| the same circuit at random angles (no training) | 4 | 100000 angle vectors | 0.000 | 0.000 | - |
| control: same loss, 24 free parameters, no quantum state | - | 100 restarts | 0.190 | 0.190 | 8 |
| simulated annealing on the same QUBO | 24 | 100 reads | 0.950 | 0.950 | 8 |

A uniformly random 24-bit string is optimal with probability 7.7e-07 (13 optimal schedules). Restarts needed for 99 % success at the raw rate: 22.

Read-out used for the schedule: restart 65, the optimal read-out (QUBO energy 0, the ground energy) with the largest margin, min |<P_i>| = 0.028. Qiskit gate-level circuit with the same angles: max |<P_i>_numpy - <P_i>_qiskit| = 5.0e-16. Estimating the 24 correlators from 4096 shots in each of the 3 settings gives the same bit string: True (makespan 8). The smallest margin is only 1.8 shot-noise standard deviations at 4096 shots, so a hardware run would need more shots for a reliable read-out.

```
      01234567
    T 11233...
    F ..12233.
    S ....1123
```

Caveats: PCE is a variational heuristic without a guarantee: the enumeration certifies the QUBOs, not the PCE runs. The qubits hold correlators, not independent bits, and their simulation is classical. The untrained and control rows show what the circuit achieves without training and what the same relaxation achieves without any quantum state.

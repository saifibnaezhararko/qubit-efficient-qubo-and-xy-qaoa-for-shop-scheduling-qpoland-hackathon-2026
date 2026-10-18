# Part 7 - instance B (3x3) on 4 qubits: Pauli correlation encoding

The certified 24-variable QUBO of instance B (H = 8, SAC + domain wall, 87 couplings, the model behind `schedule_3x3.json`) is solved on **4 qubits** with Pauli correlation encoding (PCE; Sciorilli et al., arXiv:2401.09421). Variable i is the sign of the expectation value of one Pauli string on a single 4-qubit state, x_i = (1 - sgn<P_i>) / 2. The strings are the weight-2 and weight-1 strings of the Z..Z, X..X and Y..Y families (3 x (6 + 4) = 30 >= 24), so one evaluation needs only 3 measurement settings. The QUBO itself is unchanged: no coefficient comes from brute force, and every read-out is decoded and checked by the validator.

Ansatz: RY, RZ on every qubit, then 4 x (CNOT ring, RY, RZ), 40 angles. Loss: the paper's tanh relaxation of the Ising energy plus its regulariser, alpha = 4 (= n^floor(k/2)), beta = 0.5, nu = 45.125; L-BFGS-B with exact parameter-shift gradients, 100 independent random restarts (seed 7), 90 s in total.

| method | qubits | runs | P(optimal) per run | P(feasible) | best makespan |
|---|---|---|---|---|---|
| PCE, raw read-out | 4 | 100 restarts | **0.190** | 0.190 | 8 |
| PCE + one bit-swap pass (classical post-processing) | 4 | 100 restarts | 0.440 | 0.440 | 8 |
| control: same loss, 24 free parameters, no quantum state | - | 100 restarts | 0.190 | 0.190 | 8 |
| simulated annealing on the same QUBO | 24 | 100 reads | 0.950 | 0.950 | 8 |

A uniformly random 24-bit string is optimal with probability 7.7e-07 (13 optimal schedules). Restarts needed for 99 % success at the raw rate: 22.

Read-out used for the schedule: restart 65, the optimal read-out (QUBO energy 0: feasible at the lower bound) with the largest margin, min |<P_i>| = 0.028. Qiskit gate-level circuit with the same angles: max |<P_i>_numpy - <P_i>_qiskit| = 5.0e-16. Estimating the 24 correlators from 4096 shots in each of the 3 settings gives the same bit string: True (makespan 8). The smallest margin is only 1.8 shot-noise standard deviations at 4096 shots, so a hardware run would need more shots for a reliable read-out.

```
      01234567
    T 11233...
    F ..12233.
    S ....1123
```

Caveats: PCE is a variational heuristic without a guarantee (the ground state is not certified by the 4-qubit run; certification stays with the 24-variable QUBO, see the baseline report). The 4 qubits hold correlators, not 24 independent bits, and their simulation is classical. The control row shows what the same relaxation achieves without any quantum state.

# Part 6 - VeloxQ at scale: the whole QUBO vs decomposition

Random extended instances (features: due_dates, setups, routes, outage; instance k=0 of each size from the generator of part 3), shift horizon (optimal makespan + 1 h), CP-SAT with the same horizon as the reference. Every read of every solver is decoded and checked by the validator.

## One call on the whole time-indexed QUBO (SAC, provable penalties)

| jobs | qubits | couplings | penalty | optimum | SA best (600 reads) | SA P(optimal) | VeloxQ best (1024 reads) | VeloxQ P(optimal) | VeloxQ P(feasible) | VeloxQ solver time [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 74 | 532 | 56 | 43 | 43 | 0.007 | 43 | 0.018 | 0.405 | 0.125 |
| 6 | 130 | 1344 | 38 | 24 | 24 | 0.015 | 24 | 0.001 | 0.140 | 0.126 |
| 8 | 272 | 4679 | 94 | 38 | 49 | 0.000 | 50 | 0.000 | 0.213 | 0.183 |
| 10 | 415 | 9208 | 125 | 54 | 63 | 0.000 | 66 | 0.000 | 0.057 | 0.499 |
| 12 | 726 | 24778 | 292 | 106 | 155 | 0.000 | 169 | 0.000 | 0.001 | 0.549 |

## VeloxQ settings on the whole QUBO (one call each, best plan found)

| jobs | optimum | default (1024 x 5000) | more steps (x4) | penalty x0.5 | penalty x0.25 | coefficients scaled to max 1 |
|---|---|---|---|---|---|---|
| 8 | 38 | 50 | 49 (feasible 0.249) | 48 (feasible 0.246) | 44 (feasible 0.168) | 50 (feasible 0.181) |
| 10 | 54 | 66 | 66 (feasible 0.175) | 64 (feasible 0.057) | 63 (feasible 0.041) | 60 (feasible 0.050) |

Penalties below the provable U + 1 no longer guarantee that ground states are optimal; every returned plan is still validated. The last column divides every coefficient by the largest absolute one (same problem, different scale).

## Decomposition: 6 jobs re-optimised per sub-QUBO, 8 sub-QUBOs per round (`erpq/decompose.py`)

A sub-QUBO frees k random jobs, keeps every other operation fixed at its planned time and is built with SAC pruning and the provable penalties; its objective equals the full objective up to a constant. Each round solves 8 such neighbourhoods of the current plan: **VeloxQ gets them as one block-diagonal QUBO, i.e. one call per round** (256 reads x 5000 steps), SA solves them one after another (100 reads x 1000 sweeps each). The candidates are tried best first, each merged into the current plan and accepted only if the merged plan passes the validator of the original instance and is not worse. Up to 30 rounds; the search stops early at the CP-SAT optimum (only to save calls). Both solvers start from the same plan and see the same neighbourhood sequence (seed 0).

| jobs | whole-QUBO qubits | optimum | start plan | VeloxQ decomposition | gap | rounds = VeloxQ calls | qubits per call median / max | VeloxQ solver time [s] | SA decomposition | gap | SA solver time [s] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 272 | 38 | 50 | **38** | 0.0% | 5 | 940 / 1062 | 1.23 | 41 | 7.9% | 87.74 |
| 10 | 415 | 54 | 66 | **55** | 1.9% | 30 | 460 / 633 | 3.66 | 54 | 0.0% | 12.88 |
| 12 | 726 | 106 | 169 | **122** | 15.1% | 30 | 368 / 643 | 3.56 | 108 | 1.9% | 29.24 |

Start plan: 8 jobs: best read of the whole-QUBO VeloxQ call; 10 jobs: best read of the whole-QUBO VeloxQ call; 12 jobs: best read of the whole-QUBO VeloxQ call.

VeloxQ solver time is the time reported by the service; every call also takes a few seconds of network round trip. SA time is the local wall clock.

![veloxq](veloxq.png)

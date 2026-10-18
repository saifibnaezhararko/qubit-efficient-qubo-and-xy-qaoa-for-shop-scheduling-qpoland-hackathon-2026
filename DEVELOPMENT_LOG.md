# Development log

Dated record of how the project was built: what was done and when, the problems we hit, the decisions
we made and what we rejected. Times are UTC. Commit hashes link entries to the code.

---

## 2026-10-17 (Saturday)

### 05:13 - Reading the challenge
* Read the challenge description and the opening slides. Deliverables: baseline for instances A and B
  (QUBO, quantum algorithm for A, any QUBO solver for B), Stage-2 extension, development log, project
  design, demo video, README, two schedule JSON files.
* Reference numbers to reproduce: 72 variables for the 3x3 at H = 8, 39 with start-window pruning;
  the slides show an optimal 3x3 schedule with makespan 8.
* Scoring note: the baseline only gets us assessed; the points are in the extension. Plan: get a
  solid, verified baseline quickly, then invest in one integrated extension.

### 05:17 - Environment and VeloxQ
* Python 3.13 virtualenv with numpy, scipy, OR-Tools, dimod / dwave-samplers, Qiskit, matplotlib, pytest.
* Found `veloxq-sdk` 1.1.0 on PyPI and read its source before writing the adapter. Findings: a
  `dimod.BinaryQuadraticModel` can be uploaded directly; the token comes from `VELOX_TOKEN`; result
  labels come back as *strings*. **Decision:** use integer labels 0..n-1 and recompute energies
  locally after a VeloxQ call. We have no token in this environment, so the VeloxQ path is opt-in
  (`--veloxq`) and is not exercised by our runs.

### 05:21 - Data model, validator, classical references (commit 22eab06)
* `erpq/model.py`: one JSON schema for the baseline and the planned extensions (routes, units, setups,
  outages, release dates, due dates, rolling state).
* **Decision:** the feasibility checker (`erpq/schedule.py`) shares no code with the QUBO builder, so a
  bug in the encoding cannot hide itself.
* Classical references: lower bound, FIFO / NEH list scheduling, brute force over permutations, CP-SAT.
* Observation: the lower bound is tight on both baselines (LB = optimum = 4 and 8). The FIFO plan
  gives 5 for A and 8 for B.

### 05:30 - Time-indexed QUBO and pruning
* Reproduced the reference sizes: 72 (all t < 8) and 39 (start windows).
* Added AC-3 (no gain on the 3x3) and **singleton arc consistency (SAC)**: 39 -> 33 qubits, still exact.
* Surprise: at H = 4, SAC alone fixes every start time of instance A (0 qubits). **Decision:** run the
  instance-A QAOA at H = 5 (the FIFO plan's makespan), so the QUBO has to *optimise*. That gives 12
  qubits instead of a trivial problem.
* Makespan objective: exponential weights on the end times of last operations (exact
  lexicographically, no extra qubits) for pure makespan; thermometer bits for weighted objectives.
* **Decision on penalty weights:** all penalties = U + 1, with U the objective energy of the FIFO plan.
  Proof in PROJECT_DESIGN.md Sec. 3.1. Rejected "large penalties to be safe": they flatten the landscape.

### 05:40 - Quantum solvers
* X-mixer QAOA on our own NumPy state vector: instance A (12 qubits) reached P(optimal) = 6.5% at p = 5,
  but took 19 s with finite-difference gradients.
* Instance B: 39 qubits means 2^39 amplitudes, impossible. **Decision: XY-mixer QAOA** (one W-state
  register per operation). The mixer conserves one-hot, so we simulate it *exactly* inside the
  512,000-dimensional (39 qubits) / 103,680-dimensional (33 qubits) feasible subspace.
* Problem: the first XY run was slow. **Fix:** adjoint-method gradients (forward and backward sweep),
  checked against finite differences to 1e-9.
* Verification: rebuilt both ansätze as Qiskit gate-level circuits (RZ/RZZ/RX; W-state preparation
  plus `XXPlusYYGate` for the parity-ring mixer). Max probability deviation is about 1e-16.
* **Domain-wall encoding:** 33 -> 24 qubits for the 3x3. Certified by enumerating all 2^24 states
  (4.6 s): every ground state is an optimal schedule.

### 05:50 - First baseline run (commit 22eab06)
* `run_baseline.py`: A -> makespan 4 (QAOA p = 6, P(optimal) = 9.9%); B -> makespan 8 (XY-QAOA p = 4,
  P(optimal) = 17.2%). Both independently validated; CP-SAT and brute force agree.
* SA cross-check on four 3x3 formulations: success per read 40% (72 qubits), 92% (39), 97% (33),
  94% (24). Exact qubit reduction directly helps a classical QUBO solver too.
* Small change: among equally optimal samples, prefer the left-justified schedule.

### 05:55 - Designing the extension
* Prototyped the features one at a time on the 3x3 (due dates, setups, maintenance, parallel milling).
* Key finding: **the horizon dominates the qubit count** (+10-15 qubits per extra hour; e.g. setups at
  H = 8: 0 qubits after SAC, at H = 10: 56). **Decision: horizon ascent.** Start at LB, skip horizons
  that SAC proves infeasible, stop with a *horizon certificate* (a lower bound on the cost of any
  schedule that would need a longer horizon).
* Weighted objective: with makespan weight 1 the certificate needed one extra hour (+25 qubits). Chose
  cost weights 2 per hour of makespan (overtime) and w_j per hour late, which is also the natural
  business reading. The certificate then holds at H = 9 for the integrated model.
* Integrated model `metaltech_monday`: 3x3 + urgent part Z4 with its own route (F -> T), families with
  1 h changeovers on F and S, maintenance of S in [5, 6), due dates. 102 naive -> 62 windows -> 35 SAC ->
  24 domain-wall qubits, optimum 21 = CP-SAT.

### 06:05 - Bugs found while building the experiments
* NEH evaluates partial sequences, so tardiness crashed on unscheduled jobs. Fixed (`completion` returns
  None).
* Right-shift repair passed bare indices instead of (job, index). Caught by a new test.
* **Overlapping outage windows** (breakdown during maintenance) made CP-SAT infeasible. Fixed: windows
  are merged when an instance is built.
* Setup after a still-running operation was enforced by the heuristic but not by the QUBO/CP-SAT.
  Unified in `Instance.fixed_conflict` and used by all three. Part families are now kept even for
  finished jobs.
* Rolling residual problems: the certificate only closed at H = 13 (59 qubits). Tightened the bound
  with per-job completion bounds, added a `patience` limit, and fell back to SA when the subspace is
  too large to enumerate.
* Performance: XY-QAOA took 0.9 s per gradient on the 332k subspace. Fusing neighbouring registers into
  one axis (Kronecker product of their mixers) gave 2.3x with identical results.

### 06:20 - Scaling and investment studies
* First scaling design (certified horizon for random instances) failed: with tight random due dates
  the certificate needed 180+ qubits. **Decision:** a shift model, where all work must finish by the
  end of the shift H = C*max + 1. Exact for that model, CP-SAT with the same H as reference. Qubits now
  grow smoothly with the number of jobs.
* Investment study: SA on 170-300-qubit QUBOs missed optima (63 vs 53). Switched to 4-job order books,
  SA on both exact encodings (one-hot and domain wall), more sweeps.
* Rolling re-planning: the residual QUBOs are small (full run: median 18.5 qubits, max 51), so we added XY-QAOA with
  **fixed angles transferred** from the Monday instance (no variational loop at re-planning time).

### 06:26 - Commit c1a03ca, full experiment run started (30 minutes on 4 cores)
* Price of realism: integrated model 102 -> 62 -> 35 -> 24 qubits, certified exact at every step. Due
  dates cost 0 qubits. With setups at H = 8, SAC fixes every start time (0 qubits). The second milling
  machine costs +45 qubits.
* QAOA on the 35-qubit Monday QUBO: ring 6.0% at p = 5; clique catches up at p = 4 (6.1%); **CVaR(0.1)
  9.8% at p = 4**; parity (hardware gate order) tracks the ideal ring. Angles transferred from the
  3x3 give 4.2% vs 4.5% optimised. Parameter transfer works across instances.
* SA success per read 4.5% (102 qubits) -> 33% (62) -> 43% (35) -> 83% (24). Tabu solves everything
  up to 62 qubits.
* **Penalty sweep (unexpected):** the provable U+1 = 17 is sufficient but not necessary. At 0.25x and
  0.5x the ground state is still optimal and SA does best at 0.5x (0.61 vs 0.43). Larger penalties
  hurt both SA and QAOA. **Decision:** keep U+1 as the default because it is *proven*, and document
  that a tighter U (a better heuristic) would directly help the solvers.
* Scaling: success degrades from about 0.8 (15-25 qubits) to about 0 (150+). The domain-wall QUBO
  beats one-hot for SA on most instances.
* Disruptions (36 scenarios): the rolling QUBO re-plan always equals CP-SAT, with SA and with
  fixed-angle XY-QAOA. It is never worse than right-shift and 0.97 better on average, up to 8 cost
  units.
* Investment: 10.5 cost units/day saved by a second milling machine (95% CI 9.0-12.1). The QUBO was
  optimal in 80/80 solves.

### 06:50 - Finishing
* Charts: integer axis ticks, legend moved off the reference line; `run_extension.py replot`
  regenerates charts and reports from the saved JSON.
* Re-ran `run_baseline.py` with the final code: identical numbers (fixed seeds); the 3x3 output is now
  the left-justified optimal schedule.
* Tests strengthened: the random-instance exactness tests had been skipped at the FIFO horizon
  (subspace too large). Switched to the shift horizon. Now 32 tests, no skips.
* `demo.py` for the live presentation (about 1 minute): sizes 72 -> 24, XY-QAOA on the 3x3, the
  Monday model, a breakdown with fixed-angle QAOA re-plan.
* Documentation: README (run instructions, results), PROJECT_DESIGN.md, this log.

### 07:40 - Project notes (commit 4d14a95) and an adversarial verification round
* Wrote a project notes file (status, setup, commands, structure, methods, rules).
* Verification round: the notes were split into five slices, and each slice was checked against code,
  results and git history with the aim of *refuting* it; a sixth pass looked for missing information.
  About 200 claims were confirmed. The real problems found:
  - **Correctness bug:** the unpruned levels `none` / `horizon` ignored *unary* constraints (release
    dates, maintenance windows, ready times, running operations). For metaltech_monday, an
    outage-violating schedule had zero constraint energy, so the 102-qubit "naive" QUBO was not
    exact (the baseline 72 was unaffected; it has no unary constraints). **Fix:** forbidden start
    values keep their qubit (naive counts unchanged) and get a linear penalty C
    (`timeindexed.unary_feasible`). New tests check this exhaustively on small extended instances.
  - `horizon_ascent` caught *any* `ValueError` as an infeasibility proof, so a typo such as
    `pruning="SAC"` silently "proved" every horizon infeasible. **Fix:** a dedicated
    `InfeasibleHorizon` exception, plus up-front argument validation.
  - `run_baseline.py --out` still overwrote the repo-root deliverables. **Fix:** with a custom `--out`,
    the schedules are written there too.
  - The disruption "XY-QAOA" column silently fell back to SA for large residuals. **Fix:** each
    scenario now records which solver produced the result (`qaoa_column_solver`), and the docs say
    "XY-QAOA where simulable, SA fallback".
  - The exact-keys test only checked the serializer. It now also checks the raw files.
  - `replot` now rebuilds every report from the JSON. `schedule_metaltech_monday.json` got its
    `method` string. Fixed a stale docstring reference in `domainwall.py`.
  - Wording: the validator "shares no code" with the QUBO builder is false (they share
    `Instance.setup` / `fixed_conflict`); U is not always from FIFO (for metaltech_monday it is the
    analytic bound, U = 16); "smallest correct QUBO" means the smallest *we built* (minimality not
    proven); the residual-QUBO median is 18.5 (an earlier entry said "about 15").
* 38 tests pass. A re-run of the experiments was started and then stopped, so the committed
  `results/` predate these fixes. What that means:
  - Part-1 qubit counts and certificates are unchanged.
  - The 102-qubit naive SA rate (4.5%) was measured on the old naive QUBO.
  - `disruption.json` does not yet record the per-scenario solver.
  - `schedule_metaltech_monday.json` still has an empty `method`.
  - The baseline deliverables are unaffected (instances A and B have no unary constraints).

### 12:15 - VeloxQ on the live service (local Windows copy, not a git checkout)

**Setup**
* We received a VeloxQ API token.
* Installed `veloxq-sdk` 1.1.0 in a local venv (Windows 10, Python 3.12.1). A dry run showed it only
  adds packages (httpx, pydantic, h5py, ...) and changes no pinned version.
* The token is passed per process as `VELOX_TOKEN` and never written to a file. The smoke test from
  the SDK's welcome email passed.

**Checking the adapter**
* Before any experiment, we sent the 33-qubit 3x3 QUBO once and inspected the raw HDF5 result:
  - a BINARY BQM comes back BINARY;
  - the labels are strings;
  - the energies the service reports equal ours, offset included;
  - 98.3% of 1024 reads were optimal.
* Problem found on a second read of the SDK: `sample()` treats in-memory problems as SPIN unless told
  otherwise. For a BQM it keeps the BQM's own domain, and our adapter relied on that silently.
* **Fix:**
  - `veloxq()` passes `vartype="BINARY"`;
  - `_from_sampleset` converts any SPIN answer with x = (s + 1) / 2 before mapping states back by
    label;
  - new test `test_sampleset_maps_back_by_label_and_from_spins` (39 tests).

**Timing**
* A call takes 5-15 s of wall time, but the service reports only about 0.1 s of solver time. The rest
  is upload, queueing and download.
* **Decision:** VeloxQ's TTS99 [s] uses the reported solver time (`info["solver_time_s"]`; `time_basis`
  in the JSON). The wall time is recorded next to it (`wall_seconds_per_run`). Otherwise the TTS would
  measure our internet connection.

**Experiment changes**
* VeloxQ now also runs on the naive formulation, like SA and tabu.
* Part 2 makes 3 independent calls per formulation, because the service takes no seed.
* `algorithms.png` shows SA and VeloxQ side by side when VeloxQ rows exist. Without them it is
  byte-identical to before.

**12:33-13:26 - the runs:** `run_baseline.py --veloxq` and `run_extension.py algorithms --veloxq`,
both into a scratch directory first.
* 3x3, VeloxQ optimal reads: 15.0% (72 q, 18.5% feasible), 93.2% (39), 98.4% (33), 94.7% (24).
  Makespan 8 in every call. SA (500 reads): 39.6 / 91.6 / 96.6 / 94.2%.
* metaltech_monday, 3 calls each, all reaching objective 21:
  - VeloxQ: 4.3% / 46.7% / 69.0% / 77.8% at 102 / 62 / 35 / 24 qubits;
  - SA: 7.8% / 32.7% / 42.7% / 82.7%;
  - VeloxQ leads on the 62- and 35-qubit QUBOs, SA on the 102- and 24-qubit ones;
  - tabu still solves everything up to 62 qubits.
* The rerun also refreshed two stale items from 07:40:
  - SA on the corrected 102-qubit naive QUBO succeeds in 7.8% of reads (4.5% on the old QUBO). Tabu
    there: 19%, with 9 of 10 runs optimal.
  - `schedule_metaltech_monday.json` now has its `method`.
* Everything else reproduced: all QAOA probabilities, parameter transfer, the penalty sweep, and the
  deliverables (see the next bullet). Only the L-BFGS-B evaluation counts differ, by 3-4 (platform
  floating point).

**Line endings**
* Problem: on Windows, `Path.write_text` writes CRLF, so the rerun "changed" every output file although
  the content was identical.
* **Fix:** all ten writers use `newline="\n"`. Re-saving the run's schedules now reproduces both
  deliverables byte for byte.

**Promoted to `results/`**
* `baseline/report.*`, `extension/algorithms.*` and `extension/schedule_metaltech_monday.json`,
  after backing up the old files.
* The Gantt PNGs were left as committed: same schedules, and a Windows re-render only changes pixels.
* Still stale: `disruption.json` lacks `qaoa_column_solver`.

### 16:36 - Fewest qubits: the job-order code (comparison only)

**Goal:** bring the 3x3 below the 24 qubits of the smallest time-indexed QUBO (target: 4 qubits).

**What was built** (`erpq/permutation.py`)
* The job order as a binary code in ceil(log2 n!) qubits, decoded by list scheduling. In a same-route
  flow shop with <= 3 machines and pure makespan some permutation schedule is optimal, so the code is
  exact there.
* Cost table (makespan of each order; unused codes get max + 1) -> Moebius transform -> multilinear
  polynomial -> Rosenberg quadratisation of the terms of degree >= 3. The penalty bound makes every
  ground state consistent (module docstring, PROJECT_DESIGN §5.6).
* Instance B: **3 qubits**, 2 couplings, E = 8 + x0 - x0*x1 + 2*x1*x2. The cubic coefficient of its cost
  table is 0, so it needs no auxiliary qubit (we had expected 3 + 1 = 4). Instance A: 1 qubit.

**Verification** (`run_baseline.py` into a scratch directory, 16:37)
* All 2^3 states enumerated: 4 ground states, the 4 optimal job orders (makespan 8). Instance A: all
  2^1 states.
* X-mixer QAOA p = 3: P(optimal) 0.9939 for B and 1.0 for A, with uniform sampling at 0.5 for both.
  SA: 100% of 500 reads.
* Everything else in the report reproduced exactly, and both deliverables byte for byte. Only the
  VeloxQ rows were missing, since this run had no token.
* Ad-hoc check, not part of `results/`: on random 3-machine flow shops (20 instances each for 2-4 jobs,
  5 for 5-6 jobs) the code was exact in every enumerated case. Qubits: 3-4 for 3 jobs, 9-10 for 4, 22
  for 5, 82-94 for 6, with 6 / 24 / 120 / 720 cost-table entries.
* New tests `tests/test_permutation.py`; 43 tests pass.

**Decision: report it, but as a comparison only**
* Its coefficients are the makespans of all n! orders, so brute force solves the problem while the
  QUBO is built. This is why permutation encodings were rejected as the model (see "Rejected
  alternatives").
* The qubits hold only the job order; start times come from a classical decoder.
* It does not cover metaltech_monday (job-specific route, setups, maintenance, tardiness); the builder
  refuses it.
* The deliverables, the 72 / 39 / 33 / 24 reference counts and Stage 2 are unchanged.
* `run_baseline.py` reports it (a table row, the certificate, QAOA, an SA cross-check row), and
  `demo.py` prints it in step 1. README and PROJECT_DESIGN (§5.6) now say "fewest qubits: 3
  (job-order code, brute-force coefficients); smallest time-indexed QUBO: 24".

**Not yet promoted:** `results/baseline/report.*` still comes from the 12:33 run. Regenerating it needs
`--veloxq` with the token; without it the VeloxQ rows would disappear.

### 18:13 - The 3-qubit job-order code on VeloxQ (ad hoc, one live call)

**Goal:** run instance B's 3-qubit job-order code on VeloxQ. The 12:33 VeloxQ
round predates the code, and `run_baseline.py --veloxq` still sends only the four time-indexed QUBOs.

**Run** (scratch script outside the repo, this local Windows copy; the token was passed to that one
process only)
* Same call and scoring as the VeloxQ rows of `run_baseline.py`: `samplers.veloxq` with its defaults
  (1024 reads x 5000 steps), then `pipeline.report_samples`, which decodes every read and checks it
  with `Schedule.violations()`.
* All 1024 reads optimal (makespan 8), and all four optimal job orders came back: Z1-Z2-Z3 (392 reads),
  Z3-Z1-Z2 (319), Z2-Z3-Z1 (169), Z2-Z1-Z3 (144).
* Solver time 0.117 s as reported by the service, 10.3 s wall. That is about the same as each of the
  four 12:33 calls on 24-72 qubits (about 0.12 s), so at these sizes the solver time is set by
  reads x steps, not by the qubit count.
* With 8 states this is no solver benchmark. It shows that the 3-qubit QUBO runs unchanged on a cloud
  QUBO solver. The caveat stands: its coefficients are the makespans of all 6 job orders (brute force).

**Not in `results/`:** the run was ad hoc and VeloxQ takes no seed. To get it into the report, add
`("permutation", perm_form)` to the VeloxQ loop of `run_baseline.py` and regenerate with `--veloxq`
(5 calls instead of 4).

### 18:30 - Submission checklist check (local Windows copy)

**Goal:** check every item of the submission checklist against GitHub and against the tree that
would be pushed.

**GitHub** (read-only: anonymous `git ls-remote`, the public API, a fresh clone)
* The repository is public (`visibility: public`), GitHub detects the license as MIT, and the
  working branch is its default and only branch, so a plain `git clone` gets it.
* GitHub is behind this copy. Its last commit is `7585d1e` (08:20 UTC); the local round of 12:15-18:13
  changes 22 files, 2 of them new (`erpq/permutation.py`, `tests/test_permutation.py`). No file exists
  only on GitHub. Both deliverables are identical on GitHub and here.
* The local round is pushed separately.

**Code runs** (on the tree that would be pushed: the GitHub clone plus the local files, in a scratch
directory; every output went to scratch, the committed results were not touched)
* `pytest`: 43 passed in 21 s.
* Full `run_baseline.py`: both deliverables reproduced byte for byte.
* `run_baseline.py --quick --veloxq` without a token: prints "VeloxQ skipped", exit 0.
* `demo.py`: matches the expected demo output.
* `run_extension.py all --quick`, then `replot`: exit 0. Part 1 reproduces 72 / 39 / 33 / 24 (3x3)
  and 102 / 62 / 35 / 24 (Monday), and the QUBO optimum equals CP-SAT at every level.
* Wall times on this machine, partly run side by side: 5 min, 1 min, 2 min, 24 min, 9 s.
* A dry-run fresh install (`pip install --dry-run --ignore-installed -r requirements.txt`) resolves
  today to exactly the versions behind the committed results.

**Schedule files:** an independent check with the Python standard library only (no `erpq`) confirmed
the exact Section-14 keys, integer times from 0, the durations, the technological order, no overlap
and makespan = max end. Makespans 4 and 8 equal both the brute-force optimum over all job orders and
the machine lower bound.

**README run instructions completed:** the real clone URL, a PowerShell fallback when `Activate.ps1`
is blocked, the package versions behind the results, `--shots` / `--seed`, `run_extension.py --out`
and `replot`, and the investment flags.

### Still open
* Record the demo video and add the link to the README.
* Push the local round (12:15 onwards) to GitHub. GitHub still ends at `7585d1e`.
* Optional: re-run Part 4 (`run_extension.py disruption`), so `disruption.json` records
  `qaoa_column_solver`.
* Regenerate `results/baseline/report.*` with `python run_baseline.py --veloxq` (token needed), so the
  report contains the job-order code. Then update the 3x3 VeloxQ numbers, which change slightly
  because the service takes no seed.

---

## 2026-10-18 (Sunday)

All of this day's work was done in the same local Windows copy (not a git checkout). Every
experimental script ran outside the repository; only the scripted runs listed at the end write to
`results/`.

### 07:20 - VeloxQ token, account check
* The VeloxQ token is now kept in the environment, as the Windows user environment variable
  `VELOX_TOKEN` on our machine. No repository file contains it.
* A free API call (the account's job list, no solver time) confirmed the key: same account as on
  2026-10-17, 19 jobs, 2,307 quota units. The service bills about 1 unit per millisecond of solver
  time; the cost shown is 0 USD.
* There is a prize for the best use of VeloxQ. Goal of the day: use VeloxQ where it matters,
  on larger problems, and report it with the same verification as everything else.

### 07:30 - Large QUBOs on VeloxQ: pilots (scratch scripts, not in `results/`)
* Random extended instances (instance k = 0 of the Part-3 generator) with 8, 10 and 12 jobs at the
  shift horizon. SAC QUBOs: 272, 415 and 726 qubits (4,679 / 9,208 / 24,778 couplings).
* SA (300 reads): no optimal read. Best plans 49 / 70 / 158 against the CP-SAT optimum 38 / 54 / 106.
* VeloxQ, one call (1024 reads x 5000 steps): no optimal read either. Best 49 / 60 / 194; feasible
  reads 22.6% / 5.4% / 0.1%; solver time 0.19 / 0.28 / 0.55 s. On the domain-wall QUBOs no read was
  feasible.
* Settings tried on 8 and 10 jobs (one call each):
  - 4x more steps: 47 instead of 49 (8 jobs);
  - all coefficients divided by the largest one: no change on 8 jobs (49). The 09:20 run shows that a
    single call does not settle this question;
  - penalties x0.5 / x0.25: 48 / 44 (8 jobs), 63 / 60 (10 jobs). A little better, but below U + 1
    exactness is no longer guaranteed;
  - `SBMSolver` (simulated bifurcation, the SDK's second solver): HTTP 401 "User cannot access this
    solver". Not available to our account.
* **Conclusion:** at 270-730 qubits the one-hot time-indexed QUBO itself is the obstacle for any
  single call. A penalty of U + 1 = 94 (8 jobs) against objective steps of 1-3 blocks local moves.

### 08:20 - Decomposition: small exact sub-QUBOs (`erpq/decompose.py`)
* Our own data shows where VeloxQ is strong: exact QUBOs of 30-60 qubits (Monday: 47-78% optimal
  reads). So we keep the QUBOs that small: free k jobs, keep every other operation as an
  `Instance.fixed` entry at its planned time, and solve the SAC sub-QUBO. A move is accepted when the
  merged plan passes the validator of the original instance and is not worse.
* Why each step is exact: `Schedule.makespan` and `makespan_lower_bound` both include fixed
  operations. So the sub-QUBO's objective is the full objective minus a constant (the fixed jobs'
  tardiness), and its ground states are the best re-placements. New test
  `test_sub_qubo_objective_is_the_full_objective_up_to_a_constant`.
* SA pilot, k = 3: sub-QUBOs of only 6-23 qubits, and the search stalls (8 jobs 44 vs 38, 12 jobs 140
  vs 106). k = 5-6: 10 jobs reach the optimum 54, while 8 and 12 jobs stall at 41 and 125.
* VeloxQ as the sub-solver (k = 6, 12 jobs, 30 calls of 256 reads): also 125. The solver is not the
  bottleneck; the number of neighbourhoods explored is.

### 08:55 - Batching: 8 sub-QUBOs per VeloxQ call
* VeloxQ's time per call barely depends on the size at these scales (0.12 s at 3-72 qubits, 0.55 s at
  726). Every call pays a network round trip of 2-15 s, though. So each round now draws 8
  neighbourhoods of the current plan and stacks their sub-QUBOs into one block-diagonal QUBO
  (`stack_qubos`), solved in one call.
  - The best read is taken per block, which is valid because the blocks share no variables or
    couplings.
  - The candidates are tried best first. Each is merged into the plan as it is at that moment and
    validated again.
  - SA solves the same 8 sub-QUBOs one after another, so both solvers see the same neighbourhoods.
* SA pilot: 8 jobs reach the optimum 38 in 10 rounds; 12 jobs reach 108 vs 106 (1.9%) in 30 rounds.
  Without batching the search had stalled at 41 and 125.
* New tests (46 in total): the stacked QUBO is the sum of its blocks, and the search stays feasible
  and never gets worse.

### 09:00 - Code for the runs
* `run_baseline.py --veloxq` now also sends the 3-qubit job-order code (5 calls).
* `run_extension.py disruption --veloxq`: a live VeloxQ re-plan column. It uses the same horizon
  ascent, with one call of 256 reads per horizon that has qubits (`experiments.veloxq_solve`).
* `run_extension.py veloxq` (Part 6, needs the token, not part of `all`): the whole QUBO of 4-12-job
  books on SA and VeloxQ, the settings on 8 and 10 jobs, and the batched decomposition with VeloxQ vs
  SA. It saves its JSON before plotting, because live calls cannot be repeated exactly.
* `demo.py --veloxq` adds step 5: the t = 2 breakdown re-planned live on VeloxQ. Without the flag the
  demo is unchanged.

### 09:00-09:20 - The runs (all with the live service, results promoted after checks)
Before the runs, `results/`, both deliverables and the documents were backed up outside the
repository.

**Baseline** (`run_baseline.py --veloxq`)
* Both deliverables reproduced byte for byte.
* VeloxQ optimal reads: 12.9% (72 q, 17.1% feasible), 93.1% (39), 98.5% (33), 94.1% (24), 100% (3-qubit
  job-order code). Makespan 8 in every call, 0.12-0.13 s solver time per call.
* On 2026-10-17 the same calls gave 15.0 / 93.2 / 98.4 / 94.7%. The service takes no seed.

**Part 4** (`run_extension.py disruption --veloxq`)
* Every old column reproduced exactly, and `residual_t2_F2.json` and `schedule_replan_t2_F2.json` are
  byte-identical. `qaoa_column_solver` is now recorded: XY-QAOA in 32 scenarios, the SA fallback in 3,
  exact in 1. The horizon certificate is missed in 1 scenario (CP-SAT confirms the optimum there).
* First run with 256 reads per call: VeloxQ equal to CP-SAT in 32 / 36 scenarios, 63 calls, 7.62 s of
  solver time. That is about 0.12 s per call, the same as the 1024-read calls of 2026-10-17. The
  solver time has a floor, so fewer reads save nothing.
* **Decision:** 1024 reads for re-planning (`veloxq_solve` default). The re-run gave 33 / 36, 63 calls,
  7.51 s. Mean gain over right-shift 0.67 (SA: 0.97). Better than right-shift in 9 scenarios, worse in
  1 (t = 4, T down 3 h: 33 vs 30).
* Misses (VeloxQ vs CP-SAT): t = 3, S down 2 h and 3 h: 34 vs 30; t = 4, T down 3 h: 33 vs 30.
* Diagnosis (scratch script, 4 calls) on t = 3, S down 3 h, horizon by horizon:
  - at H = 12 (31 qubits) and H = 13 (39 qubits) VeloxQ's best read has energy 16, while exact
    enumeration and SA reach the ground energy 12;
  - only 22-23% of its reads are feasible (SA: 86-88%);
  - 4x more steps gave the same result.
  - So VeloxQ gets stuck in a local minimum of these residual QUBOs. The adapter is not the cause: the
    energies agree.
* The superseded 256-read result was kept outside the repository.

**Part 6** (`run_extension.py veloxq`, 891 s, 78 calls)
* Whole SAC QUBO, SA (600 reads) / VeloxQ (1024 reads), best plan vs the optimum:
  - 4 jobs (74 q): 43 / 43 vs 43;
  - 6 jobs (130 q): 24 / 24 vs 24;
  - 8 jobs (272 q): 49 / 50 vs 38;
  - 10 jobs (415 q): 63 / 66 vs 54;
  - 12 jobs (726 q): 155 / 169 vs 106, with 0.1% of VeloxQ's reads feasible.
* Settings, one call each (8 / 10 jobs):
  - 4x steps: 49 / 66;
  - penalty x0.5: 48 / 64;
  - penalty x0.25: 44 / 63;
  - coefficients scaled to a maximum of 1: 50 / 60.
  - The 10-job default call gave 60 in the 07:30 pilot and 66 here. So differences of this size are
    within the spread between identical calls, and we make no claim about scale (in)dependence beyond
    "no consistent effect".
* Decomposition, k = 6, 8 sub-QUBOs per round, up to 30 rounds, from the whole-QUBO call's best read.
  VeloxQ ran with 256 reads per batch call; at 400-1,000 qubits per call, 1024 reads would cost up to
  0.5 s instead of 0.12 s.
  - 8 jobs: VeloxQ **38 (optimal) in 5 calls**, 1.23 s solver time, 53 s wall. SA: 41 after 30 rounds,
    88 s.
  - 10 jobs: VeloxQ 55 (+1.9%) in 30 calls, 3.66 s solver time, 219 s wall. SA: 54 (optimal) in 10
    rounds, 13 s.
  - 12 jobs: VeloxQ 122 (+15.1%) in 30 calls, 3.56 s solver time, 217 s wall. SA: 108 (+1.9%), 29 s.
  - Batch QUBOs per call: median 368-940, max 1,062 qubits.
* Reading: decomposition is what makes these sizes tractable, for both solvers. VeloxQ explores a round
  of 8 neighbourhoods in about 0.12 s of GPU time, but its sub-QUBO answers are sometimes stuck (as in
  Part 4), and SA's are not. Single instances and an unseeded service: a trend, not a statistic.
* Not re-run with 1024 reads after the Part-4 finding: up to 4x the quota per call, the quota limit is
  unknown, and the Part-4 diagnosis says more effort does not free the stuck reads.

**Demo:** `demo.py --veloxq` reproduces steps 1-4 as documented. Step 5 re-plans the t = 2 breakdown on
VeloxQ: objective 33 = CP-SAT, certified at H = 13, 3 calls, 0.34 s of solver time, 83 s for the whole
demo.

**Cosmetics:** the Windows runs re-rendered the baseline and disruption Gantt PNGs. Their schedules are
identical, so the committed renders were kept (as on 2026-10-17).

**VeloxQ account totals:** 2026-10-17: 19 jobs, 2,307 quota units; 2026-10-18: 258 jobs, 38,798
units. Together 277 calls and 41.1 s of solver time, at 0 USD. 158 calls are behind committed results.
No quota error occurred.

### 09:40 - `VELOXQ.md`
* Everything about VeloxQ is now in one document, written for the jury of the VeloxQ prize. It covers
  the setup and adapter, the five uses with all results, the decomposition design, the lessons, the
  cost and the limitations. It is linked from README and PROJECT_DESIGN.
* Every number was taken from `results/*.json`. Proofreading against the data corrected three claims
  in the drafts (and in README):
  - "every call optimal" holds for the 3x3 and the Monday model, not for all QUBOs up to 62 qubits:
    the Part-4 misses are 31-39-qubit QUBOs;
  - the whole-QUBO gap from 8 jobs on is 17-59%, because SA's 10-job plan is 16.7% above the optimum;
  - a decomposition call takes 0.12-0.25 s of solver time, not 0.12 s.

### Still open
* Record the demo video and add the link to the README. For the VeloxQ prize, `python demo.py
  --veloxq` shows a live call (+20-30 s), and `results/extension/veloxq.png` is the at-scale figure.
* Push everything since 2026-10-17 12:15 to GitHub; GitHub ended at
  `7585d1e` when last checked. New files: `VELOXQ.md`, `erpq/decompose.py`, `tests/test_decompose.py`,
  `results/extension/veloxq.*` (plus the 2026-10-17 ones).

---

## Rejected alternatives (and why)
* **Standard X-mixer QAOA for the 3x3:** 2^33 amplitudes, and most amplitude is wasted on non-one-hot
  states. XY mixers remove that subspace exactly.
* **Binary (log) start-time encoding:** fewer qubits per operation, but the pairwise constraints become
  higher-order and need auxiliary qubits. Domain walls save a qubit per operation and keep everything
  quadratic.
* **Permutation (position) encodings as the model:** the makespan is not quadratic in them. An exact
  form needs the n! cost table (the problem is solved while building it), and surrogates lose
  exactness and the extended constraints. The binary job-order code was built later as a comparison
  (16:36 entry): 3 qubits for the 3x3, with exactly this catch.
* **Slack variables:** unnecessary in the time-indexed model, where every constraint is a forbidden
  pair of start times.
* **Big-M penalties:** replaced by the provable U + 1.

# Project Overview: QPoland Quantum Hackathon 2026 - ERP Challenge

This repository is the solution to the **Production Scheduling Optimization (ERP)** challenge of the
QPoland Quantum Hackathon 2026 (16-18 Oct 2026; submission deadline Sun 18.10, 15:00 UTC+2).

MetalTech Ltd. has three machines: lathe **T**, milling **F**, welding **S**. Every part goes
T -> F -> S, and a machine processes one operation at a time. The goal is a schedule with minimal
makespan.

The core search is a **QUBO**. It is solved with quantum algorithms (QAOA on state-vector simulators)
and QUBO solvers (simulated annealing, tabu search, optionally VeloxQ). Every result is verified against
classical references.

* **Stage 1 (mandatory baseline, challenge §4):**
  - Instance A (2 jobs x 2 machines, T -> F), solved with a quantum algorithm.
  - Instance B (3 jobs x 3 machines, T -> F -> S), solved with a QUBO solver.
  - Outputs: `schedule_2x2.json`, `schedule_3x3.json` (challenge §14 format).
* **Stage 2 (extension, challenge §5):** one integrated, more realistic model, `metaltech_monday`.
  - It is used for qubit reduction / price of realism, the algorithm comparison, and disruptions
    with rolling re-planning.
  - The scaling and variance study (random instances with 2-6 jobs) and the second-milling-machine
    investment study (40 random 4-job order books) use **random instances of the same extended model**.

Companion documents:
* `README.md`: how to run, results, AI usage.
* `PROJECT_DESIGN.md`: data model, QUBO, proofs, solvers.
* `DEVELOPMENT_LOG.md`: dated log.
* `VELOXQ.md`: everything about VeloxQ in one place (setup, five uses, results, decomposition,
  lessons, cost, limitations), written for the VeloxQ prize jury. Keep its numbers in sync with
  `results/*.json` like the other docs.
* `results/README.md`: what each result file is.

The challenge PDFs are **not** in the repo. Section references used here:
* §4 baseline;
* §5 extension directions;
* §11 scoring: the baseline is only the entry gate, points come from the extension, and
  consistency between log, code and presentation is scored;
* §12 the AI-usage statement required in the README;
* §14 the I/O format.

**Mapping from the original template layout:**
* `/src` = `erpq/` (plus `run_*.py`, `demo.py`).
* `/outputs` = the repo-root `schedule_*.json` (plus `results/`).
* `/docs/dev_log.md` = `DEVELOPMENT_LOG.md`.

Do not create a second log or move the deliverables. A local `docs/` directory, if present, is empty and
untracked.

---

## Current Status (what has been done)

| Submission checklist item | Status |
|---|---|
| Code runs without errors | Done. Fresh clone + `pip install -r requirements.txt` + `python run_baseline.py --quick` + `pytest` verified. Re-verified 2026-10-17 18:30 UTC on Windows on the tree to be pushed: pytest, full and quick baseline, demo, `run_extension.py all --quick` + `replot` (DEVELOPMENT_LOG 18:30). After the 2026-10-18 VeloxQ round, on Windows: pytest (46), full baseline with VeloxQ (deliverables byte-identical), Part 4 with VeloxQ (old columns identical), Part 6, `demo.py --veloxq`, `replot` (every report byte-identical), and Part 4 `--quick` without a token |
| Repository is public | Done. Verified 2026-10-17 18:30 UTC via the GitHub API (`visibility: public`) |
| `LICENSE` with MIT license | Done (`LICENSE`; GitHub detects it as MIT) |
| README with full run instructions | Done (`README.md`: clone URL, Windows notes, all script options) |
| README contains link to demo video | **TODO (team):** placeholder at the top of `README.md` ("**Demo video:** ...") |
| Development log | Done (`DEVELOPMENT_LOG.md`, dated UTC entries); the team should append its own entries (video, review) |
| Project design | Done (`PROJECT_DESIGN.md`) |
| `schedule_2x2.json`, `schedule_3x3.json` | Done (repo root), produced by `run_baseline.py`, validated |
| How AI was used (README, challenge §12) | Done (README section "How AI was used") |

**Other open items:**
* VeloxQ: done, run live on 2026-10-17 and 2026-10-18 with the team's token; the numbers are below.
  The token is never stored in the repo. On the team's Windows machine it is the user environment
  variable `VELOX_TOKEN` (set 2026-10-18 at the team's request); elsewhere pass it as `VELOX_TOKEN`.
* The VeloxQ "best usage" round (2026-10-18, DEVELOPMENT_LOG 07:20 onwards): the baseline report
  regenerated with VeloxQ on all five formulations (incl. the job-order code), a live VeloxQ column in
  Part 4, and the new Part 6 (`run_extension.py veloxq`, `erpq/decompose.py`).
* Everything since 2026-10-17 12:15 was done in a local Windows copy that is *not* a git checkout.
  GitHub still ended at `7585d1e` (08:20 UTC) when last checked, so the team must push these rounds
  (see DEVELOPMENT_LOG 12:15, 18:30 and 2026-10-18).
* All work is on branch `claude/quirky-einstein-3xg207`. It is the repository's default and only
  branch (verified 2026-10-17 18:30 UTC), so `git clone` gets it.

**Git history (2026-10-17, UTC):**
1. `22eab06` (05:51): core package and baseline.
2. `c1a03ca` (06:26): Stage 2 code, tests, design doc.
3. `c887509` (07:24): results, docs, demo, final fixes.
4. `4d14a95` (07:40): first CLAUDE.md.
5. Later: verification-round code fixes and this file; see `git log`.

Most committed `results/` come from the run *before* the verification fixes; those experiments were
deliberately not re-run.
* On 2026-10-17 (12:33-13:26 UTC) two parts were regenerated with the current code plus `--veloxq`,
  on Windows 10 with Python 3.12.1 and the same package versions:
  - `results/baseline/report.*`;
  - Part 2 (`algorithms.*` and `schedule_metaltech_monday.json`).
* That fixed the 102-qubit naive SA value and the empty `method`.
* On 2026-10-18 (same machine and versions) three more were regenerated with `--veloxq`:
  - `results/baseline/report.*`, now with VeloxQ on the job-order code too;
  - Part 4 (`disruption.*`), which now records `qaoa_column_solver` and has a live VeloxQ column. Every
    old column reproduced exactly, and the example files (`residual_t2_F2.json`,
    `schedule_replan_t2_F2.json`) are byte-identical;
  - Part 6 (`veloxq.*`) is new.

Deliverables, baseline numbers and all certified qubit counts are unaffected. The rerun reproduced
the deliverables byte for byte and every other number, except:
* L-BFGS-B evaluation counts (+3 to +4, platform floating point);
* the naive-QUBO SA / tabu rows, which reflect the fix.

### Headline results (canonical values, keep consistent everywhere)

**Instance A**
* Optimum 4 (LB = 4, FIFO plan = 5).
* QUBO at H = 5: **12 qubits**, penalties 2 (U = 1).
* QAOA (X mixer) at p = 6: P(optimal) = 0.0994 per shot (uniform: 2.44e-4) -> **makespan 4**.
* Qiskit cross-check deviation about 3e-16.
* Job-order code (comparison only, coefficients from brute force): 1 qubit, certified; QAOA p = 3
  P(optimal) 1.0 (uniform: 0.5).

**Instance B**
* Optimum 8 (LB = 8 = FIFO).
* QUBO at H = 8: **72 naive -> 39 windows -> 33 SAC -> 24 domain wall**. At window/sac it is a pure
  feasibility QUBO: U = 0, penalties 1, makespan encoding `none`.
* XY-mixer QAOA, p = 4, on 33 qubits (exact simulation in the 103,680-dim one-hot subspace):
  P(optimal) = 0.172 -> **makespan 8**.
* 13 optimal schedules exist at H = 8; H = 7 is proven infeasible by SAC.
* SA success per read: 39.6% (72 q), 91.6% (39 q), 96.6% (33 q), 94.2% (24 q). Tabu: 100% (33 q).
* VeloxQ (live, re-run 2026-10-18, one call of 1024 reads x 5000 steps per formulation, unseeded):
  12.9% (72 q, 17.1% feasible), 93.1% (39 q), 98.5% (33 q), 94.1% (24 q), 100% (3-qubit job-order
  code). Every call found makespan 8, in 0.12-0.13 s of solver time per call (2-4 s wall). The
  2026-10-17 call gave 15.0 / 93.2 / 98.4 / 94.7%.

**Fewest qubits for the 3x3: 3** with the job-order code (`erpq/permutation.py`, comparison only).
* E = 8 + x0 - x0*x1 + 2*x1*x2 (3 code bits for the 6 job orders, no auxiliary qubit, 2 couplings).
* All 2^3 states enumerated: the 4 ground states are the 4 optimal job orders (makespan 8).
* X-mixer QAOA p = 3: P(optimal) 0.9939 (uniform: 0.5). SA: 100% of 500 reads. VeloxQ: 100% of
  1024 reads (one call, in `results/baseline/report.*` since 2026-10-18).
* The catch, always say it: the coefficients are the makespans of all 6 job orders (brute force), the
  table grows as n!, and the qubits hold only the order (start times are decoded classically).

**Our smallest time-indexed 3x3 QUBO: 24 qubits** (SAC + domain wall). This is the model behind the
deliverables and Stage 2.
* Its correctness (all 13 ground states are optimal schedules) is certified by enumerating all 2^24
  states.
* Minimality is not proven.

**Instance B on 4 qubits (Part 7, `run_extension.py pce`, `erpq/solvers/pce.py`, DEVELOPMENT_LOG
2026-10-18 11:05):** the same certified 24-variable domain-wall QUBO, solved with Pauli correlation
encoding (PCE; Sciorilli et al., arXiv:2401.09421).
* Variable i = sign of <P_i> on one 4-qubit state. The P_i are weight-2/1 strings of the Z..Z / X..X /
  Y..Y families (30 >= 24), so 3 measurement settings suffice. No brute-force coefficients.
* 40-angle hardware-efficient ansatz, the paper's loss with alpha = 4, beta = 1/2, nu = 45.125,
  L-BFGS-B with parameter-shift gradients, 100 restarts (seed 7), 90 s.
* Optimal read-out in **19%** of restarts (44% after one bit-swap pass; 22 restarts for 99%; uniform
  7.7e-7). Qiskit agrees to 5.0e-16; 4096 shots x 3 settings reproduce the read-out (smallest margin
  0.028 = 1.8 sigma of shot noise).
* Always say: a variational heuristic, not a certificate; the same loss without a quantum state (24 free
  parameters) also gives 19%; SA on the 24 qubits gives 95%. Why no 4-qubit time-indexed QUBO: after SAC
  103,680 start-time combinations remain (>= 17 bits); the 13 feasible ones fit in 4 bits only after
  solving.

**Stage 2 (`metaltech_monday`)**
* Qubits at the certified H* = 9: 102 naive -> 62 windows -> 35 SAC -> 24 domain wall.
* Optimum 21 (makespan 9, weighted tardiness 3), equal to CP-SAT.
* XY-QAOA: CVaR(0.1) at p = 4 reaches P(optimal) 9.8% (uniform: 8.1e-5). Ring mixer at p = 5: 6.0%.
* Parameter transfer from the 3x3: 4.2% vs 4.5% optimised.
* SA success per read: 7.8% / 33% / 43% / 83% at 102 / 62 / 35 / 24 qubits. The 102-qubit value was
  re-run on 2026-10-17 on the fixed naive QUBO; before the unary-penalty fix it was 4.5%. Tabu: 100%
  for <= 62 qubits, 19% per read at 102 (9 of 10 runs hit the optimum).
* VeloxQ (live, 3 unseeded calls of 1024 reads per formulation): 4.3% / 46.7% / 69.0% / 77.8% at
  102 / 62 / 35 / 24 qubits. Every call found objective 21. TTS99 [s] uses the solver time the
  service reports (0.3-13 ms); the wall time is about 5-7 s per call.
* 36 breakdown scenarios:
  - The QUBO re-plan equals CP-SAT in 100% of scenarios, both with SA and in the "XY-QAOA" column.
  - The "XY-QAOA" column means fixed-angle XY-QAOA where the subspace is <= 2e6 states, with an SA
    fallback otherwise and pure propagation at 0 qubits.
  - `qaoa_column_solver` (run of 2026-10-18): XY-QAOA produced the schedule in 32 scenarios, the SA
    fallback in 3 (t = 1: T down 2 h and 3 h, F down 2 h; subspace > 2e6), exact propagation in 1.
  - On average 0.97 cost units cheaper than right-shift (95% CI 0.42-1.58). Better in 31% of
    scenarios (by up to 8), never worse.
  - Residual QUBOs: median 18.5 qubits, max 51. Horizon certificate missed in 1 scenario (CP-SAT
    confirms the optimum).
  - **Live VeloxQ column** (same horizon ascent, 1 call of 1024 reads per horizon with qubits):
    - equals CP-SAT in 33 / 36 scenarios (92%), mean gain over right-shift 0.67;
    - better than right-shift in 9 scenarios, worse in 1 (t = 4, T down 3 h: 33 vs 30);
    - 63 calls, 7.51 s of solver time;
    - misses: t = 3, S down 2 h and 3 h: 34 vs 30; t = 4, T down 3 h: 33 vs 30;
    - cause: VeloxQ's reads stall in a local minimum of those residual QUBOs (energy 16 vs ground 12
      at 31 qubits; 4x steps do not help).
    - A first run with 256 reads gave 32 / 36 at the same solver time (floor of about 0.12 s per
      call), hence 1024 reads.
* Part 6, VeloxQ at scale (`veloxq.md`; random books, instance k = 0 per size, shift horizon):
  - Whole SAC QUBO (qubits 74 / 130 / 272 / 415 / 726 for 4 / 6 / 8 / 10 / 12 jobs):
    - SA best 43 / 24 / 49 / 63 / 155;
    - VeloxQ best 43 / 24 / 50 / 66 / 169;
    - optimum 43 / 24 / 38 / 54 / 106.
  - Settings (one call each) close no gap: the best is penalty x0.25 with 44 on 8 jobs, which is no
    longer provably exact.
  - Decomposition (k = 6, 8 sub-QUBOs per VeloxQ call, <= 30 rounds):
    - VeloxQ **38 (optimal, 5 calls, 1.23 s)** / 55 (30 calls, 3.66 s) / 122 (3.56 s);
    - SA 41 / **54** / **108** (88 / 13 / 29 s).
    - Single instances and an unseeded service: a trend, not a statistic.
  - Account totals over both days: 277 calls, 41.1 s of solver time (41,105 quota units, 0 USD).
    158 of them are behind committed results.
* Second milling machine:
  - Saves 10.5 cost units/day (95% CI 9.0-12.1). QUBO+SA was optimal in 80/80 solves.
  - Payback about 1.1 years, under illustrative CLI assumptions (1 cost unit = 150 PLN, 250 days,
    machine 450,000 PLN).

---

## Tech Stack & Tools

- **Language:** Python >= 3.10 (developed and tested with **Python 3.13.16**).
- **Quantum simulation:** own exact NumPy state-vector QAOA simulators (`erpq/solvers/qaoa.py`),
  X-mixer and XY-mixer (one-hot subspace), with adjoint gradients.
  - **Qiskit 2.6** is used *only* to cross-check them against gate-level circuits
    (`erpq/solvers/qiskit_check.py`).
  - Pauli correlation encoding (`erpq/solvers/pce.py`): exact 4-qubit state-vector simulation,
    parameter-shift gradients, also cross-checked with Qiskit (Part 7).
- **QUBO model:** own `QUBO` class (`erpq/qubo.py`), converted to `dimod.BinaryQuadraticModel` for
  the samplers. **PyQUBO is not used.**
- **QUBO solvers:**
  - `dwave-samplers` 1.8 (`SimulatedAnnealingSampler`, `TabuSampler`);
  - exhaustive enumeration (own code);
  - **VeloxQ** via the official `veloxq-sdk` 1.1.0 (optional, needs `VELOX_TOKEN`): Quantumz.io's
    classical GPU QUBO solver, default backend `VeloxQH100_1`. Run live on 2026-10-17 and 2026-10-18
    (baseline, Part 2, Part 4 re-planning column, Part 6 at scale + decomposition). The SDK's
    `SBMSolver` is not enabled for our account (HTTP 401).
- **Classical reference:** Google **OR-Tools 9.15 CP-SAT** (`erpq/classical.py`), plus brute force
  over job permutations and lower bounds (`erpq/heuristics.py`).
- **Numerics:** numpy 2.5, scipy 1.18 (L-BFGS-B optimiser for QAOA angles).
- **Visualization:** **matplotlib** 3.11 static PNG and Gantt charts (`erpq/gantt.py`,
  `erpq/plotstyle.py`, validated categorical palette in fixed order). No Plotly, no interactive Gantt.
- **Tests:** pytest 9.
- **Data formats:** JSON instances (`instances/`) and JSON schedules (challenge §14 format).

**Exact versions behind the committed numbers:**
Python 3.13.16, numpy 2.5.4, scipy 1.18.1, matplotlib 3.11.2, ortools 9.15.6755, dimod 0.12.22,
dwave-samplers 1.8.0, qiskit 2.6.0, pytest 9.1.1, veloxq-sdk 1.1.0.

The 2026-10-17 regeneration of `results/baseline/report.*` and Part 2 used the same package versions,
but on Windows 10 with Python 3.12.1.

`requirements.txt` only has lower bounds. Pin these versions to reproduce the SA statistics bit for bit.

---

## Environment & Setup

### Fresh machine
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                          # numpy scipy matplotlib ortools dimod dwave-samplers qiskit pytest
pip install veloxq-sdk                                   # optional, only for --veloxq
```

### This cloud session
* A virtualenv already exists at **`/home/user/venv`**, with all requirements and `veloxq-sdk`
  installed.
  - Use `/home/user/venv/bin/python ...`.
  - The system `python3` only has numpy and pandas.
* The scripts (`run_baseline.py`, `run_extension.py`, `demo.py`) live in the repo root.
  - They import `erpq` from their own directory.
  - They resolve instance and result paths through `ROOT = Path(__file__).resolve().parent`, so they
    work from any working directory.
  - Only a *relative* `--out` path is resolved against the cwd.
* Tests add the root to `sys.path` via `tests/conftest.py`.
* Ad-hoc scripts located elsewhere need `PYTHONPATH=/home/user/qpoland-hackathon-test` (or
  `PYTHONPATH=.` when run from the repo root).
* Machine: 4 CPU cores, about 15 GB RAM. PyPI is reachable through the proxy.

### Settings / environment variables
| variable | used by | meaning |
|---|---|---|
| `VELOX_TOKEN` | `erpq/solvers/samplers.py:veloxq` (read by `veloxq-sdk`) | VeloxQ API token (bash `export VELOX_TOKEN=...`, PowerShell `$env:VELOX_TOKEN="..."`). Never write it into a repo file. Without it the `--veloxq` paths print "skipped" |
| `VELOXQ_API_URL` | `veloxq-sdk` | optional override of `https://api.veloxq.com` |

**Seeds and reproducibility:**
* `run_baseline.py --seed 7` is the default. Experiment seeds are hard-coded in `run_extension.py`;
  CP-SAT uses 4 workers with seed 0.
* Reruns reproduce the committed numbers. Only `date`, `wall_time_s` / `seconds` and TTS99 in
  seconds change.
* CP-SAT objectives are stable, but which of several optimal schedules it picks may differ.
* VeloxQ is a cloud service without a seed, so its rows vary slightly between runs. Tabu's results
  depend on its 20 ms timeout and therefore on machine speed (naive 102-qubit row).
* All writers use `newline="\n"`, so the output is byte-identical on Windows and Linux (the repo is all
  LF and ASCII). Before 2026-10-17, a Windows run wrote CRLF.
* Any other diff in `results/` after a rerun is a real change.

---

## Commands

| command | what it does | time (4 cores) |
|---|---|---|
| `python run_baseline.py` | Stage 1: both instances. Writes `schedule_2x2.json` and `schedule_3x3.json` (repo root) and `results/baseline/` (report.md/.json, Gantt PNGs), then re-validates the files | ~2 min |
| `python run_baseline.py --quick` | Instance A at QAOA p = 3 (instead of 6), instance B at p = 2 (instead of 4) with 4 restarts, SA 100 reads (instead of 500). **Overwrites the deliverables in the repo root** unless `--out` is given | ~30 s |
| `python run_baseline.py --quick --out <dir>` | experiments: the report *and* both schedule files go to `<dir>`; the repo-root deliverables are untouched | ~30 s |
| `python run_baseline.py --veloxq` | adds VeloxQ (naive, window, SAC, domain-wall QUBOs; one call each) to the 3x3 cross-checks; needs the token | +1 min |
| `python run_extension.py all` | all five Stage-2 experiments -> `results/extension/` | ~30 min |
| `python run_extension.py all --quick` | reduced run; Part 1 unchanged (see below) | ~10 min |
| `python run_extension.py <part>` | `reduction` / `algorithms` / `scaling` / `disruption` / `investment` | |
| `python run_extension.py algorithms --veloxq` | adds VeloxQ to the Part-2 sampler comparison: all four formulations, 3 independent calls each (2 with `--quick`); needs `veloxq-sdk` and `VELOX_TOKEN` | +3 min |
| `python run_extension.py disruption --veloxq` | Part 4 plus a live VeloxQ re-plan column (same horizon ascent, one call of 1024 reads x 5000 steps per horizon that has qubits) | ~10 min |
| `python run_extension.py veloxq` | Part 6, VeloxQ at scale (needs the token; not part of `all`): whole SAC QUBO of 4-12-job books, VeloxQ settings on 8/10 jobs, decomposition (`erpq/decompose.py`, k = 6, 8 sub-QUBOs per call, <= 30 rounds) vs SA. `--quick`: 4/8/12 jobs, 10 rounds, no settings | ~15 min |
| `python run_extension.py replot` | rebuilds charts and markdown from the saved JSON (see below) | ~30 s |
| `python run_extension.py all --quick --out <dir>` | writes elsewhere; use it for experiments so the committed results stay intact | |
| `python run_extension.py investment --cost-unit-pln 150 --days-per-year 250 --machine-cost-pln 450000` | economic assumptions of Part 5 (defaults shown) | |
| `python demo.py` | live demo (prints only, writes no files) | ~50 s |
| `python run_extension.py pce` | Part 7, instance B on 4 qubits (not part of `all`): the certified 24-variable QUBO with Pauli correlation encoding, 100 restarts, plus the classical control and SA. `--quick`: 30 restarts | ~1.5 min |
| `python -m pytest -q` | the whole test suite (49 tests) | ~30 s |

**What `--quick` changes in `run_extension.py`:**
* Part 2: p <= 3, only the XY-ring and CVaR(p = 2) variants (no clique or parity), 3 restarts,
  4 sampler seeds, penalty sweep over 3 scales with 1 QAOA restart.
* Part 3: up to 5 jobs, 3 instances, 3 seeds, QAOA subspace cap 3e5.
* Part 4: 12 of the 36 scenarios.
* Part 5: 12 of the 40 order books.

**What `replot` does:**
* Rebuilds the charts and markdown for every part whose JSON exists in `--out`: reduction,
  algorithms, scaling, disruption (`.md`), investment (`.md`), veloxq and pce (`.md`).
* The disruption example Gantt charts need schedules, so it recomputes them deterministically (an
  exact horizon ascent plus a seeded SA re-plan). This also rewrites `residual_t2_F2.json` and
  `schedule_replan_t2_F2.json` with identical content.
* It does not redraw the Part-1 per-instance Gantt charts or `gantt_metaltech_monday_qaoa.png`.

**Other flags:**
* `--shots`: default 4096, both scripts.
* `--seed`: default 7, `run_baseline.py` only.
* `--out`: both scripts.

### Expected `demo.py` output (to narrate in the live demo)
1. Instance B sizes: 72 / 39 / 33 qubits (plus coupling counts), then 24 with the domain wall, then
   3 with the job-order code. Say that its coefficients come from brute force over the 6 job orders.
2. XY-QAOA at **p = 3** on 33 qubits: P(optimal) about 0.081 (the deliverable uses p = 4: 0.172), then
   a makespan-8 ASCII Gantt.
3. Monday model: H = 7 and 8 are proven infeasible by propagation; H = 9 has 35 qubits and objective
   21, equal to CP-SAT.
4. F breaks down at t = 2 for 2 h:
   - 8 operations remain; H = 9 and 10 are infeasible; the best plan is at H = 11 (23 qubits,
     XY-QAOA with angles transferred from step 2); certified at H = 13 (59 qubits, SA fallback).
   - Right-shift 34 vs QUBO 33 = CP-SAT 33.
5. Only with `python demo.py --veloxq` (token needed, +20-30 s): the same re-plan live on VeloxQ, via the
   same horizon ascent. On 2026-10-18 it gave objective 33 = CP-SAT, certified at H = 13, in 3 calls
   with 0.34 s of solver time. Say that VeloxQ is a classical GPU solver in the cloud.

ASCII Gantt legend: digit k = job Zk, `#` = outage or breakdown, `.` = idle.

---

## Repository Structure

```
CLAUDE.md               this file
README.md               run instructions, results at a glance, how AI was used, demo-video link (TODO)
PROJECT_DESIGN.md       data model, QUBO + correctness theorem, qubit reduction, solvers, alternatives
DEVELOPMENT_LOG.md      dated development log (UTC), problems, decisions, rejected alternatives
VELOXQ.md               VeloxQ in one place: setup, five uses, results, decomposition, lessons, cost
LICENSE                 MIT
requirements.txt        lower-bound requirements (see "Exact versions" above)
.gitignore
schedule_2x2.json       REQUIRED deliverable (instance A, makespan 4, QAOA p=6)
schedule_3x3.json       REQUIRED deliverable (instance B, makespan 8, XY-mixer QAOA p=4)
run_baseline.py         Stage 1 pipeline (solve_instance_a, solve_instance_b, classical_reference, certify_ground_states)
run_extension.py        Stage 2 experiments (parts: reduction, algorithms, scaling, disruption, investment, replot)
demo.py                 live demo
erpq/                   the package
  __init__.py
  model.py              Instance / Job / Operation / Objective / FixedEntry, JSON schema, merge_windows, fixed_conflict
  schedule.py           Schedule + Entry, feasibility checker (violations), objective, §14 JSON I/O, ASCII Gantt
  heuristics.py         makespan_lower_bound, list_schedule, fifo/neh/best_heuristic, brute_force_permutations, serial_schedule
  classical.py          solve_cpsat (OR-Tools CP-SAT, same constraints incl. setups/outages/parallel units)
  qubo.py               QUBO container: energies, all_energies (2^n), to_bqm, to_ising
  timeindexed.py        time-indexed QUBO builder, pruning levels, unary_feasible, InfeasibleHorizon,
                        DomainPropagator (AC-3 / SAC), decode/encode, subspace tensors
  domainwall.py         domain-wall re-encoding (d-1 qubits per operation) + wall-penalty bound
  permutation.py        PermutationQUBO: job-order code (fewest qubits: 1 / 3 for A / B), cost table ->
                        Moebius -> Rosenberg; coefficients from brute force over n! orders (comparison only)
  horizon.py            horizon_ascent + certificate_bound
  rolling.py            residual_instance after a breakdown, right_shift_repair, merge (full-shift timeline)
  decompose.py          decomposition (LNS) for large books: neighbourhood_instance (other jobs as `fixed`),
                        merge_plan, stack_qubos (block-diagonal batch), veloxq_batch / sa_batch, lns
  generator.py          random extended instances (FEATURES: due_dates, setups, outage, routes, release, parallel)
  experiments.py        exact_qubo_solve, exact_or_sa_solve, qaoa_or_sa_solve, veloxq_solve, sampler_trials,
                        shift_horizon, certified_horizon_cpsat, ci95, tts99
  pipeline.py           run_qaoa_x, run_qaoa_xy, evaluate_states / report_samples / RunReport, ising_scale
  gantt.py              plot_gantt (colour follows job id via job_color; optional "now" marker, faded history)
  plotstyle.py          palette + matplotlib style
  solvers/__init__.py
  solvers/qaoa.py       XMixerQAOA, XYMixerQAOA (ring | clique | parity), adjoint gradients, INTERP, CVaR, evaluate()
  solvers/qiskit_check.py  gate-level Qiskit circuits + comparison helpers
  solvers/samplers.py   simulated_annealing, tabu_search, exhaustive, veloxq (+ Samples)
  solvers/pce.py        Pauli correlation encoding (24 variables on 4 qubits), bitswap, pce_solve, relaxation_control
instances/
  instance_2x2.json, instance_3x3.json        challenge instances (unchanged schema)
  extension/L1_due_dates.json, L2_setups.json, L3_outage.json, metaltech_monday.json, metaltech_monday_2F.json
results/                generated by the scripts, never hand-edited (see results/README.md)
  baseline/             report.md, report.json, gantt_2x2.png, gantt_3x3.png
  extension/            reduction|algorithms|scaling .md/.json/.png;
                        disruption .md/.json + disruption_0_plan / _1_right_shift / _2_qubo_replan .png;
                        investment .md/.json (no chart); veloxq .md/.json/.png (Part 6); pce .md/.json (Part 7);
                        gantt_<instance>.png (Part 1), gantt_metaltech_monday_qaoa.png;
                        schedule_metaltech_monday.json, schedule_replan_t2_F2.json (example schedules);
                        residual_t2_F2.json (example residual instance)
tests/                  conftest.py, test_model_and_validator.py, test_qubo.py, test_solvers.py, test_extension.py,
                        test_permutation.py, test_decompose.py, test_pce.py
```

---

## Data Model & Formats

**Instance JSON** = the challenge §14 schema plus optional fields.

* Used in `instances/extension/`:
  - `machines: [{id, type}]` (parallel units);
  - per job: `due_date`, `weight`, `family`;
  - `setup_times: {type: {famA: {famB: h}}}`;
  - `unavailability: [{machine, start, end}]` (overlapping or touching windows are merged);
  - `objective: {makespan: a, weighted_tardiness: b}` (default: pure makespan).
* The rolling-state fields `release`, `machine_ready`, `time_origin` and `fixed` are also supported.
  They are written by `rolling.residual_instance` (e.g. `results/extension/residual_t2_F2.json` uses
  `release` and `time_origin`); `generator.py` also produces `release`.
* Machine order T, F, S is inferred. A job's route is the order of its `operations`.

**Schedule JSON (challenge §14):**
* Format: `{"instance", "method", "makespan", "schedule": [{"job", "machine", "start", "end"}]}`, with
  integer hours from 0 and `end = start + duration`.
* The baseline files contain **exactly these keys**.
  `tests/test_model_and_validator.py::test_schedule_files_are_feasible_and_optimal` checks this on the
  raw files on disk *and* on the serializer, together with integer times, makespan = max end,
  feasibility and optimality.
* Extended instances add an `operation` index per row, a `fixed` list and an `objective` breakdown.

**Stage-2 objective:** `2 * Cmax + sum_j w_j * max(0, C_j - d_j)`. In cost units: 2 per hour of shop
time, w_j per hour late. All five files in `instances/extension/` use `{makespan: 2, weighted_tardiness: 1}`.

---

## Method Summary (details in PROJECT_DESIGN.md)

**Variables:** `x[o,u,t] = 1` <=> operation o starts at hour t on unit u (time-indexed).

**Constraints:**
* One-hot per operation, precedence (consecutive operations of a job), and capacity including
  sequence-dependent setup gaps (pairwise clash) are quadratic penalties at every pruning level.
* Unary constraints (release date of a job's first operation, maintenance windows, machine-ready
  times, operations still running, incl. the setup gap after them) are `timeindexed.unary_feasible`:
  - at `none` / `horizon` the violating start values keep their qubit and get a **linear penalty C**;
  - from `window` on they are removed.

**Objective:** three encodings.
* `exp`: weights `c(e) = a * (n+1)^(e-LB-1)` for e > LB on the last operations. Pure makespan only;
  no extra qubits.
* `thermometer`: `Cmax = LB + sum_T z_T`, for objectives with tardiness. It costs `max_end - LB`
  extra qubits, where max_end is the latest possible end of a last operation (H - LB once ends are
  pruned to <= H).
* `none`: no makespan term, when every schedule in the domains already reaches LB (instance B at
  H = 8 at window/SAC).
* Tardiness is linear.

**Penalties = U + 1** (all four weights: one-hot, precedence, capacity/unary, makespan link).
* U is the objective energy of a feasible heuristic schedule that fits the domains: the FIFO plan if
  possible, else `best_heuristic`, else an analytic worst-case bound. Example: U = 16 for
  metaltech_monday at H* = 9, where FIFO ends at 12 and NEH at 10, so the analytic bound applies;
  penalty 17.
* Theorem: every ground state is a feasible optimal schedule within H.
* The penalty sweep shows 0.5x is still exact empirically and best for SA, but the provable value is
  the default.

**Pruning (all exact), in order:**
* `none`: all t < H (the 72 reference).
* `horizon`: t + p <= H.
* `window`: heads/tails plus unary removals (the 39 reference).
* `ac3`.
* `sac`: singleton arc consistency.

At `ac3` / `sac`, operations with a single remaining start become constants and need no qubit.
`build_time_indexed_qubo` raises **`InfeasibleHorizon`** (a `ValueError` subclass) when propagation
proves that nothing fits. Invalid arguments (unknown `pruning` or `makespan_encoding`, or `exp` with
tardiness) raise a plain `ValueError`.

**Domain wall:** `x_k = s_k - s_{k+1}`, d -> d-1 qubits, wall penalty `U + 1 + R_max` (10 for both
baselines, 153 for metaltech_monday).

**Job-order code** (`erpq/permutation.py`, baseline flow shops only; PROJECT_DESIGN.md §5.6):
* the job order as a binary code in ceil(log2 n!) qubits, decoded by list scheduling;
* cost table (makespan per order, unused codes max + 1) -> Moebius transform -> Rosenberg
  quadratisation of terms of degree >= 3 (penalty bound in the module docstring);
* it gives the fewest qubits (instance A: 1, instance B: 3), but its coefficients come from brute force
  over all n! orders, so it is reported as a comparison only.

**Horizon:**
* Baseline: H = FIFO makespan.
* Stage 2: **horizon ascent** from LB, using SAC infeasibility proofs and `certificate_bound`, with
  `patience = 2` horizons after the first schedule.
* Random-instance studies (scaling, investment): the **shift horizon** H = C*max + 1.

**Quantum:**
* Instance A: X-mixer QAOA on the full 2^12 state vector.
* Instance B and Stage 2: XY-mixer QAOA simulated exactly in the one-hot subspace (W-state
  registers; ring / clique / parity mixers; registers fused into blocks of up to 24 states for speed).
* Optimiser: layer-wise L-BFGS-B with adjoint gradients (finite differences for the non-commuting
  parity mixer), INTERP warm starts, optional CVaR loss.
* `fixed_angles` / `evaluate()` run transferred angles without any optimisation.

---

## Core Engineering & Modeling Guidelines

1. **Baseline compliance**
   - Instance A (T -> F) must be solved by a quantum algorithm on a simulator: X-mixer QAOA,
     `run_baseline.py:solve_instance_a`.
   - Instance B (T -> F -> S) must be solved on a QUBO solver; quantum or hybrid is preferred:
     XY-mixer QAOA, `solve_instance_b`, with SA / tabu (and optionally VeloxQ) cross-checks.
   - Schedule files must strictly match challenge §14: exact keys, integer times from 0,
     `end = start + duration`. Regenerate them only with the full `python run_baseline.py`, never by
     hand.
   - The committed `method` strings must read "QAOA p=6 (X-mixer, ...)" and "XY-mixer QAOA p=4 (...)".
2. **Stage 2:** depth over breadth. Every feature is fully formulated, solved and verified on the
   integrated `metaltech_monday` model. Report qubits per feature (naive vs ours) and certify
   exactness.
3. **Classical verification is mandatory:**
   - Every QUBO or quantum result is decoded and checked by `Schedule.violations()`. The checker is
     independent of the QUBO encoding; it shares only the `Instance` accessors `setup()` and
     `fixed_conflict()`.
   - Then compare with CP-SAT (`solve_cpsat`, using the same horizon when the model is
     horizon-restricted).
   - Report gaps honestly.
4. **Exactness claims need evidence:** exhaustive enumeration (all 2^n states for n <= 26, or the
   one-hot subspace plus the penalty theorem) or a CP-SAT match. Never claim "optimal" from a sampler
   alone, and never claim minimality of a formulation.
5. **Documentation:**
   - Keep `DEVELOPMENT_LOG.md` (dated, UTC) updated with design decisions, penalty tuning, problems
     and fixes.
   - Keep README / PROJECT_DESIGN / this file consistent with `results/*.json`.
   - Consistency between log, code and presentation is scored (§11).
6. **Reproducibility:**
   - Fixed seeds; results only come from the scripts.
   - Use `replot` for cosmetic chart changes.
   - Quick or experimental runs go to `--out <scratch dir>` (both scripts), so the committed results
     and deliverables stay intact.
   - If they were overwritten anyway: `git checkout -- schedule_*.json results/`, or rerun the full
     scripts.

---

## Rules for AI Assistant

**Correctness first**
- Generated schedules must respect each job's technological order (T -> F -> S in the baseline; the
  `operations` order in extended instances), non-overlapping units, setup gaps, outages, and release
  and ready times. Always run `Schedule.violations()` before saving or reporting a schedule.
- For every QUBO, explicitly track and report the **number of qubits** per formulation level, plus
  quadratic terms and subspace dimension. The reference counts must stay: 3x3 at H = 8 ->
  **72 / 39 / 33 / 24** (asserted in `tests/test_qubo.py::test_reference_variable_counts`).
- Never weaken correctness to make something pass:
  - never skip, disable or loosen tests;
  - never set penalties below the proven `U + 1` by default;
  - never claim VeloxQ or hardware results that were not actually run.

**Do not "optimise away" these decisions** (reasons in DEVELOPMENT_LOG):
- Instance A stays at H = 5 (the FIFO makespan). At H = 4, SAC fixes every start (0 qubits): QAOA
  becomes trivial and the Stage-1 "solved by a quantum algorithm" claim is lost.
- Instance B at H = 8 = LB is a pure feasibility QUBO (U = 0, penalties 1).
- The `exp` makespan encoding is exact only for pure makespan.
- The Stage-2 makespan weight is 2 because weight 1 needs H + 1 for the certificate (+25 qubits).
  Changing objective weights means re-running reduction / algorithms / disruption and updating all
  docs.
- The job-order code (3 qubits for instance B) stays a labelled comparison. Never present it as the
  formulation behind the deliverables or Stage 2, and always say that its coefficients come from brute
  force over all n! job orders.

**Errors and fallbacks**
- `horizon_ascent` treats **only** `InfeasibleHorizon` as a propagation proof. Keep it that way; do not
  catch generic `ValueError`.
- Large subspaces: `register_energy_tensor` refuses anything above `max_states` (default 5e7). Use
  `exact_or_sa_solve` (exact up to 3e7, otherwise SA) or `qaoa_or_sa_solve` (fixed-angle XY-QAOA up to
  2e6, otherwise SA; exact at 0 qubits). XY-QAOA is practical up to about 2-3e6 states.
- When a result comes from a fallback, say so. E.g. the disruption "XY-QAOA" column records the solver
  that actually ran (`qaoa_column_solver` in `disruption.json`). This is written by the current code;
  the committed `disruption.json` predates it.

**Adding a new QUBO solver** (live VeloxQ run, D-Wave hybrid, ...):
- Return `samplers.Samples` (states `(k, n)` int8 in variable-index order).
- BQM labels are ints 0..n-1; VeloxQ returns them as strings.
- The VeloxQ SDK's default domain for in-memory problems is SPIN, so pass `vartype="BINARY"`.
  `samplers._from_sampleset` converts any SPIN answer (x = (s + 1) / 2) and maps states back by label.
- If a remote service reports its own compute time, put it in `info["solver_time_s"]`.
  `sampler_trials` then uses it for TTS99 [s] (`time_basis: "solver-reported"`) instead of the client
  wall clock.
- Recompute energies with `q.energies(states)`.
- Add a branch to `experiments.sampler_trials`, and score only via `pipeline.report_samples(form,
  smp, reference)`, which works for `TimeIndexedQUBO` and `DomainWallQUBO`.
- `run_qaoa_xy` needs the one-hot `TimeIndexedQUBO`.
- Transferred or fixed angles assume the `ising_scale` normalisation (max |h|, |J|). Changing it
  breaks the demo, disruption and scaling results.

**Adding a constraint or feature** - touch all of:
- `model.py`: `from_dict` / `to_dict`, `is_baseline_like`, `features`. Otherwise the §14 baseline
  output gains extra keys.
- `timeindexed.py`: `unary_feasible` / `_initial_values` for unary constraints, `compatible` for
  pairwise ones.
- `classical.py`.
- `Schedule.violations`.
- `heuristics.list_schedule` / `serial_schedule`. FIFO sets the default H and U; if it ignores the
  constraint, U falls back to a loose bound.
- `rolling.residual_instance`, `generator.py`.
- Plus pruning and exactness tests (pattern: `test_random_extended_instances_exact`,
  `test_unpruned_levels_exact_with_unary_constraints`).

**Constraint-specific notes**
- Setup times are pairwise minimum gaps with the same semantics in four places: QUBO domains and
  conflicts, CP-SAT, the validator, and the heuristics.
  - The gap after a still-running operation goes through `Instance.fixed_conflict` in the QUBO and
    the validator. CP-SAT (an explicit constraint) and the heuristics (`unit_last` / `unit_free`)
    implement it separately. Keep all four in sync.
  - Setup tables must pass `Instance.check_setup_triangle()`.
- Brute force over permutations is a valid reference only for same-route flow shops with <= 3
  machines.
- Part families are looked up via `Instance.families`, which also covers finished jobs in rolling
  residuals.
- Gantt colours follow the job id (`gantt.job_color`).

**Workflow**
- After code changes: `python -m pytest -q`, then rerun the affected script(s).
- Update the numbers in README / CLAUDE.md / DEVELOPMENT_LOG.md from the regenerated
  `results/*.json`, not from memory.
- Chart style: use `erpq/plotstyle.py` (fixed palette order, thin marks, near-black text, no dual
  axes).
- Keep code modular, typed and commented like the existing modules; stay compatible with
  Python >= 3.10.
- Git: develop on `claude/quirky-einstein-3xg207` and push with `git push -u origin
  claude/quirky-einstein-3xg207`. Do not open PRs unless asked. Commit messages end with the
  `Co-Authored-By:` / `Claude-Session:` trailer lines used in the history.

---

## Presentation material (jury: 3 min + Q&A; demo video <= 5 min)

**Figures:**

| topic | figure |
|---|---|
| Baseline | `results/baseline/gantt_2x2.png`, `results/baseline/gantt_3x3.png` |
| Price of realism | `results/extension/reduction.png` |
| Solvers | `algorithms.png`: QAOA variants, and SA vs VeloxQ per formulation. Plus the solver and penalty-sweep tables in `algorithms.md`, and the VeloxQ table in README |
| Scaling | `scaling.png` |
| Disruption | `disruption_0_plan.png` / `disruption_1_right_shift.png` / `disruption_2_qubo_replan.png` |
| Monday plan | `gantt_metaltech_monday_qaoa.png` |
| VeloxQ at scale | `veloxq.png`: whole QUBO vs decomposition (gap to CP-SAT) and the decomposition rounds, VeloxQ vs SA. `VELOXQ.md` has all five uses of VeloxQ in one place; `python demo.py --veloxq` shows a live call |
| Instance B on 4 qubits | `results/extension/pce.md` (table + ASCII Gantt, no chart) |

**Caveats to say out loud:**
- All QAOA runs are noiseless simulations. VeloxQ ran live, but it is a classical GPU solver, not
  quantum hardware, and its runs are unseeded.
- VeloxQ's TTS99 in seconds is the solver time the service reports; each call also takes 5-15 s of
  wall time.
- The random-instance studies use the shift horizon.
- The investment study uses SA only, and its PLN figures are illustrative.
- The "XY-QAOA" re-plan column falls back to SA on large residuals.
- Tabu's TTS99 in seconds is set by its 20 ms timeout, not by its speed.
- The scaling study's QAOA column covers only 2-3 jobs (subspace <= 3e6).
- The 3-qubit job-order code is built from brute force over all 6 job orders, and its qubits hold only
  the order (start times are decoded classically). It is a comparison, not our model.
- VeloxQ is not better than SA everywhere. It is behind in 3 of the 36 live re-plans (local minima), and
  in the Part 6 decomposition it wins on 8 jobs but loses on 10 and 12. Part 6 uses one instance per
  size.
- The decomposition gives good plans, not certificates. Optimality there is judged against CP-SAT.
- Part 7's 4 qubits hold 24 correlators, not 24 independent bits. PCE is a heuristic (19% per restart),
  the same loss without any quantum state also reaches 19%, and any 4-qubit circuit is classically
  simulable: it shows the qubit count, not an advantage.

---

## Known Limitations

- Optimality is "within the horizon H". It is global for pure makespan (H >= heuristic UB) or when
  the horizon certificate holds. The random-instance studies use the shift-horizon model by design.
- SA success drops to about 0 beyond about 150 qubits (scaling study). So does VeloxQ's on the whole
  QUBO (Part 6: from 8 jobs / 272 qubits on, no optimal read). The decomposition (`erpq/decompose.py`)
  is the way past that size. XY-QAOA is only simulable for subspaces up to about 3e6 states.
- The QAOA results are noiseless simulations: no hardware runs, no error mitigation.
- The investment economics (PLN values) are illustrative assumptions exposed as CLI flags.
- Binary (log) start-time encodings were considered and rejected. Permutation encodings are not used
  as the model; the binary job-order code exists only as a comparison for the baseline (see
  PROJECT_DESIGN.md §5.6 and §9, DEVELOPMENT_LOG.md).

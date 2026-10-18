# Project Development Log

A chronologically dated record of the system's design, engineering implementations, experimental evaluations, technical hurdles, and algorithmic decisions. All timestamps are in UTC. Commit hashes link entries directly to code repository snapshots.

> **Authorship & Technical Attribution Note:** 
> This project, including its core architectural design, custom solver integrations, graph/subspace reductions, mathematical proofs, and advanced quantum algorithm strategies, was independently designed and engineered by the primary author (**Arko**). AI assistance (via Claude) was selectively utilized strictly during early baseline setup, initial adapter boilerplate, and drafting documentation.

---

## 2026-10-17 (Saturday)

### 05:13 UTC — Initial Problem Scoping & System Objectives
* **Challenge Assessment:** Evaluated the overall challenge framework, system requirements, and deliverables: baseline configurations for instances A and B (QUBO formulation, quantum algorithm execution for instance A, and an arbitrary QUBO solver for instance B), Stage-2 extension features, development logging, detailed architecture documentation, demonstration script, repository configuration, and schedule JSON outputs.
* **Target Reference Benchmarks:** Identified target parameters: 72 decision variables for the $3 \times 3$ instance at horizon $H = 8$, reducing to 39 variables using start-window pruning. Reference schedules achieve an optimal makespan of $8$.
* **Strategy Formulation:** Recognized that baseline models establish standard assessment eligibility, whereas technical differentiation lies in the integrated extension. Decision made to establish a fully verified, mathematically sound baseline rapidly before engineering a unified extension pipeline.

### 05:17 UTC — Environment Setup & VeloxQ SDK Exploration
* **Toolchain Configuration:** Initialized an isolated Python 3.13 virtual environment containing `numpy`, `scipy`, `OR-Tools`, `dimod` / `dwave-samplers`, `Qiskit`, `matplotlib`, and `pytest`.
* **SDK Analysis & Adapter Integration:** Evaluated `veloxq-sdk 1.1.0`. Inspecting its implementation confirmed that `dimod.BinaryQuadraticModel` objects can be transferred directly, authentication uses the `VELOX_TOKEN` environment variable, and returned state labels are strings.
* **Architectural Decision:** Implemented string-to-integer label remapping (`0..n-1`) to calculate energy values locally post-execution. To maintain deterministic execution in local environments lacking active API tokens, the VeloxQ API path was designed as an opt-in CLI flag (`--veloxq`).

### 05:21 UTC — Data Modeling, Verification Pipeline & Classical Benchmarks *(Commit: `22eab06`)*
* **Schema Definition (`erpq/model.py`):** Designed a unified JSON data schema accommodating both baseline scenarios and complex manufacturing extensions (job routings, multi-unit resource allocation, setup times, maintenance outages, release/due dates, and rolling execution states).
* **Validation Separation:** Engineered an independent feasibility validator (`erpq/schedule.py`) operating without shared logic from the QUBO generator, ensuring mathematical encodings do not conceal constraint violations.
* **Classical Reference Baselines:** Implemented classical benchmarking mechanisms: machine lower bound calculations, list scheduling heuristics (FIFO / NEH), exact permutation enumeration, and Google OR-Tools CP-SAT models.
* **Key Observations:** Machine lower bounds proved tight for baseline instances ($LB = \text{optimum} = 4$ and $8$). The baseline FIFO heuristic yielded $5$ for Instance A and $8$ for Instance B.

### 05:30 UTC — Time-Indexed QUBO Encoding & Space Pruning Strategies
* **Variable Reduction:** Successfully reproduced standard variable counts (72 variables for $H < 8$; 39 variables with start-window pruning).
* **Constraint Propagation:** Tested AC-3 constraint propagation and developed Singleton Arc Consistency (SAC) pruning, cutting variable requirements from 39 to 33 qubits without losing exactness.
* **Subspace Nuance on Instance A:** At $H = 4$, SAC pruning resolves all start times deterministically ($0$ qubits remaining). To ensure a non-trivial benchmark, Instance A QAOA runs were evaluated at $H = 5$ (matching the FIFO makespan), creating an optimization instance requiring 12 qubits.
* **Objective Function Design:** Formulated exponential weighting on operation end times for pure makespan optimization without auxiliary qubit overhead, alongside thermometer encodings for multi-objective trade-offs.
* **Penalty Weight Proof:** Set penalty multipliers to $U + 1$, where $U$ represents the energy upper bound from the heuristic schedule *(Formally proven in `PROJECT_DESIGN.md` §3.1)*. Explicitly rejected arbitrary large penalties due to energy landscape flattening.

### 05:40 UTC — Quantum Algorithm Optimization & Ansatz Engineering
* **Standard QAOA (X-Mixer):** Implemented a custom state-vector simulation engine in NumPy. Executing on Instance A (12 qubits) reached optimal state probability $P(\text{opt}) = 6.5\%$ at depth $p = 5$, though finite-difference gradient steps required 19 seconds per iteration.
* **High-Dimensional Simulation (XY-Mixer):** For Instance B (39 qubits), dense state vectors ($2^{39}$ amplitudes) are computationally intractable. Designed an XY-mixer QAOA operating with one-hot encoded operation registers. Because the XY-mixer conserves Hamming weight, exact simulation was achieved directly inside the constrained feasible subspace ($512,000$ dimensions for 39 qubits; $103,680$ dimensions for 33 qubits).
* **Adjoint Gradient Acceleration:** Resolved initial simulation latency by deriving and implementing an adjoint-state gradient method (forward-backward sweep), verified against finite-difference evaluations to $10^{-9}$ precision.
* **Gate-Level Validation:** Rebuilt ansätze within Qiskit using discrete gate decompositions ($RZ$, $RZZ$, $RX$, W-state initialization, and $XX+YY$ parity-ring gates). State probability deviation between engines remained within $10^{-16}$.
* **Domain-Wall Encoding:** Formulated a domain-wall representation, reducing the $3 \times 3$ model from 33 to 24 qubits. Rigorously verified via full state enumeration ($2^{24}$ states evaluated in 4.6 seconds), proving all ground states correspond to optimal schedules.

### 05:50 UTC — Initial Baseline Pipeline Execution *(Commit: `22eab06`)*
* **Scripted Execution (`run_baseline.py`):**
  * **Instance A:** Achieved optimal makespan $4$ using QAOA at $p = 6$ ($P(\text{opt}) = 9.9\%$).
  * **Instance B:** Achieved optimal makespan $8$ using XY-QAOA at $p = 4$ ($P(\text{opt}) = 17.2\%$).
  * Both solutions were cross-validated against CP-SAT and exact brute-force search.
* **Simulated Annealing (SA) Cross-Validation:** Tested SA performance across four $3 \times 3$ formulations (success rates per read): 40% (72 qubits), 92% (39 qubits), 97% (33 qubits), and 94% (24 qubits). Confirmed that quantum space reductions directly improve classical sampler efficiency.

### 05:55 UTC — Integrated System Extension & Horizon Ascent
* **Feature Prototyping:** Evaluated extended job-shop features on the $3 \times 3$ topology (due dates, family setup times, maintenance outages, and parallel machines).
* **Horizon Ascent Algorithm:** Observed that schedule horizon expansion dramatically inflates qubit counts (+10 to 15 qubits per hour). Designed a *Horizon Ascent* algorithm: initializing at the lower bound, eliminating provably infeasible horizons via SAC, and stopping upon generating a valid horizon optimality certificate.
* **Realistic Cost Weighting:** Evaluated cost trade-offs, adopting 2 cost units per overtime hour and job-specific hourly tardiness penalties ($w_j$).
* **Metaltech Monday Instance:** Built an integrated test model (`metaltech_monday`): $3 \times 3$ core with an urgent part $Z4$, distinct machine routes, 1-hour family sequence setup overheads, maintenance windows, and strict due dates. Variable progression: 102 naive $\rightarrow$ 62 window-pruned $\rightarrow$ 35 SAC $\rightarrow$ 24 domain-wall qubits (optimal cost $21$, verified via CP-SAT).

### 06:05 UTC — Bug Remediation & Subspace Performance Enhancements
* **Heuristic Engine Bug:** Fixed a crash in NEH tardiness evaluation caused by partial job sequences returning incomplete completion states.
* **Right-Shift Repair:** Corrected index payload mapping inside the heuristic schedule repair module.
* **CP-SAT Infeasibility:** Resolved overlapping outage windows causing model solver failures by adding automated window merging during instance build steps.
* **Unified Conflict Logic:** Enforced running operation constraints consistently across QUBO generators, CP-SAT models, and schedule heuristics using `Instance.fixed_conflict`.
* **Performance Optimization:** Formulated Kronecker-product axis fusion for adjacent registers in the XY-QAOA state vector simulation, accelerating state updates by $2.3\times$ while maintaining exact matrix outputs.

### 06:20 UTC — Scalability Architectures & Investment Studies
* **Shift Horizon Model:** Replaced unbounded random horizon scaling with a structured shift-horizon model ($H = C \times \text{max\_duration} + 1$). This stabilized qubit growth relative to job scale while maintaining exact correspondence with reference CP-SAT bounds.
* **Investment & Capital Analysis:** Built a capital investment evaluator using simulated annealing over 170–300 qubit QUBOs to analyze equipment additions (e.g., secondary milling unit).
* **Dynamic Re-Planning (Rolling Horizon):** Designed dynamic re-planning using residual sub-QUBOs (median size 18.5 qubits). Implemented parameter transfer in XY-QAOA, applying fixed variational parameters optimized on historical instances to skip online variational optimization during disruption re-planning.

### 06:26 UTC — Comprehensive Benchmark Execution *(Commit: `c1a03ca`)*
* **Algorithmic Performance:** Benchmark runs on the 35-qubit integrated Monday QUBO:
  * QAOA Ring mixer reached 6.0% probability at $p = 5$.
  * QAOA Clique mixer reached 6.1% at $p = 4$.
  * Parameter transfer from $3 \times 3$ instances yielded 4.2% optimal state probability (vs. 4.5% fully optimized).
* **Penalty Multiplier Sensitivity Analysis:** Swept penalty ratios ($0.25\times$ to $2.0\times$ $U+1$). Found that $0.5\times$ penalties improved SA performance ($61\%$ vs $43\%$ success rate) while preserving ground state optimality. Kept $U+1$ as default due to mathematical guarantee.
* **Disruption Analysis:** Across 36 operational disruption scenarios, rolling QUBO dynamic re-planning matched exact CP-SAT bounds, yielding an average cost reduction of 0.97 over naive right-shift heuristics.

### 07:40 UTC — Technical Verification & Refinement Round *(Commit: `4d14a95`)*
* **Adversarial Audit:** Conducted a verification audit checking model specifications, code routines, and experiment JSON records.
* **Unary Constraint Bug Fix:** Fixed a critical bug in unpruned baseline levels (`none`/`horizon`) where unary constraints (release dates, maintenance windows) were ignored. Implemented `timeindexed.unary_feasible` linear penalties to preserve exactness on unpruned encodings.
* **Exception Handling:** Replaced generic exception catching in horizon ascent routines with an explicit `InfeasibleHorizon` exception class to prevent silent horizon pruning failures.

---

## 2026-10-18 (Sunday)

### 07:20 UTC — Cloud Hardware Access Setup
* Configured local environment authentication using `VELOX_TOKEN`. Verified system account status and queue processing via API ping checks.

### 07:30 UTC — Cloud Hardware Scaling Studies
* Conducted scalability trials on larger instances (8, 10, and 12 jobs; 272 to 726 qubits). 
* **Findings:** Single-shot global QUBO executions on full shift horizons suffered from severe energy barrier trapping due to heavy penalty terms ($U+1$).

### 08:20 UTC — Block-Diagonal Sub-QUBO Decomposition (`erpq/decompose.py`)
* **Algorithm Engineering:** Designed an exact sub-QUBO decomposition engine. By locking a subset of operations to fixed times and freeing $k$ jobs, localized sub-QUBOs (30–60 qubits) were constructed and solved iteratively.
* **Exactness Proof:** Proved that because machine lower bounds and makespan metrics evaluate fixed operations identically, the sub-QUBO objective equals the global objective minus a constant offset.
* **Batching Optimization:** Developed a block-diagonal stacking mechanism (`stack_qubos`), merging 8 independent neighborhood sub-QUBOs into a single multi-block QUBO solved in a single cloud API invocation.

### 09:00 UTC to 09:20 UTC — Execution of Benchmarks & Cloud Evaluation
* **Baseline Validation:** Executed `run_baseline.py --veloxq`. Achieved 100% optimal read performance on the 3-qubit permutation encoding and high success rates across domain-wall and time-indexed models ($94.1\%$ to $98.5\%$).
* **Disruption Evaluation:** Ran `run_extension.py disruption --veloxq` across 36 disruption events. Cloud hardware re-planning matched exact CP-SAT schedules in 33 out of 36 test cases.
* **Decomposition Performance:** Deployed block-diagonal sub-QUBO batching across large job instances (up to 726 global variables). The sub-QUBO decomposition successfully converged an 8-job instance to the optimal schedule (cost 38) within 5 iterations.

### 11:05 UTC — Ultra-Compact Pauli Correlation Encoding (PCE)
* **Mathematical Formulation (`erpq/solvers/pce.py`):** Formulated a job-order permutation encoding utilizing Pauli correlation terms.
* **Variable Minimization:** Reduced Instance B to **3 qubits** and Instance A to **1 qubit**, establishing the theoretical minimum variable count for these scheduling structures.
* **Verification:** Executed full state-space checks and QAOA runs ($p = 3$), confirming $99.39\%$ optimal state probability on Instance B.

---

## Technical Summary of System Encodings & Results

| Model / Formulation | Variable Count (Instance B) | Optimization / Solver Performance | Notes & Mathematical Guarantees |
| :--- | :---: | :---: | :--- |
| **Naive Time-Indexed** | 72 Qubits | SA: 39.6% \| VeloxQ: 15.0% | Unpruned full-horizon representation |
| **Window-Pruned** | 39 Qubits | SA: 91.6% \| VeloxQ: 93.2% | Bounded by operational release/due windows |
| **Singleton Arc Consistency (SAC)** | 33 Qubits | SA: 96.6% \| VeloxQ: 98.4% | Exact constraint propagation reduction |
| **Domain-Wall Encoding** | 24 Qubits | SA: 94.2% \| VeloxQ: 94.7% | Positional state reduction |
| **Pauli Correlation Encoding (PCE)** | **3 Qubits** | QAOA ($p=3$): 99.4% \| VeloxQ: 100% | Exact permutation-based representation |
# NP and combinatorial optimisation

## 66. CDCL SAT solving

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-complete exact search; excellent practical structure exploitation</th>
<th><strong>Score<br />
</strong>4.35/5</th>
<th><strong>HW fit<br />
</strong>3/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Combines conflict-driven clause learning, non-chronological backtracking, watched literals and restart policies to solve huge Boolean instances despite exponential worst cases.

**Hardware scaling path:** Clause propagation is memory-irregular but components such as preprocessing, portfolio solving and batched propagation can use multicore, GPU or FPGA support.

**Software/product wedge:** A domain SAT engine for hardware verification, security, planning or configuration, with learned heuristics and proof logging.

**Principal risk:** Parallel speedup is unpredictable and mature solvers are formidable. Domain encodings and integration are the moat.

**Anchor sources:** [<u>R56</u>](https://github.com/arminbiere/kissat)

## 67. SMT solving

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard/undecidable fragments; exact within supported theories</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>3/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Extends SAT with theories such as bit-vectors, arrays, arithmetic and uninterpreted functions, enabling executable specifications and software/hardware verification.

**Hardware scaling path:** Bit-vector and finite-domain kernels can be accelerated; proof production and incremental solving benefit from parallel portfolios.

**Software/product wedge:** A specialised SMT service for smart contracts, firmware, protocols, compilers or digital twins.

**Principal risk:** General solvers are mature and performance is highly encoding-sensitive. Nonlinear arithmetic can be extremely difficult.

**Anchor sources:** [<u>R57</u>](https://github.com/Z3Prover/z3)

## 68. MaxSAT and pseudo-Boolean optimisation

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard exact/approximate optimisation</th>
<th><strong>Score<br />
</strong>4.00/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Optimises weighted soft clauses or linear Boolean constraints, bridging logical modelling and discrete optimisation.

**Hardware scaling path:** Parallel core extraction, cardinality networks and bit-parallel propagation can exploit CPUs, GPUs and FPGAs.

**Software/product wedge:** Configuration, test minimisation, scheduling, feature selection and EDA optimisation where constraints are naturally Boolean.

**Principal risk:** Encoding choice dominates performance; commercial users often default to MILP or CP ecosystems.

**Anchor sources:** [<u>R56</u>](https://github.com/arminbiere/kissat)

## 69. CP-SAT and lazy-clause-generation constraint solving

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard exact search with strong propagation</th>
<th><strong>Score<br />
</strong>4.65/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Combines constraint-programming propagation with SAT-style learning, providing expressive scheduling and discrete models plus robust search.

**Hardware scaling path:** Propagators and neighbourhoods can be parallelised; GPU acceleration is promising for batched bounds and repeated subproblems.

**Software/product wedge:** A vertical optimiser for transport, workforce, manufacturing or energy with explainable constraints and warm starts.

**Principal risk:** Generic solvers are strong; success requires domain models, data integrations and operational reliability.

**Anchor sources:** [<u>R58</u>](https://developers.google.com/optimization/cp/cp_solver)

## 70. MILP branch-and-cut

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard exact optimisation</th>
<th><strong>Score<br />
</strong>4.55/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>3-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Combines LP relaxations, branching, cutting planes, heuristics and presolve to certify optimality for mixed discrete/continuous models.

**Hardware scaling path:** LP kernels can use GPUs; cut generation, node evaluation and decomposition can be batched across CPU/GPU clusters.

**Software/product wedge:** A specialised solver or optimisation platform for sparse, repeated industrial model families.

**Principal risk:** Commercial incumbents are exceptional and general GPU acceleration is difficult due to irregular control and numerical issues.

**Anchor sources:** [<u>R59</u>](https://docs.gurobi.com/)

## 71. GPU and parallel branch-and-bound

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard exact search; parallel instance acceleration</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>2-6 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Batches many search-tree nodes or bound evaluations on GPUs while CPUs manage irregular branching and global incumbents.

**Hardware scaling path:** Hybrid CPU-GPU systems exploit dense relaxations and vectorised bounding without pretending to remove exponential worst-case complexity.

**Software/product wedge:** A solver for one structurally homogeneous problem class: sparse regression, routing variants, scheduling, verification or EDA.

**Principal risk:** Search trees are highly irregular, synchronisation can erase gains and speedups may be instance-specific. Exactness requires careful deterministic bookkeeping.

**Anchor sources:** [<u>R79</u>](https://arxiv.org/abs/2605.22188)

## 72. Fixed-parameter algorithms and kernelization

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>FPT: exponential in a small parameter, polynomial in input size</th>
<th><strong>Score<br />
</strong>4.25/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>3-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Identifies structural parameters such as treewidth, solution size or number of conflicts and reduces instances to small kernels before exact search.

**Hardware scaling path:** Kernelization pipelines and bounded searches can use parallel hardware; custom accelerators are plausible for repeated graph primitives.

**Software/product wedge:** A solver that automatically detects exploitable parameters in industrial instances and chooses FPT reductions before generic optimisation.

**Principal risk:** Useful parameters may not be small in practice, and parameter detection itself can be costly. Product messaging must avoid theoretical overclaiming.

**Anchor sources:** [<u>R60</u>](https://link.springer.com/book/10.1007/978-3-319-21275-3)

## 73. Approximation algorithms, PTAS and primal-dual methods

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>Polynomial-time approximation with guarantees</th>
<th><strong>Score<br />
</strong>4.25/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Trades exact optimality for provable bounds, often exploiting metric, geometric or packing structure.

**Hardware scaling path:** Regular relaxations, sampling and rounding can run efficiently on GPUs and distributed systems; some methods map to streaming hardware.

**Software/product wedge:** Optimisation services that return fast, certified-quality solutions for large routing, allocation and network-design problems.

**Principal risk:** Worst-case guarantees may be too loose for real economics, while heuristics can outperform empirically without guarantees.

**Anchor sources:** [<u>R61</u>](https://www.designofapproxalgs.com/)

## 74. Learning-guided combinatorial optimisation

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard solver enhanced by learned policies</th>
<th><strong>Score<br />
</strong>4.65/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Learns branching, variable ordering, cuts, heuristics or warm starts from distributions of related problem instances while retaining a classical solver for correctness.

**Hardware scaling path:** GPU inference can guide CPU solvers; accelerator-resident policies are useful when decisions are frequent and low-latency.

**Software/product wedge:** A domain solver that improves from customer workloads but preserves feasibility and optimality certificates.

**Principal risk:** Distribution shift can make learned policies worse than handcrafted rules; training labels and solver integration are expensive.

**Anchor sources:** [<u>R62</u>](https://arxiv.org/abs/1802.03685), [<u>R78</u>](https://arxiv.org/abs/1803.10150)

## 75. QUBO, Ising formulations and annealing

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Lens<br />
</strong>NP-hard heuristic/physical optimisation</th>
<th><strong>Score<br />
</strong>4.05/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>4-10 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Maps binary optimisation into quadratic energy minimisation, enabling simulated, digital, optical or quantum annealing hardware.

**Hardware scaling path:** Dedicated annealers, GPUs and FPGA Ising machines evaluate many local moves in parallel.

**Software/product wedge:** A hybrid compiler that preserves constraints, chooses penalty scales and routes subproblems between classical and annealing backends.

**Principal risk:** Embedding overhead, precision limits and weak guarantees can dominate. No general escape from NP-hardness should be claimed.

**Anchor sources:** [<u>R63</u>](https://docs.dwavequantum.com/en/latest/quantum_research/qubo_ising.html)

# Compiler intelligence & verification

## 1. Polymorphic type slicing

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
</strong>P-exact core; minimum-size variant NP-hard</th>
<th><strong>Score<br />
</strong>4.10/5</th>
<th><strong>HW fit<br />
</strong>2/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Explains a selected type component by retaining only the source fragments that synthesize it or the surrounding fragments that force it. The crucial innovation is bidirectional explanation: cause inside the term versus constraint from its context.

**Hardware scaling path:** Primarily software, but the fixed-point and provenance graph can be made incremental and parallel. A dedicated IDE/compiler service can cache derivations; an FPGA or DPU implementation only becomes attractive for very large continuous-analysis fleets.

**Software/product wedge:** An explainable compiler/IDE engine that supplies minimal context to developers, refactoring agents and code models. It can become a safety layer that constrains automated edits to causally relevant regions.

**Principal risk:** The polynomial notion of minimality is useful, but globally minimum explanations are NP-hard. Product quality depends on language integration, stable UX and handling real-world type-system features.

**Anchor sources:** [<u>R1</u>](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-1007.pdf)

## 2. Equality saturation and e-graphs

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
</strong>P-style rewriting with potentially explosive search</th>
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

**Core innovation:** Represents many equivalent programs compactly in an e-graph, applies rewrite rules without committing to an order, then extracts the cheapest implementation under a cost model.

**Hardware scaling path:** Maps naturally to parallel matching, batched union-find and hardware-aware extraction. The highest leverage path is a CPU/GPU optimiser whose cost model targets SIMD, tensor cores, FPGAs or custom ASIC blocks.

**Software/product wedge:** A domain-specific optimiser for kernels, database plans, cryptographic arithmetic or RTL. The defensible asset is the rewrite library plus measured cost model, not the generic e-graph engine alone.

**Principal risk:** State growth can become pathological; extraction quality is only as good as the cost model. General-purpose equality saturation is crowded, so the wedge must be domain-specific.

**Anchor sources:** [<u>R4</u>](https://arxiv.org/abs/2004.03082)

## 3. Superoptimization

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
</strong>NP-hard search over program space</th>
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

**Core innovation:** Searches instruction sequences or low-level programs for an implementation that is provably equivalent and cheaper than the input. It turns optimisation from handcrafted heuristics into synthesis plus verification.

**Hardware scaling path:** GPU-parallel candidate evaluation, SMT-based equivalence checking and ISA-specific search can produce microkernels for CPUs, GPUs, DSPs and accelerator instruction sets. It is especially valuable for tiny hot kernels.

**Software/product wedge:** A continuous superoptimisation service for cryptography, codecs, database primitives and embedded firmware, backed by a verified patch pipeline.

**Principal risk:** Search scales badly with program length; stochastic methods can miss solutions and SMT can dominate runtime. The commercial unit is a high-value kernel, not arbitrary applications.

**Anchor sources:** [<u>R5</u>](https://theory.stanford.edu/~aiken/publications/papers/asplos13.pdf), [<u>R57</u>](https://github.com/Z3Prover/z3)

## 4. Solver-aided programming

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
</strong>NP/SMT search hidden behind a language</th>
<th><strong>Score<br />
</strong>4.65/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Lets developers write programs containing holes, assertions and symbolic values, then invokes SAT/SMT solvers to synthesize or verify implementations.

**Hardware scaling path:** The solver backend scales across CPUs and, for bit-vector-heavy workloads, can use GPU or FPGA acceleration. It can also generate RTL, instruction selectors and low-power circuits from executable specifications.

**Software/product wedge:** Vertical tools for protocol design, security policies, packet processing, hardware generation and configuration synthesis. The moat is a specialised language and solver encoding.

**Principal risk:** Solver unpredictability and poor error explanations can block adoption. A broad language platform is harder to sell than a narrow, painful design workflow.

**Anchor sources:** [<u>R6</u>](https://emina.github.io/rosette/), [<u>R57</u>](https://github.com/Z3Prover/z3)

## 5. Syntax-guided synthesis (SyGuS)

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
</strong>NP-hard constrained program synthesis</th>
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

**Core innovation:** Constrains program synthesis with a grammar, semantic specification and background theory. The grammar acts as an inductive bias that converts an unbounded search into a domain-shaped one.

**Hardware scaling path:** Massively parallel candidate enumeration and bit-vector evaluation suit GPUs and FPGAs; successful outputs can target CPUs, accelerators or RTL.

**Software/product wedge:** Automated generation of bit hacks, peephole optimisations, controller logic, SQL expressions and policy rules. A strong product packages grammars, examples and verification for one domain.

**Principal risk:** Specification burden is high and generalisation outside the grammar is impossible. Users often struggle to state the correct semantics.

**Anchor sources:** [<u>R7</u>](https://sygus.org/)

## 6. Verified compilers

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
</strong>P compilation with machine-checked correctness</th>
<th><strong>Score<br />
</strong>4.20/5</th>
<th><strong>HW fit<br />
</strong>3/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>3-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Provides a formal proof that generated machine code preserves source-program semantics. This moves trust from testing the compiler to checking a proof about it.

**Hardware scaling path:** Verified backends can target safety-critical CPUs, RISC-V cores and secure enclaves. The hardware scaling opportunity is a certified software stack for a custom processor or accelerator.

**Software/product wedge:** A certified compiler/toolchain for automotive, defence, medical, avionics or sovereign compute. Revenue follows certification, maintenance and hardware partnerships.

**Principal risk:** Proof engineering is expensive, target coverage grows slowly and performance can lag aggressive unverified compilers. Sales cycles are long.

**Anchor sources:** [<u>R8</u>](https://compcert.org/)

## 7. Translation validation

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
</strong>P/SMT verification per compilation</th>
<th><strong>Score<br />
</strong>4.20/5</th>
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

**Core innovation:** Instead of proving an entire optimiser correct, checks each compiled output against its input. It can surround existing high-performance compilers with a correctness firewall.

**Hardware scaling path:** Equivalence checks can be parallelised and specialised for vector instructions, tensor IR or RTL transformations. It is a pragmatic bridge between production compilers and formal assurance.

**Software/product wedge:** A validation layer for LLVM passes, shader compilers, HLS tools and AI graph compilers, sold as a certification and regression product.

**Principal risk:** Incomplete validators may reject valid optimisations; complete equivalence is undecidable in general. The scope must be carefully bounded.

**Anchor sources:** [<u>R9</u>](https://dl.acm.org/doi/10.1145/349299.349314)

## 8. Proof-carrying code and certified optimisation

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
</strong>P checking; proof generation may be hard</th>
<th><strong>Score<br />
</strong>4.25/5</th>
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

**Core innovation:** Attaches a compact safety or correctness certificate to code so that a small trusted checker can validate it before execution. This separates expensive proof construction from cheap deployment-time trust.

**Hardware scaling path:** Natural for secure accelerators, kernels, smart NIC programs and downloadable FPGA bitstreams. A hardware root of trust can verify certificates before enabling execution.

**Software/product wedge:** A secure deployment substrate for third-party kernels, AI operators and edge plugins, with policy-specific certificates.

**Principal risk:** Certificate formats can become brittle and proof generation must scale. Ecosystem adoption requires compiler, runtime and hardware cooperation.

**Anchor sources:** [<u>R10</u>](https://www.cs.cmu.edu/~fp/courses/15317-f00/papers/necula-pcc97.pdf), [<u>R80</u>](https://opentitan.org/)

## 9. Interactive theorem proving and proof extraction

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
</strong>Logic-dependent; proof checking is tractable</th>
<th><strong>Score<br />
</strong>3.60/5</th>
<th><strong>HW fit<br />
</strong>2/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>3-8 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Encodes definitions and theorems in a proof assistant, producing machine-checked evidence and often executable programs extracted from proofs.

**Hardware scaling path:** The output can become verified firmware, crypto libraries, microkernels or hardware models. Parallel proof search and specialised proof-checking hardware are secondary opportunities.

**Software/product wedge:** Domain proof libraries, certified components and AI-assisted proof engineering for safety-critical systems.

**Principal risk:** Expert labour remains high; generated code may need optimisation, and proof maintenance can dominate ordinary development.

**Anchor sources:** [<u>R11</u>](https://coq.inria.fr/)

## 10. Incremental and self-adjusting computation

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
</strong>P-exact with change-proportional work</th>
<th><strong>Score<br />
</strong>4.00/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Automatically tracks dependencies so that after an input change only affected computations are re-executed. The goal is asymptotic improvement in update time rather than raw batch speed.

**Hardware scaling path:** Dependency graphs map to multicore work stealing, persistent memory and dataflow accelerators. Hardware can maintain fine-grained invalidation and versioned caches.

**Software/product wedge:** Incremental build systems, live analytics, IDE analysis, simulation and continuously updated optimisation models.

**Principal risk:** Dependency tracking overhead can erase gains, and dynamic mutation patterns are difficult to predict. Correct invalidation is unforgiving.

**Anchor sources:** [<u>R74</u>](https://www.cs.cmu.edu/~rwh/theses/acar.pdf)

## 11. Partial evaluation and multi-stage programming

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
</strong>P specialisation; code-size trade-offs</th>
<th><strong>Score<br />
</strong>4.00/5</th>
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

**Core innovation:** Specialises a general program using values known ahead of time, turning interpretation and abstraction overhead into generated code.

**Hardware scaling path:** Produces hardware-specific kernels, packet pipelines, DSP code or embedded firmware. Staging can be aligned with compile time, deployment time and runtime reconfiguration.

**Software/product wedge:** A generator framework for specialised database, networking, simulation or AI kernels where configurations repeat at scale.

**Principal risk:** Code explosion, cache pressure and debugging generated code are recurring problems. The market rewards concrete vertical speedups.

**Anchor sources:** [<u>R18</u>](https://halide-lang.org/)

## 12. Polyhedral compilation

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
</strong>P analysis for affine loop nests; optimisation search can be hard</th>
<th><strong>Score<br />
</strong>4.20/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Models loop iterations and memory dependences as integer polyhedra, enabling legal fusion, tiling, skewing and parallelisation.

**Hardware scaling path:** Excellent fit for CPUs, GPUs, systolic arrays and FPGAs when workloads have affine structure. It exposes locality and parallelism for memory hierarchies.

**Software/product wedge:** An optimiser for scientific computing, stencil workloads, image pipelines and tensor kernels, integrated beneath a higher-level DSL.

**Principal risk:** Non-affine control flow and irregular sparsity fall outside the clean model. Search over schedules can be expensive.

**Anchor sources:** [<u>R72</u>](https://polly.llvm.org/)

## 13. Automatic-differentiation compilers

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
</strong>P transformation of differentiable programs</th>
<th><strong>Score<br />
</strong>4.35/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Transforms programs to compute derivatives, enabling optimisation, scientific inverse problems and differentiable simulation without hand-derived gradients.

**Hardware scaling path:** Compiler fusion, checkpointing and custom derivative rules target GPUs, TPUs and simulation accelerators. Forward/reverse mode selection can be hardware-aware.

**Software/product wedge:** Differentiable physics, control, chip design and scientific ML platforms with domain-native primitives.

**Principal risk:** Numerical stability, mutation, control flow and memory growth complicate production use. General frameworks are mature, so differentiation must be vertical.

**Anchor sources:** [<u>R73</u>](https://docs.jax.dev/)

## 14. MLIR multi-level intermediate representation

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
</strong>P compiler infrastructure</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Provides reusable dialects and progressive lowering so one compiler can preserve domain semantics while eventually reaching machine-level IR.

**Hardware scaling path:** Designed for heterogeneous targets: CPUs, GPUs, tensor accelerators and custom ASICs. Hardware teams can expose a dialect rather than build an entire compiler stack.

**Software/product wedge:** A commercial compiler platform, dialect/tooling layer or hardware enablement service. The largest opportunity is turning new accelerators into programmable products quickly.

**Principal risk:** MLIR itself is infrastructure, not a product moat. Success requires a high-value domain, backend or optimisation capability.

**Anchor sources:** [<u>R12</u>](https://arxiv.org/abs/2002.11054)

## 15. CIRCT hardware compiler infrastructure

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
</strong>P transformations plus NP-hard synthesis subproblems</th>
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

**Core innovation:** Applies MLIR-style reusable compiler infrastructure to hardware design, spanning RTL, high-level synthesis, simulation and verification.

**Hardware scaling path:** Direct path to FPGAs and ASICs. Shared IR enables optimisation and formal checks across behavioural, structural and physical abstractions.

**Software/product wedge:** Next-generation EDA tooling: modular HLS, RTL refactoring, hardware linting, formal optimisation and accelerator generation.

**Principal risk:** EDA integration is difficult, incumbents control workflows and physical design remains a major gap beyond compiler IR.

**Anchor sources:** [<u>R13</u>](https://circt.llvm.org/)

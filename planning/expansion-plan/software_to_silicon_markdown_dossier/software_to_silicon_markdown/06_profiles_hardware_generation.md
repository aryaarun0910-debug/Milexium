# Heterogeneous compilation & hardware generation

## 16. TVM, MetaSchedule and hardware-native tensor IR

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
</strong>P compilation with combinatorial schedule search</th>
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

**Core innovation:** Separates tensor computation from schedule and automatically searches implementation choices across hardware targets.

**Hardware scaling path:** Targets CPUs, GPUs and accelerators; hardware-native IR can express memory scopes, pipelines and custom instructions close to a device's architecture.

**Software/product wedge:** An enablement stack for new accelerators or a vertical auto-tuner for inference, genomics, signal processing and databases.

**Principal risk:** Auto-tuning consumes compute and can overfit benchmarks. Broad compiler stacks face maintenance burdens across rapidly changing hardware.

**Anchor sources:** [<u>R14</u>](https://tvm.apache.org/docs/), [<u>R75</u>](https://tvm.apache.org/)

## 17. Triton and Gluon-style GPU kernel DSLs

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
</strong>P compilation; schedule tuning search</th>
<th><strong>Score<br />
</strong>4.85/5</th>
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

**Core innovation:** Expose blocked tensor programs at a level above CUDA while retaining enough control for high-performance custom kernels.

**Hardware scaling path:** Maps directly to GPU warps, shared memory, tensor cores and future accelerator backends. Compiler-generated layouts can replace hand-written CUDA for many kernels.

**Software/product wedge:** A kernel platform for under-served operators, non-NVIDIA hardware, finance, scientific computing or secure inference.

**Principal risk:** Performance portability is incomplete and debugging remains difficult. Vendor toolchains may absorb successful abstractions.

**Anchor sources:** [<u>R15</u>](https://triton-lang.org/)

## 18. DaCe data-centric compilation

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
</strong>P transformations with schedule/search components</th>
<th><strong>Score<br />
</strong>4.45/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Represents programs as stateful dataflow graphs, making movement and storage explicit rather than treating them as compiler afterthoughts.

**Hardware scaling path:** Compiles Python/NumPy-like programs to CPUs, GPUs and FPGAs. Explicit memlets and maps expose opportunities for tiling, streaming and on-chip buffering.

**Software/product wedge:** A compiler for HPC or scientific teams that need one codebase across clusters and FPGAs, with cost models for data movement.

**Principal risk:** Graph transformations can be expert-heavy; irregular Python semantics and external libraries complicate full-program coverage.

**Anchor sources:** [<u>R16</u>](https://spcl.inf.ethz.ch/Research/DAPP/)

## 19. Sparse tensor algebra compilation (TACO-class)

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
</strong>P code generation; format/schedule selection can be combinatorial</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Generates loops for sparse tensor expressions from algebra plus storage-format descriptions, avoiding hand-written kernels for every format combination.

**Hardware scaling path:** A strong fit for GPUs, FPGAs and sparse ASICs where compressed formats, merge networks and dataflow must be co-designed.

**Software/product wedge:** A sparse compiler and runtime for recommender systems, graph analytics, scientific matrices or 3D workloads.

**Principal risk:** Sparse workloads have data-dependent imbalance and format conversion costs. One representation rarely dominates across the pipeline.

**Anchor sources:** [<u>R17</u>](https://tensor-compiler.org/)

## 20. Halide-style separation of algorithm and schedule

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
</strong>P semantics with schedule search</th>
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

**Core innovation:** Keeps the mathematical algorithm distinct from the execution schedule, enabling aggressive retargeting without rewriting correctness logic.

**Hardware scaling path:** Schedules map pipelines to CPU vector units, GPUs, DSPs and FPGA line buffers. The abstraction is especially effective for stencil and imaging pipelines.

**Software/product wedge:** A vertical DSL for radar, medical imaging, video, computational photography or sensor fusion.

**Principal risk:** Works best on regular pipelines; general control flow and dynamic data structures weaken the model.

**Anchor sources:** [<u>R18</u>](https://halide-lang.org/)

## 21. Graph DSLs and graph-specific compilation

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
</strong>P graph algorithms; scheduling/partitioning may be NP-hard</th>
<th><strong>Score<br />
</strong>3.85/5</th>
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

**Core innovation:** Separates graph algorithm logic from traversal, frontier, partitioning and parallel scheduling choices.

**Hardware scaling path:** Targets multicore CPUs, GPUs, distributed systems and graph accelerators; graph reorderings improve locality and bandwidth use.

**Software/product wedge:** Compiler/runtime for fraud, cybersecurity, knowledge graphs and network science where graph workloads dominate.

**Principal risk:** Graph shapes vary widely, and communication or random memory access often dominates compute. Generic acceleration claims must be workload-specific.

**Anchor sources:** [<u>R19</u>](https://graphit-lang.org/)

## 22. RISC-V custom instruction extensions

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
</strong>P execution; ISA/compiler co-design</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>3-8 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Uses an open ISA and reserved encoding space to add domain instructions without designing an entire software ecosystem from scratch.

**Hardware scaling path:** Direct ASIC/FPGA path for crypto, DSP, ML, safety and control. Compiler intrinsics or custom dialects can expose extensions safely.

**Software/product wedge:** A licensable accelerator subsystem or domain processor with compiler, simulator and verification stack.

**Principal risk:** Fragmentation can destroy portability; custom instructions need enough volume to justify silicon and toolchain costs.

**Anchor sources:** [<u>R20</u>](https://riscv.org/specifications/)

## 23. Chisel and parameterized RTL generators

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
</strong>P elaboration; downstream synthesis is hard</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>2-6 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Builds hardware through parameterized generators and software abstractions rather than manually duplicated RTL.

**Hardware scaling path:** Produces ASIC and FPGA RTL families; generators can sweep cache sizes, pipelines, NoCs and accelerator arrays.

**Software/product wedge:** Reusable IP generators, design-space exploration and configurable edge accelerators.

**Principal risk:** Verification burden grows with configuration space, and generated RTL can be harder to debug than hand-written modules.

**Anchor sources:** [<u>R21</u>](https://www.chisel-lang.org/)

## 24. High-level synthesis (HLS)

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
</strong>P compilation with NP-hard scheduling/allocation components</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>1-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Converts algorithmic C/C++ or DSL descriptions into RTL while scheduling operations and allocating hardware resources.

**Hardware scaling path:** Direct FPGA/ASIC implementation; strongest when paired with domain-specific types, memory models and constraints rather than generic C.

**Software/product wedge:** Domain-specific HLS for networking, finance, robotics, codecs and scientific instruments with predictable quality-of-results.

**Principal risk:** Timing closure, memory architecture and verification remain expert tasks. Generic HLS can produce inefficient hardware.

**Anchor sources:** [<u>R22</u>](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vitis/vitis-hls.html), [<u>R13</u>](https://circt.llvm.org/)

## 25. CGRA compilers and FPGA overlays

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
</strong>NP-hard mapping/routing in general</th>
<th><strong>Score<br />
</strong>4.45/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>4-8 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Maps computation graphs onto coarse-grained reconfigurable arrays or prebuilt FPGA fabrics, trading peak efficiency for fast programmability.

**Hardware scaling path:** Hardware consists of reusable processing elements and interconnect; software performs placement, routing and scheduling.

**Software/product wedge:** A deployable accelerator substrate for edge inference, DSP or industrial control where ASIC volume is insufficient and FPGA flows are too slow.

**Principal risk:** Mapping quality and interconnect congestion are hard; overlays can waste area and power compared with custom RTL.

**Anchor sources:** [<u>R23</u>](https://doi.org/10.1145/3293882.3330550)

## 26. Dynamic FPGA partial reconfiguration

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
</strong>P orchestration; placement/scheduling can be NP-hard</th>
<th><strong>Score<br />
</strong>4.45/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>3-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Changes part of an FPGA while the remainder continues running, allowing hardware functions to be paged in like software modules.

**Hardware scaling path:** Enables multi-tenant accelerators, adaptive radio, security rotation and workload-specific datapaths on one device.

**Software/product wedge:** A hardware-function runtime and marketplace with verified partial bitstreams, scheduling and isolation.

**Principal risk:** Tool flows are fragile, reconfiguration latency matters and safe multi-tenancy requires strong isolation and verification.

**Anchor sources:** [<u>R22</u>](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vitis/vitis-hls.html)

## 27. Systolic and dataflow accelerator generators

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
</strong>P mapping for regular kernels; design search can be hard</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>3-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Generates spatial pipelines where data moves rhythmically through processing elements, exploiting reuse and local communication.

**Hardware scaling path:** Ideal for matrix operations, convolution, dynamic programming, genomics and signal processing on FPGAs/ASICs.

**Software/product wedge:** A generator plus compiler for one high-volume kernel family, with fast design-space exploration and performance models.

**Principal risk:** Irregular workloads and changing dimensions reduce utilisation. Memory feeding and layout often determine real performance.

**Anchor sources:** [<u>R13</u>](https://circt.llvm.org/), [<u>R21</u>](https://www.chisel-lang.org/)

## 28. Processing-in-memory and near-memory computing

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
</strong>P computation; system mapping is the innovation</th>
<th><strong>Score<br />
</strong>4.60/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>5-10 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Moves computation into or near memory to avoid the energy and latency of shuttling data through conventional processor hierarchies.

**Hardware scaling path:** Can use DRAM logic, HBM base dies, SRAM compute, resistive arrays or near-memory accelerators. Software must partition operations and manage precision.

**Software/product wedge:** Database scans, vector search, graph traversal, recommendation and cryptographic transforms where bandwidth dominates.

**Principal risk:** Programming models, coherence, yield and data movement between conventional and in-memory regions remain difficult. Hardware capital is substantial.

**Anchor sources:** [<u>R24</u>](https://arxiv.org/abs/1903.03988)

## 29. Computational storage

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
</strong>P offloaded computation</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>2-6 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Executes filtering, compression, vector search or transformation near SSDs, reducing host I/O and network movement.

**Hardware scaling path:** Uses storage processors, FPGAs or ASICs integrated with drives or controllers. Standard programming models can make functions portable.

**Software/product wedge:** A storage appliance for RAG, logs, genomics, security scanning or database predicates where datasets exceed host memory.

**Principal risk:** Workload selectivity must justify offload overhead; storage vendors and cloud platforms control deployment channels.

**Anchor sources:** [<u>R25</u>](https://www.snia.org/tech_activities/standards/curr_standards/cs)

## 30. DPUs and SmartNICs

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
</strong>P packet/storage processing; rule placement may be hard</th>
<th><strong>Score<br />
</strong>5.00/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>1-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Offload networking, storage, security and infrastructure control from host CPUs onto programmable NIC-side processors.

**Hardware scaling path:** Combines ARM cores, packet engines, crypto blocks and accelerators. eBPF, P4 and vendor SDKs expose the datapath.

**Software/product wedge:** Infrastructure isolation, telemetry, storage virtualisation, firewalling and AI cluster networking delivered as programmable services.

**Principal risk:** Vendor fragmentation and operational complexity are high. Products must beat mature cloud and NIC offerings on a specific pain point.

**Anchor sources:** [<u>R26</u>](https://www.nvidia.com/en-us/networking/products/data-processing-unit/)

# 7. Build and commercialisation roadmap

## 7.1 The staged software-to-silicon path

| **Stage**                                               | **Deliverable**                                                                                                                                                            | **Indicative timing** |
|---------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|
| **Stage 0 - Choose an invariant**                       | Identify the property that remains stable across data or hardware: an equivalence relation, distribution, sparse structure, proof obligation, topology or workload family. | 0-3 months            |
| **Stage 1 - Build a measurable software wedge**         | Ship a CPU/GPU reference implementation with benchmarks, correctness tests and real instrumentation. Win one workflow, not a platform narrative.                           | 3-12 months           |
| **Stage 2 - Learn the cost model**                      | Collect hardware counters, solver traces, query distributions and failure cases. Build automatic scheduling, compression or search decisions.                              | 6-18 months           |
| **Stage 3 - Create an accelerator contract**            | Define a stable IR, packed format, instruction set or offload API. Prototype hot kernels on FPGA, DPU or SmartNIC while preserving software fallback.                      | 12-30 months          |
| **Stage 4 - Commit to silicon only with workload pull** | ASIC investment is justified when the same kernels recur at sufficient volume and the software channel controls deployment.                                                | 24-60+ months         |

## 7.2 Three portfolio archetypes

**Compiler-control plane -** Own the IR, cost model and verification layer. Hardware vendors become backends. **Examples:** MLIR/CIRCT, e-graphs, sparse compilers, distributed schedulers.

**Compressed data plane -** Own a representation that reduces bandwidth and has direct SIMD/FPGA/ASIC kernels. **Examples:** TurboVec, sketches, succinct indexes, low-bit AI, KV compression.

**Certified hard-search engine -** Own the domain model, exact/approximate solver and certificate, then accelerate bottleneck subroutines. **Examples:** CP-SAT verticals, GPU B&B, solver-aided synthesis, ZK/FHE.

## 7.3 A 12-month research programme

**Months 1-2:** Select three wedges and reproduce primary benchmarks on the same hardware. Build a common harness for throughput, latency, memory, energy proxy and quality/correctness.

**Months 3-4:** Implement one differentiating algorithmic change for each wedge. Prefer changes that alter representation or data movement rather than minor kernel tuning.

**Months 5-6:** Collect workload traces and build a first cost model or heuristic controller. Test distribution shift and adversarial cases.

**Months 7-9:** Integrate into a real workflow: IDE, vector database, solver, inference server or storage engine. Measure end-to-end economics.

**Months 10-12:** Prototype the stable hot path on FPGA/DPU or a cycle-accurate architecture model. Decide whether the hardware path creates a 5-10x system advantage, not merely a kernel benchmark.

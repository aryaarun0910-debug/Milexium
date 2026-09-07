# 4. Portfolio matrix: all 80 technologies

The score is a directional prioritisation tool, not a forecast. A score above 4.4 indicates a particularly strong combination of technical leverage and plausible commercial timing. Capital intensity is shown separately so software-first and silicon-heavy opportunities are not conflated.

## Compiler intelligence & verification

| **\#** | **Technology**                                   | **Complexity lens**                                               | **Score** | **Capital** | **HW fit** |
|--------|--------------------------------------------------|-------------------------------------------------------------------|-----------|-------------|------------|
| 8      | CIRCT hardware compiler infrastructure           | P transformations plus NP-hard synthesis subproblems              | 4.85      | Medium      | 5          |
| 16     | MLIR multi-level intermediate representation     | P compiler infrastructure                                         | 4.85      | Low         | 5          |
| 27     | Equality saturation and e-graphs                 | P-style rewriting with potentially explosive search               | 4.65      | Low         | 4          |
| 29     | Solver-aided programming                         | NP/SMT search hidden behind a language                            | 4.65      | Low         | 4          |
| 48     | Automatic-differentiation compilers              | P transformation of differentiable programs                       | 4.35      | Low         | 5          |
| 57     | Proof-carrying code and certified optimisation   | P checking; proof generation may be hard                          | 4.25      | Medium      | 4          |
| 58     | Superoptimization                                | NP-hard search over program space                                 | 4.25      | Low         | 4          |
| 59     | Syntax-guided synthesis (SyGuS)                  | NP-hard constrained program synthesis                             | 4.25      | Low         | 4          |
| 61     | Verified compilers                               | P compilation with machine-checked correctness                    | 4.20      | Medium      | 3          |
| 65     | Polyhedral compilation                           | P analysis for affine loop nests; optimisation search can be hard | 4.20      | Low         | 5          |
| 67     | Translation validation                           | P/SMT verification per compilation                                | 4.20      | Low         | 3          |
| 70     | Polymorphic type slicing                         | P-exact core; minimum-size variant NP-hard                        | 4.10      | Low         | 2          |
| 72     | Incremental and self-adjusting computation       | P-exact with change-proportional work                             | 4.00      | Low         | 4          |
| 74     | Partial evaluation and multi-stage programming   | P specialisation; code-size trade-offs                            | 4.00      | Low         | 4          |
| 79     | Interactive theorem proving and proof extraction | Logic-dependent; proof checking is tractable                      | 3.60      | Low         | 2          |

## Heterogeneous compilation & hardware generation

| **\#** | **Technology**                                    | **Complexity lens**                                               | **Score** | **Capital** | **HW fit** |
|--------|---------------------------------------------------|-------------------------------------------------------------------|-----------|-------------|------------|
| 1      | DPUs and SmartNICs                                | P packet/storage processing; rule placement may be hard           | 5.00      | High        | 5          |
| 11     | Computational storage                             | P offloaded computation                                           | 4.85      | High        | 5          |
| 18     | Sparse tensor algebra compilation (TACO-class)    | P code generation; format/schedule selection can be combinatorial | 4.85      | Low         | 5          |
| 20     | TVM, MetaSchedule and hardware-native tensor IR   | P compilation with combinatorial schedule search                  | 4.85      | Low         | 5          |
| 21     | Triton and Gluon-style GPU kernel DSLs            | P compilation; schedule tuning search                             | 4.85      | Low         | 5          |
| 30     | Chisel and parameterized RTL generators           | P elaboration; downstream synthesis is hard                       | 4.60      | High        | 5          |
| 32     | Processing-in-memory and near-memory computing    | P computation; system mapping is the innovation                   | 4.60      | Very High   | 5          |
| 33     | RISC-V custom instruction extensions              | P execution; ISA/compiler co-design                               | 4.60      | Very High   | 5          |
| 37     | Systolic and dataflow accelerator generators      | P mapping for regular kernels; design search can be hard          | 4.60      | Very High   | 5          |
| 38     | High-level synthesis (HLS)                        | P compilation with NP-hard scheduling/allocation components       | 4.60      | High        | 5          |
| 42     | CGRA compilers and FPGA overlays                  | NP-hard mapping/routing in general                                | 4.45      | Very High   | 5          |
| 43     | DaCe data-centric compilation                     | P transformations with schedule/search components                 | 4.45      | Low         | 5          |
| 44     | Dynamic FPGA partial reconfiguration              | P orchestration; placement/scheduling can be NP-hard              | 4.45      | High        | 5          |
| 63     | Halide-style separation of algorithm and schedule | P semantics with schedule search                                  | 4.20      | Low         | 5          |
| 76     | Graph DSLs and graph-specific compilation         | P graph algorithms; scheduling/partitioning may be NP-hard        | 3.85      | Low         | 4          |

## Datacenter systems & data movement

| **\#** | **Technology**                                 | **Complexity lens**                            | **Score** | **Capital** | **HW fit** |
|--------|------------------------------------------------|------------------------------------------------|-----------|-------------|------------|
| 9      | CXL memory pooling and fabric management       | P allocation; placement is combinatorial       | 4.85      | High        | 5          |
| 23     | eBPF and XDP programmable datapaths            | P verified bytecode execution                  | 4.85      | Low         | 5          |
| 24     | Compiler-managed compute/communication overlap | P scheduling; optimal placement may be NP-hard | 4.70      | Low         | 5          |
| 49     | DPDK and userspace kernel bypass               | P packet processing                            | 4.35      | Low         | 5          |
| 50     | GPUDirect RDMA and direct storage              | P direct data movement                         | 4.35      | Medium      | 5          |
| 52     | RDMA and RoCE                                  | P communication primitive                      | 4.35      | Medium      | 5          |
| 54     | Topology-aware collective communication        | P communication algorithms                     | 4.35      | Medium      | 5          |
| 60     | io_uring and zero-copy asynchronous I/O        | P asynchronous systems primitive               | 4.25      | Low         | 4          |
| 62     | CUDA Graphs and captured execution             | P scheduling primitive                         | 4.20      | Low         | 5          |
| 64     | NVMe-over-Fabrics and storage disaggregation   | P storage transport                            | 4.20      | High        | 5          |
| 68     | ZeRO and fully sharded data parallelism        | P distributed training transformation          | 4.20      | Low         | 5          |

## Data structures, retrieval & mathematical compression

| **\#** | **Technology**                                                   | **Complexity lens**                                      | **Score** | **Capital** | **HW fit** |
|--------|------------------------------------------------------------------|----------------------------------------------------------|-----------|-------------|------------|
| 3      | Filtered and hybrid ANN execution                                | P-approximate retrieval with exact predicate constraints | 5.00      | Low         | 5          |
| 6      | TurboQuant and TurboVec                                          | P-approximate search with data-oblivious quantization    | 5.00      | Low         | 5          |
| 12     | DiskANN and SSD-native graph search                              | P-approximate search with external-memory design         | 4.85      | Medium      | 5          |
| 31     | Compressed sensing and sparse recovery                           | P convex/greedy recovery under structural assumptions    | 4.60      | High        | 5          |
| 34     | Randomized numerical linear algebra and graph sparsification     | P-approximate algorithms with probabilistic guarantees   | 4.60      | Low         | 5          |
| 36     | Succinct data structures and FM-indexes                          | P-exact with near-information-theoretic space            | 4.60      | Low         | 5          |
| 41     | Anisotropic vector quantization and ScaNN                        | P-approximate search                                     | 4.45      | Low         | 5          |
| 51     | Product quantization and asymmetric distance computation         | P-approximate compression/search                         | 4.35      | Low         | 5          |
| 66     | Streaming sketches: Count-Min, HyperLogLog and quantile sketches | P-approximate streaming algorithms                       | 4.20      | Low         | 5          |
| 69     | Learned index structures                                         | P-exact lookup with model-based position prediction      | 4.10      | Low         | 4          |
| 75     | Roaring and bit-sliced indexes                                   | P-exact set and predicate operations                     | 3.95      | Low         | 5          |
| 77     | Cuckoo and XOR filters                                           | P-probabilistic membership queries                       | 3.80      | Low         | 5          |
| 78     | HNSW navigable small-world graphs                                | P-approximate search; graph construction heuristic       | 3.80      | Low         | 3          |
| 80     | Locality-sensitive hashing                                       | P-approximate nearest-neighbour search                   | 3.20      | Low         | 4          |

## AI execution & model systems

| **\#** | **Technology**                                              | **Complexity lens**                                      | **Score** | **Capital** | **HW fit** |
|--------|-------------------------------------------------------------|----------------------------------------------------------|-----------|-------------|------------|
| 2      | Distributed inference scheduling and expert/cache placement | NP-hard placement/scheduling; heuristic online control   | 5.00      | Medium      | 5          |
| 4      | KV-cache compression and quantization                       | P-approximate representation                             | 5.00      | Low         | 5          |
| 10     | Compiler-driven kernel fusion and tensor compilers          | P graph transformation; optimal fusion can be hard       | 4.85      | Low         | 5          |
| 15     | Low-bit AI quantization: INT4, FP8 and FP4                  | P-approximate numerical representation                   | 4.85      | Low         | 5          |
| 17     | Sparse Mixture-of-Experts routing                           | P routing; balancing and placement are combinatorial     | 4.85      | Medium      | 5          |
| 19     | Speculative decoding                                        | P-exact sampling under verification                      | 4.85      | Low         | 5          |
| 25     | PagedAttention and continuous-batching inference runtimes   | P scheduling and memory management                       | 4.70      | Low         | 5          |
| 45     | FlashAttention and IO-aware exact attention                 | P-exact attention with lower IO complexity               | 4.45      | Low         | 5          |
| 46     | Selective state-space and scan-based sequence models        | P linear-time sequence computation                       | 4.45      | Medium      | 5          |
| 53     | Structured sparsity                                         | P sparse computation; pruning is an optimisation problem | 4.35      | Low         | 5          |

## NP and combinatorial optimisation

| **\#** | **Technology**                                         | **Complexity lens**                                                  | **Score** | **Capital** | **HW fit** |
|--------|--------------------------------------------------------|----------------------------------------------------------------------|-----------|-------------|------------|
| 14     | GPU and parallel branch-and-bound                      | NP-hard exact search; parallel instance acceleration                 | 4.85      | Medium      | 5          |
| 26     | CP-SAT and lazy-clause-generation constraint solving   | NP-hard exact search with strong propagation                         | 4.65      | Low         | 4          |
| 28     | Learning-guided combinatorial optimisation             | NP-hard solver enhanced by learned policies                          | 4.65      | Low         | 4          |
| 35     | SMT solving                                            | NP-hard/undecidable fragments; exact within supported theories       | 4.60      | Low         | 3          |
| 39     | MILP branch-and-cut                                    | NP-hard exact optimisation                                           | 4.55      | Medium      | 4          |
| 47     | CDCL SAT solving                                       | NP-complete exact search; excellent practical structure exploitation | 4.35      | Low         | 3          |
| 55     | Approximation algorithms, PTAS and primal-dual methods | Polynomial-time approximation with guarantees                        | 4.25      | Low         | 4          |
| 56     | Fixed-parameter algorithms and kernelization           | FPT: exponential in a small parameter, polynomial in input size      | 4.25      | Low         | 4          |
| 71     | QUBO, Ising formulations and annealing                 | NP-hard heuristic/physical optimisation                              | 4.05      | High        | 5          |
| 73     | MaxSAT and pseudo-Boolean optimisation                 | NP-hard exact/approximate optimisation                               | 4.00      | Low         | 4          |

## Private, verifiable & memory-safe computing

| **\#** | **Technology**                                           | **Complexity lens**                                                 | **Score** | **Capital** | **HW fit** |
|--------|----------------------------------------------------------|---------------------------------------------------------------------|-----------|-------------|------------|
| 5      | Trusted execution and confidential computing             | P execution with hardware-enforced isolation                        | 5.00      | High        | 5          |
| 7      | CHERI capability systems and memory-safe embedded stacks | P enforcement of spatial/authority safety                           | 4.85      | Very High   | 5          |
| 13     | Fully homomorphic encryption                             | P cryptographic computation with enormous constants                 | 4.85      | Very High   | 5          |
| 22     | Zero-knowledge proof systems and proof accelerators      | P prover/verifier protocols grounded in hardness assumptions        | 4.85      | High        | 5          |
| 40     | Secure multiparty computation, PIR and ORAM              | P cryptographic protocols with communication/obliviousness overhead | 4.50      | High        | 4          |

# 3. What the two seed examples reveal

## 3.1 Polymorphic type slicing: explanation as a computational primitive

The Cambridge work formalises a system in which a programmer selects a sub-term and a component of its type, then receives a minimal source slice explaining either what inside the term produced that type or what surrounding context required it. The paper also draws the exact boundary requested in this dossier: useful term-minimal slices can be calculated in polynomial time, while globally minimum-size slicing is NP-hard through a reduction from set cover.

**Commercial translation:** Build an “explanation graph” beneath an IDE or coding agent. It can constrain refactors, isolate the context sent to an LLM, explain non-local errors and record why generated changes are permitted.

**Hardware path:** Initially weak: this is a software/compiler product. At fleet scale, persistent derivation graphs, incremental fixed points and parallel provenance queries could move to graph accelerators or DPUs, but hardware should follow adoption rather than lead it.

**Strategic lesson:** A mathematically defined minimal explanation can be both a developer feature and an enforcement boundary for automated code modification.

## 3.2 TurboQuant/TurboVec: distributional mathematics translated into packed hardware work

TurboVec is a particularly instructive software-to-silicon pattern. It normalises vectors, applies a random orthogonal rotation, quantises predictable coordinate marginals into 2- or 4-bit codes, and scores packed vectors directly through lookup tables. The repository implements architecture-specific NEON and AVX paths, avoids a separate codebook-training phase and integrates filtering into block-level scoring.

**Commercial translation:** Start as a fast local vector library; expand into embedded indexes, private RAG, filtered retrieval and SSD/CXL-resident search; move stable scoring kernels into FPGA, DPU or ASIC IP.

**Why the mathematics matters:** The rotation and known marginal distribution simplify training and make the representation data-oblivious, while bit packing changes the bottleneck from floating-point bandwidth to compact table lookup and accumulation.

**Strategic lesson:** The best acceleration ideas often combine a theorem or distributional invariant, a compressed representation, and an implementation layout that maps directly to instructions and memory blocks.

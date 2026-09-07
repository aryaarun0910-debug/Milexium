# Data structures, retrieval & mathematical compression

## 42. Learned index structures

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
</strong>P-exact lookup with model-based position prediction</th>
<th><strong>Score<br />
</strong>4.10/5</th>
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

**Core innovation:** Treats an index as a model of the data distribution, predicting where a key lies and correcting within a bounded local search.

**Hardware scaling path:** Inference can use SIMD, vector units or tiny accelerators; hierarchical models map to cache and memory tiers.

**Software/product wedge:** Indexes for stable, high-volume datasets in analytics, time series and storage engines, with automatic fallback and retraining.

**Principal risk:** Distribution shifts and updates can destroy guarantees. Traditional B-trees are robust and operationally trusted.

**Anchor sources:** [<u>R38</u>](https://arxiv.org/abs/1712.01208)

## 43. Succinct data structures and FM-indexes

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
</strong>P-exact with near-information-theoretic space</th>
<th><strong>Score<br />
</strong>4.60/5</th>
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

**Core innovation:** Supports queries while storing data close to entropy or combinatorial lower bounds, often using rank/select primitives over bitvectors.

**Hardware scaling path:** Bit-parallel CPU instructions, wide memory buses and FPGA rank/select units can accelerate queries with minimal bandwidth.

**Software/product wedge:** Genomics, log search, compressed text, graph representations and embedded databases where memory is the binding constraint.

**Principal risk:** Implementations are complex, updates are difficult and constant factors matter. Domain-specific packaging is essential.

**Anchor sources:** [<u>R39</u>](https://doi.org/10.1109/SFCS.2000.892127)

## 44. Roaring and bit-sliced indexes

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
</strong>P-exact set and predicate operations</th>
<th><strong>Score<br />
</strong>3.95/5</th>
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

**Core innovation:** Partitions integer sets into containers and selects dense or sparse encodings, enabling fast intersections and scans without full decompression.

**Hardware scaling path:** Maps exceptionally well to SIMD, wide registers, GPUs and FPGA bitwise pipelines.

**Software/product wedge:** Analytics, observability, search filters and access-control engines with compressed predicate execution.

**Principal risk:** Mature open-source implementations reduce moat. The opportunity is an integrated query engine or hardware offload.

**Anchor sources:** [<u>R40</u>](https://roaringbitmap.org/)

## 45. Cuckoo and XOR filters

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
</strong>P-probabilistic membership queries</th>
<th><strong>Score<br />
</strong>3.80/5</th>
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

**Core innovation:** Compact approximate membership structures trade a controlled false-positive rate for fewer memory accesses than general hash tables.

**Hardware scaling path:** Hash pipelines and random-access SRAM fit NICs, SSD controllers, CPUs and FPGAs.

**Software/product wedge:** Deduplication, cache admission, database joins, security blocklists and storage metadata filters.

**Principal risk:** Updates and construction failure modes vary by design; false positives must be acceptable to the application.

**Anchor sources:** [<u>R41</u>](https://arxiv.org/abs/1912.08258)

## 46. Streaming sketches: Count-Min, HyperLogLog and quantile sketches

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
</strong>P-approximate streaming algorithms</th>
<th><strong>Score<br />
</strong>4.20/5</th>
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

**Core innovation:** Summarises frequency, cardinality or quantiles in sublinear memory with probabilistic error bounds.

**Hardware scaling path:** Simple counters and hash functions are ideal for SmartNICs, switches, FPGAs and high-rate telemetry ASICs.

**Software/product wedge:** Network telemetry, fraud detection, observability, metering and database optimisation at line rate.

**Principal risk:** Adversarial inputs, merge semantics and error interpretation can be misunderstood. Many primitives are commoditised.

**Anchor sources:** [<u>R42</u>](https://dimacs.rutgers.edu/~graham/pubs/papers/cm-full.pdf)

## 47. Locality-sensitive hashing

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
</strong>P-approximate nearest-neighbour search</th>
<th><strong>Score<br />
</strong>3.20/5</th>
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

**Core innovation:** Uses randomized hashes that collide more often for nearby points, converting similarity search into multiple table probes.

**Hardware scaling path:** Highly parallel hashing and probing suit GPUs, FPGAs and distributed sharded indexes.

**Software/product wedge:** A predictable-recall retrieval layer for high-dimensional or streaming data where graph indexes are hard to update.

**Principal risk:** Memory overhead can be high and modern graph or quantization methods often win empirically.

**Anchor sources:** [<u>R44</u>](https://hal.inria.fr/inria-00514462/document)

## 48. HNSW navigable small-world graphs

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
</strong>P-approximate search; graph construction heuristic</th>
<th><strong>Score<br />
</strong>3.80/5</th>
<th><strong>HW fit<br />
</strong>3/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Builds layered proximity graphs that allow greedy navigation from coarse to fine neighbourhoods, delivering strong recall-latency trade-offs.

**Hardware scaling path:** CPU-friendly random access, prefetching and SIMD distance kernels; FPGA/ASIC acceleration is possible but pointer-heavy traversal is challenging.

**Software/product wedge:** Vector databases, recommendation and multimodal retrieval with dynamic insertions.

**Principal risk:** Memory overhead is large, deletions and filtering are awkward, and worst-case guarantees are weak.

**Anchor sources:** [<u>R43</u>](https://arxiv.org/abs/1603.09320)

## 49. Product quantization and asymmetric distance computation

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
</strong>P-approximate compression/search</th>
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

**Core innovation:** Splits vectors into subspaces, quantizes each with a codebook and evaluates distances using compact lookup tables.

**Hardware scaling path:** Excellent SIMD/GPU/FPGA fit: packed codes, table lookups and accumulators replace floating-point vector loads.

**Software/product wedge:** Large-scale retrieval and recommendation where memory bandwidth costs more than arithmetic.

**Principal risk:** Training and codebook drift complicate online ingestion; low-bit configurations can lose recall.

**Anchor sources:** [<u>R44</u>](https://hal.inria.fr/inria-00514462/document)

## 50. TurboQuant and TurboVec

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
</strong>P-approximate search with data-oblivious quantization</th>
<th><strong>Score<br />
</strong>5.00/5</th>
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

**Core innovation:** Applies a random orthogonal rotation so coordinates follow a predictable marginal distribution, then uses precomputed scalar quantizers and packed SIMD scoring without a separate data-trained codebook.

**Hardware scaling path:** The algorithm is unusually hardware-friendly: 2/4-bit codes, nibble lookup tables, NEON/AVX kernels, per-vector scale factors and block-level filter short-circuiting. It is a clear candidate for FPGA, DPU, SSD or ASIC vector-search engines.

**Software/product wedge:** A local/private vector engine, embedded ANN library, computational-storage index or licensable search IP. The wedge is online ingest plus compression and deterministic hardware mapping.

**Principal risk:** Claims need independent benchmarking across datasets, filters, concurrency and update patterns. Random rotation cost and low-dimensional behaviour require careful engineering.

**Anchor sources:** [<u>R2</u>](https://github.com/RyanCodrai/turbovec), [<u>R3</u>](https://arxiv.org/abs/2504.19874)

## 51. Anisotropic vector quantization and ScaNN

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
</strong>P-approximate search</th>
<th><strong>Score<br />
</strong>4.45/5</th>
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

**Core innovation:** Optimises quantization error in directions that matter most for maximum-inner-product search rather than minimising isotropic reconstruction error.

**Hardware scaling path:** Lookup-table distance evaluation and partitioning fit SIMD, GPUs and accelerator pipelines.

**Software/product wedge:** High-recall semantic retrieval and recommendation where query-aligned error matters more than generic reconstruction fidelity.

**Principal risk:** Training, parameter selection and dataset-specific tuning increase operational burden.

**Anchor sources:** [<u>R45</u>](https://arxiv.org/abs/1908.10396)

## 52. DiskANN and SSD-native graph search

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
</strong>P-approximate search with external-memory design</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>1-4 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Co-designs graph traversal, caching and SSD access so billion-scale vector search works beyond DRAM.

**Hardware scaling path:** NVMe queues, direct I/O, computational storage and CXL caches are natural hardware extensions.

**Software/product wedge:** A vector retrieval layer for enterprises that cannot afford all-DRAM indexes, especially private/on-premise deployments.

**Principal risk:** Tail latency depends on storage behaviour, and graph build/update costs can be substantial.

**Anchor sources:** [<u>R46</u>](https://www.microsoft.com/en-us/research/publication/diskann-fast-accurate-billion-point-nearest-neighbor-search-on-a-single-node/)

## 53. Filtered and hybrid ANN execution

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
</strong>P-approximate retrieval with exact predicate constraints</th>
<th><strong>Score<br />
</strong>5.00/5</th>
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

**Core innovation:** Integrates metadata, ACL or SQL predicates into the vector-search kernel instead of over-fetching and discarding results later.

**Hardware scaling path:** Bitmasks, bitmap indexes, SIMD block skipping and SmartNIC/storage offload make selectivity reduce actual work.

**Software/product wedge:** Multi-tenant RAG, ecommerce, security and enterprise search where every query carries filters.

**Principal risk:** Filter distributions are workload-specific; supporting arbitrary predicates without destroying index efficiency is hard.

**Anchor sources:** [<u>R2</u>](https://github.com/RyanCodrai/turbovec), [<u>R40</u>](https://roaringbitmap.org/)

## 54. Compressed sensing and sparse recovery

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
</strong>P convex/greedy recovery under structural assumptions</th>
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

**Core innovation:** Reconstructs sparse signals from far fewer measurements than classical sampling suggests by exploiting sparsity and incoherence.

**Hardware scaling path:** Random projections, FFTs and iterative thresholding map to GPUs, FPGAs, sensor ASICs and edge DSPs.

**Software/product wedge:** Medical imaging, radar, spectrum sensing, scientific instruments and low-power sensor acquisition.

**Principal risk:** Recovery guarantees require assumptions that real signals may violate; iterative solvers and calibration can dominate latency.

**Anchor sources:** [<u>R47</u>](https://ieeexplore.ieee.org/document/1614066)

## 55. Randomized numerical linear algebra and graph sparsification

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
</strong>P-approximate algorithms with probabilistic guarantees</th>
<th><strong>Score<br />
</strong>4.60/5</th>
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

**Core innovation:** Uses sketches, random projections and sampled structure to approximate matrices or graphs while preserving key spectral or geometric properties.

**Hardware scaling path:** Dense sketching uses GPUs/tensor cores; sparse sampling and reductions fit CPUs, FPGAs and distributed systems.

**Software/product wedge:** Preconditioners, least-squares solvers, graph analytics and data-reduction layers that make downstream optimisation cheaper.

**Principal risk:** Approximation error must be tied to business metrics, and memory traffic can still dominate. Choosing the correct sketch is non-trivial.

**Anchor sources:** [<u>R48</u>](https://arxiv.org/abs/2002.01387)

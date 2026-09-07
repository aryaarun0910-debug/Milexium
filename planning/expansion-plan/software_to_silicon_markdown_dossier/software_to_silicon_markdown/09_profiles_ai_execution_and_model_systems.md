# AI execution & model systems

## 56. FlashAttention and IO-aware exact attention

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
</strong>P-exact attention with lower IO complexity</th>
<th><strong>Score<br />
</strong>4.45/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Low</th>
<th><strong>Horizon<br />
</strong>1-2 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Tiles attention so intermediate score matrices remain in on-chip memory, reducing HBM traffic while computing mathematically exact attention.

**Hardware scaling path:** Explicitly co-designed for GPU SRAM, warps and tensor cores; successive versions adapt to new architectures and parallelism.

**Software/product wedge:** A broader IO-aware kernel suite for attention variants, scientific operators and non-NVIDIA accelerators.

**Principal risk:** The core technique is widely adopted and rapidly commoditised. Differentiation requires new operators, hardware or automatic generation.

**Anchor sources:** [<u>R49</u>](https://arxiv.org/abs/2205.14135)

## 57. PagedAttention and continuous-batching inference runtimes

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
</strong>P scheduling and memory management</th>
<th><strong>Score<br />
</strong>4.70/5</th>
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

**Core innovation:** Treats KV-cache blocks like virtual-memory pages, reducing fragmentation and enabling flexible sharing across sequences while continuously batching requests.

**Hardware scaling path:** GPU memory managers, block tables and kernels cooperate; future accelerators can expose hardware page-table support for model state.

**Software/product wedge:** Inference infrastructure for high utilisation, prefix sharing, multi-LoRA and long-context workloads.

**Principal risk:** Serving frameworks are intensely competitive; workload variability and tail latency complicate universal scheduling.

**Anchor sources:** [<u>R50</u>](https://arxiv.org/abs/2309.06180)

## 58. Speculative decoding

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
</strong>P-exact sampling under verification</th>
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

**Core innovation:** Uses a smaller draft model to propose multiple tokens and a larger model to verify them in parallel, preserving the target distribution while reducing sequential steps.

**Hardware scaling path:** Needs fused verification kernels, efficient KV management and possibly heterogeneous accelerators for drafter and verifier.

**Software/product wedge:** A model-agnostic acceleration layer that selects draft models, tree shapes and acceptance strategies dynamically.

**Principal risk:** Speedup collapses when acceptance is low or memory bandwidth dominates. Model and workload tuning is essential.

**Anchor sources:** [<u>R51</u>](https://arxiv.org/abs/2211.17192)

## 59. KV-cache compression and quantization

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
</strong>P-approximate representation</th>
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

**Core innovation:** Compresses attention keys and values by lower precision, eviction, low-rank structure or token selection to extend context and batch size.

**Hardware scaling path:** Maps to low-bit tensor cores, decompression units, CXL memory and tiered cache systems.

**Software/product wedge:** A context-memory runtime for long-context inference, agents and retrieval-heavy serving.

**Principal risk:** Quality loss is model- and layer-dependent, and compression overhead can offset bandwidth savings.

**Anchor sources:** [<u>R50</u>](https://arxiv.org/abs/2309.06180), [<u>R52</u>](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/work-with-quantized-types.html)

## 60. Low-bit AI quantization: INT4, FP8 and FP4

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
</strong>P-approximate numerical representation</th>
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

**Core innovation:** Represents weights and activations with fewer bits using calibration, scaling and outlier handling, cutting memory and increasing arithmetic throughput.

**Hardware scaling path:** Directly exploits tensor-core and ASIC low-precision units; custom formats can be decoded in fused kernels.

**Software/product wedge:** Quantization toolchains for difficult models, edge devices and cross-vendor deployment, with accuracy contracts and automated mixed precision.

**Principal risk:** Hardware formats change quickly, and strong open/vendor tooling compresses margins. Evaluation must cover real tasks, not perplexity alone.

**Anchor sources:** [<u>R52</u>](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/work-with-quantized-types.html)

## 61. Structured sparsity

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
</strong>P sparse computation; pruning is an optimisation problem</th>
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

**Core innovation:** Constrains zero patterns, such as 2:4 sparsity, so hardware can skip work without irregular indexing overhead.

**Hardware scaling path:** Tensor cores and ASIC datapaths can accelerate predictable patterns; compilers propagate sparsity and select sparse kernels.

**Software/product wedge:** Training and compression software that finds hardware-compatible sparsity with minimal accuracy loss.

**Principal risk:** Rigid patterns may save less than expected end-to-end; retraining cost and kernel coverage matter.

**Anchor sources:** [<u>R53</u>](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/data-formats-tensors.html)

## 62. Sparse Mixture-of-Experts routing

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
</strong>P routing; balancing and placement are combinatorial</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Activates only a subset of experts for each token, increasing model capacity without proportional arithmetic.

**Hardware scaling path:** Requires high-bandwidth all-to-all communication, expert placement, batching and potentially switch/NIC support.

**Software/product wedge:** An MoE runtime that co-optimises routing, load balance, quantisation and hardware placement for inference.

**Principal risk:** Communication, hot experts, instability and massive weight memory can erase theoretical savings.

**Anchor sources:** [<u>R54</u>](https://www.jmlr.org/papers/v23/21-0998.html)

## 63. Compiler-driven kernel fusion and tensor compilers

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
</strong>P graph transformation; optimal fusion can be hard</th>
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

**Core innovation:** Combines operators to eliminate intermediate memory traffic and launch overhead while selecting layouts and tiling jointly.

**Hardware scaling path:** Targets GPUs, CPUs and accelerators; fusion decisions depend on registers, shared memory, cache and tensor-core shapes.

**Software/product wedge:** A compiler backend for dynamic models, custom operators and emerging accelerators that current stacks handle poorly.

**Principal risk:** Compile times, shape dynamism and cost-model errors can produce regressions. Major frameworks invest heavily here.

**Anchor sources:** [<u>R12</u>](https://arxiv.org/abs/2002.11054), [<u>R14</u>](https://tvm.apache.org/docs/), [<u>R15</u>](https://triton-lang.org/)

## 64. Selective state-space and scan-based sequence models

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
</strong>P linear-time sequence computation</th>
<th><strong>Score<br />
</strong>4.45/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Replaces quadratic attention with recurrent/state-space updates that can be expressed as parallel scans while retaining input-dependent selectivity.

**Hardware scaling path:** Fused scan kernels suit GPUs; streaming variants map to edge ASICs and FPGAs with bounded state.

**Software/product wedge:** Long-sequence models for audio, genomics, sensors and on-device agents where memory is constrained.

**Principal risk:** Model quality and ecosystem support vary by task; hardware wins depend on stable architectures rather than rapid model churn.

**Anchor sources:** [<u>R55</u>](https://arxiv.org/abs/2312.00752)

## 65. Distributed inference scheduling and expert/cache placement

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
</strong>NP-hard placement/scheduling; heuristic online control</th>
<th><strong>Score<br />
</strong>5.00/5</th>
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

**Core innovation:** Jointly assigns requests, model shards, experts, KV caches and communication paths across heterogeneous accelerators.

**Hardware scaling path:** Uses GPUs, CPUs, DPUs, CXL memory and network topology as one resource fabric.

**Software/product wedge:** A cluster operating system for multi-model inference that optimises cost, latency and energy under changing demand.

**Principal risk:** Online demand is noisy, migrations are expensive and hyperscalers may build internally. The scheduler needs deep observability.

**Anchor sources:** [<u>R26</u>](https://www.nvidia.com/en-us/networking/products/data-processing-unit/), [<u>R27</u>](https://www.computeexpresslink.org/spec-landing), [<u>R35</u>](https://docs.nvidia.com/deeplearning/nccl/)

# Datacenter systems & data movement

## 31. CXL memory pooling and fabric management

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
</strong>P allocation; placement is combinatorial</th>
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

**Core innovation:** Disaggregates memory from individual hosts and allows coherent expansion or pooling across a fabric.

**Hardware scaling path:** CXL switches, memory expanders and pooled devices create a new datacenter memory tier; software predicts hotness, latency tolerance and failure domains.

**Software/product wedge:** A memory operating system for AI inference, databases and virtualisation that allocates pooled capacity with application-aware policies.

**Principal risk:** Latency, contention, security and interoperability complicate deployment. The market depends on hardware rollout and operational proof.

**Anchor sources:** [<u>R27</u>](https://www.computeexpresslink.org/spec-landing), [<u>R77</u>](https://www.microsoft.com/en-us/research/publication/pond-cxl-based-memory-pooling-systems-for-cloud-platforms/)

## 32. RDMA and RoCE

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
</strong>P communication primitive</th>
<th><strong>Score<br />
</strong>4.35/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Moves data directly between application memory across the network with minimal CPU intervention and kernel crossings.

**Hardware scaling path:** NIC hardware performs transport, DMA and ordering; software designs zero-copy protocols and congestion control around it.

**Software/product wedge:** Low-latency storage, distributed databases, model serving and HPC communication libraries.

**Principal risk:** Operational fragility, congestion and memory-registration complexity can erase gains. Benefits are strongest at scale.

**Anchor sources:** [<u>R28</u>](https://docs.nvidia.com/networking/display/rdmaawareprogrammingv17)

## 33. eBPF and XDP programmable datapaths

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
</strong>P verified bytecode execution</th>
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

**Core innovation:** Runs sandboxed programs in the kernel or earliest packet-receive path, enabling safe runtime extensibility without kernel modules.

**Hardware scaling path:** JITs to CPUs and can be offloaded to SmartNICs. Hardware-aware maps and helpers create a portable control layer.

**Software/product wedge:** Observability, security, load balancing and edge packet processing with centrally managed policies.

**Principal risk:** Verifier constraints, kernel-version differences and debugging complexity limit arbitrary applications.

**Anchor sources:** [<u>R29</u>](https://docs.kernel.org/bpf/), [<u>R76</u>](https://docs.kernel.org/networking/af_xdp.html)

## 34. DPDK and userspace kernel bypass

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
</strong>P packet processing</th>
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

**Core innovation:** Bypasses the traditional kernel networking stack with poll-mode drivers, huge pages and batch processing for predictable high throughput.

**Hardware scaling path:** Uses NIC queues and CPU cores directly; pairs with vector instructions, SmartNIC offload and NUMA-aware memory placement.

**Software/product wedge:** High-frequency trading, telecom, firewalls and packet analytics frameworks.

**Principal risk:** Dedicated cores and polling consume power; operational safety and portability are lower than kernel networking.

**Anchor sources:** [<u>R30</u>](https://doc.dpdk.org/guides/prog_guide/)

## 35. io_uring and zero-copy asynchronous I/O

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
</strong>P asynchronous systems primitive</th>
<th><strong>Score<br />
</strong>4.25/5</th>
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

**Core innovation:** Uses shared submission and completion rings to batch asynchronous file and network operations with fewer syscalls and context switches.

**Hardware scaling path:** Aligns with NVMe queues, zero-copy networking and userspace storage servers. Hardware can DMA directly into registered buffers.

**Software/product wedge:** High-throughput object stores, databases, proxies and edge runtimes with a safer abstraction than bespoke polling loops.

**Principal risk:** API complexity and kernel evolution create correctness and compatibility risks. Poor workload design can produce little gain.

**Anchor sources:** [<u>R31</u>](https://docs.kernel.org/io_uring/)

## 36. NVMe-over-Fabrics and storage disaggregation

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
</strong>P storage transport</th>
<th><strong>Score<br />
</strong>4.20/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>2-5 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Exposes remote NVMe devices over low-latency fabrics, separating compute from flash capacity while preserving queue semantics.

**Hardware scaling path:** Relies on RDMA/TCP transports, NVMe controllers and fabric management. Computational storage can be layered beneath it.

**Software/product wedge:** Elastic database, AI dataset and cloud storage pools with application-aware placement and QoS.

**Principal risk:** Tail latency, failure handling and network cost determine economics. Cloud providers already offer integrated alternatives.

**Anchor sources:** [<u>R32</u>](https://nvmexpress.org/specifications/)

## 37. GPUDirect RDMA and direct storage

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
</strong>P direct data movement</th>
<th><strong>Score<br />
</strong>4.35/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Medium</th>
<th><strong>Horizon<br />
</strong>1-3 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Allows NICs or storage devices to move data directly into GPU memory, avoiding CPU staging and extra copies.

**Hardware scaling path:** Requires IOMMU, PCIe, NIC, storage and GPU coordination. It is a key substrate for distributed training and streaming analytics.

**Software/product wedge:** Data ingestion and transport libraries for AI, scientific instruments and real-time signal processing.

**Principal risk:** Topology and vendor dependence are strong; poorly aligned transfers may remain bottlenecked elsewhere.

**Anchor sources:** [<u>R33</u>](https://docs.nvidia.com/cuda/gpudirect-rdma/)

## 38. CUDA Graphs and captured execution

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
</strong>P scheduling primitive</th>
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

**Core innovation:** Captures a repeated workflow and its dependencies once, then launches it with reduced CPU overhead and global optimisation opportunities.

**Hardware scaling path:** Maps directly to GPU command processors and multi-stream execution; can include memory copies, kernels and collectives.

**Software/product wedge:** An execution layer for low-latency inference, simulation and batched finance workloads with stable shapes.

**Principal risk:** Dynamic control flow and pointer changes complicate capture. Frameworks already expose graphs, so value lies in automatic partitioning and adaptation.

**Anchor sources:** [<u>R34</u>](https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/cuda-graphs.html)

## 39. Topology-aware collective communication

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
</strong>P communication algorithms</th>
<th><strong>Score<br />
</strong>4.35/5</th>
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

**Core innovation:** Chooses ring, tree, hierarchical and transport strategies for all-reduce, all-gather and related collectives based on topology.

**Hardware scaling path:** Uses NVLink, PCIe, InfiniBand and Ethernet; future switches and NICs can execute reductions in-network.

**Software/product wedge:** A cross-vendor collective optimiser for heterogeneous AI clusters and disaggregated accelerators.

**Principal risk:** Incumbent libraries are strong and hardware details are proprietary. Performance tuning is topology- and model-specific.

**Anchor sources:** [<u>R35</u>](https://docs.nvidia.com/deeplearning/nccl/)

## 40. ZeRO and fully sharded data parallelism

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
</strong>P distributed training transformation</th>
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

**Core innovation:** Partitions parameters, gradients and optimizer state across workers rather than replicating them, exchanging shards only when required.

**Hardware scaling path:** Uses GPU memory, CPU memory, NVMe and collectives as a hierarchy. Compiler support can overlap gathers with compute.

**Software/product wedge:** A training runtime that chooses sharding, offload and checkpoint strategies automatically across mixed clusters.

**Principal risk:** Communication can dominate and failure recovery is complex. PyTorch and DeepSpeed already provide strong baselines.

**Anchor sources:** [<u>R36</u>](https://docs.pytorch.org/docs/stable/fsdp.html), [<u>R37</u>](https://deepspeed.readthedocs.io/en/stable/zero3.html)

## 41. Compiler-managed compute/communication overlap

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
</strong>P scheduling; optimal placement may be NP-hard</th>
<th><strong>Score<br />
</strong>4.70/5</th>
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

**Core innovation:** Traces compute and collective operations together, then reorders, buckets and pipelines them to hide network latency behind useful work.

**Hardware scaling path:** Targets multi-GPU and multi-node systems, using topology, memory pressure and dependency information.

**Software/product wedge:** A distributed compiler layer for training and inference that is model- and cluster-aware rather than relying on manual tuning.

**Principal risk:** Static schedules can break under stragglers and dynamic shapes. Integration with frameworks and collectives is demanding.

**Anchor sources:** [<u>R35</u>](https://docs.nvidia.com/deeplearning/nccl/), [<u>R36</u>](https://docs.pytorch.org/docs/stable/fsdp.html)

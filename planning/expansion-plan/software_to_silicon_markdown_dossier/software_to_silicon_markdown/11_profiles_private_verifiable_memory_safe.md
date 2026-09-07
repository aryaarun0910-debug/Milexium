# Private, verifiable & memory-safe computing

## 76. Fully homomorphic encryption

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
</strong>P cryptographic computation with enormous constants</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>4-10 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Evaluates arithmetic on ciphertexts so data can remain encrypted during computation, using lattice-based schemes and noise management.

**Hardware scaling path:** NTTs, modular arithmetic, key switching and bootstrapping are highly parallel and ideal for GPUs, FPGAs and dedicated ASICs with HBM.

**Software/product wedge:** Confidential analytics and AI inference where the operator must never see plaintext. The strongest wedge is a narrow circuit family with an accelerator-aware compiler.

**Principal risk:** Latency, ciphertext expansion and parameter complexity remain severe. General-purpose claims are less credible than application-specific pipelines.

**Anchor sources:** [<u>R64</u>](https://openfhe.org/)

## 77. Zero-knowledge proof systems and proof accelerators

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
</strong>P prover/verifier protocols grounded in hardness assumptions</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>2-7 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Proves a computation was performed correctly without revealing witnesses, using polynomial commitments, FFTs/NTTs and multi-scalar multiplication.

**Hardware scaling path:** Prover workloads map exceptionally well to GPUs, FPGAs and ASICs; verifiers can be tiny and embedded.

**Software/product wedge:** Verifiable AI, outsourced computation, blockchains, identity and audit systems with domain-specific circuit compilers.

**Principal risk:** Circuit generation, trusted setup choices, proof-system churn and hardware utilisation are risks. End-user demand outside crypto is still forming.

**Anchor sources:** [<u>R65</u>](https://arxiv.org/abs/2109.09848)

## 78. Secure multiparty computation, PIR and ORAM

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
</strong>P cryptographic protocols with communication/obliviousness overhead</th>
<th><strong>Score<br />
</strong>4.50/5</th>
<th><strong>HW fit<br />
</strong>4/5</th>
<th><strong>Capital<br />
</strong>High</th>
<th><strong>Horizon<br />
</strong>3-8 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** MPC computes jointly over private inputs; PIR retrieves records without revealing the query; ORAM hides memory-access patterns. Together they address privacy beyond encryption-at-rest.

**Hardware scaling path:** Vectorised finite-field arithmetic, network offload, trusted NICs and memory controllers can reduce protocol and oblivious-access overhead.

**Software/product wedge:** Cross-company analytics, private fraud collaboration, confidential retrieval and regulated data clean rooms.

**Principal risk:** Communication dominates many protocols, trust models are subtle and product UX must hide cryptographic complexity.

**Anchor sources:** [<u>R66</u>](https://eprint.iacr.org/2011/535), [<u>R67</u>](https://doi.org/10.1007/978-3-642-00457-5_21), [<u>R68</u>](https://eprint.iacr.org/2013/280)

## 79. Trusted execution and confidential computing

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
</strong>P execution with hardware-enforced isolation</th>
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

**Core innovation:** Protects code and data in use through encrypted memory, isolated execution and remote attestation.

**Hardware scaling path:** CPU and GPU TEEs, secure boot, IOMMUs and roots of trust create an end-to-end confidential compute boundary.

**Software/product wedge:** Confidential AI, regulated cloud workloads and secure model/data marketplaces with attested deployment.

**Principal risk:** Side channels, firmware vulnerabilities and a large trusted-computing base weaken guarantees. Attestation and patch management are operationally critical.

**Anchor sources:** [<u>R69</u>](https://confidentialcomputing.io/), [<u>R80</u>](https://opentitan.org/)

## 80. CHERI capability systems and memory-safe embedded stacks

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
</strong>P enforcement of spatial/authority safety</th>
<th><strong>Score<br />
</strong>4.85/5</th>
<th><strong>HW fit<br />
</strong>5/5</th>
<th><strong>Capital<br />
</strong>Very High</th>
<th><strong>Horizon<br />
</strong>4-10 years</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

**Core innovation:** Uses unforgeable hardware capabilities to bind pointers to bounds and permissions, while memory-safe languages reduce whole classes of software defects.

**Hardware scaling path:** Capability-aware CPUs, tagged memory, secure microcontrollers and Rust firmware form a hardware-software safety stack.

**Software/product wedge:** Secure edge devices, defence, automotive, industrial control and compartmentalised operating systems with measurable exploit reduction.

**Principal risk:** Requires ISA, OS, compiler and ecosystem migration. Compatibility and performance must be demonstrated on real workloads.

**Anchor sources:** [<u>R70</u>](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/), [<u>R71</u>](https://docs.rust-embedded.org/book/)

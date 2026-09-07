# 8. Risk framework and diligence questions

**Benchmark risk:** Does the result survive different datasets, batch sizes, selectivity, concurrency, tail latency and energy? Is the baseline current and tuned?

**Amdahl risk:** What fraction of end-to-end cost is actually accelerated? Does preprocessing, transfer, compilation or host orchestration dominate?

**Complexity risk:** Is an NP-hard problem being reframed honestly as instance acceleration, approximation or restricted structure? What certificate or gap is reported?

**Portability risk:** Is the advantage tied to one instruction set, GPU generation, FPGA family or proprietary runtime?

**Correctness risk:** Can outputs be verified by a small checker, reference implementation, proof, recall metric or exact fallback?

**Data-moat risk:** Will usage create proprietary cost models, rewrite libraries, workload distributions or solver traces?

**Capital risk:** Can each stage create customer value before a tape-out or large hardware commitment?

**Channel risk:** Who controls deployment: cloud, chip vendor, database, IDE, storage vendor or enterprise platform team?

## Diligence scorecard for any new candidate

| **Dimension**        | **Question**                                   | **Pass condition**                                                      |
|----------------------|------------------------------------------------|-------------------------------------------------------------------------|
| **Mathematics**      | What invariant or bound makes the method work? | It is stated precisely and tested where assumptions weaken.             |
| **Representation**   | What data/IR format unlocks the speedup?       | The format reduces movement or exposes parallel structure.              |
| **Hardware mapping** | Which primitive dominates?                     | Clear mapping to SIMD, tensor core, SRAM, pipeline, NTT, lookup or DMA. |
| **End-to-end value** | What system cost is removed?                   | A measurable customer metric improves, not only a microbenchmark.       |
| **Defensibility**    | What compounds with use?                       | Cost model, corpus, proofs, schedules, traces or integration depth.     |
| **Failure mode**     | When does it lose?                             | Known triggers, fallback and monitoring are explicit.                   |

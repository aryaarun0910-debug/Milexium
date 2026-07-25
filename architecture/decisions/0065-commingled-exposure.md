# ADR-0065: The cost of not seeing the future, and who pays it

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-F-COMMINGLED-EXPOSURE-010

## Context

We put a specific technical argument to a former WMATA accessibility chief, and
he engaged with it rather than dismissing it:

> Commingling makes the scheduling problem harder, not easier. Next-day service is
> generous in one specific way: the scheduler sees every trip before it commits to
> any of them. Same-day service removes that. You accept a general-public rider at
> nine in the morning without knowing whether doing so costs you a wheelchair user
> at four in the afternoon, and you cannot take the decision back.

We also said, in the same email, that we do **not** think this is solved. This
packet had to make the measurement real without quietly retracting that.

## Decision

Measure the **online-vs-offline gap** and, crucially, **who bears it**.

1. An online commitment harness: requests arrive sequentially, each accept/decline
   is irrevocable, and the scheduler cannot see future arrivals.
2. The offline optimum as yardstick. ADR-0060's CP-SAT backend proves optimal
   solutions on the *full* instance, so the difference between the online outcome
   and that optimum is a measurable **cost of not seeing the future** — a quantity
   nobody in this industry currently computes.
3. **The distributional split is the point.** The shortfall is broken down by
   accessibility requirement, so *"we served 3% fewer trips"* can be separated
   from *"we served 3% fewer trips and every one of them needed a
   wheelchair-accessible vehicle."* The second sentence is the entire reason the
   packet exists.
4. Attribution, not blame. For an accessible request later denied, the earlier
   commitments that consumed the capacity are identified — but a later denial can
   have several sufficient causes, and the output represents that rather than
   naming a single culprit. It also distinguishes a shortfall caused by *earlier
   commitments* from one caused by an empty fleet (no accessible vehicle on shift
   at all), because blaming commingling for a structural service gap would be
   wrong.

**The module states plainly that online stochastic scheduling is not solved and
does not pretend otherwise.** Measuring the gap is the contribution; closing it
is not, and claiming otherwise in something we may show him would destroy the
relationship the packet was written to serve.

Framing is fixed deliberately: this measures whether a commingling policy quietly
shifts cost onto disabled riders. It is **not** usable as a justification for
serving fewer riders — the recipient has published that *"restricting transit use
should not be our objective"*, and the module docstring says so.

## Consequences

**46 tests** (26 online-commitment + 20 exposure-attribution). Full repo suite
**2337 passed, 1 skipped**.

## Honest limitations

- **The accessibility labels are ASSIGNED, not observed.** The Cordeau benchmark
  files carry no accessibility attribute whatsoever, so the wheelchair/ambulatory
  split is synthetic. Results support the *method* — that the gap can be measured
  and decomposed — and say nothing about how any real fleet behaves. This is the
  most important limitation in the packet and it is stated in the module itself.
- **Not Validated, and not close.** Synthetic and academic instances support
  algorithmic claims only.
- **`certified_optimal` inherits ADR-0060's tolerance** — optimal within the
  lattice resolution (~3.4e-5), never absolutely. Quoting the flag without the
  tolerance overstates it.
- **One online policy is not the online frontier.** The measured gap is the gap
  for *the policy we ran*. A better online policy would show a smaller one, so
  the number is an upper bound on the cost of myopia, not its true value.
- Attribution identifies capacity consumers; it does **not** establish that a
  different earlier decision would have been feasible overall.

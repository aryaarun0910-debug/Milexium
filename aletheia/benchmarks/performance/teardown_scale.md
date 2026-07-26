# Deadhead teardown at operator scale -- measured, not asserted

_Generated 2026-07-25T15:34:43.066607+00:00 by `aletheia/benchmarks/performance/teardown_scale.py` at commit `bd45540e16fc`._

ADR-0026 gates the Rust rewrite behind three triggers and no others: a real user, a **measured** bottleneck, or a second engineer to own Rust. This is the measurement for `aletheia/replay/teardown.py` (ADR-0039), whose published demonstration sampled 40,000 of ~4.9M rows in one TLC week. **A null result here is a success**: if Python holds at operator scale the trigger has not fired and no Rust work is justified yet.

## Machine

- CPU: Intel(R) Core(TM) i7-10510U CPU @ 1.80GHz (4 physical / 8 logical cores)
- RAM: 16,138 MB total, 2,607 MB available when the run started, 14,848 MB swap
- Python 3.14.2 (CPython) on Windows-11-10.0.26200-SP0
- Input: `data/curated/raw_tlc/fhvhv_tripdata_2019-02.parquet` -- 1 real NYC TLC FHVHV Parquet file(s)

This is a 4-core ultrabook under real memory pressure, not a benchmark rig. It is the honest floor: a server would be faster, so a PASS here is a conservative pass and a FAIL would need re-checking on better hardware.

## The ladder

| segments | rows read | wall median (s) | wall min (s) | spread | us/segment | peak RSS (MB) | teardown heap peak (MB) | status |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 40,000 | 26,000 | 2.80 | 2.76 | 10% | 69.9 | 141 | 20 | ok |
| 66,940 | 42,837 | 4.14 | 4.03 | 14% | 61.8 | 191 | 33 | ok |
| 200,000 | 123,253 | 13.66 | 13.36 | 22% | 68.3 | 450 | 99 | ok |
| 500,000 | 305,907 | 46.09 | 46.09 | 0% | 92.2 | 1,017 | 248 | ok |
| 1,000,000 | 605,190 | 76.46 | 76.46 | 0% | 76.5 | 1,923 | 497 | ok |
| 2,000,000 | 1,200,000 | 107.61 | 107.61 | 0% | 53.8 | 3,756 | 990 | ok |
| 5,000,000 | 2,990,817 | 156.54 | 156.54 | 0% | 31.3 | 5,954 | 2,470 | ok |

`wall median` is over the repeats for that rung and is what every derived figure below uses; `wall min` and `spread` (max-min over the median) are shown so run-to-run noise on a working laptop is visible rather than smoothed away. `peak RSS` is the whole child process at its high-water mark -- segments plus teardown -- because that is the number that decides whether a machine can run it at all. `teardown heap peak` is the extra Python-heap allocation the call itself makes above the resident segments, measured in a separate `tracemalloc` pass so the clock is never charged for the profiler.

**Top of the ladder: 5,000,000 segments.** Every requested rung completed -- **the ladder did not hit a wall**, it stopped because that was the largest rung asked for. The top rung did push this 16 GB laptop into sustained paging (the whole rung took about 21 minutes wall-clock, of which the teardown call itself was the time reported above), so it is the practical ceiling for this machine, not for the code.

## Curve shape

| from | to | input x | time x | log-log slope |
|---:|---:|---:|---:|---:|
| 40,000 | 66,940 | 1.67 | 1.48 | 0.76 |
| 66,940 | 200,000 | 2.99 | 3.30 | 1.09 |
| 200,000 | 500,000 | 2.50 | 3.38 | 1.33 |
| 500,000 | 1,000,000 | 2.00 | 1.66 | 0.73 |
| 1,000,000 | 2,000,000 | 2.00 | 1.41 | 0.49 |
| 2,000,000 | 5,000,000 | 2.50 | 1.46 | 0.41 |

**End to end: 125x the input for 56x the time — an overall log-log slope of 0.83.** Slope 1.0 is linear; 2.0 would be quadratic (10x input, 100x time).

The sharper statement is the per-segment cost, which over the whole ladder stays between **31 and 92 us/segment with no upward trend** — the largest rungs are, if anything, cheaper per segment than the smallest. **The teardown is linear in segment count.** It does not fall over, and there is no superlinear term waiting at scale.

The step-by-step slopes above swing between 0.41 and 1.33, and that spread is the machine, not the algorithm: this laptop thermally throttles under sustained load and its available RAM moved between 0.2 GB and 4.5 GB during the run. Those numbers are honest about resolution -- this ladder can prove linearity over two orders of magnitude, but it cannot resolve whether the true curve is n or n log n.

## Memory

- **519 bytes per segment** of peak Python heap inside the `teardown_deadhead` call itself. Measured per rung by `tracemalloc`, it ranged only 517-521 bytes/segment across the whole ladder. A constant to within about 1% over a 125x input range is as clean a linear memory law as this kind of measurement produces.
- **654 bytes per segment** to *hold* the input `VehicleSegment` objects, fitted across rungs.
- **Together, about 1.1 KB per segment** is what an operator's machine needs.

## Where the time goes

**About half the time is the reproducibility fingerprint, not the analysis.** At 5,000,000 segments `fingerprint_sha256` is 51% of the work and `hour_boundary_split` is 26%; the shares are stable across the whole ladder, which is itself evidence that every stage is linear.

`segment_set_fingerprint` is the dominant cost, and it is not computing anything an operator reads: it renders two ISO-8601 strings per segment, sorts the whole list, serialises it to canonical JSON and SHA-256s it, so the teardown can be re-derived and audited. That is a deliberate evidence cost (ADR-0039), and it is the first place to look if this ever needs to be faster -- **in Python, before any language change**. The point is not that it should change today; it is that the largest cost is optional bookkeeping rather than irreducible analysis, so a language rewrite would be optimising the wrong thing.

| stage | 40,000 | 66,940 | 200,000 | 500,000 | 1,000,000 | 2,000,000 | 5,000,000 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `materialise_input` | 0.00s (0%) | 0.00s (0%) | 0.00s (0%) | 0.00s (0%) | 0.00s (0%) | 0.00s (0%) | 0.00s (0%) |
| `headline_totals` | 0.16s (6%) | 0.26s (6%) | 1.05s (7%) | 2.53s (7%) | 4.91s (7%) | 6.87s (7%) | 7.77s (6%) |
| `hour_boundary_split` | 0.78s (28%) | 1.19s (29%) | 4.58s (29%) | 9.92s (26%) | 19.62s (28%) | 20.62s (22%) | 31.89s (26%) |
| `bucket_rollup` | 0.25s (9%) | 0.32s (8%) | 1.12s (7%) | 2.76s (7%) | 5.21s (7%) | 5.23s (6%) | 9.50s (8%) |
| `run_grouping` | 0.25s (9%) | 0.32s (8%) | 1.18s (7%) | 4.08s (11%) | 6.47s (9%) | 9.72s (11%) | 8.75s (7%) |
| `fingerprint_sha256` | 1.33s (47%) | 1.92s (47%) | 7.54s (48%) | 17.31s (46%) | 33.64s (47%) | 48.66s (53%) | 62.15s (51%) |
| `observation_window` | 0.06s (2%) | 0.09s (2%) | 0.29s (2%) | 0.94s (3%) | 1.46s (2%) | 1.31s (1%) | 2.75s (2%) |

Shares are of the stage pass's own total, because the stage pass and the timed full call are separate passes over the same input and agree only to within measurement noise (stage total vs full call: 2.83s vs 2.80s / 4.08s vs 4.14s / 15.76s vs 13.66s / 37.55s vs 46.09s / 71.30s vs 76.46s / 92.42s vs 107.61s / 122.81s vs 156.54s). The gap is manifest and model assembly -- a fixed number of pydantic objects regardless of input size -- plus run-to-run variance; it is reported rather than clamped into a fabricated residual.

Stage timers call `teardown.py`'s own helpers in the order `teardown_deadhead` calls them, so this is attribution, not inference.

A cProfile pass at 200,000 segments, by self time (the profiler inflates per-call cost, so this ranks functions -- it does not measure them; the stage table above does):

| function | calls | self (s) |
|---|---:|---:|
| `~:0(<method 'isoformat' of 'datetime.datetime' objects>)` | 400,002 | 4.25 |
| `teardown.py:457(_hour_slices)` | 200,000 | 3.47 |
| `teardown.py:491(_buckets)` | 3 | 1.66 |
| `teardown.py:475(_atoms)` | 1 | 1.54 |
| `~:0(<method 'total_seconds' of 'datetime.timedelta' objects>)` | 641,131 | 1.40 |
| `teardown.py:597(segment_set_fingerprint)` | 1 | 1.28 |
| `teardown.py:213(minutes)` | 400,000 | 1.25 |
| `~:0(<built-in method builtins.sorted>)` | 4 | 1.20 |
| `encoder.py:207(iterencode)` | 2 | 0.99 |
| `teardown.py:527(_run_contributions)` | 1 | 0.99 |
| `~:0(<method 'append' of 'list' objects>)` | 482,293 | 0.53 |
| `~:0(<method 'replace' of 'datetime.datetime' objects>)` | 241,131 | 0.47 |

## Input construction, for context

| segments | build (s) | us/segment | rows read | unmeasured rows | rejected |
|---:|---:|---:|---:|---:|---:|
| 40,000 | 3.13 | 78.3 | 26,000 | 8,638 | 0 |
| 66,940 | 5.21 | 77.8 | 42,837 | 14,871 | 0 |
| 200,000 | 16.16 | 80.8 | 123,253 | 44,693 | 0 |
| 500,000 | 49.75 | 99.5 | 305,907 | 109,866 | 0 |
| 1,000,000 | 83.51 | 83.5 | 605,190 | 208,420 | 0 |
| 2,000,000 | 132.51 | 66.3 | 1,200,000 | 394,763 | 0 |
| 5,000,000 | 156.02 | 31.2 | 2,990,817 | 972,217 | 0 |

Building the segments (DuckDB scan + `VehicleSegment.from_row` pydantic validation) is measured separately because it is the adapter's cost, not `teardown_deadhead`'s. An operator pipeline pays both, so it is reported -- but a Rust rewrite of the teardown would not remove it.

## Verdict

**The workload being judged.** `forge/business/outreach/design_partner_pitch.md` names the target as mid-size agencies running roughly **50,000-300,000 annual demand-response trips**. A trip-level export yields about two vehicle segments per trip (the empty approach drive and the revenue leg), so a design partner sending **a full year** arrives with roughly **300,000-600,000 segments** -- hundreds of thousands, not millions. That is the number the verdict is against.

**Measured, not projected.** 500,000 real segments -- inside that band -- tear down in **46.1 s**. Even at the worst per-segment cost seen anywhere on the ladder (92 us/segment), a full operator year of 600,000 segments is **about 55 seconds**. A whole year of an operator's trip history tears down in well under two minutes on a four-year-old ultrabook that is also running a browser and a container runtime.

**Memory is the binding constraint, and it is comfortable here.** The measured cost is about **1.1 KB per segment** (654 B to hold the segment plus 519 B of transient heap during the call). PROJECTION (not a measurement): an operator year of 600,000 segments needs roughly **0.7 GB** on top of the interpreter -- fine on any laptop. Memory, not the clock, is what eventually bites: the same law says ten million segments would want about 11 GB, which is a reason to batch a multi-year corpus, not a reason to change language.

**ADR-0026 trigger: NOT FIRED.** The measured-bottleneck trigger requires a bottleneck at a workload the product actually faces. The teardown is a batch analysis run once per operator export; at that workload it costs tens of seconds and under a gigabyte. Nothing here justifies crate #2, and the ladder found no wall at all -- it stopped at 5,000,000 segments because that was the largest rung requested, roughly ten times a realistic operator year.

**Where this is genuinely tight, stated rather than glossed.** The pre-registered threshold below is ~60 s, and 600,000 segments at the worst observed rate is ~55 s. That is a pass, but not a comfortable one, and it is only a pass **because this is a batch job**. On an interactive path -- the HTTP/SDK teardown surface (ADR-0042), where a person waits on a request -- a 46-second response at 500,000 segments is already unacceptable, today, before any growth. That is a real limit this benchmark found. It is not, however, an argument for Rust: the fix for an interactive path is to precompute, cache or run it asynchronously, not to make a once-per-export batch job 30x faster in another language. Roughly half the cost is the audit fingerprint, which could be made cheaper in Python first if it ever mattered.

**What would change the verdict** (stated in advance so it cannot be moved afterwards): a single teardown exceeding ~60 s at an operator's real segment count on hardware they would actually use; a peak footprint exceeding the memory of the machine it must run on; or the teardown becoming a synchronous, per-request operation rather than a per-export one. The first two do not hold today. The third is a design decision, not a performance measurement -- and it would call for caching, not a rewrite.

## Honest limitations

- **Sample, not census.** Each rung reads the first N rows of the source file in file order, so the rungs are nested (good for a curve) but are a contiguous slice of one month, not a random sample of the year. This supports claims about **runtime as a function of segment count**; it does not support claims about NYC deadhead rates, and the ADR-0039 headline (8.89%) is not restated or revised here.
- **FHVHV is rideshare, not paratransit.** Real and public, but not an operator export. Segment durations and the number of distinct run references (28 TLC bases) differ from a real paratransit export, and the run-grouping stage's cost depends on that cardinality -- see the verdict's caveat.
- **Wall-clock varies with machine state by more than the effect being measured.** The same 40,000-segment rung was measured at 25 us/segment on a cold machine and 70 us/segment once this ultrabook had thermally throttled under sustained load -- a ~2.8x swing that has nothing to do with the input. The committed ladder was taken under sustained load, i.e. at the slow end, which makes the verdict conservative. It also means the pairwise slopes are too noisy to distinguish n from n log n; what the ladder does support is the absence of any superlinear blow-up over 125x.
- **Rungs above 200,000 segments were timed once, not repeated** (a repeat costs minutes at those sizes), so they carry no spread estimate. The repeated small rungs spread 10-22%.
- **One machine, one run.** No cross-machine comparison, no CPU pinning, no isolated benchmark host. The machine was doing other work; `available RAM at start` is recorded so a reader can judge how much slack there was.
- **Projections are labelled.** Any figure beyond the largest successful rung is arithmetic on measured per-segment constants, marked PROJECTION, and is not a measurement.
- **Stage attribution is white-box and version-bound.** It calls teardown.py's private helpers; if those change, the stage table must be regenerated. The headline wall-clock does not depend on them.

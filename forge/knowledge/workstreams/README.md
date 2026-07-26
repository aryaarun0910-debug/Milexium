# forge/knowledge/workstreams/

Work-packet definitions in the format from
`blueprint/19-agent-swarm-execution-system.md` of the expansion plan, plus the
live dossier coverage ledger and cross-program status.

- `DOSSIER_COVERAGE.md` — traceability ledger for all 80 software-to-silicon
  technologies and 72 intelligence-layer projects from
  `blueprint/20-dossier-coverage-ledger.md`.
- `packets/` — one YAML file per dispatched work packet, named
  `MX-<WORKSTREAM>-<CAPABILITY>-<NNN>.yaml`.

A packet moves from this directory into an implementation only once its
`upstream_blockers` are empty and its `read_only_dependencies` resolve to a
versioned contract in `forge/knowledge/architecture/contracts/`.

**Owner:** integration workstream (adjudicates packet completion and merges).

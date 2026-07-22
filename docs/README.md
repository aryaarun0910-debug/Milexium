# Documentation index

This directory separates active operating documents from dated historical notes.
Only the documents in **Active** should drive current work.

## Active

- [MASTER_ROADMAP.md](MASTER_ROADMAP.md): canonical backlog and scope boundary.
- [DATA_SOURCES.md](DATA_SOURCES.md): public source catalog and claim provenance.
- [DATA_STORAGE.md](DATA_STORAGE.md): tracked, ignored, raw, derived, and artifact storage contract.
- [JOURNAL.md](JOURNAL.md): append-only record of completed work and decisions.
- [RND_QUESTIONS.md](RND_QUESTIONS.md): unresolved technical and domain questions.
- [yc/application-draft.md](yc/application-draft.md): current YC application working copy.

## Historical

`archive/` contains superseded handoffs, initial plans, website briefs, and
strategy notes. They preserve context but are not current instructions. Dated
generated outputs live under `artifacts/`, not under `docs/`.

## Maintenance rules

1. Update the roadmap when scope or status changes.
2. Append completed work to the journal; do not rewrite history into the roadmap.
3. Add every new public dataset to both `DATA_SOURCES.md` and the repository audit.
4. Move superseded plans to `archive/` instead of leaving competing active plans.
5. Keep generated screenshots, graphs, and reports under `artifacts/`.

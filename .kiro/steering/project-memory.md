---
inclusion: always
---

# Project memory: README and CHANGELOG

`README.md` and `CHANGELOG.md` are the project's own memory. They are included below so they are read before every task. Before implementing a feature, check them for existing decisions, naming and earlier changes, and stay consistent with them. If a request conflicts with something recorded there, point out the conflict before proceeding.

## README.md

#[[file:README.md]]

## CHANGELOG.md

#[[file:CHANGELOG.md]]

## Keeping them current

- Update `CHANGELOG.md` in the same change as the code. Add entries under `## [Unreleased]`, grouped by `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security` (Keep a Changelog format).
- Prefix each entry with its scope: `core:`, `factory:`, `festival:`, `repo:` or `kiro:`.
- Write entries for a reader who missed the work: what changed and why, and the spec or task it came from when there is one. One line per entry.
- Record notable design decisions in the changelog entry that introduced them ("Chose SQLite FTS5 over a vector store to keep demos offline").
- Update `README.md` when setup steps, commands, architecture, extension points or project status change. Keep the README's status section truthful: do not describe features as working before they are.
- When cutting a release, move `[Unreleased]` entries under a new version heading with the date (`## [0.1.0] - 2026-11-20`), following Semantic Versioning.

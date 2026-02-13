This repository is designed to be developed with coding agents (Codex, Cursor, etc.).

## Source of truth

**Start here:** `docs/design/README.md`

That index points to the canonical requirements, architecture, contracts, and test strategy.
If anything conflicts, prefer (in order):

1. `docs/design/*` (design docs / contracts)
2. `src/diffsan/contracts/*` (Pydantic models + error codes, once implemented)
3. Everything else (README, issues, comments)

## How to work in this repo

- Keep changes **small and composable**. Prefer thin vertical slices over broad refactors.
- If you change behavior that affects outputs, you must update:
  - the relevant `docs/design/*.md` doc(s), and
  - any example JSON in `docs/specs/schema/` (if present), and
  - the Pydantic models in `src/diffsan/contracts/models.py` (if present).
- If you add a config variable or change a config default, you must update:
  - `docs/configuration.md`, and
  - the relevant `docs/design/*.md` doc(s), and
  - `src/diffsan/contracts/models.py` defaults (if applicable).

## Key product intent (short)

- `diffsan` is an AI code reviewer for GitLab CI MRs.
- It prepares MR diffs (ignore/truncate/redact), runs an AI agent headlessly (MVP: Cursor CLI),
  validates strict JSON output against a schema, then posts a summary note + inline discussions to GitLab.
- Must **not block merges** (pipeline stage can be “allow failure”), but the CLI should exit non-zero on failures.
- Must **avoid spam** (verbosity tunable, avoid repeating prior findings).
- Must **redact secrets** before prompting; if secrets detected, log high severity and post a warning to the MR.

## Quick pointers for common tasks

- **Changing schemas / artifacts / error codes:** read `docs/design/02-contracts-and-schemas.md`
- **Pipeline flow / module boundaries:** read `docs/design/01-architecture.md`
- **Agent prompting / JSON repair loop:** read `docs/design/07-agent-prompting.md`
- **GitLab posting & positions:** read `docs/design/06-gitlab-integration.md`
- **How to test:** read `docs/design/05-test-strategy.md`

## Development commands

Use `make` targets for common development tasks:

- `make install` - install all dependencies
- `make verify` - run lint, format checks, and type checks
- `make fix` - auto-fix lint and format issues
- `make test` - run tests
- `make test-cov` - run tests with coverage
- `make test-matrix` - run tests across all Python versions
- `make test-matrix-cov` - run coverage tests across all Python versions
- `make pysentry` - run dependency vulnerability scanning
- `make docs` - build documentation
- `make docs-serve` - serve documentation locally

## Conventions

- Prefer typed code, keep functions small, and isolate side effects (Git, network, subprocess) behind modules.
- Always write artifacts to the run workdir (e.g. `.diffsan/` or `.ai-review/`) even on failure.
- Structured logging/events should be emitted (JSONL) to an artifacts file.

## Before you finish

- Ensure quality gates pass (`make verify`).
- Ensure unit tests pass (`make test`).
- Ensure the thin-slice pipeline still works end-to-end (even if GitLab/agent calls are mocked).
- Update docs when behavior/contracts change.

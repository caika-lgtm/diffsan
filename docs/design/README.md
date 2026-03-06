This directory contains the **canonical design context** for `diffsan`.
Agents and humans should treat these docs as the **source of truth** for requirements, contracts, and behavior.

## What is diffsan?

`diffsan` is a Python CLI intended to run in **GitLab CI** to perform AI-assisted MR diff reviews:

1. Obtain the MR diff against the target branch.
2. Preprocess (ignore paths, prioritize code, truncate to limits, redact secrets).
3. Decide whether to skip (MVP: skip on auto-merge).
4. Build a prompt and run an AI agent headlessly (Cursor default, Codex optional).
5. Validate the agent output as strict JSON (Pydantic schema), with retry/repair for unstructured agents.
6. Format and post:
   - a **summary MR note** (markdown) with collapsible metadata and truncation details
   - **inline discussions** for findings (when a valid position can be computed)
7. Always store prompt/output artifacts and structured events.

## Non-goals

- Do not block merges (the merge decision remains with humans; CI job may be allow-failure).
- Standalone mode is minimal (prints to stdout, no GitLab posting).
- Support for additional agents beyond Cursor/Codex and other forges (GitHub) is future work.

## Reading guide (use this as an index)

If you are working on…

### Requirements and scope

- **Product goals / non-goals / success metrics:** `00-product-brief.md`

### Architecture and pipeline

- **Monolith module boundaries and data flow:** `01-architecture.md`

### Contracts (must stay stable)

- **Pydantic schemas, artifact files, error codes, events:** `02-contracts-and-schemas.md`
- **Artifact directory layout + event schema:** `03-artifacts-and-events.md`

### Testing

- **Unit tests, fakes, fixtures, CI smoke tests:** `05-test-strategy.md`

### GitLab specifics

- **CI variables, APIs, posting notes/discussions, position pitfalls:** `06-gitlab-integration.md`

### Agent behavior

- **Prompt templates, JSON-only requirement, repair loop strategy:** `07-agent-prompting.md`

### Decisions (ADR-lite)

- **Key decisions and rationale (keep terse):** `08-decision-log.md`

## Change rules (important)

- If you change any contract (schemas, artifacts, error codes, event names):
  1. Update `02-contracts-and-schemas.md`
  2. Update `src/diffsan/contracts/models.py` and `src/diffsan/contracts/errors.py` (once implemented)

## Quick invariants (do not violate)

- Secrets must be redacted before prompting.
- Avoid spam: verbosity tunable; include compact prior digest; avoid repeating prior findings.
- Artifacts (prompt + raw output + validated review) should be written even when failures occur.
- Cursor output is unstructured; JSON validation + repair retries are required for cursor runs.
- Codex output is schema-structured; diffsan still validates once before post formatting.
- Summary note contains collapsible metadata (fingerprint, timings, token usage, truncation info, redaction flag).

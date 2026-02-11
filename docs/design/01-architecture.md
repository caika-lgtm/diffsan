## Overview

`diffsan` is a **single-process (monolithic) CLI** with clear internal module boundaries. It is designed for:

- strong debuggability (artifacts always written),
- robust unstructured agent handling (Cursor JSON repair retries),
- easy extension later (additional skip rules, agents, GitHub support).

The monolith is structured as a pipeline of modules with contracts defined in `02-contracts-and-schemas.md`.

## High-level components (internal modules)

- **ConfigLoader**: merge defaults + repo config + env + CLI args
- **DiffProvider**: obtain MR diff (CI path is primary)
- **Preprocessor**: ignore/prioritize/truncate + secret scan/redact
- **Fingerprinting**: sha256(raw diff), deterministic finding IDs (optional)
- **PriorDigestResolver**: fetch prior bot summary note and extract digest
- **SkipEngine**: decide whether to skip (MVP: auto-merge)
- **PromptBuilder**: build agent prompt, inject schema + diff + digest + flags
- **AgentRunner (Cursor)**: run headless Cursor; JSON repair retry loop
- **Parser/Validator**: parse agent output to strict JSON and validate with Pydantic
- **Formatter**: render summary markdown + collapsible metadata and truncation
- **GitLabPoster**: post summary note and inline discussions with retries
- **Artifacts/Events**: write prompt/output/review + structured events JSONL

## Data flow (CI mode)

1. `load_config()` -> `AppConfig`
2. `get_diff()` -> `DiffBundle` + write `diff.raw.patch`
3. `prepare_diff()` -> `PreparedDiff` + write `diff.prepared.patch`, `truncation.json`, `redaction.json`
4. `compute_fingerprint(raw_diff)` -> `Fingerprint`
5. `get_prior_digest()` -> `PriorDigest | None` + write `prior_digest.json`
6. `decide_skip()` -> `SkipDecision`
   - if skip: write `run.json` ok=true with skip reason; exit 0
7. `build_agent_request()` -> `AgentRequest` + write `prompt.txt`
8. `run_agent_with_retries()` -> `AgentRawResponse` + `ReviewOutput`
   - write `agent.raw.txt` (and optionally per-attempt outputs)
9. `validate_review()` -> `ReviewOutput` + write `review.json`
10. `build_post_plan()` -> `PostPlan` + write `post_plan.json`
11. `post_to_gitlab()` -> `PostResults` + write `post_results.json`
12. Write `run.json` and `events.jsonl` throughout

Standalone mode is minimal:

- acquire diff locally (simple)
- run agent and validate
- print summary to stdout
- no GitLab posting

## Invariants (must hold)

- Artifacts must be written even on failure (prompt/raw output/review when available).
- Secret redaction occurs before prompting.
- Cursor output must be validated as strict JSON; use repair retries.
- Avoid spam: verbosity configurable; inject compact prior digest; avoid repeating prior findings.
- Tool exits non-zero on failures (pipeline can be configured allow-failure).

## Extensibility points (future)

- Additional agents (Codex CLI) via adapter modules
- Additional forges (GitHub) by swapping posting client and MR context
- Additional skip rules (draft/WIP, docs-only, etc.)
- More sophisticated diff selection/truncation (risk-based sampling)

## What is diffsan?

`diffsan` is a Python CLI tool intended to run primarily in **GitLab CI** on **Merge Request pipelines**. It performs an AI-assisted review of the MR diff against the target branch, then posts review feedback back to the MR as:

- A **summary note** (markdown) that includes:
    - high-level summary of issues
    - a **collapsible metadata** section (fingerprint, timings, token usage, agent info, truncation/redaction flags)
    - a **collapsible truncation** section (what was truncated/excluded)
- **Inline discussions** (per-finding comments) positioned on diffs when possible.

Supported agents are **Codex CLI** (default) and **Cursor CLI**.

## Primary goals (priority order)

1. Catch **correctness & security** issues in code changes.
2. Improve maintainability/quality.
3. Enforce project-specific conventions (“skills” / rules).
4. Speed up human review with good summaries and highlighted hotspots.

## Non-goals

- Do **not** block merges. The tool may exit non-zero on error, but the pipeline stage can be configured allow-failure. Merge decisions remain with humans.
- Standalone mode is minimal (reviews local `git diff` output, prints to stdout only, and does not post to GitLab).
- Not aiming for org-wide service/infrastructure; it is a **local CLI** installed via pipx.
- Not aiming for perfect dedupe/policy enforcement at MVP (keep extensible).

## Must-not-do failure modes

- **Leak secrets** into prompts, logs, artifacts, or MR comments.
- Generate **spammy** comments (verbosity must be tunable; avoid repeating prior findings).
- Produce output that is impossible to consume (must validate strict JSON schema).

## Constraints & assumptions

- The CI runner runs the selected agent CLI (Cursor or Codex); code diffs will be sent to the internet by that agent.
    - This is acceptable under enterprise/compliance oversight.
- Must do **best-effort secret redaction** before prompting.
    - If secrets are detected, log high severity and (optionally) post a warning on the MR (without exposing the secret).
- Must support multiple config sources with precedence:
    - repo config file
    - env/CI variables
    - CLI flags
    - sensible defaults with minimal setup (opinionated tool)

## Typical CI flow

1. Identify MR and compute diff against target branch.
2. Preprocess diff: ignore paths, prioritize code, truncate to limits, redact secrets.
3. Decide if review should run (MVP: skip if auto-merge enabled).
4. Build prompt and run the selected agent headlessly.
5. Validate output as strict JSON using Pydantic schema; retry/repair is used for cursor only.
6. Format summary + discussions.
7. Post to GitLab (notes + discussions) with retries.
8. Always store artifacts (prompt + raw output + validated JSON + events).

## Standalone mode

When `mode.ci = false`, `diffsan` runs inside a local git repository and reviews the unstaged working-tree diff from `git diff --no-color`.

- No MR variables are required.
- No GitLab prior-context fetch or posting occurs.
- If the local diff is empty, diffsan exits successfully with a skip reason instead of invoking the agent.

## Success metrics (practical)

- **Reliability:** % runs producing valid `review.json` and successfully posting summary note.
- **Signal-to-noise:** low number of low-value comments; avoids repeats.
- **Safety:** zero incidents of unredacted secrets in prompt/artifacts/MR.
- **Latency:** agent runtime and job duration within acceptable CI budget.

## MVP v0 scope

- Agent: Codex CLI by default, Cursor CLI optional
- GitLab posting: summary note + inline discussions (when position computable)
- Skip: auto-merge true => silent skip (stdout only)
- Fingerprint: sha256(raw diff)
- Prior digest: compact digest injected into prompt to avoid repeating

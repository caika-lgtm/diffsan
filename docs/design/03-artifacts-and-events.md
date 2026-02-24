This document defines what `diffsan` must write to disk during a run and the structured events it should emit.
Artifacts are critical for debugging CI runs and for auditing prompt/output handling.

## Guiding principles

- **Artifacts are always written**, even on failure.
- **Never store raw secrets** in artifacts. Redaction must occur before prompting.
- Prefer **plain text** for prompt and raw agent output, and **JSON** for structured reports.
- Events should be **structured JSONL** (one JSON object per line) for easy grep and post-processing.
- Emit concise console lines for key events during execution:
  - info/warn events to stdout
  - error events to stderr
  - include enough context to diagnose failures without opening artifacts

---

## Workdir location and naming

- Default workdir is a directory in the repo workspace, e.g.:
  - `.diffsan/` (recommended branding)
- Allow override via:
  - repo config file key: `workdir`
  - Env var: `DIFFSAN_WORKDIR`

The workdir must be created early (before network/subprocess work).

---

## Artifact file list (MVP v0)

### Always present (even on failures)

- `run.json`
  - final status: ok/false
  - skip status/reasons (if skipped)
  - error info (if failed)
  - fingerprint (if available)
- `events.jsonl`
  - structured events emitted throughout the run

### Diff acquisition and preparation

- `diff.raw.patch`
  - raw diff as acquired (may contain secrets before redaction)
  - NOTE: if secrets policy requires, consider storing only redacted raw diff; MVP allows raw diff artifact but should be configurable. If stored, ensure it is not printed to stdout.
- `diff.prepared.patch`
  - the diff that was actually sent to the agent (post ignore + truncation + redaction)
- `truncation.json`
  - `TruncationReport` (see `02-contracts-and-schemas.md`)
- `redaction.json`
  - `RedactionReport` (hashes/length only, no raw secrets)
- `prior_digest.json`
  - `PriorDigest` merged from prior tagged summary notes and inline discussions; if unavailable, write `{}` or omit (implementation choice)
- `skip.json` (optional but useful)
  - `SkipDecision` (should_skip + reasons + fingerprint)

### Agent invocation

- `prompt.txt`
  - exact prompt passed to the agent (must contain redacted diff only)
- `agent.raw.txt`
  - raw stdout from agent attempt 1 (may not be valid JSON)
- `agent.stderr.txt` (optional but helpful)
  - raw stderr from agent attempt 1
- `agent.raw.attemptN.txt` (optional)
  - if repair retries occur, store each attempt separately
- `agent.run.json` (optional)
  - `AgentRunStats` and exit code for each attempt

### Validated outputs and posting

- `review.json`
  - validated `ReviewOutput` JSON
- `post_plan.json`
  - `PostPlan` (what we intended to post)
- `post_results.json`
  - `PostResults` (what was posted + any errors)

---

## Minimal `run.json` schema

`run.json` is the canonical summary of the run outcome.

Example success (posted):

```json
{
  "ok": true,
  "skipped": false,
  "fingerprint": { "algo": "sha256", "value": "b7d4..." },
  "artifacts": {
    "workdir": ".diffsan",
    "prompt": "prompt.txt",
    "raw_output": "agent.raw.txt",
    "review": "review.json"
  }
}
```

Example skipped:

```json
{
  "ok": true,
  "skipped": true,
  "skip_reasons": [
    { "code": "AUTO_MERGE", "message": "MR has auto-merge enabled" }
  ],
  "fingerprint": { "algo": "sha256", "value": "b7d4..." }
}
```

Example failure:

```json
{
  "ok": false,
  "skipped": false,
  "fingerprint": { "algo": "sha256", "value": "b7d4..." },
  "error": {
    "error_code": "AGENT_OUTPUT_INVALID",
    "message": "Failed to obtain valid JSON output after 3 attempts",
    "retryable": false,
    "context": { "attempts": 3, "agent": "cursor" },
    "cause": "pydantic.ValidationError: ..."
  }
}
```

---

## Events (events.jsonl)

### Event envelope

Each line is a JSON object:

```json
{
  "ts": "2026-02-10T12:01:00Z",
  "level": "info",
  "event": "diff.fetched",
  "data": { "chars": 18342, "files": 12 }
}
```

Fields:

- `ts`: ISO8601 UTC timestamp
- `level`: `error|warn|info|debug`
- `event`: event name string
- `data`: object with event-specific payload

### Required events (MVP v0)

- `run.started`
  - `{"version": "...", "ci": true, "workdir": ".diffsan"}`

- `config.loaded`
  - minimal: `{"ci": true, "agent":"cursor", "verbosity":"medium"}`

- `diff.fetched`
  - `{"chars":..., "files":..., "base_sha":"...", "head_sha":"..."}`

- `diff.prepared`
  - `{"final_chars":..., "truncated":true|false, "redaction_found":true|false}`

- `skip.decided`
  - `{"should_skip":true|false, "reasons":[...], "fingerprint":"sha256:..."}`

- `prompt.written`
  - `{"path":"prompt.txt", "chars":...}`

- `agent.attempt`
  - `{"attempt":1, "exit_code":0, "duration_ms":...}`

- `review.validated`
  - `{"findings":3, "truncated":true|false}`

- `post.plan_built`
  - `{"discussions":3, "idempotent_summary":false}`

- `gitlab.post.summary`
  - `{"ok":true, "http_status":201, "id":987654, "retry":0}`

- `gitlab.post.discussion`
  - `{"ok":true, "http_status":201, "path":"...", "line":95, "retry":0}`

- `error.raised`
  - `{"error_code":"...", "retryable":false, "context":{...}}`

- `run.finished`
  - `{"ok":true|false, "skipped":true|false, "duration_ms":...}`

### Event hygiene

- Do not log raw diffs or prompts to stdout by default.
- `events.jsonl` may contain file paths and counts; avoid dumping large bodies.
- Console event lines should stay compact and summarize key scalar fields only.

---

## Redaction and artifact safety notes

- Redaction must be applied before `prompt.txt` is written.
- `redaction.json` must never contain raw secrets (only hashes/length).
- If you store `diff.raw.patch`, it may include secrets prior to redaction. Consider:
  - making raw diff artifact optional via config (recommended), or
  - storing only a redacted raw diff and preserving original only in memory.
  - MVP can start with storing raw diff but should not print it and should document the risk.

---

## Practical defaults (recommended)

- Always write:
  - `prompt.txt`, `agent.raw.txt`, `review.json` (when available)

- Always write `events.jsonl` and `run.json`
- On retries, store per-attempt output files for debugging

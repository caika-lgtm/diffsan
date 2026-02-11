# Test Strategy

This document describes the practical test approach for `diffsan` (a monolithic Python CLI run via `pipx`) with a focus on: **fast local feedback**, **high confidence in CI**, and **minimal operational overhead**.

## Goals

- Catch regressions in core behaviors: diff preparation, redaction, truncation, prompt construction, schema validation, and GitLab posting.
- Ensure **artifacts are always written** (prompt + agent output + run status) even on failure.
- Keep tests **small, deterministic, and offline** by default.
- Make it easy to add new skip rules, agents, and SCM providers without rewriting tests.

## Non-goals

- Full end-to-end integration tests on every CI run (agent calls are expensive and flaky).
- Perfect secret detection correctness (best-effort regex); tests assert **no raw secret leaks** rather than perfect detection coverage.
- Exhaustive GitLab position algorithm validation (we test happy paths + graceful degradation).

---

## Test pyramid

### 1) Unit tests (offline, fast)

These cover deterministic pure logic and schema validation. They should run in <5s locally.

**Targets**

- Config merging / precedence
- Diff filtering, prioritization, truncation
- Secret scanning + redaction
- Fingerprinting + stable IDs
- Prompt assembly
- JSON parsing + Pydantic validation
- Markdown formatting of summary metadata/truncation

**Tooling**

- `pytest`
- `pytest-cov` (optional)
- Avoid network and subprocess calls (mock them)

### 2) Component tests (offline with fakes/mocks)

These test modules with controlled dependencies:

- Agent runner with a fake subprocess runner (Cursor output simulation)
- GitLab client with a fake HTTP server or mocked transport
- Orchestrator pipeline with faked agent + faked GitLab client, verifying artifacts/events

These provide confidence in interactions and error handling without calling external services.

### 3) Smoke test (optional, manual or scheduled)

A single real run against:

- Cursor CLI (enterprise)
- GitLab API posting

This is expensive; keep it **manual** or run nightly/scheduled to avoid flakiness and cost.

---

## Canonical test fixtures

All fixtures live under `tests/fixtures/`:

```

tests/fixtures/
diffs/
small.patch
large.patch
secrets.patch
only_docs.patch
agent_outputs/
valid_review.json
invalid_not_json.txt
invalid_schema.json
mixed_markdown_and_json.txt
gitlab/
mr_notes_with_prior_summary.json
mr_details_auto_merge_true.json
create_note_response.json
create_discussion_response.json
create_discussion_position_error.json

```

Fixture guidance:

- `*.patch` should be small and readable.
- `secrets.patch` should include synthetic secrets (not real) and assert they are redacted.
- Agent outputs should include both parse failures (not JSON) and schema failures (JSON but wrong fields).

---

## What to test (by module)

### `core/config.py`

**Unit tests**

- Default config loads with sensible values.
- Precedence: CLI flags > env/CI vars > repo file > defaults.
- Invalid config produces `CONFIG_PARSE_ERROR`.

**Example checks**

- `max_diff_chars` overridden by env var is reflected in `AppConfig`.
- Unknown field behavior matches your policy (strict or permissive).

---

### `core/diff_provider.py`

**Unit tests**

- Environment parsing for CI variables (MR iid, project id, branches).
- Command construction for `git diff target...head`.

**Component tests**

- Subprocess wrapper returns a fixture diff for “git diff”; provider returns `DiffBundle`.

**Failure tests**

- Missing required CI vars raises `DIFF_FETCH_FAILED` with context.
- Git command non-zero exit raises `DIFF_FETCH_FAILED` (retryable: false by default).

---

### `core/preprocess.py`

**Unit tests**

- Ignore globs exclude expected paths.
- Prioritization sorts code files ahead of docs.
- Truncation obeys:
  - `max_diff_chars`
  - `max_files`
  - `max_hunks_per_file`
- Truncation report contains:
  - `truncated`, counts, and at least one `TruncationItem` when truncated.
- Secret scanning/redaction:
  - matches generate `RedactionReport.found == true`
  - secrets replaced with `[REDACTED]`
  - no raw secret ends up in report, events, or stdout (only hash/length)

**Edge cases**

- Binary diffs / large blobs are handled without crashes (may be excluded).
- Diff with unusual encoding doesn’t crash (best-effort).

---

### `core/fingerprint.py`

**Unit tests**

- Fingerprint stable for identical diff text.
- Fingerprint changes when diff text changes.
- If you compute `finding_id`: stable across identical findings after normalization.

---

### `core/prior.py`

**Component tests**

- Given fixture MR notes with a prior summary note, returns:
  - `prior_fingerprint`
  - compact `PriorDigest.findings`

**Failure tests**

- Notes endpoint failure maps to `GITLAB_FETCH_PRIOR_FAILED` (retryable depending on HTTP status).
- Missing/invalid prior format returns empty digest (should not crash).

---

### `core/skip.py`

**Unit tests**

- Auto-merge signal true => `should_skip == true` with reason `AUTO_MERGE`.
- Otherwise `should_skip == false`.

**Component tests**

- MR details fixture used to confirm skip decision.

---

### `core/prompt.py`

**Unit tests**

- Prompt includes:
  - schema instruction (“JSON only”)
  - prepared diff content
  - truncation disclosure + what was truncated (or instruction to include it)
  - redaction flag (if secrets found)
  - prior digest + “avoid repeating” instruction
  - verbosity + skills if configured

**Safety tests**

- Prompt does not include raw secret strings (use `secrets.patch` fixture).

---

### `core/agent_cursor.py`

**Component tests with fake subprocess**

- Attempt 1 returns invalid JSON -> repair attempt succeeds -> returns validated `ReviewOutput`.
- Attempt N exhaustion -> raises `AGENT_OUTPUT_INVALID` and writes all raw outputs to artifacts.

**Timing tests**

- Stats are captured and included in `ReviewMeta.timings` (optional tokens allowed to be empty).

---

### `core/parse_validate.py`

**Unit tests**

- Valid JSON fixture parses to `ReviewOutput`.
- Invalid JSON fixture raises parse error with helpful context.
- JSON missing required fields fails Pydantic validation.
- If you support stripping code fences: test mixed markdown+json fixture behavior (decide policy and test it).

---

### `core/format.py`

**Unit tests**

- Produces summary note markdown that includes:
  - `<details><summary>Metadata</summary>...`
  - fingerprint, agent, duration, token usage (if available)
  - truncation disclosure clearly marked when truncated
  - truncation details `<details>` section listing excluded/limited items
  - redaction warning section if secrets found (without raw secrets)

- Builds `PostPlan` with:
  - `discussions[]` mapped from findings
  - unpositioned findings degrade gracefully (if position not computable)

---

### `core/gitlab.py`

**Component tests with mocked HTTP**

- `POST note` success -> records correct payload.
- `POST discussion` success -> records correct payload.
- Retry behavior:
  - 429 then 201 -> succeeds with retry_count incremented
  - 5xx then 201 -> succeeds
- Non-retryable:
  - 401/403 -> `GITLAB_AUTH_ERROR` (no retries)
  - 400 invalid position -> `GITLAB_POSITION_INVALID` (no retries unless recompute is implemented)

---

### `run.py` (orchestrator)

**Component tests**

- Happy path with fake agent + fake gitlab:
  - writes artifacts: `prompt.txt`, `agent.raw.txt`, `review.json`, `post_plan.json`, `post_results.json`, `events.jsonl`, `run.json`
  - `run.json.ok == true`
- Failure path (agent invalid after retries):
  - still writes: `prompt.txt`, `agent.raw.txt`, `run.json` with structured error
  - exits non-zero (test via calling `run()` directly or using `pytest` to capture SystemExit)
- Skip path:
  - writes minimal artifacts + stdout message
  - does not call agent or GitLab poster

---

## Assertions that matter most (high ROI)

1. **No secret leaks**

- Redaction report never stores raw secrets.
- Prompt artifact contains `[REDACTED]` not the original token.
- Summary/discussions do not include raw secrets.

2. **Artifacts always exist**

- On any error, `run.json` and `events.jsonl` are written.
- `prompt.txt` and `agent.raw.txt` are written once prompt/agent stages begin.

3. **Schema contract enforcement**

- Any agent output must validate against `ReviewOutput` Pydantic schema.
- Invalid outputs fail loudly (non-zero exit) and are preserved as artifacts.

4. **Graceful degradation**

- If a discussion position can’t be computed or GitLab rejects it, the tool still posts/keeps a usable summary (and records the failure in `post_results.json`).

---

## Suggested CI test jobs (GitHub Actions)

- `unit`:
  - `pytest -q`
- `lint` / `typecheck`:
  - ruff/black + mypy (if enabled)
- `smoke` (manual trigger):
  - runs `diffsan` with real Cursor + GitLab token against a controlled MR

Keep smoke tests out of the default pipeline or make them `workflow_dispatch` only.

---

## Adding new features without breaking tests

When you add:

- New skip rules: add unit tests in `test_skip.py` and extend fixtures.
- New agent (Codex CLI): add a parallel fake runner and reuse parse/validate + format tests.
- GitHub support: replicate `core/gitlab.py` tests for a `core/github.py` module and keep contracts stable.

---

## Quick checklist for a new PR

- [ ] Updated/added fixtures if behavior changed
- [ ] Unit tests cover new logic
- [ ] Component tests cover interactions (agent or API)
- [ ] No secrets printed or stored unredacted
- [ ] Artifacts are still written on failure
- [ ] `ReviewOutput` schema remains the single source of truth

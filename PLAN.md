# diffsan MVP v0

This plan targets a small, practical MVP that works in **GitLab CI** and is installable via **pipx**.

## MVP v0 Definition of Done

MVP v0 is done when:

- CI mode can run on a Merge Request pipeline and produce these artifacts under the run workdir (e.g. `.diffsan/`):
  - `prompt.txt`, `agent.raw.txt`, `review.json`, `events.jsonl`, `run.json`
- Cursor CLI output is made robust via a **JSON repair retry loop**.
- GitLab posting works:
  - posts a **summary note** containing markdown + collapsible metadata + truncation details
  - posts **inline discussions** when a valid position can be computed
  - degrades gracefully (summary-only) when positions can’t be computed
- Skip works for MVP:
  - silently skip (stdout only) when **auto-merge is true**
- Tool exits **non-zero on failures**, and artifacts are still written (pipeline can be configured allow-failure).

---

## Milestone 0 — Project skeleton + run harness

**Goal:** runnable CLI + artifacts + structured events, even for no-op runs.

### Work items

- Implement CLI entrypoint:
  - `src/diffsan/cli.py` parses args and calls orchestrator
  - command: `diffsan` (via `pyproject.toml` entrypoint)
- Implement orchestrator:
  - `src/diffsan/run.py` with top-level try/except and error normalization
- Implement contracts:
  - `src/diffsan/contracts/models.py` (Pydantic models: config, diff/prep, agent I/O, review output, post plan/results)
  - `src/diffsan/contracts/errors.py` (`ReviewerError`, `ErrorInfo`, error codes)
  - `src/diffsan/contracts/events.py` event names + `Event` schema
- Implement artifact IO + event logging:
  - `src/diffsan/io/artifacts.py` to create workdir + write/read json/text
  - `src/diffsan/io/logging.py` to emit `events.jsonl`

### Acceptance criteria

- `pipx install -e .` then `diffsan --help` works
- `diffsan --ci --dry-run` (or similar) creates the workdir and writes:
  - `events.jsonl` and `run.json`
- Failures still produce `run.json` with structured `error` and a non-zero exit code.

---

## Milestone 1 — Thin slice: diff → prompt → cursor → validate → stdout (no GitLab post)

**Goal:** generate a validated `review.json` from a real MR diff.

### Work items

- Diff provider (CI only first):
  - `src/diffsan/core/diff_provider.py`
  - Implement `get_diff()` using `git diff <target>...<head>` with GitLab CI variables
- Preprocessor MVP:
  - `src/diffsan/core/preprocess.py`
  - Ignore globs
  - Prioritize code extensions over docs
  - Truncate by:
    - `max_diff_chars`, `max_files`, `max_hunks_per_file` (simple heuristic is fine)
  - Secrets scan + redact (best-effort regex)
    - store _only hashes_ of matches, never raw secrets
  - Write artifacts:
    - `diff.raw.patch`, `diff.prepared.patch`, `truncation.json`, `redaction.json`
- Fingerprinting:
  - `src/diffsan/core/fingerprint.py`
  - sha256(raw diff)
- Prompt builder:
  - `src/diffsan/core/prompt.py`
  - Include schema + “JSON only” + prepared diff + truncation/redaction flags
  - Write `prompt.txt`
- Cursor runner (single attempt for now):
  - `src/diffsan/core/agent_cursor.py`
  - Write `agent.raw.txt`
- Parse & validate:
  - `src/diffsan/core/parse_validate.py` -> Pydantic `ReviewOutput`
  - Write `review.json`
- Formatter (stdout only):
  - `src/diffsan/core/format.py` prints `summary_markdown` to stdout

### Acceptance criteria

- In a GitLab MR pipeline, job produces:
  - `prompt.txt`, `agent.raw.txt`, `review.json`, `events.jsonl`, `run.json`
- `review.json` validates against Pydantic schema
- If truncation occurred, it’s logged and included in summary instructions.

---

## Milestone 2 — Cursor reliability: JSON repair retries

**Goal:** robust JSON output even when Cursor responds with extra text.

### Work items

- Add retry loop to `run_agent_with_retries()`:
  - Attempt 1 normal prompt
  - On parse/validation error:
    - generate repair prompt including:
      - strict “return ONLY valid JSON”
      - concise validation error summary
      - raw output excerpt (bounded)
  - Stop on success or `max_json_retries` exhaustion
- Capture per-attempt raw outputs optionally:
  - `agent.raw.attempt1.txt`, `agent.raw.attempt2.txt`, etc.
- On exhaustion:
  - exit non-zero
  - keep artifacts

### Acceptance criteria

- Unit/component test covers:
  - attempt 1 invalid output → attempt 2 repaired JSON → success
- `run.json` clearly indicates `AGENT_OUTPUT_INVALID` when retries exhausted.

---

## Milestone 3 — GitLab posting: summary note

**Goal:** post a summary note to MR with metadata and truncation details.

### Work items

- GitLab client:
  - `src/diffsan/core/gitlab.py`
  - Project Access Token from env
  - Implement:
    - `get_mr()` (needed later for auto-merge)
    - `create_note()`
- Format summary note body:
  - markdown + `<details>` metadata:
    - fingerprint, agent, timings, token usage (if present), truncation, redaction flag
  - `<details>` truncation details (“what was truncated”)
  - Secret detection warning section (no raw secret content)
- Retry policy:
  - retry on 429/5xx/timeouts up to `retry_max`
  - fail fast on 401/403/404

### Acceptance criteria

- Running in MR pipeline posts a bot note successfully
- Failures to post are retried then return non-zero while preserving artifacts.

---

## Milestone 4 — Inline discussions (findings → discussions)

**Goal:** post discussions when position can be computed; otherwise degrade to summary-only.

### Work items

- Build `PostPlan`:
  - `src/diffsan/core/format.py` maps findings → discussion payloads
- Implement position strategy (practical MVP):
  - Compute positions for cases where a **new line** can be mapped (use `base_sha/head_sha` from CI vars / MR API)
  - If cannot compute position:
    - do not post discussion
    - add the finding into a summary section: “Unpositioned findings”
- Add `create_discussion()` with retries
- Write `post_plan.json` and `post_results.json`

### Acceptance criteria

- At least common “new line” cases create discussions
- Invalid position errors do not crash posting of summary; tool exits non-zero (posting partially failed) and records results.

---

## Milestone 5 — Skip + prior digest (MVP)

**Goal:** skip when auto-merge is true; include compact prior digest when re-reviewing.

### Work items

- Auto-merge detection (MVP):
  - `core/skip.py` uses MR API fields to determine “auto-merge enabled”
  - If enabled and `skip_on_auto_merge=true`: skip silently (stdout only)
- Prior digest extraction:
  - `core/prior.py` reads prior bot summary note(s) tagged by `summary_note_tag`
  - Extract:
    - prior fingerprint
    - compact digest of findings (ids/titles/severity/path/line range)
- Prompt injection:
  - `core/prompt.py` includes digest + “avoid repeating, don’t re-assert unresolved”
- Fingerprint logic:
  - if diff unchanged and already reviewed (optional future):
    - could skip, but MVP can simply re-run unless explicitly enabled

### Acceptance criteria

- Auto-merge MRs skip (no MR note/discussion), stdout indicates skip reason
- On re-run with changed diff, prompt includes prior digest and reviews avoid repeats (best-effort).

---

## Test Strategy (for MVP v0)

### Unit tests (offline, fast)

- `test_config.py`: precedence (defaults < repo < env < flags)
- `test_preprocess.py`: ignore/prioritize/truncate + truncation report correctness
- `test_redaction.py`: patterns redact and never store raw secret
- `test_fingerprint.py`: stable sha256
- `test_prompt.py`: schema + truncation/redaction flags + prior digest included
- `test_parse_validate.py`: valid passes; invalid fails with clear error

### Component tests (offline, fakes)

- Fake Cursor runner:
  - invalid output then valid output to verify retry/repair loop
- Fake GitLab client:
  - note creation success
  - discussion creation 400 invalid position
  - 429 then success (retry behavior)

### Integration test (no network)

- Run orchestrator with fakes and a fixture diff; assert artifacts exist and `run.json.ok` correct.

### Optional CI smoke test (manual trigger)

- In a test repo:
  - real Cursor + real GitLab token
  - asserts artifacts are uploaded; manual check that note/discussions appear

---

## Operational notes

- The tool should be installable via `pipx install diffsan`.
- Default behavior should work with minimal config in GitLab CI:
  - relies on standard MR CI variables
  - requires `GITLAB_TOKEN` (project access token) when posting is enabled
- Always write artifacts early and often; never lose prompt/raw output on failure.

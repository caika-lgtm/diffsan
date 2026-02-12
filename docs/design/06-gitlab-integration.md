This document describes how `diffsan` integrates with GitLab in **CI Merge Request pipelines**:

- how we identify the MR and refs,
- how we fetch diffs,
- how we detect skip conditions (MVP: auto-merge),
- how we post summary notes and inline discussions,
- how we handle retries and failures.

> Design intent: keep GitLab integration small and robust for MVP v0, but extensible for future features (idempotency, richer skip rules, GitHub support).

---

## 1) Authentication

### MVP: Project Access Token

- `diffsan` uses a **Project Access Token** (bot user) provided via an env var.
- Config field: `gitlab.token_env` (default `GITLAB_TOKEN`).

**Required scopes/permissions**

- Must be able to:
  - read MR metadata
  - list MR notes
  - create MR notes
  - create MR discussions
- Exact scopes vary by GitLab setup; ensure token is allowed for MR notes/discussions.

**Failure modes**

- `401 Unauthorized` / `403 Forbidden`: treat as non-retryable; exit non-zero; write artifacts and `run.json`.

---

## 2) Identifying the MR in CI

### Inputs

`diffsan` expects to run in **MR pipelines** and uses GitLab-provided CI environment variables.

Common variables (names vary by GitLab version/config):

- `CI_MERGE_REQUEST_IID` (MR IID within project)
- `CI_PROJECT_ID` (project numeric ID)
- `CI_API_V4_URL` (base API URL, e.g. `https://gitlab.example.com/api/v4`)
- `CI_PROJECT_URL` (project URL)
- `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`
- `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`
- `CI_COMMIT_SHA` (head SHA for current pipeline commit)
- `CI_MERGE_REQUEST_DIFF_BASE_SHA` (sometimes available; useful for positions)
- `CI_SERVER_URL` or `CI_SERVER_HOST` (fallback for base_url composition)

> Implementation note: treat env vars as best-effort and log which were used. If `mr_iid`/`project_id` cannot be determined, fail fast with `GITLAB_CONTEXT_MISSING`.

### Config mapping (MVP)

`AppConfig.gitlab` requires:

- `project_id`
- `mr_iid`
- `base_url` or `api_v4_url` (derive from `CI_API_V4_URL` when present)

---

## 3) Diff retrieval strategies

### Preferred MVP: `git diff` in the runner

In CI, the runner usually has a checkout and can run `git diff`.

**Strategy**

1. Ensure target branch refs exist locally:
   - `git fetch origin <target_branch> --depth=...`
2. Compute diff:
   - `git diff origin/<target_branch>...<head_sha>`

**Pros**

- No GitLab API dependency for diff text.
- Fast and simple.

**Cons**

- Requires proper fetch depth / refs.
- For forks or unusual CI setups, refs may not exist.

### Optional fallback (future): GitLab API MR changes/diff

If `git diff` fails, optionally:

- call MR endpoints to fetch changes/diffs.

> Keep fallback as a future enhancement unless it’s necessary in your environment.

---

## 4) Skip conditions (MVP)

### Goal

`diffsan` should skip posting and only output skip reason to stdout when either:

- auto-merge is enabled (or equivalent), or
- `skip_on_same_fingerprint=true` and the latest prior diffsan summary note has the same fingerprint as the current diff.

### Detection approach

Use GitLab API to fetch MR details and read the field(s) that indicate:

- auto-merge is enabled / merge when pipeline succeeds / merge train / etc.

**Endpoint (typical)**

- `GET /api/v4/projects/:project_id/merge_requests/:mr_iid`

**Implementation notes**

- GitLab fields differ by version; implement a small compatibility layer:
  - check presence of known fields (e.g., `merge_when_pipeline_succeeds`, `auto_merge_enabled`, `merge_status`, etc.)
  - if uncertain, emit event `skip.auto_merge.unknown` and **do not skip** (fail-open for MVP).
- If `skip_on_auto_merge=true` and auto-merge detected:
  - `SkipDecision.should_skip = true`
  - do not post to MR
  - still write artifacts that were already produced (at least `events.jsonl` + `run.json`)
- If `skip_on_same_fingerprint=true` and latest prior fingerprint equals current fingerprint:
  - `SkipDecision.should_skip = true`
  - do not post to MR
  - still write artifacts that were already produced (at least `events.jsonl` + `run.json`)

---

## 5) Posting: Summary note

### Purpose

Post a single MR note containing:

- `summary_markdown` from the agent
- a collapsible `<details>` metadata section (fingerprint, agent info, timings, token usage if available, flags)
- include total findings count and MR pipeline id (when available from CI)
- human-readable timestamps and duration in metadata
  - timezone is configurable via CLI (`--note-timezone`), default `SGT`
- a collapsible truncation section describing what was omitted (only when truncation occurred)
- if secrets were detected during scan, include a warning section (never include raw secret)
- if posting errors occurred during the run (for example invalid discussion positions), include a collapsible "Run errors" section with brief, non-secret error summaries

### Endpoint (typical)

- `POST /api/v4/projects/:project_id/merge_requests/:mr_iid/notes`
  - body: `{ "body": "<markdown>" }`

### Tagging (to locate prior notes)

To find previous diffsan notes, include a small marker:

- e.g. a line near the top or bottom:
  - `<!-- diffsan:ai-reviewer -->`
- include fingerprint marker for fast re-run detection:
  - `<!-- diffsan:fingerprint:sha256:<value> -->`
- include a machine-readable digest marker for future runs:
  - `<!-- diffsan:prior_digest:<base64-json> -->`
- or a consistent heading prefix.

Config:

- `gitlab.summary_note_tag` (default `ai-reviewer`)

---

## 6) Posting: Inline discussions (findings → discussions)

### Endpoint (typical)

- `POST /api/v4/projects/:project_id/merge_requests/:mr_iid/discussions`
  - body: `{ "body": "...", "position": {...} }`

### Position computation (important)

GitLab requires a **position** object referencing:

- the diff refs (base/head)
- the file path
- a line number in the diff (usually `new_line` or `old_line`)
- sometimes `start_sha` / `base_sha` / `head_sha`

**MVP positioning strategy**

- Prefer positions on **new lines** (`new_path` + `new_line`) where possible.
- When a finding points to unchanged lines or cannot be mapped reliably:
  - do **not** post a discussion
  - include it under an “Unpositioned findings” section in the summary note
  - still keep it in `review.json` artifacts

This “degrade gracefully” approach avoids flakey 400 errors from invalid positions.

### Common failure: invalid position

If GitLab returns `400` with message like “position is invalid”:

- mark that discussion as failed in `post_results.json`
- continue posting remaining items (best-effort)
- exit non-zero at end (posting incomplete) so CI can reflect issue (allow-failure recommended)

---

## 7) Prior note parsing (for digest + fingerprint)

`diffsan` stores the fingerprint and optional compact digest inside the summary note’s metadata section.

### How to locate the prior summary note

- list MR notes and search for:
  - `summary_note_tag` marker (comment tag or heading)
  - optionally ensure author is the bot user (if accessible)

### What to parse out

- fingerprint: `sha256:<value>`
- compact digest: a short list of prior findings
  - `finding_id`, `title`, `severity`, `path`, `line range`
- preferred source is the embedded digest marker payload; if absent, fall back to
  parsing the fingerprint marker comment; if that is absent, fall back to
  parsing the metadata fingerprint line.

**Robustness**

- Parsing should be tolerant:
  - ignore malformed sections
  - if fingerprint is missing, proceed without “already reviewed” context
- Always prefer structured storage in the note content over trying to infer from discussions.

---

## 8) Retry policy & error handling

### Retryable cases

Retry (bounded) on:

- `429` (rate limited)
- `5xx` (server error)
- timeouts / transient network failures

Config:

- `gitlab.retry_max` (default 3)

### Non-retryable cases

Do not retry:

- `401/403` auth issues
- `404` MR/project not found (likely config error)
- `400` invalid request (e.g., invalid position) unless you can correct it

### Backoff strategy (MVP)

- Exponential backoff with jitter (small):
  - e.g. 1s, 2s, 4s (+ random 0–250ms)
- Log each retry attempt as a structured event.

---

## 9) Artifacts related to GitLab integration

The following artifacts are written for debuggability:

- `post_plan.json`
  - the exact payloads intended for note/discussion posting (minus secrets)
- `post_results.json`
  - per-item results including HTTP status codes and any error messages
- `events.jsonl`
  - `gitlab.post.summary` / `gitlab.post.discussion` events with success/failure

> Never store raw secrets. If GitLab returns error bodies that might echo request content, store only what’s necessary.

---

## 10) Examples (illustrative)

### Create summary note request

```json
{
  "body": "## **diffsan** Summary\n<sub><em>Automated merge request review</em></sub>\n\n### AI Review Summary\n...\n\n<!-- diffsan:ai-reviewer -->\n\n<details><summary><strong>Metadata</strong></summary>\n- **Fingerprint:** `sha256:abcd...`\n- **Agent:** `cursor`\n- **Findings:** `3`\n- **MR pipeline ID:** `123456789`\n- **Started:** `12 Feb 2026, 4:34PM SGT`\n- **Ended:** `12 Feb 2026, 4:35PM SGT`\n- **Duration:** `36.0 s`\n- **Truncated:** `true`\n- **Redaction found:** `false`\n</details>\n\n<details><summary><strong>Truncation details</strong></summary>\n- **Original files:** `48`\n- **Final files:** `30`\n</details>"
}
```

### Create discussion request (new line position)

````json
{
  "body": "**[security/high]** Avoid `eval()` on user input.\n\nSuggested fix:\n```diff\n...\n```",
  "position": {
    "position_type": "text",
    "base_sha": "aaa111",
    "start_sha": "aaa111",
    "head_sha": "bbb222",
    "new_path": "app/auth.py",
    "new_line": 95
  }
}
````

### Invalid position response handling

- HTTP `400` with “position is invalid”
  - record in `post_results.json`
  - continue posting others
  - exit non-zero at end

---

## 11) Future considerations (not MVP requirements)

- Support `CI_JOB_TOKEN` (when permitted) or OAuth flows
- True idempotency: update/replace existing summary note instead of creating new
- Rich skip rules:
  - draft/WIP, author == bot, only-docs changes, already-reviewed fingerprint, merge train, etc.

- GitHub support via separate adapter layer

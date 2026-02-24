This document defines the **canonical contracts** for `diffsan`: schemas, artifact files, events, and error codes.
Agents should treat these as authoritative. If you change these, update this doc and the corresponding code.

---

## Artifact directory and files

All runs create a workdir (default name TBD, e.g. `.diffsan/`).

Minimum artifacts (MVP v0):

- `run.json` — final status + error info (always written)
- `events.jsonl` — structured events (always written)
- `diff.raw.patch` — raw diff text (as obtained)
- `diff.prepared.patch` — ignored/prioritized/truncated/redacted diff used in prompt
- `truncation.json` — truncation report
- `redaction.json` — secret scanning/redaction report
- `prior_digest.json` — extracted digest from prior bot summary notes + inline discussions (if any)
- `prompt.txt` — prompt passed to agent
- `agent.raw.txt` — raw agent stdout (may be invalid JSON)
- `agent.raw.attemptN.txt` — per-attempt raw agent stdout for retry debugging
- `review.json` — validated `ReviewOutput` JSON
- `post_plan.json` — what we intended to post (summary + discussions)
- `post_results.json` — posting outcomes (IDs/errors)

---

## Core schemas (Pydantic)

### AppConfig (merged config)

Fields are grouped for clarity. Exact defaults are implementation-defined but should be opinionated and reasonable.

```json
{
  "workdir": ".diffsan",
  "note_timezone": "system-local",
  "mode": { "ci": false },
  "limits": {
    "max_diff_chars": 200000,
    "max_files": 60,
    "max_hunks_per_file": 40
  },
  "truncation": {
    "priority_extensions": [
      ".py",
      ".js",
      ".ts",
      ".go",
      ".java",
      ".rb",
      ".php",
      ".rs"
    ],
    "depriority_extensions": [".md", ".rst", ".txt", ".lock"],
    "include_extensions": null,
    "ignore_globs": ["docs/**", "**/*.generated.*"]
  },
  "secrets": {
    "enabled": true,
    "extra_patterns": [],
    "post_warning_to_mr": true
  },
  "skip": {
    "skip_on_auto_merge": true,
    "skip_on_same_fingerprint": true
  },
  "agent": {
    "agent": "cursor",
    "cursor_command": null,
    "max_json_retries": 3,
    "json_repair_prompt": "Return ONLY valid JSON that matches the schema.",
    "verbosity": "medium",
    "skills": [],
    "prompt_template": null
  },
  "gitlab": {
    "enabled": true,
    "base_url": "https://gitlab.com",
    "project_id": "12345",
    "mr_iid": 67,
    "token_env": "GITLAB_TOKEN",
    "idempotent_summary": false,
    "summary_note_tag": "ai-reviewer",
    "retry_max": 3
  },
  "logging": { "level": "info", "structured": true }
}
```

### DiffBundle (diff acquisition)

```json
{
  "source": {
    "kind": "git-diff",
    "ref": {
      "target_branch": "main",
      "source_branch": "feature-1",
      "base_sha": "aaa111",
      "head_sha": "bbb222"
    }
  },
  "raw_diff": "diff --git a/... b/...\n...",
  "files": [
    {
      "path": "app/auth.py",
      "additions": 10,
      "deletions": 2,
      "is_binary": false
    }
  ]
}
```

### TruncationReport

```json
{
  "truncated": true,
  "original_chars": 340000,
  "final_chars": 200000,
  "original_files": 120,
  "final_files": 60,
  "items": [
    {
      "kind": "file",
      "path": "docs/guide.md",
      "details": "Dropped (deprioritized extension)"
    },
    {
      "kind": "chars",
      "path": null,
      "details": "Stopped at max_diff_chars=200000"
    }
  ]
}
```

### RedactionReport

**Important:** never store raw secrets. Only hashes/lengths.

```json
{
  "enabled": true,
  "found": true,
  "matches": [
    {
      "pattern_name": "AWS_ACCESS_KEY_ID",
      "path": "app/config.py",
      "line_hint": 12,
      "match_sha256": "3d5e...",
      "match_length": 20
    }
  ],
  "redaction_token": "[REDACTED]"
}
```

### PreparedDiff

```json
{
  "prepared_diff": "diff --git a/... b/...\n... [REDACTED] ...",
  "truncation": { "...": "see TruncationReport" },
  "redaction": { "...": "see RedactionReport" },
  "ignored_paths": ["docs/guide.md"],
  "included_paths": ["app/auth.py", "app/config.py"]
}
```

### Fingerprint

```json
{ "algo": "sha256", "value": "b7d4..." }
```

### PriorDigest (compact memory to avoid repeats)

```json
{
  "prior_fingerprint": { "algo": "sha256", "value": "1111..." },
  "findings": [
    {
      "finding_id": "f-9c21...",
      "path": "app/auth.py",
      "line_range": "88-106",
      "title": "Avoid eval() on user input",
      "severity": "high"
    }
  ],
  "summary_hint": "Previously flagged unsafe eval and missing tests.",
  "summaries": [
    {
      "note_id": 98765,
      "text": "### AI Review Summary\n- Prior summary markdown..."
    }
  ],
  "inline_comments": [
    {
      "discussion_id": "a1b2c3",
      "note_id": 24680,
      "path": "app/auth.py",
      "line": 95,
      "resolved": false,
      "body": "Please avoid eval() here."
    }
  ]
}
```

### SkipDecision

```json
{
  "should_skip": false,
  "reasons": [],
  "fingerprint": { "algo": "sha256", "value": "b7d4..." },
  "prior_digest": { "...": "see PriorDigest" }
}
```

---

## Agent contracts

### AgentRequest (internal)

Contains the prompt plus metadata used for artifacts/logging. The prompt itself must instruct “JSON only.”

```json
{
  "prompt": "You are diffsan, an AI code reviewer...\nReturn ONLY JSON...\nSCHEMA: ...\nDIFF:\n...",
  "meta": {
    "fingerprint": { "algo": "sha256", "value": "b7d4..." },
    "truncation": { "truncated": true, "...": "..." },
    "redaction_found": false,
    "agent": "cursor",
    "verbosity": "high",
    "skills": ["security", "python"]
  }
}
```

### AgentReviewOutput (agent _must_ emit this JSON)

- Cursor is unstructured → diffsan must validate and retry/repair until this schema is satisfied.

```json
{
  "summary_markdown": "### AI Review Summary\n- ...\n\n<details><summary>Truncation</summary>\n...\n</details>",
  "findings": [
    {
      "finding_id": "optional",
      "severity": "high",
      "category": "security",
      "path": "app/auth.py",
      "line_start": 88,
      "line_end": 106,
      "body_markdown": "User-controlled input is passed to `eval()`.",
      "suggested_patch": {
        "format": "unified-diff",
        "content": "--- a/app/auth.py\n+++ b/app/auth.py\n@@\n- eval(expr)\n+ ast.literal_eval(expr)\n"
      }
    }
  ]
}
```

### ReviewOutput (final validated artifact written by diffsan)

`diffsan` composes `ReviewOutput` after parsing `AgentReviewOutput`, and populates `meta`
outside the agent using runtime context:

- `fingerprint` from `sha256(raw diff)`
- `agent` from runtime config
- `timings` from agent execution timing
- `token_usage` best-effort (empty if unavailable)
- `truncated` and `redaction_found` from preprocessor results

### Finding fields (minimum required)

Each finding must include:

- `severity`: info|low|medium|high|critical
- `category`: correctness|security|performance|maintainability|style|testing|docs|other
- `path`: file path
- `line_start`, `line_end`: integer line numbers
- `body_markdown`: text
- optional `suggested_patch`

---

## Posting contracts (internal)

### PostPlan

```json
{
  "summary_markdown": "### AI Review Summary\n...",
  "summary_meta_collapsible": "<details><summary>Metadata</summary>\n...\n</details>",
  "discussions": [
    {
      "path": "app/auth.py",
      "line_start": 88,
      "line_end": 106,
      "body_markdown": "**[security/high]** ...",
      "position": {
        "position_type": "text",
        "base_sha": "aaa111",
        "head_sha": "bbb222",
        "start_sha": "aaa111",
        "new_path": "app/auth.py",
        "new_line": 95
      },
      "severity": "high",
      "category": "security"
    }
  ],
  "idempotent_summary": false,
  "prior_summary_note_id": null
}
```

### PostResults

```json
{
  "ok": true,
  "items": [
    {
      "kind": "summary_note",
      "ok": true,
      "http_status": 201,
      "gitlab_id": 987654,
      "retry_count": 0
    },
    {
      "kind": "discussion",
      "ok": true,
      "http_status": 201,
      "gitlab_id": 1234567,
      "retry_count": 0
    }
  ]
}
```

Summary note body should include:

- tag marker: `<!-- diffsan:<summary_note_tag> -->`
- fingerprint marker: `<!-- diffsan:fingerprint:<algo>:<value> -->`
- prior digest marker (when available): `<!-- diffsan:prior_digest:<base64-json> -->`

---

## Structured events (events.jsonl)

Each line is a JSON object:

```json
{
  "ts": "2026-02-10T12:01:00Z",
  "level": "info",
  "event": "diff.fetched",
  "data": { "chars": 18342, "files": 12 }
}
```

Suggested events (MVP):

- `run.started`, `run.finished`
- `config.loaded`
- `diff.fetched`
- `diff.prepared` (includes truncated/redaction flags)
- `skip.decided` (reasons)
- `prompt.written`
- `agent.attempt`
- `review.validated`
- `post.plan_built`
- `gitlab.post.summary`
- `gitlab.post.discussion`
- `error.raised`

---

## Errors (run.json + exceptions)

### ErrorInfo (stored in run.json)

```json
{
  "error_code": "AGENT_OUTPUT_INVALID",
  "message": "Failed to obtain valid JSON output after 3 attempts",
  "retryable": false,
  "context": { "attempts": 3, "agent": "cursor" },
  "cause": "pydantic.ValidationError: ..."
}
```

### Suggested error codes

- `CONFIG_PARSE_ERROR`
- `DIFF_FETCH_FAILED`
- `DIFF_PARSE_FAILED`
- `REDACTION_ENGINE_FAILED`
- `GITLAB_FETCH_PRIOR_FAILED`
- `AGENT_EXEC_FAILED`
- `AGENT_OUTPUT_INVALID`
- `FORMAT_FAILED`
- `GITLAB_AUTH_ERROR`
- `GITLAB_POSITION_INVALID`
- `GITLAB_POST_FAILED`

---

## Contract change rules

If any schema, artifact name, event name, or error code changes:

- Update this doc (`02-contracts-and-schemas.md`)
- Update code in `src/diffsan/contracts/*`

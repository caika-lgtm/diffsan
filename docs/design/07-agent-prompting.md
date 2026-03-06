This document defines how `diffsan` builds prompts and handles agent output for both Cursor (unstructured) and Codex (structured) to reliably obtain valid review JSON.

## Goals

- The final agent payload must validate against `AgentReviewOutput`.
- Avoid spam:
  - verbosity is configurable
  - inject compact prior digest
  - instruct to avoid repeating prior findings
- Make truncation explicit:
  - if truncated, agent must clearly disclose partial review in the summary
  - include a collapsible section listing what was truncated
- Protect secrets:
  - diff must already be redacted before prompting
  - if redaction found, agent should mention that redaction occurred (without including any secret)

---

## Prompt composition

### Inputs to prompt builder

- Prepared diff: `diff.prepared.patch` contents (ignored/prioritized/truncated/redacted)
- Truncation report: `TruncationReport`
- Redaction flag: `redaction.found`
- Prior digest: `PriorDigest` (prior findings + all previous summaries + all prior inline comments)
- Config: verbosity + skills

### Prompt sections (recommended order)

1. **Role and task**
   - “You are diffsan, an AI code reviewer…”
2. **Output rules** (Cursor only)
   - “Return ONLY valid JSON. No markdown, no code fences, no commentary.”
   - “Must match the schema exactly.”
3. **Schema** (Cursor only)
   - Embed the `AgentReviewOutput` schema description (field names/types and allowed enums)
4. **Review instructions**
   - Prioritize correctness/security first
   - Keep comments concise and actionable
   - Avoid repeating prior findings
   - Use line ranges; reference file paths exactly
5. **Context flags**
   - Truncation: mention and require disclosure in summary
   - Redaction: mention redaction occurred if found
6. **Prior digest**
   - Provide minimal digest and explicit instruction:
     - “Do NOT repeat these unless the code changed substantially.”
     - “Do NOT re-assert unresolved issues.”
7. **Prepared diff**
   - Include diff text

---

## Cursor JSON-only requirement

### Hard rules to include in the prompt

- “Return **ONLY** a JSON object.”
- “Do not wrap in markdown or triple backticks.”
- “Do not include any text before or after the JSON.”
- “Do not include planning/process text or explanations.”
- “The first character must be `{` and the last character must be `}`.”
- “If you are unsure, still output valid JSON with best-effort findings.”

### Recommended guardrails

- Provide an explicit “example structure” (not too large), e.g.:
  - top-level fields: `summary_markdown`, `findings`
- Enumerate allowed `severity` and `category` values.
- Require numeric `line_start`/`line_end` (integers).

---

## Repair / retry strategy (Cursor)

Cursor CLI does not guarantee structured output. `diffsan` must:

1. Capture raw stdout/stderr.
2. Attempt to parse JSON strictly.
   - If using `cursor-agent --output-format json`, unwrap the outer envelope and
     parse the nested `result` JSON string before validating against
     `AgentReviewOutput`.
   - If output has leading non-JSON preamble text, recover by parsing from the
     first valid top-level JSON object start.
   - Tolerate non-JSON trailing text after that recovered object.
3. Validate with Pydantic.
4. If parsing/validation fails, retry with a repair prompt.

Execution defaults for Cursor CLI in diffsan:

- Default command: `cursor-agent --print --output-format json --trust`
- If `CURSOR_API_KEY` is set, diffsan passes it via `--api-key`.
- If a custom `agent.cursor_command` is configured without a trust flag (`--trust`, `--yolo`, `-f`), diffsan appends `--trust`.
- Any sensitive command argument values are redacted in persisted error context.

---

## Codex structured-output strategy

Codex CLI supports structured output directly through schema/output-file flags.

Execution defaults for Codex CLI in diffsan:

- Default command: `codex exec --output-schema <workdir>/codex-output-schema.json --output-last-message <workdir>/codex-output.json --sandbox read-only`
- Prompt is passed through stdin.
- diffsan reads JSON from `codex-output.json` and validates against `AgentReviewOutput`.
- No JSON repair retry loop is used for codex runs.
- `max_json_retries` and `json_repair_prompt` are cursor-only controls.

### Retry loop rules

- Maximum attempts: `max_json_retries` (default 3)
- Each attempt writes its output artifact:
  - `agent.raw.attempt1.txt`, `agent.raw.attempt2.txt`, etc.
- If all attempts fail:
  - exit non-zero with `AGENT_OUTPUT_INVALID`
  - do not post invalid output to GitLab
  - keep artifacts for debugging

### Repair prompt template (recommended)

The repair prompt should:

- Be short and strict
- Include a concise error summary (parse error or validation errors)
- Include the invalid output (bounded length) for correction
- Repeat: “Return ONLY corrected JSON”

Example repair prompt:

```

You produced invalid output.

Return ONLY a corrected JSON object that matches this schema exactly: <SCHEMA SUMMARY HERE>

Constraints:

* Output must be valid JSON.
* No markdown, no backticks, no extra text.

Validation errors:

* findings[0].line_start: field required
* findings[0].line_end: field required

Here is your previous output:
<<<
... (previous output, truncated) ...

> > >

```

### How to generate a concise validation error summary

- For Pydantic errors, include:
  - JSON path (e.g., `findings.0.line_start`)
  - message (e.g., `field required`)
- Limit to the first N errors (e.g., 10) to keep prompt short.

---

## Handling truncation in the prompt

When truncation occurred:

- Include a mandatory instruction:
  - “In `summary_markdown`, clearly state this is a **partial review** due to truncation.”
- Provide agent the truncation stats:
  - original vs final chars/files, and a short list of dropped items
- Require a collapsible section in summary, e.g.:
  - `<details><summary>Truncation</summary> ... </details>`

---

## Handling redaction in the prompt

When redaction found:

- The prompt should say:
  - “Some secrets-like strings were redacted as `[REDACTED]`.”
  - “Do not attempt to guess the secret.”
- The summary should contain a brief note:
  - “Redaction occurred; review includes redacted content.”

Additionally, diffsan itself may post a separate warning note to GitLab (without secret details).

---

## Avoiding spam + repeats

Prompt must instruct:

- Focus on high-impact findings (correctness/security first).
- Prefer fewer, higher-quality findings over many minor nits.
- Avoid repeating anything present in the prior digest.
- Do not re-assert unresolved prior issues (MVP requirement).

Suggested text:

- “If an issue is already listed in the prior digest, do NOT repeat it.”
- “Only add new findings that are materially different or newly introduced.”

---

## Suggested “skills” mechanism (lightweight)

Skills are optional prompt additions. In MVP:

- `skills` is a list of short identifiers.
- diffsan maps skills to small prompt snippets (stored under `resources/prompts/skills/` later).
- Example skills:
  - `security`: focus on injection, auth, secrets, SSRF, etc.
  - `python`: focus on typing, exceptions, idioms
  - `testing`: focus on test coverage and cases

Skill text must be short to avoid prompt bloat.

---

## Output quality notes (agent guidance)

- Each finding must be actionable and point to a specific file + line range.
- Suggested patch is optional; include only when confident.
- Use `severity` consistently:
  - `critical/high`: security vulnerabilities, data loss, auth bypass, crashes
  - `medium`: likely bugs, race conditions, incorrect edge cases
  - `low/info`: minor improvements, style, cleanup

---

## Example (very short) base instruction snippet (Cursor)

```

Return ONLY valid JSON for the schema AgentReviewOutput.
No markdown, no backticks, no extra text.

Prioritize correctness and security issues.
Avoid repeating any item from the prior digest.
If truncation occurred, clearly disclose partial review in summary_markdown and include a <details> section describing what was truncated.

```

This document defines how `diffsan` builds prompts and handles Cursor’s unstructured output to reliably obtain valid JSON.

## Goals

- The agent must output **ONLY valid JSON** matching `ReviewOutput`.
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
- Prior digest: `PriorDigest` (compact list of previously raised findings)
- Config: verbosity + skills

### Prompt sections (recommended order)

1. **Role and task**
   - “You are diffsan, an AI code reviewer…”
2. **Output rules**
   - “Return ONLY valid JSON. No markdown, no code fences, no commentary.”
   - “Must match the schema exactly.”
3. **Schema**
   - Embed the `ReviewOutput` schema description (field names/types and allowed enums)
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

## JSON-only requirement

### Hard rules to include in the prompt

- “Return **ONLY** a JSON object.”
- “Do not wrap in markdown or triple backticks.”
- “Do not include any text before or after the JSON.”
- “If you are unsure, still output valid JSON with best-effort findings.”

### Recommended guardrails

- Provide an explicit “example structure” (not too large), e.g.:
  - top-level fields: `summary_markdown`, `findings`, `meta`
- Enumerate allowed `severity` and `category` values.
- Require numeric `line_start`/`line_end` (integers).

---

## Repair / retry strategy (Cursor)

Cursor CLI does not guarantee structured output. `diffsan` must:

1. Capture raw stdout/stderr.
2. Attempt to parse JSON strictly.
   - If using `cursor-agent --output-format json`, unwrap the outer envelope and
     parse the nested `result` JSON string before validating against
     `ReviewOutput`.
3. Validate with Pydantic.
4. If parsing/validation fails, retry with a repair prompt.

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
* meta.fingerprint.value: field required

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

## Example (very short) base instruction snippet

```

Return ONLY valid JSON for the schema ReviewOutput.
No markdown, no backticks, no extra text.

Prioritize correctness and security issues.
Avoid repeating any item from the prior digest.
If truncation occurred, clearly disclose partial review in summary_markdown and include a <details> section describing what was truncated.

```

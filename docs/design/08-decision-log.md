This file records key decisions for `diffsan`. Keep entries short and factual.
When changing a decision, add a new entry (do not rewrite history).

---

## D001 — Tool scope and primary goal

**Decision:** `diffsan` focuses on AI review of MR diffs in GitLab CI, prioritizing **correctness/security** findings first.
**Why:** Highest value and aligns with “do not block merges” human-review workflow.
**Implications:** Output schema and prompting emphasize correctness/security; other categories exist but are secondary.

---

## D002 — Monolithic CLI architecture

**Decision:** Build as a single Python CLI (monolith) with internal module boundaries and contracts.
**Why:** Small project, fastest to ship/debug, simple pipx distribution, minimal ops overhead.
**Implications:** Clear internal contracts (Pydantic models + error codes + events) to prevent a “ball of mud.”

---

## D003 — Distribution via pipx

**Decision:** Users install/run `diffsan` primarily via `pipx`.
**Why:** Simple, isolated installs; good for CI usage.
**Implications:** Keep dependencies reasonable; avoid heavy system requirements; ensure CLI entrypoint is stable.

---

## D004 — Primary execution mode is GitLab CI

**Decision:** CI mode is the primary path; standalone mode is minimal and not a priority.
**Why:** Main use case is MR pipelines.
**Implications:** Standalone prints to stdout only; CI mode handles GitLab context, posting, skip logic, artifacts.

---

## D005 — Agent support MVP: Cursor CLI only

**Decision:** MVP supports Cursor CLI headless agent only; Codex CLI is future work.
**Why:** Reduces scope and accelerates MVP delivery.
**Implications:** Design agent runner with an adapter seam to add Codex later.

---

## D006 — Cursor output handling: strict JSON + repair retries

**Decision:** Require the agent to output **only JSON** matching schema; implement repair retries because Cursor is unstructured.
**Why:** Posting requires structured data; Cursor may emit extra text.
**Implications:** Pydantic validation drives retry loop; raw outputs are stored as artifacts; invalid outputs never posted to MR.

---

## D007 — Review output schema: Pydantic as source of truth

**Decision:** Define review output and internal contracts with Pydantic models.
**Why:** Strong typing and validation; easy to serialize artifacts; clearer contracts for agents.
**Implications:** Any contract change must update both docs and Pydantic models and example JSON fixtures.

---

## D008 — Findings minimum fields

**Decision:** Each finding includes: `severity`, `category`, `path`, `line_start`, `line_end`, `body_markdown`, optional `suggested_patch`.
**Why:** Minimum needed to create discussions and be useful.
**Implications:** Agents must supply line ranges; if positions cannot be computed, findings still appear in summary and artifacts.

---

## D009 — Fingerprinting: sha256(raw diff text)

**Decision:** Fingerprint is `sha256` of the **raw diff text**.
**Why:** Simple and deterministic for MVP.
**Implications:** Whitespace-only changes or ordering changes alter fingerprint; normalization may be added later.

---

## D010 — Prior context: compact digest, avoid repeats

**Decision:** Store prior fingerprint in the summary note; feed agent a **compact digest** of prior findings and instruct it to **avoid repeating** and not re-assert unresolved issues.
**Why:** Prevent spam and improve signal-to-noise.
**Implications:** Digest parsing must be tolerant; agent prompting must explicitly discourage repetition.

---

## D011 — Secret handling: best-effort redaction + MR warning

**Decision:** Perform best-effort regex-based secret detection and redaction before prompting; if secrets found, log high severity and include a warning in MR summary.
**Why:** Prevent sensitive data leakage; raise awareness when secrets are in diffs.
**Implications:** Never store raw secrets; store only hashes/lengths. MR warning must not reveal secret content.

---

## D012 — Truncation: configurable hard limits, disclose in summary

**Decision:** Apply configurable hard limits (`max_diff_chars`, `max_files`, `max_hunks_per_file`). If truncation occurs, proceed with review but clearly disclose truncation in summary, including collapsible details of what was omitted.
**Why:** Context limits and cost control; transparency to reviewers.
**Implications:** Preprocessor must emit truncation report; formatter must include a truncation `<details>` section.

---

## D013 — Skip rules MVP: auto-merge only, silent skip

**Decision:** MVP skip condition is **auto-merge enabled**. When skipping, do not post to MR; only print to stdout.
**Why:** Start simple; avoid noise in auto-merge flows.
**Implications:** GitLab integration must reliably detect auto-merge; if uncertain, fail open (do not skip).

---

## D014 — Posting target: GitLab only (MVP)

**Decision:** Post to GitLab MR as:

- summary as a **note**
- findings as **discussions** when position is computable
  **Why:** Primary environment is GitLab; keep scope tight.
  **Implications:** GitLab API client is required; positioning errors must degrade gracefully.

---

## D015 — Posting identity: dedicated bot user + project access token

**Decision:** Use a dedicated bot user via project access token.
**Why:** Clear attribution and permissions management.
**Implications:** Token must be provided via env var; auth failures are non-retryable.

---

## D016 — Posting behavior: default new summary note; idempotent optional

**Decision:** Default is posting a new summary note each time; allow idempotent mode via config to update/replace.
**Why:** Default is simple; idempotency helps reduce clutter for some teams.
**Implications:** Idempotent mode requires locating prior note via tag/marker.

---

## D017 — Failure behavior: non-zero exit, artifacts always

**Decision:** Return non-zero on errors; CI job can be configured allow-failure. Always write artifacts (prompt, raw output, review where possible) even on failure.
**Why:** Don’t block merges, but do surface failures; preserve debuggability.
**Implications:** Orchestrator must be careful to persist artifacts early and often.

---

## D018 — Standalone mode: stdout only

**Decision:** Standalone mode prints to stdout and writes artifacts, but does not post to GitLab.
**Why:** Keep MVP small; CI is the priority.
**Implications:** CLI flags should make CI mode explicit; standalone accepts simplest diff source.

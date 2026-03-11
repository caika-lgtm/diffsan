# Configuration

This page documents the runtime inputs that affect `diffsan` today:

- TOML config file values
- `DIFFSAN_*` environment overrides
- CLI flags that override part of the config
- required CI and auth environment variables that are not part of `AppConfig`

The canonical config schema lives in `src/diffsan/contracts/models.py`. This page reflects the current implementation in `src/diffsan/core/config.py`, `src/diffsan/run.py`, and related runtime modules.

## Precedence

`diffsan` resolves configuration in this order:

1. CLI overrides
2. `DIFFSAN_*` environment variables
3. Config file
4. Built-in defaults

Current CLI overrides:

- `--ci/--no-ci` overrides `mode.ci`
- `--agent <cursor|codex>` overrides `agent.agent`
- `--proxy-url <url>` overrides `agent.proxy_url` (Codex only)
- `--config <path>` selects the TOML config file to load

`workdir` and `note_timezone` are config values, but the current public CLI does not expose dedicated flags for them.

## Config File Discovery

`diffsan` looks for a TOML config file in this order:

1. `--config <path>`
2. `DIFFSAN_CONFIG_FILE`
3. `.diffsan.toml` in the current working directory
4. no config file

Rules:

- The selected path must exist.
- The selected path must be a file, not a directory.
- The file must contain a top-level TOML table/object.
- Unknown config keys are rejected during validation.

If config parsing or validation fails, `diffsan` exits with `CONFIG_PARSE_ERROR`.

## Environment Variable Mapping

`diffsan` uses the `DIFFSAN_` prefix for config overrides.

- Top-level keys map directly:
  - `DIFFSAN_WORKDIR=.ai-review`
  - `DIFFSAN_NOTE_TIMEZONE=Asia/Singapore`
- Nested keys use `__`:
  - `DIFFSAN_MODE__CI=true`
  - `DIFFSAN_LIMITS__MAX_FILES=80`
  - `DIFFSAN_GITLAB__SUMMARY_NOTE_TAG=security-bot`

Notes:

- Booleans should be passed as `true` / `false`.
- Integers should be passed as numeric strings.
- Lists and other structured values should be passed as JSON strings.
- `DIFFSAN_CONFIG_FILE` is special: it selects the config file path and is not part of `AppConfig`.

Examples:

```bash
export DIFFSAN_WORKDIR=".ai-review"
export DIFFSAN_MODE__CI="true"
export DIFFSAN_AGENT__AGENT="codex"
export DIFFSAN_AGENT__PROXY_URL="https://proxy.example.com/v1"
export DIFFSAN_TRUNCATION__INCLUDE_EXTENSIONS='[".py",".ts"]'
export DIFFSAN_SECRETS__EXTRA_PATTERNS='["ghp_[A-Za-z0-9]{36}"]'
```

## CLI Flags

Current `diffsan` CLI flags:

| Flag | Effect |
| --- | --- |
| `--ci/--no-ci` | Overrides `mode.ci` |
| `--agent <cursor|codex>` | Overrides `agent.agent` |
| `--proxy-url <url>` | Overrides `agent.proxy_url` for Codex runs |
| `--config <path>` | Selects the TOML config file |
| `--dry-run` | Runs the no-op harness and writes run artifacts without executing the review pipeline |
| `--version` | Prints the CLI version and exits |

`--dry-run` is runtime behavior, not part of the persisted config schema.

## Full Config Reference

### Top-Level Keys

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `workdir` | `str` | `.diffsan` | Artifact directory. Created early in the run. |
| `note_timezone` | `str` | system local timezone | Used when rendering timestamps in MR summary metadata. See timezone notes below. |

### `mode`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `mode.ci` | `bool` | `false` | Enables CI mode. Real diff acquisition currently only works in CI mode; `mode.ci = false` is not yet a full standalone review path. |

### `limits`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `limits.max_diff_chars` | `int` | `200000` | Hard cap on prepared diff length sent to the agent. |
| `limits.max_files` | `int` | `60` | Maximum number of diff files kept after ranking/filtering. |
| `limits.max_hunks_per_file` | `int` | `40` | Maximum hunks retained per file before truncation. |

### `truncation`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `truncation.priority_extensions` | `list[str]` | `[".py", ".js", ".ts", ".go", ".java", ".rb", ".php", ".rs"]` | Extensions ranked earlier when truncation is needed. |
| `truncation.depriority_extensions` | `list[str]` | `[".md", ".rst", ".txt", ".lock"]` | Extensions ranked later when truncation is needed. |
| `truncation.include_extensions` | `list[str] \| null` | `null` | If set, only files with these extensions are kept. |
| `truncation.ignore_globs` | `list[str]` | `["docs/**", "**/*.generated.*"]` | Paths dropped before prompt construction. |

### `secrets`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `secrets.enabled` | `bool` | `true` | Enables secret scanning and redaction before prompting. |
| `secrets.extra_patterns` | `list[str]` | `[]` | Extra regex patterns to redact in addition to built-in detectors. |
| `secrets.post_warning_to_mr` | `bool` | `true` | When redaction occurs, include a warning section in the summary note. Despite the name, the current implementation does not post a separate warning note. |

### `skip`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `skip.skip_on_auto_merge` | `bool` | `true` | Skip posting when MR auto-merge is detected. |
| `skip.skip_on_same_fingerprint` | `bool` | `true` | Skip posting when the current diff fingerprint matches the latest prior diffsan fingerprint. |

### `agent`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `agent.agent` | `"cursor" \| "codex"` | `cursor` | Selects the agent backend. |
| `agent.cursor_command` | `str \| null` | `null` | Custom Cursor command. If omitted, diffsan uses the built-in default. |
| `agent.codex_command` | `str \| null` | `null` | Custom Codex command. If omitted, diffsan uses the built-in default. |
| `agent.proxy_url` | `str \| null` | `null` | Codex-only proxy URL. When set, diffsan updates `~/.codex/config.toml` before invoking Codex. |
| `agent.max_json_retries` | `int` | `3` | Maximum Cursor parse/repair attempts. Ignored for Codex runs. |
| `agent.json_repair_prompt` | `str` | `Return ONLY valid JSON that matches the schema.` | Prefix text used when building Cursor repair prompts. Ignored for Codex runs. |
| `agent.verbosity` | `"low" \| "medium" \| "high"` | `medium` | Passed into prompt guidance. |
| `agent.skills` | `list[str]` | `[]` | Passed into prompt guidance as lightweight review hints. |
| `agent.prompt_template` | `str \| null` | `null` | Reserved in the schema, but not currently used by the prompt builder. |

Validation rule:

- `agent.proxy_url` is only valid when `agent.agent = "codex"`.

### `gitlab`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `gitlab.enabled` | `bool` | `true` | Controls GitLab prior-context fetches and posting. When `false`, diffsan still prints the summary to stdout. |
| `gitlab.base_url` | `str` | `https://gitlab.com` | Base GitLab URL. Can be a site root or an `/api/v4` URL. In CI, `CI_API_V4_URL` takes precedence when present. |
| `gitlab.project_id` | `str \| null` | `null` | GitLab project identifier. If unset, diffsan falls back to `CI_PROJECT_ID`. |
| `gitlab.mr_iid` | `int \| null` | `null` | Merge request IID. If unset, diffsan falls back to `CI_MERGE_REQUEST_IID`. |
| `gitlab.token_env` | `str` | `GITLAB_TOKEN` | Name of the environment variable that contains the GitLab token. |
| `gitlab.idempotent_summary` | `bool` | `false` | Included in post planning metadata, but current posting still creates a new summary note each run. |
| `gitlab.summary_note_tag` | `str` | `ai-reviewer` | Marker used to locate prior diffsan summary notes. |
| `gitlab.retry_max` | `int` | `3` | Maximum GitLab API attempts for retryable failures such as `429`, `5xx`, and transient network errors. |

### `logging`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `logging.level` | `"error" \| "warn" \| "info" \| "debug"` | `info` | Present in the schema, but not currently wired into runtime logging behavior. |
| `logging.structured` | `bool` | `true` | Present in the schema, but current runs always emit structured `events.jsonl`. |

## Timezone Values

`note_timezone` controls how MR summary timestamps are rendered.

Supported values in the current formatter:

- IANA timezone names such as `UTC` or `Asia/Singapore`
- `LOCAL` to use the runner's local timezone at render time
- `SGT` as an alias for `Asia/Singapore`
- UTC offsets such as `+08:00` or `-05:30`

If the configured value is invalid, summary-note rendering falls back to `Asia/Singapore` (`SGT`).

## Agent Command Behavior

### Cursor

If `agent.cursor_command` is unset, diffsan runs:

```bash
cursor-agent --print --output-format json --trust
```

If `CURSOR_API_KEY` is set, diffsan inserts:

```bash
--api-key <value>
```

If you provide a custom `agent.cursor_command` and it does not already include one of these trust flags, diffsan appends `--trust`:

- `--trust`
- `--yolo`
- `-f`

Sensitive argument values such as API keys are redacted from persisted error context.

### Codex

If `agent.codex_command` is unset, diffsan runs:

```bash
codex exec --output-schema <workdir>/codex-output-schema.json --output-last-message <workdir>/codex-output.json --sandbox read-only
```

Current Codex behavior:

- The prompt is passed on stdin.
- diffsan always writes the output schema to `<workdir>/codex-output-schema.json`.
- diffsan always reads structured JSON from `<workdir>/codex-output.json`.
- If a custom command already includes `--output-schema` or `--output-last-message`, diffsan rewrites those flags to point at the workdir artifacts.
- If a custom command does not include a sandbox value, diffsan inserts `--sandbox read-only`.
- If a custom command already provides a sandbox value, diffsan preserves it.
- If `agent.proxy_url` is set, diffsan rewrites `~/.codex/config.toml` before invoking Codex:
  - sets top-level `model_provider = "proxy"`
  - writes a single `[model_providers.proxy]` block with the supplied `base_url`
  - sets `env_key = "DIFFSAN_OPENAI_API_KEY"`
- When proxy mode is used, diffsan prints a reminder to set `DIFFSAN_OPENAI_API_KEY`.

## Runtime Environment Outside `DIFFSAN_*`

Some runtime inputs are not part of the config schema but are still required for a working CI run.

### GitLab token

`diffsan` reads the GitLab token from the environment variable named by `gitlab.token_env`.

By default:

```bash
export GITLAB_TOKEN="..."
```

### GitLab CI variables

Current diff fetching requires these CI variables:

- `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`
- `CI_COMMIT_SHA`

These are used when available and are required unless you override with config where noted:

- `CI_PROJECT_ID`
  - required for GitLab API calls unless `gitlab.project_id` is configured
- `CI_MERGE_REQUEST_IID`
  - required for GitLab API calls unless `gitlab.mr_iid` is configured
- `CI_API_V4_URL`
  - optional; overrides `gitlab.base_url` resolution when present
- `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`
  - optional; stored in diff metadata
- `CI_MERGE_REQUEST_DIFF_BASE_SHA`
  - optional; used as part of diff metadata and positioning
- `CI_PIPELINE_ID`
  - optional; shown in summary-note metadata

### Agent authentication

- Cursor default command optionally reads `CURSOR_API_KEY`
- Codex authentication is handled by the `codex` CLI itself unless `agent.proxy_url` is set

If `agent.proxy_url` is set, diffsan configures Codex with:

```toml
[model_providers.proxy]
name = "proxy"
base_url = "<your proxy url>"
env_key = "DIFFSAN_OPENAI_API_KEY"
```

For proxy-backed Codex runs, you must provide:

```bash
export DIFFSAN_OPENAI_API_KEY="..."
```

If `agent.proxy_url` is not set, any non-proxy Codex authentication still depends on your existing Codex CLI setup.

## Example `.diffsan.toml`

### Minimal GitLab CI config using Codex

```toml
workdir = ".diffsan"
note_timezone = "UTC"

[mode]
ci = true

[agent]
agent = "codex"
verbosity = "medium"

[gitlab]
enabled = true
summary_note_tag = "ai-reviewer"
```

### More opinionated config with filtering and secret rules

```toml
workdir = ".ai-review"
note_timezone = "Asia/Singapore"

[mode]
ci = true

[limits]
max_diff_chars = 250000
max_files = 80
max_hunks_per_file = 60

[truncation]
include_extensions = [".py", ".ts", ".tsx"]
ignore_globs = ["docs/**", "vendor/**", "**/*.generated.*"]

[secrets]
enabled = true
extra_patterns = [
  "ghp_[A-Za-z0-9]{36}",
  "glpat-[A-Za-z0-9_-]{20,}",
]
post_warning_to_mr = true

[skip]
skip_on_auto_merge = true
skip_on_same_fingerprint = true

[agent]
agent = "cursor"
verbosity = "high"
skills = ["security", "testing"]
max_json_retries = 3

[gitlab]
enabled = true
base_url = "https://gitlab.example.com"
token_env = "GITLAB_TOKEN"
summary_note_tag = "team-diffsan"
retry_max = 5
```

## Practical Recommendations

- Set `mode.ci = true` for real MR reviews.
- Keep `workdir` inside the repository workspace so CI artifacts are easy to collect.
- Prefer TOML for stable repo defaults, then use `DIFFSAN_*` env vars for CI-specific overrides.
- Use `gitlab.project_id` and `gitlab.mr_iid` only when you cannot rely on GitLab CI variables.
- Keep `gitlab.summary_note_tag` stable once you start using diffsan on a project, or prior-review detection will fragment.
- Treat `agent.prompt_template`, `logging.level`, `logging.structured`, and `gitlab.idempotent_summary` as forward-looking knobs until their runtime behavior is implemented.

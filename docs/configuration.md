# Configuration

`diffsan` derives runtime config from four sources, in this precedence order:

1. CLI overrides
2. Environment variables
3. Config file
4. Built-in defaults

## Source Details

- CLI overrides
  - `--ci/--no-ci` overrides `mode.ci`
  - `--agent <cursor|codex>` overrides `agent.agent`
  - `--config <path>` selects a specific TOML config file
- Environment variables
  - All config env vars use `DIFFSAN_` prefix
  - Nested keys use `__` as delimiter (for example: `DIFFSAN_LIMITS__MAX_FILES=80`)
  - Config-file selector env var: `DIFFSAN_CONFIG_FILE`
- Config file
  - Default file name: `.diffsan.toml` in current working directory
  - If `--config` is passed, that file is used
  - If `DIFFSAN_CONFIG_FILE` is set (and `--config` is not), that file is used
  - File format: TOML

`workdir` and `note_timezone` are config values, not dedicated CLI flags.

## Example `.diffsan.toml`

```toml
workdir = ".diffsan"
note_timezone = "UTC"

[mode]
ci = true

[limits]
max_diff_chars = 250000
max_files = 80

[agent]
verbosity = "high"
skills = ["security", "testing"]
```

## Defaults

| Key | Default |
| --- | --- |
| `workdir` | `.diffsan` |
| `note_timezone` | system local timezone |
| `mode.ci` | `false` |
| `limits.max_diff_chars` | `200000` |
| `limits.max_files` | `60` |
| `limits.max_hunks_per_file` | `40` |
| `truncation.priority_extensions` | `[".py",".js",".ts",".go",".java",".rb",".php",".rs"]` |
| `truncation.depriority_extensions` | `[".md",".rst",".txt",".lock"]` |
| `truncation.include_extensions` | `null` |
| `truncation.ignore_globs` | `["docs/**","**/*.generated.*"]` |
| `secrets.enabled` | `true` |
| `secrets.extra_patterns` | `[]` |
| `secrets.post_warning_to_mr` | `true` |
| `skip.skip_on_auto_merge` | `true` |
| `skip.skip_on_same_fingerprint` | `true` |
| `agent.agent` | `cursor` |
| `agent.cursor_command` | `null` |
| `agent.codex_command` | `null` |
| `agent.max_json_retries` | `3` |
| `agent.json_repair_prompt` | `Return ONLY valid JSON that matches the schema.` |
| `agent.verbosity` | `medium` |
| `agent.skills` | `[]` |
| `agent.prompt_template` | `null` |
| `gitlab.enabled` | `true` |
| `gitlab.base_url` | `https://gitlab.com` |
| `gitlab.project_id` | `null` |
| `gitlab.mr_iid` | `null` |
| `gitlab.token_env` | `GITLAB_TOKEN` |
| `gitlab.idempotent_summary` | `false` |
| `gitlab.summary_note_tag` | `ai-reviewer` |
| `gitlab.retry_max` | `3` |
| `logging.level` | `info` |
| `logging.structured` | `true` |

## Environment Examples

```bash
export DIFFSAN_WORKDIR=".ai-review"
export DIFFSAN_NOTE_TIMEZONE="Asia/Singapore"
export DIFFSAN_MODE__CI="true"
export DIFFSAN_LIMITS__MAX_FILES="80"
export DIFFSAN_AGENT__SKILLS='["security","testing"]'
```

## Agent Selection

- `agent.agent` controls which CLI backend diffsan uses.
- Allowed values:
  - `cursor` (default): unstructured output path with schema-in-prompt and JSON repair retries.
  - `codex`: structured output path using Codex output schema/output files and single-attempt validation.
- CLI shortcut:
  - `diffsan --ci --agent codex`

## Cursor Command Behavior

- If `agent.cursor_command` is not set, diffsan runs:
  - `cursor-agent --print --output-format json --trust`
- If `CURSOR_API_KEY` is present, diffsan adds:
  - `--api-key <value>`
- If `agent.cursor_command` is set and does not include any trust flag (`--trust`, `--yolo`, `-f`), diffsan appends `--trust`.
- Error artifacts/events redact sensitive command argument values (for example, `--api-key`) as `[REDACTED]`.

## Codex Command Behavior

- If `agent.codex_command` is not set, diffsan runs:
  - `codex exec --output-schema <workdir>/codex-output-schema.json --output-last-message <workdir>/codex-output.json --sandbox read-only`
- The prompt is provided via stdin.
- diffsan writes the Codex schema/output files under the run workdir and reads JSON from `codex-output.json`.
- `agent.max_json_retries` and `agent.json_repair_prompt` are cursor-only settings and are ignored when `agent.agent = "codex"`.

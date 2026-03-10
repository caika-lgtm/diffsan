---
name: Bug report
about: Report a diffsan failure or unexpected behavior
title: "[Bug]: "
labels: ["bug"]
---

## Summary

Describe the bug clearly and concisely.

## Reproduction

Steps to reproduce the behavior:

1. Run `...`
2. Use config `...`
3. Inspect the result in `...`
4. Observe the problem

## Expected behavior

Describe what you expected `diffsan` to do.

## Actual behavior

Describe what happened instead. Include exact error messages, stack traces, or incorrect MR note/discussion output when possible.

## Environment

- `diffsan` version (`diffsan --version`):
- Install method (`pip`, `uv`, source checkout, etc.):
- Python version:
- OS:
- Run mode (`CI` or `local`):
- Agent backend (`cursor` or `codex`):
- GitLab context, if applicable (GitLab.com or self-managed, MR link, CI job link):

## Command and config

Paste the command you ran and any relevant config. Redact secrets and tokens before posting.

```bash
# command
```

```toml
# relevant .diffsan.toml settings
```

```bash
# relevant DIFFSAN_* environment variables
```

## Helpful artifacts

Drag and drop files into the issue, or paste short excerpts inline. `events.jsonl` is especially useful for debugging.

Recommended attachments:

- `run.json`
- `events.jsonl`
- `truncation.json`
- `redaction.json`
- `review.json` (if generated)

Only attach these after reviewing them for sensitive content:

- `diff.prepared.patch`
- `prompt.txt`
- `agent.raw.txt`

Do not attach `diff.raw.patch` unless you have sanitized it first. It may contain unredacted secrets.

- [ ] I reviewed any attached files for secrets, tokens, and private code/content that should not be shared.

## Additional context

Add anything else that would help debug the issue:

- Does this reproduce consistently?
- Did it work in an earlier version?
- Is the failure specific to one repository, MR, or diff shape?

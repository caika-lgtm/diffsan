"""Helpers for updating Codex CLI home-directory configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

from diffsan.contracts.errors import ErrorCode, ReviewerError

_CODEX_CONFIG_DIRNAME = ".codex"
_CODEX_CONFIG_FILENAME = "config.toml"
_MODEL_PROVIDER_LINE = 'model_provider = "proxy"\n'
_PROXY_TABLE_NAME = "model_providers.proxy"
_HEADER_RE = re.compile(r"^\s*\[\[?([^\]]+)\]\]?\s*(?:#.*)?$")
_MODEL_PROVIDER_RE = re.compile(r"^model_provider\s*=")


def configure_codex_proxy_model_provider(
    proxy_url: str,
    *,
    config_path: Path | None = None,
) -> Path:
    """Write the proxy model provider into the user's Codex config."""
    path = config_path or (Path.home() / _CODEX_CONFIG_DIRNAME / _CODEX_CONFIG_FILENAME)
    if path.exists() and path.is_dir():
        raise ReviewerError(
            "Codex config path points to a directory",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            context={"config_path": str(path)},
        )

    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        raise ReviewerError(
            "Failed to read Codex config file",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            context={"config_path": str(path)},
            cause=exc,
        ) from exc

    updated = _rewrite_codex_config(existing, proxy_url)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise ReviewerError(
            "Failed to write Codex config file",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            context={"config_path": str(path)},
            cause=exc,
        ) from exc

    return path


def _rewrite_codex_config(existing: str, proxy_url: str) -> str:
    body_lines = _remove_existing_proxy_config(existing.splitlines(keepends=True))
    body = "".join(body_lines).lstrip("\n")
    sections: list[str] = [_MODEL_PROVIDER_LINE]
    if body:
        sections.append(f"\n{body.rstrip()}\n")
    sections.append(_render_proxy_provider_block(proxy_url))
    return "".join(sections)


def _remove_existing_proxy_config(lines: list[str]) -> list[str]:
    rewritten: list[str] = []
    current_table: str | None = None
    skip_proxy_table = False

    for line in lines:
        header_name = _parse_table_name(line)
        if skip_proxy_table:
            if header_name is None:
                continue
            if _is_proxy_table(header_name):
                current_table = header_name
                continue
            skip_proxy_table = False

        if header_name is not None:
            current_table = header_name
            if _is_proxy_table(header_name):
                skip_proxy_table = True
                continue

        if current_table is None and _is_top_level_model_provider(line):
            continue

        rewritten.append(line)

    return rewritten


def _parse_table_name(line: str) -> str | None:
    match = _HEADER_RE.match(line)
    if match is None:
        return None
    return match.group(1).strip()


def _is_proxy_table(table_name: str) -> bool:
    return table_name == _PROXY_TABLE_NAME or table_name.startswith(
        f"{_PROXY_TABLE_NAME}."
    )


def _is_top_level_model_provider(line: str) -> bool:
    stripped = line.strip()
    return bool(_MODEL_PROVIDER_RE.match(stripped))


def _render_proxy_provider_block(proxy_url: str) -> str:
    return (
        "\n"
        "[model_providers.proxy]\n"
        'name = "proxy"\n'
        f"base_url = {json.dumps(proxy_url)}\n"
        'env_key = "DIFFSAN_OPENAI_API_KEY"\n'
    )

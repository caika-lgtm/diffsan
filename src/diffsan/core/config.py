"""Config loading and precedence resolution."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import (
    AgentConfig,
    AppConfig,
    GitLabConfig,
    LimitsConfig,
    LoggingConfig,
    ModeConfig,
    SecretsConfig,
    SkipConfig,
    TruncationConfig,
)

DEFAULT_CONFIG_FILE = ".diffsan.toml"


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    config: AppConfig
    config_file: str | None


class _BootstrapSettings(BaseSettings):
    """Settings used only to discover the config file path from env."""

    model_config = SettingsConfigDict(
        env_prefix="DIFFSAN_",
        extra="ignore",
    )

    config_file: str | None = None


class _EnvConfigOverrides(BaseSettings):
    """Environment-provided config overrides."""

    model_config = SettingsConfigDict(
        env_prefix="DIFFSAN_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    workdir: str | None = None
    note_timezone: str | None = None
    mode: ModeConfig | None = None
    limits: LimitsConfig | None = None
    truncation: TruncationConfig | None = None
    secrets: SecretsConfig | None = None
    skip: SkipConfig | None = None
    agent: AgentConfig | None = None
    gitlab: GitLabConfig | None = None
    logging: LoggingConfig | None = None


def load_config(
    *,
    ci: bool | None = None,
    agent: Literal["cursor", "codex"] | None = None,
    proxy_url: str | None = None,
    workdir: str | None = None,
    note_timezone: str | None = None,
    config_file: str | None = None,
) -> LoadedConfig:
    """Load config with precedence: CLI overrides > env > file > defaults."""

    resolved_config_file = _resolve_config_file(config_file)
    file_overrides = _load_file_overrides(resolved_config_file)
    env_overrides = _load_env_overrides()
    cli_overrides = _build_cli_overrides(
        ci=ci,
        agent=agent,
        proxy_url=proxy_url,
        workdir=workdir,
        note_timezone=note_timezone,
    )

    merged = AppConfig().model_dump(mode="python")
    merged = _deep_merge(merged, file_overrides)
    merged = _deep_merge(merged, env_overrides)
    merged = _deep_merge(merged, cli_overrides)
    try:
        config = AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ReviewerError(
            "Invalid configuration",
            error_code=ErrorCode.CONFIG_PARSE_ERROR,
            context={
                "config_file": str(resolved_config_file)
                if resolved_config_file is not None
                else None
            },
            cause=exc,
        ) from exc

    return LoadedConfig(
        config=config,
        config_file=(
            str(resolved_config_file) if resolved_config_file is not None else None
        ),
    )


def _resolve_config_file(cli_config_file: str | None) -> Path | None:
    if cli_config_file:
        path = Path(cli_config_file).expanduser()
        if not path.exists():
            raise ReviewerError(
                "Config file does not exist",
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                context={"config_file": str(path)},
            )
        if path.is_dir():
            raise ReviewerError(
                "Config file path points to a directory",
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                context={"config_file": str(path)},
            )
        return path

    bootstrap = _BootstrapSettings()
    if bootstrap.config_file:
        path = Path(bootstrap.config_file).expanduser()
        if not path.exists():
            raise ReviewerError(
                "Config file from DIFFSAN_CONFIG_FILE does not exist",
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                context={"config_file": str(path)},
            )
        if path.is_dir():
            raise ReviewerError(
                "Config file path points to a directory",
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                context={"config_file": str(path)},
            )
        return path

    default_path = Path(DEFAULT_CONFIG_FILE)
    if default_path.exists():
        if default_path.is_dir():
            raise ReviewerError(
                "Default config file path points to a directory",
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                context={"config_file": str(default_path)},
            )
        return default_path

    return None


def _load_file_overrides(config_file: Path | None) -> dict[str, Any]:
    if config_file is None:
        return {}

    try:
        with config_file.open("rb") as handle:
            payload = tomllib.load(handle)
    except OSError as exc:
        raise ReviewerError(
            "Failed to read config file",
            error_code=ErrorCode.CONFIG_PARSE_ERROR,
            context={"config_file": str(config_file)},
            cause=exc,
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ReviewerError(
            "Failed to parse config file",
            error_code=ErrorCode.CONFIG_PARSE_ERROR,
            context={"config_file": str(config_file)},
            cause=exc,
        ) from exc

    if not isinstance(payload, dict):
        raise ReviewerError(
            "Config file must contain a top-level table",
            error_code=ErrorCode.CONFIG_PARSE_ERROR,
            context={"config_file": str(config_file)},
        )
    return payload


def _load_env_overrides() -> dict[str, Any]:
    try:
        overrides = _EnvConfigOverrides()
    except ValidationError as exc:
        raise ReviewerError(
            "Invalid environment configuration",
            error_code=ErrorCode.CONFIG_PARSE_ERROR,
            cause=exc,
        ) from exc
    return overrides.model_dump(
        mode="python",
        exclude_none=True,
        exclude_unset=True,
    )


def _build_cli_overrides(
    *,
    ci: bool | None,
    agent: Literal["cursor", "codex"] | None,
    proxy_url: str | None,
    workdir: str | None,
    note_timezone: str | None,
) -> dict[str, Any]:
    mode_overrides: dict[str, Any] = {}
    if ci is not None:
        mode_overrides["ci"] = ci

    overrides: dict[str, Any] = {}
    if mode_overrides:
        overrides["mode"] = mode_overrides
    agent_overrides: dict[str, Any] = {}
    if agent is not None:
        agent_overrides["agent"] = agent
    if proxy_url is not None:
        agent_overrides["proxy_url"] = proxy_url
    if agent_overrides:
        overrides["agent"] = agent_overrides
    if workdir is not None:
        overrides["workdir"] = workdir
    if note_timezone is not None:
        overrides["note_timezone"] = note_timezone
    return overrides


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
            continue
        merged[key] = value
    return merged

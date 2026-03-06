"""Tests for config loading and precedence."""

from __future__ import annotations

import os

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import AppConfig
from diffsan.core import config as config_module
from diffsan.core.config import DEFAULT_CONFIG_FILE, load_config


def _clear_diffsan_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("DIFFSAN_"):
            monkeypatch.delenv(key, raising=False)


def test_load_config_uses_defaults_without_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    loaded = load_config()

    assert loaded.config_file is None
    assert loaded.config.workdir == ".diffsan"
    assert loaded.config.note_timezone == AppConfig().note_timezone
    assert loaded.config.note_timezone
    assert loaded.config.mode.ci is False


def test_load_config_reads_default_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).write_text(
        "\n".join(
            [
                'workdir = ".ai-review"',
                'note_timezone = "UTC"',
                "[limits]",
                "max_files = 7",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config()

    assert loaded.config_file is not None
    assert loaded.config.workdir == ".ai-review"
    assert loaded.config.note_timezone == "UTC"
    assert loaded.config.limits.max_files == 7


def test_load_config_env_overrides_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).write_text(
        "\n".join(
            [
                'note_timezone = "SGT"',
                "[limits]",
                "max_files = 7",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIFFSAN_NOTE_TIMEZONE", "UTC")
    monkeypatch.setenv("DIFFSAN_LIMITS__MAX_FILES", "11")

    loaded = load_config()

    assert loaded.config.note_timezone == "UTC"
    assert loaded.config.limits.max_files == 11


def test_load_config_env_can_override_to_default_value(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).write_text(
        "\n".join(
            [
                "[mode]",
                "ci = true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIFFSAN_MODE__CI", "false")

    loaded = load_config()

    assert loaded.config.mode.ci is False


def test_load_config_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.setenv("DIFFSAN_MODE__CI", "true")
    monkeypatch.setenv("DIFFSAN_WORKDIR", ".from-env")
    monkeypatch.setenv("DIFFSAN_AGENT__AGENT", "codex")

    loaded = load_config(ci=False, agent="cursor", workdir=".from-cli")

    assert loaded.config.mode.ci is False
    assert loaded.config.agent.agent == "cursor"
    assert loaded.config.workdir == ".from-cli"


def test_load_config_supports_explicit_config_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    custom_config = tmp_path / "custom.toml"
    custom_config.write_text(
        "\n".join(
            [
                'note_timezone = "Asia/Singapore"',
                "[mode]",
                "ci = true",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config(config_file=str(custom_config))

    assert loaded.config_file == str(custom_config)
    assert loaded.config.mode.ci is True
    assert loaded.config.note_timezone == "Asia/Singapore"


def test_load_config_errors_for_missing_explicit_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(tmp_path / "missing.toml"))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_for_directory_explicit_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config-dir"
    config_dir.mkdir()

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(config_dir))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_supports_env_selected_config_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "env-selected.toml"
    config_file.write_text('note_timezone = "UTC"\n', encoding="utf-8")
    monkeypatch.setenv("DIFFSAN_CONFIG_FILE", str(config_file))

    loaded = load_config()

    assert loaded.config_file == str(config_file)
    assert loaded.config.note_timezone == "UTC"


def test_load_config_errors_for_missing_env_selected_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIFFSAN_CONFIG_FILE", str(tmp_path / "missing.toml"))

    with pytest.raises(ReviewerError) as exc_info:
        load_config()

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_for_directory_env_selected_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "env-config-dir"
    config_dir.mkdir()
    monkeypatch.setenv("DIFFSAN_CONFIG_FILE", str(config_dir))

    with pytest.raises(ReviewerError) as exc_info:
        load_config()

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_for_directory_default_config_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).mkdir()

    with pytest.raises(ReviewerError) as exc_info:
        load_config()

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_for_invalid_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "invalid.toml"
    config_file.write_text("not = [valid", encoding="utf-8")

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(config_file))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_when_file_open_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "open-fail.toml"
    config_file.write_text('note_timezone = "UTC"\n', encoding="utf-8")

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr(config_module.Path, "open", _raise_oserror)

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(config_file))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_when_loaded_payload_is_not_dict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "not-dict.toml"
    config_file.write_text('note_timezone = "UTC"\n', encoding="utf-8")
    monkeypatch.setattr(config_module.tomllib, "load", lambda _handle: ["bad"])

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(config_file))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_errors_when_validation_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "invalid-types.toml"
    config_file.write_text(
        "\n".join(
            [
                "[limits]",
                'max_files = "many"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReviewerError) as exc_info:
        load_config(config_file=str(config_file))

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR


def test_load_config_cli_note_timezone_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.setenv("DIFFSAN_NOTE_TIMEZONE", "Asia/Singapore")

    loaded = load_config(note_timezone="UTC")

    assert loaded.config.note_timezone == "UTC"


def test_load_config_supports_codex_agent_and_command_from_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).write_text(
        "\n".join(
            [
                "[agent]",
                'agent = "codex"',
                'codex_command = "codex exec --model gpt-5"',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config()

    assert loaded.config.agent.agent == "codex"
    assert loaded.config.agent.codex_command == "codex exec --model gpt-5"


def test_load_config_supports_codex_agent_overrides_from_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIFFSAN_AGENT__AGENT", "codex")
    monkeypatch.setenv("DIFFSAN_AGENT__CODEX_COMMAND", "codex exec --model gpt-5")

    loaded = load_config()

    assert loaded.config.agent.agent == "codex"
    assert loaded.config.agent.codex_command == "codex exec --model gpt-5"


def test_load_config_errors_for_invalid_agent_value(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_diffsan_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_FILE).write_text(
        "\n".join(
            [
                "[agent]",
                'agent = "invalid-agent"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReviewerError) as exc_info:
        load_config()

    assert exc_info.value.error_info.error_code == ErrorCode.CONFIG_PARSE_ERROR

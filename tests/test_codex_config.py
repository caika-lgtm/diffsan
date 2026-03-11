"""Tests for Codex home-directory config updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.core.codex_config import configure_codex_proxy_model_provider

if TYPE_CHECKING:
    from pathlib import Path


def test_configure_codex_proxy_creates_missing_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / ".codex" / "config.toml"

    written_path = configure_codex_proxy_model_provider(
        "https://proxy.example.com/v1",
        config_path=config_path,
    )

    assert written_path == config_path
    assert config_path.exists()
    assert config_path.read_text(encoding="utf-8") == (
        'model_provider = "proxy"\n'
        "\n"
        "[model_providers.proxy]\n"
        'name = "proxy"\n'
        'base_url = "https://proxy.example.com/v1"\n'
        'env_key = "DIFFSAN_OPENAI_API_KEY"\n'
    )


def test_configure_codex_proxy_rewrites_existing_provider_and_proxy_block(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                'model_provider = "openai"',
                "",
                "[model_providers.proxy]",
                'name = "proxy"',
                'base_url = "https://old.example.com/v1"',
                'env_key = "OLD_KEY"',
                "",
                "[profiles.default]",
                'model = "gpt-5"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    configure_codex_proxy_model_provider(
        "https://proxy.example.com/v1",
        config_path=config_path,
    )

    updated = config_path.read_text(encoding="utf-8")
    assert updated.count('model_provider = "proxy"') == 1
    assert updated.count("[model_providers.proxy]") == 1
    assert 'base_url = "https://proxy.example.com/v1"' in updated
    assert 'env_key = "DIFFSAN_OPENAI_API_KEY"' in updated
    assert '[profiles.default]\nmodel = "gpt-5"\n' in updated
    assert "old.example.com" not in updated
    assert "OLD_KEY" not in updated


def test_configure_codex_proxy_preserves_unrelated_content_and_deduplicates(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "# existing comment",
                "",
                'model_provider = "openai"',
                "",
                "[profiles.default]",
                'model = "gpt-5"',
                "",
                "[model_providers.proxy]",
                'name = "proxy"',
                'base_url = "https://old.example.com/v1"',
                'env_key = "OLD_KEY"',
                "",
                "[model_providers.proxy.headers]",
                'x_trace = "1"',
                "",
                "[model_providers.proxy]",
                'name = "proxy"',
                'base_url = "https://older.example.com/v1"',
                'env_key = "OLDER_KEY"',
                "",
                "[profiles.ci]",
                'model = "gpt-5-codex"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    configure_codex_proxy_model_provider(
        "https://proxy.example.com/v1",
        config_path=config_path,
    )

    updated = config_path.read_text(encoding="utf-8")
    assert "# existing comment" in updated
    assert '[profiles.default]\nmodel = "gpt-5"\n' in updated
    assert '[profiles.ci]\nmodel = "gpt-5-codex"\n' in updated
    assert updated.count("[model_providers.proxy]") == 1
    assert "older.example.com" not in updated
    assert "OLD_KEY" not in updated
    assert "OLDER_KEY" not in updated
    assert "[model_providers.proxy.headers]" not in updated


def test_configure_codex_proxy_errors_for_directory_path(tmp_path: Path) -> None:
    config_dir = tmp_path / ".codex" / "config.toml"
    config_dir.mkdir(parents=True)

    with pytest.raises(ReviewerError) as exc_info:
        configure_codex_proxy_model_provider(
            "https://proxy.example.com/v1",
            config_path=config_dir,
        )

    assert exc_info.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED

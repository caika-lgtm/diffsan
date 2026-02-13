"""Command-line interface for diffsan."""

from pathlib import Path
from typing import Annotated

import typer

from diffsan import __version__
from diffsan.run import RunOptions, run

app = typer.Typer(
    name="diffsan",
    help="A Python CLI tool for AI-assisted code reviews in CI pipelines.",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"diffsan version: {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    _version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    ci: bool | None = typer.Option(
        None,
        "--ci/--no-ci",
        help="Override CI mode.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run no-op harness and write run artifacts.",
    ),
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help=(
                "Path to TOML config file. If omitted, diffsan uses "
                ".diffsan.toml when present."
            ),
        ),
    ] = None,
) -> None:
    """Run diffsan."""
    if ctx.invoked_subcommand is not None:
        return

    result = run(
        RunOptions(
            ci=ci,
            dry_run=dry_run,
            config_file=str(config_file) if config_file is not None else None,
        )
    )
    raise typer.Exit(code=0 if result.ok else 1)


if __name__ == "__main__":
    app()

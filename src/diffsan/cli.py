"""Command-line interface for diffsan."""

from pathlib import Path
from typing import Annotated

import typer

from diffsan import __version__
from diffsan.run import DEFAULT_WORKDIR, RunOptions, run

DEFAULT_WORKDIR_PATH = Path(DEFAULT_WORKDIR)

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
    ci: bool = typer.Option(
        False,
        "--ci/--no-ci",
        help="Run in CI mode.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run no-op harness and write run artifacts.",
    ),
    workdir: Annotated[
        Path,
        typer.Option(
            "--workdir",
            envvar="DIFFSAN_WORKDIR",
            help="Directory for run artifacts.",
        ),
    ] = DEFAULT_WORKDIR_PATH,
    note_timezone: Annotated[
        str,
        typer.Option(
            "--note-timezone",
            envvar="DIFFSAN_NOTE_TIMEZONE",
            help=(
                "Timezone used in MR summary note metadata "
                "(e.g. SGT, UTC, Asia/Singapore)."
            ),
        ),
    ] = "SGT",
) -> None:
    """Run diffsan."""
    if ctx.invoked_subcommand is not None:
        return

    result = run(
        RunOptions(
            ci=ci,
            dry_run=dry_run,
            workdir=str(workdir),
            note_timezone=note_timezone,
        )
    )
    raise typer.Exit(code=0 if result.ok else 1)


if __name__ == "__main__":
    app()

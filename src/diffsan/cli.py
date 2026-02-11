"""Command-line interface for diffsan."""

import typer

from diffsan import __version__

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


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """A Python CLI tool for AI-assisted code reviews in CI pipelines.."""


@app.command()
def hello(
    name: str = typer.Argument("World", help="Name to greet"),
) -> None:
    """Say hello to someone."""
    typer.echo(f"Hello, {name}!")


if __name__ == "__main__":
    app()

# Contributing to diffsan

Thank you for your interest in contributing to diffsan!

Before making behavioral changes, start with the design docs index at `docs/design/README.md`. That is the source of truth for product scope, architecture, contracts, and testing expectations.

## Development Setup

1. Fork and clone the repository:

    ```bash
    git clone https://github.com/caika-lgtm/diffsan.git
    cd diffsan
    ```

2. Install dependencies:

    ```bash
    make install
    ```

3. Optionally install prek hooks:

    ```bash
    uv run prek install
    ```

## Making Changes

1. Create a new branch for your feature or bugfix:

    ```bash
    git checkout -b feature/your-feature-name
    ```

2. Make your changes and ensure tests pass:

    ```bash
    make test
    ```

3. Ensure code quality:

    ```bash
    make verify
    ```

4. Commit your changes using [conventional commits](https://www.conventionalcommits.org/):

    ```bash
    git commit -m "feat: add new feature"
    ```

## Commit Message Format

We use [Conventional Commits](https://www.conventionalcommits.org/). Here are some examples:

- `feat: add new feature` - A new feature
- `fix: resolve bug in X` - A bug fix
- `docs: update README` - Documentation changes
- `refactor: simplify code` - Code refactoring
- `test: add tests for X` - Adding tests
- `chore: update dependencies` - Maintenance tasks

## Pull Request Process

1. Update documentation if needed
2. Add tests for new functionality
3. Ensure `make verify` and `make test` pass
4. Submit a pull request with a clear description

## Code Style

- We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting
- We use [ty](https://docs.astral.sh/ty/) for type checking
- All code should be properly typed
- Write docstrings for public functions and classes
- Keep changes small and composable
- Update docs when behavior or configuration changes

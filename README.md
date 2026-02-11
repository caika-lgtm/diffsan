# diffsan

[![CI](https://github.com/caika-lgtm/diffsan/actions/workflows/ci.yml/badge.svg)](https://github.com/caika-lgtm/diffsan/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/caika-lgtm/diffsan/branch/main/graph/badge.svg)](https://codecov.io/gh/caika-lgtm/diffsan)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checked-ty-blue?labelColor=orange)](https://github.com/astral-sh/ty)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-yellow.svg)](https://github.com/caika-lgtm/diffsan/blob/main/LICENSE)

A Python CLI tool for AI-assisted code reviews in CI pipelines.

## Features

- Fast and modern Python toolchain using Astral's tools (uv, ruff, ty)
- Type-safe with full type annotations
- Command-line interface built with Typer
- Comprehensive documentation with MkDocs — [View Docs](https://caika-lgtm.github.io/diffsan/)

## Installation

```bash
pip install diffsan
```

Or using uv (recommended):

```bash
uv add diffsan
```

## Quick Start

```python
import diffsan

print(diffsan.__version__)
```

### CLI Usage

```bash
# Show version
diffsan --version

# Say hello
diffsan hello World
```

## Development

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management

### Setup

```bash
git clone https://github.com/caika-lgtm/diffsan.git
cd diffsan
make install
```

### Running Tests

```bash
make test

# With coverage
make test-cov

# Across all Python versions
make test-matrix
```

### Code Quality

```bash
# Run all checks (lint, format, type-check)
make verify

# Auto-fix lint and format issues
make fix
```

### Prek

```bash
prek install
prek run --all-files
```

### Documentation

```bash
make docs-serve
```

## License

This project is licensed under the Apache-2.0 License - see the [LICENSE](LICENSE) file for details.

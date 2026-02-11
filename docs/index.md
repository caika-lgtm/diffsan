# diffsan

A Python CLI tool for AI-assisted code reviews in CI pipelines.

## Installation

Install using pip:

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

### Command Line Interface

diffsan provides a command-line interface:

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

Clone the repository and install dependencies:

```bash
git clone https://github.com/caika-lgtm/diffsan.git
cd diffsan
uv sync --group dev
```

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run ty check
```

### Prek Hooks

Install prek hooks:

```bash
prek install
```

## License

This project is licensed under the Apache-2.0 License - see the [LICENSE](https://github.com/caika-lgtm/diffsan/blob/main/LICENSE) file for details.

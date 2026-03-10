"""Generate MkDocs home page content from the repository README."""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme_path = repo_root / "README.md"
    output_path = repo_root / "docs" / "index.md"

    content = readme_path.read_text(encoding="utf-8")
    content = _rewrite_for_docs_site(content)
    generated = (
        "<!-- Generated from README.md by scripts/generate_docs_home.py. -->\n\n"
        f"{content.rstrip()}\n"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generated, encoding="utf-8")


def _rewrite_for_docs_site(content: str) -> str:
    replacements = {
        "docs/images/": "images/",
        "(CONTRIBUTING.md)": "(contributing.md)",
        "(LICENSE)": "(https://github.com/caika-lgtm/diffsan/blob/main/LICENSE)",
    }
    for source, target in replacements.items():
        content = content.replace(source, target)
    return content


if __name__ == "__main__":
    main()

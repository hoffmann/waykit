test:
    uv run pytest

# Bump version, tag, publish to PyPI, and push to GitHub.
# Usage: just release 0.3
release version:
    #!/usr/bin/env bash
    set -euo pipefail

    # Run tests first
    uv run pytest

    # Bump version in pyproject.toml
    sed -i '' 's/^version = ".*"/version = "{{version}}"/' pyproject.toml

    # Commit, tag, build, publish, push
    git add pyproject.toml
    git commit -m "release v{{version}}"
    git tag -a "v{{version}}" -m "v{{version}}"
    uv build
    uv publish
    git push origin main
    git push origin "v{{version}}"

#!/usr/bin/env bash
# Pre-submission check: validate manifest + smoke-test the model.
# Run this before every `git push` / Quick Submit. ~5 seconds, ~$0.001.
#
# Usage:
#   ./scripts/preflight.sh
#
# Exit codes:
#   0 — both checks passed; safe to push and submit
#   1 — manifest invalid (would fail Amber compile)
#   2 — model smoke failed (would fail at first model call)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "error: $PYTHON not found. Run: uv venv --python 3.12 && uv pip install -e ."
  exit 3
fi

echo "==> validating amber-manifest.json5 against Amber config_schema profile"
"$PYTHON" "$REPO_ROOT/scripts/validate-manifest.py" || exit 1
echo

echo "==> smoke-testing configured model via LiteLLM (one short completion)"
"$PYTHON" "$REPO_ROOT/scripts/smoke_model.py" || exit 2
echo

echo "✓ preflight clean — safe to push and re-trigger Quick Submit"

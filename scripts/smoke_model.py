#!/usr/bin/env python3
"""Cheap pre-submission smoke test: ping the configured model via LiteLLM.

Builds the EXACT model config our purple agent would ship with — same
swebench.yaml base, same `_load_env_config`, same `model_kwargs` strip
that executor.py applies — then sends a one-token completion to verify:

  - model name is recognized by LiteLLM (else: 404)
  - API key is present and valid (else: 401)
  - the kwargs our executor passes are accepted (else: 400, e.g. GPT-5
    rejecting custom temperature)

~$0.001 per run, ~5 seconds. Catches the class of failures we wasted
multiple Quick Submit cycles on (temperature, model name typos, key
not reaching the runtime).

Run from the repo root:

    ./.venv/bin/python scripts/smoke_model.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv() -> None:
    """Populate os.environ from .env if present (does not override existing)."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    _load_dotenv()

    # Imported after dotenv so executor module-level constants see the env.
    import litellm

    from minisweagent.config import get_config_from_spec
    from minisweagent.utils.serialize import recursive_merge

    from purple.executor import DEFAULT_CONFIG_PATH, _load_env_config

    base_config = get_config_from_spec(str(DEFAULT_CONFIG_PATH))
    # Mirror executor.py's pre-merge mutation. Keep this in sync — if the
    # executor's recipe diverges, this smoke gives a false-pass.
    base_config.get("model", {}).pop("model_kwargs", None)
    config = recursive_merge(base_config, _load_env_config())

    model_name = config["model"]["model_name"]
    model_kwargs = config["model"].get("model_kwargs", {}) or {}

    print(f"model:      {model_name}")
    print(f"kwargs:     {model_kwargs}")
    print("openai_key: " + ("present" if os.environ.get("OPENAI_API_KEY") else "MISSING"))
    print(
        "anthropic_key: "
        + ("present" if os.environ.get("ANTHROPIC_API_KEY") else "MISSING")
    )

    try:
        response = litellm.completion(
            model=model_name,
            messages=[
                {"role": "user", "content": "Reply with the single word: pong"}
            ],
            max_tokens=20,
            **model_kwargs,
        )
    except Exception as e:
        print(f"\n❌ smoke FAILED: {type(e).__name__}: {e}")
        return 1

    text = response.choices[0].message.content
    print(f"\n✓ model responded: {text!r}")
    usage = getattr(response, "usage", None)
    if usage:
        print(f"  prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

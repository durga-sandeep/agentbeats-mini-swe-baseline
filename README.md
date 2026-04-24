# agentbeats-mini-swe-baseline

An A2A purple agent wrapping Princeton's
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) for the
[AgentBeats SWE-bench Pro](https://agentbeats.dev/agentbeater/swe-bench)
green agent.

Baseline submission — no prompt tuning, no tool additions, no scaffolding
changes. Just `mini-swe-agent` (v2.2.8) driven by OpenAI GPT-5.5 via
LiteLLM, exposed over A2A. Anthropic models work as a drop-in via
`MINI_SWE_MODEL`.

## Flow

```
green agent ──A2A TextPart(JSON)──▶ purple/server.py
                                    │
                                    ▼
                         purple/executor.py
                                    │
                                    ▼
            mini-swe-agent (DefaultAgent + DockerEnvironment)
                                    │
                                    ▼
green agent ◀──A2A TextPart(diff)── git patch
```

The A2A message payload matches the SWE-bench Pro green agent's contract:

```json
{
  "instance_id": "...",
  "problem_statement": "...",
  "docker_image": "jefzda/sweap-images:...",
  "base_commit": "...",
  "repo": "...",
  "hints": "..."
}
```

We return the raw unified diff produced by mini-swe-agent; the green
agent's extractor handles either raw diffs or `{"patch": "..."}` JSON.

## Local development

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uv pip install json5    # for scripts/validate-manifest.py

cp .env.example .env    # then edit: OPENAI_API_KEY=... (or ANTHROPIC_API_KEY)

agentbeats-purple --host 127.0.0.1 --port 9019
```

## Pre-submission preflight

Before every `git push` + Quick Submit, run:

```bash
./scripts/preflight.sh
```

Two checks (~5s, ~$0.001):

1. `scripts/validate-manifest.py` — re-implements Amber's
   `config_schema` profile rules (lowercase-only property names,
   no defaults, `additionalProperties` boolean, banned keywords)
   so we catch validation errors locally instead of via Quick
   Submit's compile step. Mirrors
   [`compiler/manifest/src/config_schema_profile.rs`](https://github.com/RDI-Foundation/amber/blob/main/compiler/manifest/src/config_schema_profile.rs).
2. `scripts/smoke_model.py` — builds the exact mini-swe-agent
   config our purple agent ships with (same `model_kwargs` strip
   in `executor.py`) and does a one-token LiteLLM completion.
   Catches: wrong model name (404), missing/invalid key (401),
   provider rejecting our kwargs (400 — e.g. GPT-5 reasoning
   models reject custom `temperature`).

The server pulls a per-task SWE-bench Docker image for each incoming
request, so the host Docker daemon must be reachable.

## Docker build

```bash
docker build --platform linux/amd64 -t agentbeats-mini-swe-baseline:local .

docker run --rm --platform linux/amd64 \
  -p 9019:9019 \
  -e OPENAI_API_KEY \
  -v /var/run/docker.sock:/var/run/docker.sock \
  agentbeats-mini-swe-baseline:local
```

The Docker socket mount lets the agent spawn sibling evaluation
containers. AgentBeats' platform provides equivalent access at submission
time.

## Configuration

All knobs are environment variables (see [`.env.example`](./.env.example)).

| Variable              | Default                           | Purpose                                            |
| --------------------- | --------------------------------- | -------------------------------------------------- |
| `OPENAI_API_KEY`      | (required for OpenAI models)      | Auth for OpenAI model provider                     |
| `ANTHROPIC_API_KEY`   | (required for Anthropic models)   | Auth for Anthropic model provider                  |
| `MINI_SWE_MODEL`      | `openai/gpt-5.5`                  | Any LiteLLM model ID                               |
| `MINI_SWE_COST_LIMIT` | `3.0`                             | USD cap per instance                               |
| `MINI_SWE_STEP_LIMIT` | `0`                               | 0 disables; otherwise a hard step cap              |
| `LOG_LEVEL`           | `INFO`                            | Server log level                                   |

## License

MIT. mini-swe-agent is MIT licensed and used here as a PyPI dependency.

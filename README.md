# agentbeats-mini-swe-baseline

An A2A purple agent wrapping Princeton's
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) for the
[AgentBeats SWE-bench Pro](https://agentbeats.dev/agentbeater/swe-bench)
green agent.

Baseline submission — no prompt tuning, no tool additions, no scaffolding
changes. Just `mini-swe-agent` (v2.2.8) driven by Claude Sonnet 4.6 via
LiteLLM, exposed over A2A.

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

cp .env.example .env    # then edit: ANTHROPIC_API_KEY=...

agentbeats-purple --host 127.0.0.1 --port 9019
```

The server pulls a per-task SWE-bench Docker image for each incoming
request, so the host Docker daemon must be reachable.

## Docker build

```bash
docker build --platform linux/amd64 -t agentbeats-mini-swe-baseline:local .

docker run --rm --platform linux/amd64 \
  -p 9019:9019 \
  -e ANTHROPIC_API_KEY \
  -v /var/run/docker.sock:/var/run/docker.sock \
  agentbeats-mini-swe-baseline:local
```

The Docker socket mount lets the agent spawn sibling evaluation
containers. AgentBeats' platform provides equivalent access at submission
time.

## Configuration

All knobs are environment variables (see [`.env.example`](./.env.example)).

| Variable              | Default                           | Purpose                                 |
| --------------------- | --------------------------------- | --------------------------------------- |
| `ANTHROPIC_API_KEY`   | (required)                        | Auth for the model provider             |
| `MINI_SWE_MODEL`      | `anthropic/claude-sonnet-4-6`     | Any LiteLLM model ID                    |
| `MINI_SWE_COST_LIMIT` | `3.0`                             | USD cap per instance                    |
| `MINI_SWE_STEP_LIMIT` | `0`                               | 0 disables; otherwise a hard step cap   |
| `LOG_LEVEL`           | `INFO`                            | Server log level                        |

## License

MIT. mini-swe-agent is MIT licensed and used here as a PyPI dependency.

FROM ghcr.io/astral-sh/uv:python3.12-trixie

# mini-swe-agent's DockerEnvironment shells out to the `docker` CLI to
# spawn a sibling container per SWE-bench task. The AgentBeats platform
# mounts /var/run/docker.sock from the host (declared in
# amber-manifest.json5); we only need the client-side binary to talk to
# it, not the daemon. Debian trixie's `docker.io` package no longer
# includes the CLI — use the official static binary instead.
ARG DOCKER_CLI_VERSION=27.3.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz \
      -o /tmp/docker.tgz \
 && tar -xzf /tmp/docker.tgz -C /tmp \
 && mv /tmp/docker/docker /usr/local/bin/docker \
 && chmod +x /usr/local/bin/docker \
 && rm -rf /tmp/docker /tmp/docker.tgz \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY purple purple

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv \
 && uv pip install --python /app/.venv/bin/python .

ENV PATH=/app/.venv/bin:$PATH

EXPOSE 9019

ENTRYPOINT ["python", "-m", "purple.server"]
CMD ["--host", "0.0.0.0", "--port", "9019"]

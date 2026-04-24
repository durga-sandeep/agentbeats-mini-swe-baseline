FROM ghcr.io/astral-sh/uv:python3.12-trixie

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

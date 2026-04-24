"""A2A server entrypoint for the mini-swe-agent purple agent.

Exposes an A2A HTTP endpoint on the configured host/port. The AgentBeats
green agent sends a single SWE-bench instance per conversation; we delegate
the work to `MiniSWEExecutor` and return a git patch.
"""

from __future__ import annotations

import argparse
import logging
import os
import re

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from purple.executor import MiniSWEExecutor

logger = logging.getLogger(__name__)


# AgentBeats' Amber runtime exposes `${config.X}` values as
# `AMBER_CONFIG_X` env vars inside the participant container; Quick
# Submit "Participant secrets" may also land under other prefixes. If
# the canonical ANTHROPIC_API_KEY isn't set, promote any matching alias
# so mini-swe-agent / LiteLLM can pick it up.
_API_KEY_ALIAS_PATTERN = re.compile(
    r"^(AMBER_CONFIG_|AMBER_SECRET_|SECRET_|PARTICIPANT_|)?ANTHROPIC_API_KEY$"
)


def _alias_anthropic_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    for name, value in os.environ.items():
        if _API_KEY_ALIAS_PATTERN.match(name) and value:
            os.environ["ANTHROPIC_API_KEY"] = value
            logger.info("Aliased %s -> ANTHROPIC_API_KEY", name)
            return


def _log_env_diagnostic() -> None:
    """Log NAMES (not values) of env vars relevant to model auth.

    Helps diagnose how AgentBeats injects secrets when a run fails with
    'Missing Anthropic API Key' — we see what arrived vs what didn't.
    """
    pattern = re.compile(r"ANTHROPIC|OPENAI|API_KEY|TOKEN|AMBER|SECRET", re.IGNORECASE)
    matching = sorted(name for name in os.environ if pattern.search(name))
    logger.info("Env var names matching auth/secrets patterns: %s", matching)
    logger.info("ANTHROPIC_API_KEY present: %s", "ANTHROPIC_API_KEY" in os.environ)


def build_agent_card(host: str, port: int, card_url: str | None) -> AgentCard:
    skill = AgentSkill(
        id="swe-bench-pro-patch",
        name="SWE-bench Pro Coding Agent",
        description=(
            "Resolves real-world GitHub issues by generating a git patch. "
            "Receives a SWE-bench instance payload (problem statement, repo, "
            "prebuilt docker image) and returns a unified diff."
        ),
        tags=["coding", "swe-bench", "patch", "python", "bash"],
        examples=[
            "Fix the issue described in the attached problem statement",
            "Generate a patch that resolves the failing tests",
        ],
    )

    model_name = os.environ.get("MINI_SWE_MODEL", "anthropic/claude-sonnet-4-6")
    return AgentCard(
        name="mini-swe-agent-baseline",
        description=(
            "Baseline coding agent built on Princeton's mini-swe-agent, "
            f"driven by {model_name}. Single ReAct loop with bash tool use "
            "inside the per-task SWE-bench Docker container."
        ),
        url=card_url or f"http://{host}:{port}/",
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="mini-swe-agent A2A purple agent")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=9019, help="Bind port")
    parser.add_argument(
        "--card-url",
        type=str,
        default=None,
        help="External URL to advertise in the agent card (overrides host:port).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("LOG_LEVEL", "INFO"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    _log_env_diagnostic()
    _alias_anthropic_api_key()

    agent_card = build_agent_card(args.host, args.port, args.card_url)

    handler = DefaultRequestHandler(
        agent_executor=MiniSWEExecutor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(agent_card=agent_card, http_handler=handler).build()

    logger.info(
        "Starting purple agent %s v%s on %s:%d",
        agent_card.name,
        agent_card.version,
        args.host,
        args.port,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()

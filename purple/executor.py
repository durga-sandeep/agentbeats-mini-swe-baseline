"""A2A executor that bridges incoming SWE-bench tasks into mini-swe-agent.

One `execute` call handles one SWE-bench instance end-to-end:

1. Parse the JSON instance payload the green agent sent.
2. Build a mini-swe-agent environment, model, and DefaultAgent from the
   builtin swebench.yaml config.
3. Run the agent (blocking) on a worker thread.
4. Return the resulting git patch wrapped in an A2A text message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InvalidRequestError,
    TaskState,
    UnsupportedOperationError,
)
from a2a.utils import get_message_text, new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from minisweagent.agents import get_agent
from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.models import get_model
from minisweagent.run.benchmarks.swebench import get_sb_environment
from minisweagent.utils.serialize import recursive_merge

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = builtin_config_dir / "benchmarks" / "swebench.yaml"
DEFAULT_MODEL = "openai/gpt-5.5"
DEFAULT_COST_LIMIT = 3.0  # USD per instance; mirrors mini-swe-agent's default


REQUIRED_INSTANCE_FIELDS = ("instance_id", "problem_statement", "docker_image")


def _load_env_config() -> dict[str, Any]:
    """Gather runtime knobs from environment variables.

    Kept here so prompt/model tweaks don't require editing this file.
    """
    cost_limit_raw = os.environ.get("MINI_SWE_COST_LIMIT")
    cost_limit = float(cost_limit_raw) if cost_limit_raw else DEFAULT_COST_LIMIT

    step_limit_raw = os.environ.get("MINI_SWE_STEP_LIMIT")
    step_limit = int(step_limit_raw) if step_limit_raw else 0  # 0 = disabled

    # `or` falls through on the empty string too — Amber's config_schema
    # profile rejects optional fields with defaults, so we declare
    # MINI_SWE_MODEL as required and let users paste an empty string
    # when they want the hardcoded default.
    return {
        "agent": {
            "cost_limit": cost_limit,
            "step_limit": step_limit,
        },
        "model": {
            "model_name": os.environ.get("MINI_SWE_MODEL") or DEFAULT_MODEL,
        },
    }


def _parse_instance(text: str) -> dict[str, Any]:
    """Parse and validate the JSON payload the green agent sends."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Expected JSON instance payload, got: {e}") from e

    if not isinstance(payload, dict):
        raise ValueError(f"Instance payload must be a JSON object, got {type(payload).__name__}")

    missing = [k for k in REQUIRED_INSTANCE_FIELDS if not payload.get(k)]
    if missing:
        raise ValueError(f"Instance payload missing required fields: {missing}")

    return payload


def _strip_unsupported_kwargs(config: dict[str, Any], model_name: str) -> None:
    """Remove model_kwargs that the chosen provider rejects.

    OpenAI's GPT-5 reasoning family (gpt-5, gpt-5.x, gpt-5-pro, etc.)
    only accepts the default temperature; passing any value (including
    the swebench.yaml default of 0.0) returns a 400. Strip it for those
    models. mini-swe-agent's recursive_merge is additive — it can't
    remove keys — so we mutate base_config in place before merging.
    """
    if not model_name.startswith("openai/gpt-5"):
        return
    kwargs = config.get("model", {}).get("model_kwargs")
    if isinstance(kwargs, dict):
        kwargs.pop("temperature", None)


def _run_mini_swe(instance: dict[str, Any]) -> dict[str, Any]:
    """Run mini-swe-agent synchronously; returns the agent's final result dict.

    The result dict contains at minimum `submission` (git patch) and
    `exit_status`. Shape is defined by `DefaultAgent.run`.
    """
    base_config = get_config_from_spec(str(DEFAULT_CONFIG_PATH))
    env_config = _load_env_config()
    _strip_unsupported_kwargs(base_config, env_config["model"]["model_name"])
    config = recursive_merge(base_config, env_config)

    env = get_sb_environment(config, instance)
    agent = get_agent(
        get_model(config=config.get("model", {})),
        env,
        config.get("agent", {}),
        default_type="default",
    )
    return agent.run(instance["problem_statement"])


class MiniSWEExecutor(AgentExecutor):
    """Routes one A2A message → mini-swe-agent → git patch."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        msg = context.message
        if not msg:
            raise ServerError(error=InvalidRequestError(message="Missing message in request"))

        task = context.current_task
        if not task:
            task = new_task(msg)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()

        try:
            instance = _parse_instance(get_message_text(msg))
        except ValueError as e:
            logger.warning("Rejecting malformed instance payload: %s", e)
            await updater.failed(
                new_agent_text_message(
                    f"Invalid instance payload: {e}",
                    context_id=task.context_id,
                    task_id=task.id,
                )
            )
            return

        instance_id = instance["instance_id"]
        logger.info("Starting task %s", instance_id)
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(
                f"Starting mini-swe-agent on {instance_id}",
                context_id=task.context_id,
                task_id=task.id,
            ),
        )

        try:
            result = await asyncio.to_thread(_run_mini_swe, instance)
        except Exception as e:
            # mini-swe-agent itself may raise on environment failures, model
            # errors, etc. We log the traceback locally but return a terse
            # message to the green agent so the eval can proceed.
            logger.exception("Agent run failed for %s", instance_id)
            await updater.failed(
                new_agent_text_message(
                    f"Agent error: {e}",
                    context_id=task.context_id,
                    task_id=task.id,
                )
            )
            return

        patch = result.get("submission") or ""
        exit_status = result.get("exit_status", "unknown")
        logger.info(
            "Task %s complete: exit_status=%s patch_bytes=%d",
            instance_id,
            exit_status,
            len(patch),
        )

        # The green agent's patch extractor accepts raw diffs, fenced diff
        # code blocks, or JSON with a "patch" key. Raw diff is the cleanest
        # contract — no wrapping needed.
        response = patch if patch else f"No patch generated (exit_status={exit_status})"
        await updater.complete(
            new_agent_text_message(
                response,
                context_id=task.context_id,
                task_id=task.id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())

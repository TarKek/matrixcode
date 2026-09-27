#!/usr/bin/env python3
"""точка входа matrixcode.

Собирает реестры, логгер и запускает TUI.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from agent.agent import Agent  # noqa: F401  (import check, kept on purpose)
from core import paths as P
from core import policy
from core.logger import Logger
from core.registries import (
    CommandRegistry,
    Registry,
    SkillRegistry,
    load_commands,
    load_skills,
    load_tools,
)
from core.sandbox import install_sandbox
from core.summarize import needs_summary, summarize_history
from llm.client import chat_stream, fetch_context_window, list_models
from ui.app import MatrixCodeApp


def load_last_session(log_dir):
    """Читает последний session-*.jsonl и возвращает messages из request."""
    import json
    try:
        logs = sorted(log_dir.glob("session-*.jsonl"))
    except Exception:
        return None
    for path in reversed(logs):
        last_req = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("kind") == "request":
                        last_req = rec
        except Exception:
            continue
        if last_req and last_req.get("messages"):
            return last_req["messages"]
    return None


def _apply_cli_policy(argv: list[str]) -> None:
    """Читает --policy NAME / --safe / --strict / --dev ДО старта."""
    args = list(argv)
    for i, a in enumerate(args):
        if a in ("--safe",):
            policy.set_policy("safe")
        elif a in ("--strict",):
            policy.set_policy("strict")
        elif a in ("--dev",):
            policy.set_policy("dev")
        elif a == "--policy" and i + 1 < len(args):
            if not policy.set_policy(args[i + 1]):
                print(f"[cli] unknown policy: {args[i+1]}", flush=True)
        elif a.startswith("--policy="):
            name = a.split("=", 1)[1]
            if not policy.set_policy(name):
                print(f"[cli] unknown policy: {name}", flush=True)


async def amain() -> None:
    install_sandbox()
    os.chdir(P.WORKSPACE_DIR)

    registry = Registry()
    load_tools(P.TOOLS_DIR, registry)

    skill_registry = SkillRegistry()
    load_skills(P.SKILLS_DIR, skill_registry)

    cmd_registry = CommandRegistry()
    load_commands(P.COMMANDS_DIR, cmd_registry)

    resume_msgs = None
    if "--continue" in sys.argv or "-c" in sys.argv:
        resume_msgs = load_last_session(P.LOG_DIR)

    ctx_window, ctx_source = await fetch_context_window()

    models = await list_models()
    if not models:
        models = [P.ENV_MODEL]

    # резюмируем resume-историю до старта UI, если она длинная.
    if (resume_msgs and P.SUMMARY_ENABLED
            and needs_summary(resume_msgs, ctx_window=ctx_window,
                              pct=P.SUMMARY_AT, min_msgs=P.SUMMARY_MIN_MSGS)):
        _resume_model = models[0] if models else P.ENV_MODEL
        new_msgs, moved = await summarize_history(
            resume_msgs, model=_resume_model, keep_last=P.SUMMARY_KEEP,
            chat_fn=chat_stream,
        )
        if moved > 0:
            resume_msgs = new_msgs
            print(f"[resume] summarized {moved} old message(s)",
                  flush=True)

    log_path = P.LOG_DIR / (
        f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl")
    logger = Logger(log_path)
    logger.event(
        "session_start",
        endpoint=P.BASE_URL,
        models=models,
        context_window=ctx_window,
        context_source=ctx_source,
        tools=registry.names(),
        skills=list(skill_registry.skills.keys()),
        commands=list(cmd_registry.commands.keys()),
        workspace=str(P.WORKSPACE_DIR),
        thinking_budget=P.THINKING_BUDGET,
        resumed=bool(resume_msgs),
    )

    app = MatrixCodeApp(
        registry, skill_registry, logger, ctx_window, models,
        thinking_budget=P.THINKING_BUDGET,
        commands=cmd_registry,
        resume_messages=resume_msgs,
    )
    try:
        await app.run_async()
    finally:
        logger.event("session_end")
        logger.close()


def main() -> None:
    _apply_cli_policy(sys.argv[1:])
    asyncio.run(amain())


if __name__ == "__main__":
    main()

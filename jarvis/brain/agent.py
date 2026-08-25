"""The reasoning loop: Claude with tools, wrapped in conversation memory."""
from __future__ import annotations

import logging
from typing import Callable

from ..config import safe_roots
from . import tools
from .prompts import build_system_prompt

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg["assistant"]["model"]
        self.max_tokens = cfg["assistant"]["max_tokens"]
        self.history_turns = cfg["assistant"]["history_turns"]
        self.messages: list[dict] = []
        self.system_prompt = build_system_prompt(cfg, safe_roots(cfg))

        from anthropic import Anthropic

        key = cfg["secrets"]["anthropic_api_key"]
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it, or put it in a .env file "
                "next to config.yaml."
            )
        self.client = Anthropic(api_key=key)

    def ask(self, text: str, on_tool: Callable[[str, dict], None] | None = None) -> str:
        """Run one user turn to completion, including any tool calls."""
        self.messages.append({"role": "user", "content": text})
        self._trim()

        for round_num in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                tools=tools.schemas(),
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return self._text_of(response)

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if on_tool is not None:
                    on_tool(block.name, block.input)
                output = tools.dispatch(block.name, block.input or {}, self.cfg)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
            self.messages.append({"role": "user", "content": results})
            log.debug("tool round %d complete", round_num + 1)

        return "I got stuck in a loop working on that, so I've stopped."

    @staticmethod
    def _text_of(response) -> str:
        return " ".join(
            block.text.strip() for block in response.content
            if getattr(block, "type", None) == "text" and block.text.strip()
        ).strip()

    def _trim(self) -> None:
        """Keep history bounded, without orphaning a tool_result from its tool_use."""
        limit = self.history_turns * 2
        if len(self.messages) <= limit:
            return
        trimmed = self.messages[-limit:]
        # A conversation must not open with a tool_result block - the API rejects
        # it, because the matching tool_use just got cut. Walk forward to the
        # next clean user turn.
        while trimmed and _starts_with_tool_result(trimmed[0]):
            trimmed.pop(0)
        self.messages = trimmed

    def reset(self) -> None:
        self.messages = []


def _starts_with_tool_result(message: dict) -> bool:
    content = message.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return first.get("type") == "tool_result"
        return getattr(first, "type", None) == "tool_result"
    return False

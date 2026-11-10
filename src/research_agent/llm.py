"""Provider-agnostic tool calling.

The loop keeps history in one neutral shape:
    {"role": "user", "content": str}
    {"role": "assistant", "content": str | None, "tool_calls": [ToolCall, ...]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Each provider converts it to its own wire format. Swapping providers is an env var.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# USD per million tokens (input, output). Override with llm.price_per_mtok in config.
PRICES = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
}
UNKNOWN_PRICE = (3.00, 15.00)  # conservative, so an unknown model hits the cost cap early


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict | None  # None when the model sent arguments that were not valid JSON


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def price_for(model: str, override: dict | None = None) -> tuple[float, float]:
    if override:
        return float(override["input"]), float(override["output"])
    for name, p in PRICES.items():
        if model == name or model.startswith(name + "-"):
            return p
    return UNKNOWN_PRICE


def _parse_args(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else None
    except (TypeError, ValueError):
        return None


class OpenAIProvider:
    def __init__(self, model: str, temperature: float = 0.2, client=None) -> None:
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        self.client, self.model, self.temperature = client, model, temperature

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        wire = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("content")}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.args or {})}}
                                         for c in m["tool_calls"]]
                wire.append(msg)
            elif m["role"] == "tool":
                wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                wire.append({"role": "user", "content": m["content"]})
        resp = self.client.chat.completions.create(
            model=self.model, messages=wire, temperature=self.temperature,
            tools=[{"type": "function", "function": t} for t in tools])
        choice = resp.choices[0].message
        calls = [ToolCall(c.id, c.function.name, _parse_args(c.function.arguments)) for c in (choice.tool_calls or [])]
        usage = resp.usage
        return LLMResponse(choice.content, calls, getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))


class AnthropicProvider:
    def __init__(self, model: str, temperature: float = 0.2, client=None, max_tokens: int = 4096) -> None:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.temperature, self.max_tokens = client, model, temperature, max_tokens

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        wire: list[dict] = []
        for m in messages:
            if m["role"] == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args or {}})
                wire.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)  # results of parallel calls go in one user turn
                else:
                    wire.append({"role": "user", "content": [block]})
            else:
                wire.append({"role": "user", "content": m["content"]})
        resp = self.client.messages.create(
            model=self.model, system=system, messages=wire, max_tokens=self.max_tokens,
            # temperature is not sent: current Anthropic SDKs and models do not accept it.
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools])
        text = "".join(b.text for b in resp.content if b.type == "text") or None
        calls = [ToolCall(b.id, b.name, _parse_args(b.input)) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(text, calls, resp.usage.input_tokens, resp.usage.output_tokens)


def make_provider(provider: str, model: str, temperature: float = 0.2):
    if provider == "openai":
        return OpenAIProvider(model, temperature)
    if provider == "anthropic":
        return AnthropicProvider(model, temperature)
    raise ValueError(f"unknown provider {provider}")

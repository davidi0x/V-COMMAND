"""Agent output parsers: echo the agent's answer, extract provider cost, and guard the stream.

A parser receives the agent's stdout line by line while the agent runs. It may return a reason to
stop the agent immediately (the stream guard), and at the end reports cost. Nothing it reads is
persisted; only the cost figures and a guard verdict reach the evidence.

* claude-json   — `claude -p --output-format json`: cost = `total_cost_usd` (provider-reported).
* claude-stream — `claude -p --output-format stream-json --verbose`: same cost, plus the stream guard:
  every Edit/Write/MultiEdit the agent issues is checked against banned patterns (from the ledger and
  config) and the agent is killed before it can continue on a known-bad approach.
* codex-jsonl   — `codex exec --json`: token usage summed from events; USD only as an *estimate* when
  the developer configured prices for the model; otherwise unknown.
"""
from __future__ import annotations

import json
from typing import Any

PARSERS = ("claude-json", "claude-stream", "codex-jsonl")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
UNKNOWN = {"currency": "USD", "amount": None, "source": "unavailable"}


class _Base:
    # how the agent itself ended the run, when it says so ("success", "error_max_turns", ...)
    result_subtype: str | None = None

    def __init__(self, echo, context: dict[str, Any] | None = None):
        self.echo = echo
        self.context = context or {}

    def feed(self, line: str) -> str | None:  # returns a kill reason or None
        return None

    def finish(self) -> dict[str, Any]:
        return dict(UNKNOWN)

    def _say(self, text: str) -> None:
        if text and text.strip():
            self.echo.write(text.rstrip() + "\n")


class ClaudeJson(_Base):
    def __init__(self, echo, context=None):
        super().__init__(echo, context)
        self.lines: list[str] = []

    def feed(self, line: str) -> str | None:
        self.lines.append(line)
        return None

    def finish(self) -> dict[str, Any]:
        text = "".join(self.lines).strip()
        try:
            data = json.loads(text.splitlines()[-1]) if text else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            self.echo.write("".join(self.lines))
            return dict(UNKNOWN)
        if isinstance(data.get("result"), str):
            self._say(data["result"])
        self.result_subtype = data.get("subtype") if isinstance(data.get("subtype"), str) else None
        return _claude_cost(data)


def _claude_cost(data: dict[str, Any]) -> dict[str, Any]:
    amount = data.get("total_cost_usd")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount >= 0:
        return {"currency": "USD", "amount": float(amount), "source": "claude-code total_cost_usd"}
    return dict(UNKNOWN)


class ClaudeStream(_Base):
    """Stream guard: kill the agent when an edit contains a banned pattern."""

    def __init__(self, echo, context=None):
        super().__init__(echo, context)
        self.cost = dict(UNKNOWN)
        self.banned = [b for b in self.context.get("banned", []) if b.get("pattern")]

    def feed(self, line: str) -> str | None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        if event.get("type") == "result":
            self.cost = _claude_cost(event)
            self.result_subtype = event.get("subtype") if isinstance(event.get("subtype"), str) else None
            return None
        if event.get("type") != "assistant":
            return None
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                self._say(block.get("text", ""))
            elif block.get("type") == "tool_use" and block.get("name") in EDIT_TOOLS:
                reason = self._check(block.get("input") or {})
                if reason:
                    return reason
        return None

    def _check(self, tool_input: dict[str, Any]) -> str | None:
        written = [tool_input.get(k) for k in ("new_string", "content", "new_source")]
        written += [e.get("new_string") for e in tool_input.get("edits", []) if isinstance(e, dict)]
        text = "\n".join(w for w in written if isinstance(w, str))
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or "?"
        for rule in self.banned:
            if rule["pattern"] in text:
                return (f"stream guard: edit to {target} contains banned pattern `{rule['pattern']}`"
                        + (f" ({rule['reason']})" if rule.get("reason") else ""))
        return None

    def finish(self) -> dict[str, Any]:
        return self.cost


class CodexJsonl(_Base):
    """Token usage from `codex exec --json`; USD only as an estimate from configured prices."""

    def __init__(self, echo, context=None):
        super().__init__(echo, context)
        self.usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        self.seen_usage = False

    def feed(self, line: str) -> str | None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        usage = event.get("usage") or (event.get("info") or {}).get("last_token_usage")
        if isinstance(usage, dict) and event.get("type") in {"turn.completed", "token_count", None}:
            for key in self.usage:
                value = usage.get(key)
                if isinstance(value, int) and value >= 0:
                    self.usage[key] += value
                    self.seen_usage = True
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") in {"agent_message", "assistant_message"}:
            self._say(item.get("text", ""))
        return None

    def finish(self) -> dict[str, Any]:
        if not self.seen_usage:
            return dict(UNKNOWN)
        model = self.context.get("model")
        price = (self.context.get("prices") or {}).get(model) if model else None
        out = {"currency": "USD", "amount": None, "source": "codex token usage (no USD receipt)",
               "usage": dict(self.usage)}
        if isinstance(price, dict):
            uncached = max(0, self.usage["input_tokens"] - self.usage["cached_input_tokens"])
            amount = (uncached * float(price.get("input_per_mtok", 0))
                      + self.usage["cached_input_tokens"] * float(price.get("cached_input_per_mtok",
                                                                             price.get("input_per_mtok", 0)))
                      + self.usage["output_tokens"] * float(price.get("output_per_mtok", 0))) / 1_000_000
            out.update(amount=round(amount, 6), estimated=True,
                       source=f"estimate: codex tokens x configured prices['{model}']")
        return out


def make_parser(name: str | None, echo, context: dict[str, Any] | None = None):
    if name is None:
        return None
    cls = {"claude-json": ClaudeJson, "claude-stream": ClaudeStream, "codex-jsonl": CodexJsonl}.get(name)
    if cls is None:
        raise ValueError(f"Unknown output parser: {name} (known: {', '.join(PARSERS)})")
    return cls(echo, context)

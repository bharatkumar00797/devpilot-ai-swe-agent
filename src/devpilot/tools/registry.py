"""Tool abstraction: a named, documented, argument-validated capability."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ArgSpec = Mapping[str, tuple[type, bool, str]]  # name -> (type, required, description)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolArgumentError(ValueError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: ArgSpec
    handler: Callable[[dict[str, Any]], ToolResult]

    def validate(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(raw) - set(self.args)
        if unknown:
            raise ToolArgumentError(f"Unknown argument(s) for {self.name}: {sorted(unknown)}")
        clean: dict[str, Any] = {}
        for name, (typ, required, _) in self.args.items():
            if name not in raw or raw[name] is None:
                if required:
                    raise ToolArgumentError(f"Missing required argument '{name}' for {self.name}")
                continue
            value = raw[name]
            if typ is int and isinstance(value, str) and value.strip().lstrip("-").isdigit():
                value = int(value)
            if typ is bool and isinstance(value, str):
                value = value.strip().lower() in {"true", "1", "yes"}
            if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
                raise ToolArgumentError(
                    f"Argument '{name}' for {self.name} must be {typ.__name__}"
                )
            clean[name] = value
        return clean

    def signature(self) -> str:
        params = ", ".join(
            f"{n}: {t.__name__}{'' if req else ' (optional)'}" for n, (t, req, _) in self.args.items()
        )
        lines = [f"- {self.name}({params}): {self.description}"]
        lines += [f"    {n}: {desc}" for n, (_, _, desc) in self.args.items()]
        return "\n".join(lines)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe(self) -> str:
        return "\n".join(tool.signature() for tool in self._tools.values())

    def execute(self, name: str, raw_args: Mapping[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool '{name}'. Available: {', '.join(self._tools)}")
        try:
            args = tool.validate(raw_args)
            return tool.handler(args)
        except Exception as exc:  # tools report errors back to the model, never crash the loop
            return ToolResult(False, f"{exc.__class__.__name__}: {exc}")

"""Tool registry, schema validation, and dispatch engine."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

import jsonschema

from tools.base import make_error_packet

CATALOG_PATH = Path("docs/signal_catalog.csv")
TOOLS_SCHEMA_PATH = Path("docs/tools.schema.json")

_VALID_SIGNALS: set[str] = set()
_ALIAS_MAP: dict[str, str] = {}
_SIGNAL_METADATA: dict[str, tuple[str, str, str]] = {}
_TOOLS_SCHEMA: dict[str, Any] | None = None
_TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {}


def _init_catalog() -> None:
    global _VALID_SIGNALS, _ALIAS_MAP, _SIGNAL_METADATA
    if _VALID_SIGNALS:
        return
    if not CATALOG_PATH.exists():
        return
    with open(CATALOG_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sig = row["signal"]
            unit = row["unit"]
            src = row["source"]
            desc = row["description"]
            _VALID_SIGNALS.add(sig)
            _SIGNAL_METADATA[sig] = (unit, src, desc)
            _ALIAS_MAP[sig] = sig
            raw_aliases = row.get("aliases", "")
            if raw_aliases:
                try:
                    aliases = json.loads(raw_aliases)
                    for alias in aliases:
                        _ALIAS_MAP[alias.lower()] = sig
                except Exception:
                    pass


def _init_tools_schema() -> None:
    global _TOOLS_SCHEMA
    if _TOOLS_SCHEMA is not None:
        return
    if TOOLS_SCHEMA_PATH.exists():
        with open(TOOLS_SCHEMA_PATH, encoding="utf-8") as f:
            _TOOLS_SCHEMA = json.load(f)


def normalize_signal_name(name: str) -> str | None:
    """Resolve a metric/signal name or alias to its canonical catalog name.

    Returns canonical name if recognized, or None if unknown.
    """
    _init_catalog()
    clean = name.strip().lower()
    return _ALIAS_MAP.get(clean)


def get_signal_unit(signal_name: str) -> str:
    """Return unit for signal name."""
    _init_catalog()
    canonical = normalize_signal_name(signal_name)
    if canonical and canonical in _SIGNAL_METADATA:
        return _SIGNAL_METADATA[canonical][0]
    return ""


_TOOLS_VALIDATOR: Any = None


def get_tools_schema() -> dict[str, Any]:
    """Return the parsed tools schema from docs/tools.schema.json."""
    global _TOOLS_SCHEMA, _TOOLS_VALIDATOR
    _init_tools_schema()
    if _TOOLS_SCHEMA is None:
        raise FileNotFoundError(f"Schema not found: {TOOLS_SCHEMA_PATH}")
    if _TOOLS_VALIDATOR is None:
        _TOOLS_VALIDATOR = jsonschema.Draft202012Validator(_TOOLS_SCHEMA)
    return _TOOLS_SCHEMA


def validate_tool_call(tool_name: str, args: dict[str, Any]) -> None:
    """Validate a tool call against the oneOf schema in docs/tools.schema.json."""
    get_tools_schema()
    instance = {"tool": tool_name, "args": args}
    _TOOLS_VALIDATOR.validate(instance)


def register_tool(name: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Decorator to register a tool handler function."""
    def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        _TOOL_HANDLERS[name] = fn
        return fn
    return decorator


def get_registered_tools() -> list[str]:
    """Return list of all registered tool names."""
    return list(_TOOL_HANDLERS.keys())


def dispatch_tool(
    tool_name: str,
    args: dict[str, Any],
    db_path: Path | str,
) -> dict[str, Any]:
    """Validate and dispatch a tool call to its registered implementation.

    Returns schema-compliant evidence packet.
    """
    # 1. Normalize metric or signal names if present in args
    clean_args = dict(args)
    for key in ("metric", "signal"):
        if key in clean_args and isinstance(clean_args[key], str):
            canonical = normalize_signal_name(clean_args[key])
            if canonical is None:
                # Return signal_unknown error packet
                time_range = [args.get("start", "2026-10-01"), args.get("end", "2026-10-28")]
                if "window_a" in args:
                    time_range = [args["window_a"].split("/")[0], args.get("window_b", "").split("/")[-1] or args["window_a"].split("/")[-1]]
                return make_error_packet(
                    tool=tool_name,
                    query_type=tool_name,
                    time_range=time_range,
                    reason="signal_unknown",
                    detail=f"Unknown signal or metric: '{clean_args[key]}'",
                )
            clean_args[key] = canonical

    # 2. Schema validation
    try:
        validate_tool_call(tool_name, clean_args)
    except jsonschema.ValidationError as e:
        time_range = [args.get("start", "2026-10-01"), args.get("end", "2026-10-28")]
        return make_error_packet(
            tool=tool_name,
            query_type=tool_name,
            time_range=time_range,
            reason="signal_unknown",
            detail=f"Invalid arguments for tool '{tool_name}': {e.message}",
        )

    # 3. Lookup handler
    if tool_name not in _TOOL_HANDLERS:
        time_range = [args.get("start", "2026-10-01"), args.get("end", "2026-10-28")]
        return make_error_packet(
            tool=tool_name,
            query_type=tool_name,
            time_range=time_range,
            reason="source_missing",
            detail=f"Tool '{tool_name}' has no registered handler",
        )

    handler = _TOOL_HANDLERS[tool_name]
    return handler(args=clean_args, db_path=db_path)

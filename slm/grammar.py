"""Grammar generator using llama.cpp's built-in JSON schema to GBNF converter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path("docs/tools.schema.json")

# Documented schema keywords strictly enforced by llama.cpp's GBNF converter:
ENFORCED_SCHEMA_KEYWORDS: list[str] = [
    "type",
    "properties",
    "required",
    "enum",
    "const",
    "items",
    "oneOf",
    "anyOf",
    "allOf",
    "additionalProperties",
    "$defs",
    "$ref",
]

_CACHED_GBNF: str | None = None
_CACHED_LLAMA_GRAMMAR: Any = None


def get_tools_gbnf(schema_path: Path | str = SCHEMA_PATH) -> str:
    """Compile tools.schema.json into a GBNF grammar string using llama.cpp."""
    global _CACHED_GBNF
    if _CACHED_GBNF is not None:
        return _CACHED_GBNF

    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")

    with open(path, encoding="utf-8") as f:
        schema_dict = json.load(f)

    def _sanitize_for_gbnf(obj: Any) -> Any:
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                if k in ("maxLength", "pattern"):
                    continue
                new_obj[k] = _sanitize_for_gbnf(v)
            return new_obj
        elif isinstance(obj, list):
            return [_sanitize_for_gbnf(x) for x in obj]
        return obj

    sanitized_schema = _sanitize_for_gbnf(schema_dict)

    # Fix 1: Catalog-Enum Constraints for metric and signal arguments
    catalog_metrics = ["range_per_charge", "energy_per_km"]
    catalog_signals = [
        "soc", "pack_temp", "coolant_temp", "coolant_pump_duty",
        "vehicle_speed", "odometer", "range_estimate", "tire_pressure_fl",
        "ambient_temp", "cabin_temp", "motor_power", "regen_power"
    ]
    for branch in sanitized_schema.get("oneOf", []):
        props = branch.get("properties", {}).get("args", {}).get("properties", {})
        if "metric" in props:
            props["metric"] = {"type": "string", "enum": catalog_metrics}
        if "signal" in props:
            props["signal"] = {"type": "string", "enum": catalog_signals}

    # Ensure any sub-schema inside anyOf specifies type: object for GBNF parser compatibility
    for branch in sanitized_schema.get("oneOf", []):
        args = branch.get("properties", {}).get("args", {})
        if "anyOf" in args:
            for sub in args["anyOf"]:
                if "type" not in sub:
                    sub["type"] = "object"

    from llama_cpp.llama_grammar import json_schema_to_gbnf
    _CACHED_GBNF = json_schema_to_gbnf(json.dumps(sanitized_schema))
    return _CACHED_GBNF


def get_llama_grammar(schema_path: Path | str = SCHEMA_PATH) -> Any:
    """Return compiled LlamaGrammar object ready for llama.cpp decoding constraints."""
    global _CACHED_LLAMA_GRAMMAR
    if _CACHED_LLAMA_GRAMMAR is not None:
        return _CACHED_LLAMA_GRAMMAR

    gbnf_str = get_tools_gbnf(schema_path)
    try:
        from llama_cpp import LlamaGrammar
        _CACHED_LLAMA_GRAMMAR = LlamaGrammar.from_string(gbnf_str)
        return _CACHED_LLAMA_GRAMMAR
    except Exception as e:
        return None

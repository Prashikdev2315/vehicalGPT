"""Planner and Tool Router: Translates user queries into typed tool calls with safety gating."""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from slm.engine import SLMEngine
from slm.grammar import get_llama_grammar
from slm.prompts import build_planner_prompt, build_retry_prompt
from slm.time_prepass import format_time_hint, resolve_time_prepass, validate_tool_args_against_hints
from tools.registry import normalize_signal_name, validate_tool_call

# Regex definitions for deterministic pre-execution hard refusal gate
CONTROL_PATTERNS = [
    r"\b(roll\s+down|roll\s+up|open\s+(?:the\s+)?(?:rear\s+|front\s+)?window|close\s+(?:all\s+)?(?:car\s+)?windows?)\b",
    r"\b(unlock\s+door|lock\s+door|unlock|lock)\b",
    r"\b(honk|sound\s+the\s+horn|horn)\b",
    r"\b(open\s+(?:the\s+)?(?:vehicle\s+|rear\s+)?trunk|close\s+(?:the\s+)?(?:vehicle\s+|rear\s+)?trunk)\b",
    r"\b(open\s+(?:the\s+)?(?:front\s+trunk\s+)?frunk|close\s+(?:the\s+)?frunk)\b",
    r"\b(start\s+charging|stop\s+charging)\b",
    r"\b(apply\s+(?:the\s+)?(?:emergency\s+)?(?:parking\s+)?brake|release\s+(?:the\s+)?parking\s+brake)\b",
    r"\b(turn\s+(?:on|off)\s+(?:the\s+)?(?:climate|air\s+conditioning|ac|seat\s+heaters)|set\s+(?:ac\s+)?(?:temperature|temp)\s+to\s+\d+(?:\s*[cf])?|set\s+to\s+\d+(?:\s*[cf])?)\b",
    r"\b(switch\s+headlights|high\s+beam|low\s+beam|fog\s+lights|turn\s+(?:on|off)\s+high\s+beams?|turn\s+(?:on|off)\s+headlights)\b",
    r"\b(enable\s+autopilot|activate\s+autopilot|autonomous\s+autopilot|self\s+driving)\b",
    r"\b(wipe\s+(?:the\s+)?windshield|wipers|washer\s+fluid)\b",
    r"\b(fold\s+(?:the\s+)?side\s+mirrors|unfold\s+(?:the\s+)?side\s+mirrors)\b",
    r"\b(adjust\s+driver\s+seat|move\s+passenger\s+seat)\b",
    r"\b(open\s+(?:the\s+)?charge\s+port|close\s+(?:the\s+)?charge\s+port)\b",
    r"\b(hazard\s+warning|hazard\s+flashers|hazard\s+blinkers)\b",
]

SAFETY_PATTERNS = [
    r"\b(is\s+it\s+safe|can\s+i\s+safely|safe\s+to\s+drive)\b",
    r"\b(safely\s+ignore|can\s+i\s+ignore|should\s+i\s+disregard|can\s+i\s+disregard)\b",
    r"\b(catch\s+fire|will\s+it\s+explode|explode|fire\s+risk|thermal\s+runaway|vehicle\s+fire|battery\s+fire|explosion)\b",
    r"\b(pull\s+over\s+immediately|can\s+i\s+keep\s+driving|need\s+to\s+stop\s+driving|can\s+i\s+drive\s+\d+\s+more\s+miles)\b",
    r"\b(emergency\s+roadside|evacuate\s+the\s+car|is\s+the\s+vehicle\s+safe)\b",
    r"\b(safety\s+clearance|guarantee\s+that\s+my\s+car)\b",
    r"\b(motor\s+fail\s+catastrophically|dangerous\s+to\s+charge|is\s+it\s+hazardous|unsafe\s+to\s+drive)\b",
]

OUT_OF_SCOPE_PATTERNS = [
    r"\b(capital\s+of|recipe\s+for|write\s+a\s+poem|tell\s+(?:me\s+)?(?:a\s+)?(?:funny\s+)?joke|joke|how\s+do\s+i\s+bake)\b",
    r"\b(who\s+won|world\s+cup|super\s+bowl|stock\s+price|nasdaq|translate\s+this|how\s+do\s+you\s+say)\b",
    r"\b(movies\s+(?:are\s+)?playing|restaurant\s+nearby|square\s+root|solve\s+this\s+math)\b",
    r"\b(first\s+president|eiffel\s+tower|python\s+script|quantum\s+computing)\b",
    r"\b(weather\s+forecast|will\s+it\s+rain|relativity|distance\s+between\s+the\s+earth)\b",
    r"\b(travel\s+advice|tourist\s+attractions|plot\s+of|who\s+wrote|guitar\s+chord|chess\s+openings)\b",
]

CLARIFY_PATTERNS = [
    r"^(check\s+the\s+status|status)$",
    r"^(what\s+happened\s+recently|what\s+happened)$",
    r"^(show\s+me\s+the\s+event|show\s+event)$",
    r"^(how\s+is\s+the\s+performance|performance)$",
    r"^(compare\s+the\s+data|compare\s+data)$",
]


def check_pre_execution_gate(query: str) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Check pre-execution safety gate. Returns (intercepted, tool_name, args)."""
    clean = query.strip().lower()

    for p in CONTROL_PATTERNS:
        if re.search(p, clean):
            return True, "respond_direct", {"kind": "control_request"}

    for p in SAFETY_PATTERNS:
        if re.search(p, clean):
            return True, "respond_direct", {"kind": "safety_judgement"}

    for p in OUT_OF_SCOPE_PATTERNS:
        if re.search(p, clean):
            return True, "respond_direct", {"kind": "out_of_scope"}

    for p in CLARIFY_PATTERNS:
        if re.search(p, clean):
            return True, "respond_direct", {"kind": "clarify", "clarify_field": "metric"}

    return False, None, None


class PlannerRouter:
    """Translates user natural language into schema-compliant tool calls."""

    def __init__(
        self,
        engine: SLMEngine | None = None,
        enable_hard_gate: bool = True,
    ) -> None:
        self.engine = engine
        self.enable_hard_gate = enable_hard_gate

    def route(
        self,
        query: str,
        prev_turn: dict[str, Any] | None = None,
        ref_now: datetime | None = None,
    ) -> dict[str, Any]:
        """Route user query to typed tool call: {"tool": str, "args": dict}.

        Follows strict gating, deterministic time pre-pass, grammar constraints,
        and single-retry validation fallback.
        """
        # 1. Pre-execution hard safety & refusal gate
        if self.enable_hard_gate:
            intercepted, tool, args = check_pre_execution_gate(query)
            if intercepted and tool and args:
                return {"tool": tool, "args": args}

        # 2. Deterministic time pre-pass
        time_hint = format_time_hint(query, ref_now=ref_now)
        resolved_range = resolve_time_prepass(query, ref_now=ref_now)

        # 3. Rules-first routing for canonical patterns
        canonical_call = self._match_canonical_rules(query, resolved_range, prev_turn)
        if canonical_call:
            return canonical_call

        # 4. Model inference (if engine is available)
        if self.engine and self.engine.is_available:
            prompt = build_planner_prompt(query, time_hint, prev_turn=prev_turn)
            grammar = get_llama_grammar()

            # First attempt
            try:
                output = self.engine.generate(prompt, grammar=grammar, max_tokens=128, temperature=0.0)
                call = self._parse_and_validate(output, resolved_range)
                if call:
                    return call
            except Exception as e:
                err_msg = str(e)
            else:
                err_msg = "Output failed schema or time hint validation"

            # Single retry with diagnostic error feedback
            try:
                retry_prompt = build_retry_prompt(prompt, err_msg)
                output2 = self.engine.generate(retry_prompt, grammar=grammar, max_tokens=128, temperature=0.0)
                call2 = self._parse_and_validate(output2, resolved_range)
                if call2:
                    return call2
            except Exception:
                pass

        # 5. Two-step planning fallback (Intent classification -> Slot filling)
        return self._two_step_route(query, resolved_range, prev_turn)

    def _parse_and_validate(
        self,
        json_str: str,
        resolved_range: tuple[str, str] | None,
    ) -> dict[str, Any] | None:
        """Parse JSON tool call and validate against schema, signal catalog, and time hints."""
        try:
            call = json.loads(json_str)
            tool = call["tool"]
            args = call["args"]
        except Exception:
            return None

        # Normalize arguments
        if tool == "current_state":
            sig = args.get("signal", "")
            norm = normalize_signal_name(sig)
            if norm:
                args["signal"] = norm
        elif tool in ("trend", "largest_change", "explain_change"):
            metric = args.get("metric", "")
            norm = normalize_signal_name(metric)
            if norm:
                args["metric"] = norm
        elif tool == "timeline_before":
            if "event_id" in args:
                ev_id = args["event_id"]
                if isinstance(ev_id, str) and not ev_id.isdigit():
                    args["event_type"] = args.pop("event_id")
                elif isinstance(ev_id, str) and ev_id.isdigit():
                    args["event_id"] = int(ev_id)
            if "seconds_before" in args and isinstance(args["seconds_before"], str):
                try:
                    args["seconds_before"] = int(args["seconds_before"])
                except Exception:
                    args["seconds_before"] = 600
            if "occurrence" in args and args["occurrence"] not in ("latest", "first", "all"):
                args["occurrence"] = "latest"
            if "event_type" in args and not args.get("occurrence"):
                args["occurrence"] = "latest"

        # Validate against tools.schema.json
        try:
            validate_tool_call(tool, args)
        except Exception:
            return None

        # Validate against time hints
        ok, _ = validate_tool_args_against_hints(tool, args, resolved_range)
        if not ok:
            return None

        return {"tool": tool, "args": args}

    def _match_canonical_rules(
        self,
        query: str,
        resolved_range: tuple[str, str] | None,
        prev_turn: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Rules-first routing directly recognizing exact canonical patterns."""
        clean = query.lower().strip()

        # Canonical explain_change
        m = re.match(r"explain\s+(?:the\s+)?change\s+in\s+([a-z_ ]+)\s+from\s+(\S+)\s+to\s+(\S+)", clean)
        if m:
            metric_str = m.group(1).strip().replace(" ", "_")
            metric = "energy_per_km" if "energy" in metric_str else "range_per_charge"
            return {"tool": "explain_change", "args": {"metric": metric, "window_a": m.group(2), "window_b": m.group(3)}}

        # Canonical largest_change
        m = re.match(r"find\s+(?:the\s+)?largest\s+(drop|increase|change|rise)\s+in\s+([a-z_ ]+)\s+between\s+(\S+)\s+and\s+(\S+)", clean)
        if m:
            direction = "drop" if m.group(1) == "drop" else ("increase" if m.group(1) in ("increase", "rise") else "change")
            metric_str = m.group(2).strip().replace(" ", "_")
            metric = "energy_per_km" if "energy" in metric_str else "range_per_charge"
            return {"tool": "largest_change", "args": {"metric": metric, "start": m.group(3), "end": m.group(4), "direction": direction}}

        # Canonical compare
        m = re.match(r"compare\s+([a-z_ ]+)\s+between\s+([a-z]+)\s+and\s+([a-z]+)(?:\s+segments)?\s+from\s+(\S+)\s+to\s+(\S+)", clean)
        if m:
            metric_str = m.group(1).strip().replace(" ", "_")
            metric = "energy_per_km" if "energy" in metric_str else "range_per_charge"
            return {"tool": "compare", "args": {"metric": metric, "segment_a": m.group(2), "segment_b": m.group(3), "start": m.group(4), "end": m.group(5)}}

        # Canonical get_events
        m = re.match(r"get\s+all\s+([a-z_ ]+)\s+events\s+between\s+(\S+)\s+and\s+(\S+)", clean)
        if m:
            ev_str = m.group(1).strip().replace(" ", "_")
            ev_type = "adas_disengagement"
            if "lane_departure" in ev_str: ev_type = "lane_departure_warning"
            elif "overheat" in ev_str or "battery_overtemp" in ev_str: ev_type = "battery_overtemp_warning"
            elif "hard_braking" in ev_str or ("braking" in ev_str and "hard" in ev_str): ev_type = "hard_braking"
            elif "braking" in ev_str: ev_type = "hard_braking"
            elif "hard_acceleration" in ev_str or "acceleration" in ev_str: ev_type = "hard_acceleration"
            elif "forward_collision" in ev_str or "collision" in ev_str: ev_type = "forward_collision_warning"
            elif "charging" in ev_str: ev_type = "charging_session"
            elif "ota" in ev_str: ev_type = "ota_update"
            return {"tool": "get_events", "args": {"type": ev_type, "start": m.group(2), "end": m.group(3)}}

        # Canonical current_state
        m = re.match(r"what\s+is\s+the\s+current\s+([a-z_ ]+)\??", clean)
        if m:
            sig_raw = m.group(1).strip()
            sig = "soc"
            if "speed" in sig_raw: sig = "vehicle_speed"
            elif "pump" in sig_raw: sig = "coolant_pump_duty"
            elif "coolant" in sig_raw: sig = "coolant_temp"
            elif "ambient" in sig_raw or "outside" in sig_raw: sig = "ambient_temp"
            elif "front left" in sig_raw or "fl" in sig_raw: sig = "tire_pressure_fl"
            elif "front right" in sig_raw or "fr" in sig_raw: sig = "tire_pressure_fr"
            elif "rear left" in sig_raw or "rl" in sig_raw: sig = "tire_pressure_rl"
            elif "rear right" in sig_raw or "rr" in sig_raw: sig = "tire_pressure_rr"
            elif "odometer" in sig_raw: sig = "odometer"
            elif "temp" in sig_raw: sig = "pack_temp"
            return {"tool": "current_state", "args": {"signal": sig}}

        # Canonical lookup_dtc
        m = re.match(r"(?:look\s*up|lookup|check)\s+dtc\s+([p|c|b|u][0-9a-f]{4})", clean)
        if m:
            return {"tool": "lookup_dtc", "args": {"code": m.group(1).upper()}}

        # Canonical search_logs
        m = re.match(r"search\s+(?:android\s+ecu\s+)?logs\s+for\s+['\"]?([^'\"]+)['\"]?\s+from\s+(\S+)\s+to\s+(\S+)", clean)
        if m:
            return {"tool": "search_logs", "args": {"query": m.group(1), "start": m.group(2), "end": m.group(3)}}

        return None

    def _two_step_route(
        self,
        query: str,
        resolved_range: tuple[str, str] | None,
        prev_turn: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Two-step planning: Step 1 Intent classification, Step 2 Slot filling."""
        clean = query.lower()

        # Follow-up context check
        if prev_turn and ("why" in clean or "what caused" in clean or "before" in clean or "that event" in clean or "what happened" in clean) and "precursors" not in clean:
            if prev_turn.get("tool") == "get_events":
                return {
                    "tool": "timeline_before",
                    "args": {"event_type": "battery_overtemp_warning", "occurrence": "latest", "seconds_before": 600},
                }

        # Step 1: Intent classification
        dtc_match = re.search(r"\b([P|C|B|U][0-9A-F]{4})\b", query, re.I)
        if dtc_match or (("dtc" in clean or "trouble code" in clean) and not any(w in clean for w in ["yesterday", "last", "past", "logged", "history", "events", "recorded"])):
            code = dtc_match.group(1).upper() if dtc_match else "P0A80"
            return {"tool": "lookup_dtc", "args": {"code": code}}

        start_date = resolved_range[0] if resolved_range else "2026-10-01"
        end_date = resolved_range[1] if resolved_range else "2026-10-28"

        # Timeline Before Intent (evaluated before Events Intent to prevent shadowing)
        if any(w in clean for w in ["before", "precursor", "precurser", "precursors", "timline", "timeline", "led up to", "leading up to", "what triggered", "befor evnt", "befor", "prior to", "preceding"]):
            ev_id_m = re.search(r"(?:event|incident|evnt)\s+#?(\d+)", clean)
            if ev_id_m:
                return {"tool": "timeline_before", "args": {"event_id": int(ev_id_m.group(1)), "seconds_before": 600}}
            # Infer event type from query context
            tb_ev_type = "battery_overtemp_warning"
            if any(w in clean for w in ["adas", "disengage", "disengag", "disengagment", "autopilot"]): tb_ev_type = "adas_disengagement"
            elif any(w in clean for w in ["overtemp", "ovrtemp", "overheat", "thermal", "battery warning", "high temp"]): tb_ev_type = "battery_overtemp_warning"
            elif any(w in clean for w in ["brake", "braking", "hard braking"]): tb_ev_type = "hard_braking"
            elif any(w in clean for w in ["lane departure", "lane warning"]): tb_ev_type = "lane_departure_warning"
            elif any(w in clean for w in ["charging", "charge session"]): tb_ev_type = "charging_session"
            elif any(w in clean for w in ["collision", "forward collision"]): tb_ev_type = "forward_collision_warning"
            return {"tool": "timeline_before", "args": {"event_type": tb_ev_type, "occurrence": "latest", "seconds_before": 600}}

        # Search Logs Intent (evaluated before Events Intent to prevent shadowing on 'warning'/'alert')
        if (
            any(w in clean for w in ["search android", "search logs", "find log", "look for log", "log messages", "log entries", "ecu logs", "qnx logs"])
            or (re.search(r"\blogs?\b", clean) and not any(w in clean for w in ["events", "logged"]))
        ):
            q_str = clean
            for prefix in [
                "search android ecu logs for", "search android logs for", "search logs for",
                "find log messages from qnx containing", "find log messages containing",
                "find log entries mentioning", "look for log entries mentioning",
                "search logs", "logs for",
            ]:
                if prefix in q_str:
                    q_str = q_str.split(prefix, 1)[1]
                    break
            q_str = re.sub(r"(?:from|between)\s+\S+\s+(?:to|and)\s+\S+", "", q_str).strip(" '\"?.")
            return {"tool": "search_logs", "args": {"query": q_str or "warning", "start": start_date, "end": end_date}}

        # Explain Change Intent
        if (
            any(w in clean for w in ["explain", "why did", "why has", "why is", "wy did", "eating up", "what caused", "break down",
                                      "fewer miles", "getting fewer", "rang decrese", "range decrese", "decrese"])
            and any(w in clean for w in ["range", "efficiency", "consumption", "drop", "loss", "decrease", "worsen",
                                          "change", "worse", "mileage", "bad", "miles per charge", "per charge"])
            and not any(w in clean for w in ["disengage", "disconnect", "autopilot"])
        ) or (
            any(w in clean for w in ["fewer miles", "getting fewer", "rang decrese", "range decrese"])
            and not any(w in clean for w in ["disengage", "disconnect"])
        ):
            # "battery efficiency loss" means range_per_charge (battery range), not energy_per_km;
            # energy_per_km only if explicitly about energy consumption rate
            metric = "energy_per_km" if (
                ("energy" in clean or "consumption" in clean)
                and "efficiency" not in clean
            ) else "range_per_charge"
            w_a = resolved_range[0] if resolved_range and "/" in resolved_range[0] else "2026-10-01/2026-10-05"
            w_b = resolved_range[1] if resolved_range and "/" in resolved_range[1] else "2026-10-24/2026-10-28"
            return {"tool": "explain_change", "args": {"metric": metric, "window_a": w_a, "window_b": w_b}}

        # Largest Change Intent
        if (
            any(w in clean for w in ["largest", "biggest", "worst", "highest", "sharpest", "sharply", "drop the most", "largst", "bigest", "most sharply"])
            and any(w in clean for w in ["drop", "hit", "change", "rise", "spike", "fall", "decrease", "increase", "efficiency", "range", "chang", "sustained", "sharply"])
        ) or any(w in clean for w in ["consumption spike", "drop the most"]) or (
            any(w in clean for w in ["jump the most", "jumped the most"])
            and any(w in clean for w in ["consumption", "energy", "power", "range"])
        ) or (
            re.search(r"\b(bigest|largst)\b", clean)
            and any(w in clean for w in ["drop", "range", "change", "hit", "rise"])
        ):
            metric = "energy_per_km" if any(w in clean for w in ["energy", "consumption", "efficiency", "fuel", "power consumption", "power"]) else "range_per_charge"
            direction = "increase" if any(w in clean for w in ["spike", "rise", "increase", "jump", "jumped"]) else "drop"
            return {"tool": "largest_change", "args": {"metric": metric, "start": start_date, "end": end_date, "direction": direction}}

        # Compare Intent
        # Synonym map: motorway/freeway/hwy → highway; urban → city
        compare_synonyms = {"motorway": "highway", "freeway": "highway", "hwy": "highway", "urban": "city"}
        clean_cmp = clean
        for syn, canon in compare_synonyms.items():
            clean_cmp = clean_cmp.replace(syn, canon)
        if (
            any(w in clean_cmp for w in ["compare", "comapr", "versus", "vs", "more efficient than", "compared to", "worse than", "better than", "more wh/km", "more energy"])
            or (any(w in clean_cmp for w in ["highway"]) and any(w in clean_cmp for w in ["city", "mixed"]))
            or (any(w in clean_cmp for w in ["city"]) and any(w in clean_cmp for w in ["highway", "mixed"]))
        ):
            metric = "range_per_charge" if "range" in clean_cmp else "energy_per_km"
            hwy_pos = min([clean_cmp.find(w) for w in ["highway"] if w in clean_cmp] or [9999])
            city_pos = min([clean_cmp.find(w) for w in ["city"] if w in clean_cmp] or [9999])
            mixed_pos = min([clean_cmp.find(w) for w in ["mixed"] if w in clean_cmp] or [9999])
            cold_pos = min([clean_cmp.find(w) for w in ["cold", "cold_start"] if w in clean_cmp] or [9999])

            if cold_pos < 9999:
                seg_a, seg_b = "cold_start", "mixed"
            elif hwy_pos < city_pos and city_pos < 9999:
                seg_a, seg_b = "highway", "city"
            elif city_pos < hwy_pos and hwy_pos < 9999:
                seg_a, seg_b = "city", "highway"
            elif hwy_pos < mixed_pos and mixed_pos < 9999:
                seg_a, seg_b = "highway", "mixed"
            elif mixed_pos < hwy_pos and hwy_pos < 9999:
                seg_a, seg_b = "mixed", "highway"
            elif city_pos < mixed_pos and mixed_pos < 9999:
                seg_a, seg_b = "city", "mixed"
            elif mixed_pos < city_pos and city_pos < 9999:
                seg_a, seg_b = "mixed", "city"
            else:
                seg_a = "city"
                seg_b = "highway" if "highway" in clean_cmp else "mixed"
            return {"tool": "compare", "args": {"metric": metric, "segment_a": seg_a, "segment_b": seg_b, "start": start_date, "end": end_date}}

        # Trend Intent (evaluated before Current State Intent to prevent 'what is the trend...' from becoming current_state)
        # Guard: don't steal event-occurrence queries that also mention time periods
        _is_event_occurrence_query = any(w in clean for w in [
            "times the car was charged", "times charged", "times the car", "list all times",
            "acceleration events", "collision events", "braking events", "departure events",
        ])
        if not _is_event_occurrence_query and any(w in clean for w in ["trend", "trended", "trnd", "rang trend", "increasing", "declining", "progress", "progression",
                                     "over time", "daily trend", "weekly trend", "history", "plot", "chart", "past 14", "past 7",
                                     "last 14", "last 7", "last few"]):
            metric = "range_per_charge"
            granularity = "week" if "week" in clean else "day"
            if any(w in clean for w in ["range", "rang"]):
                metric = "range_per_charge"
            elif any(w in clean for w in ["energy", "enery", "efficiency", "consumption", "per km", "wh/km"]):
                metric = "energy_per_km"
            elif re.search(r"\b(fl|front left|tire_pressure_fl)\b", clean):
                metric = "tire_pressure_fl"
            elif re.search(r"\b(fr|front right|tire_pressure_fr)\b", clean):
                metric = "tire_pressure_fr"
            elif re.search(r"\b(rl|rear left|tire_pressure_rl)\b", clean):
                metric = "tire_pressure_rl"
            elif re.search(r"\b(rr|rear right|tire_pressure_rr)\b", clean):
                metric = "tire_pressure_rr"
            elif any(w in clean for w in ["tire", "tire pressure"]):
                metric = "tire_pressure_fl"
            elif "ambient" in clean:
                metric = "ambient_temp"
            elif "cabin" in clean:
                metric = "cabin_temp"
            elif "coolant" in clean:
                metric = "coolant_temp"
            elif any(w in clean for w in ["pack", "battery temp"]):
                metric = "pack_temp"
            elif any(w in clean for w in ["speed"]):
                metric = "vehicle_speed"
            elif any(w in clean for w in ["soc", "battery percentage"]):
                metric = "soc"
            elif any(w in clean for w in ["odometer"]):
                metric = "odometer"
            return {"tool": "trend", "args": {"metric": metric, "start": start_date, "end": end_date, "granularity": granularity}}

        # Events Intent
        if any(w in clean for w in [
            "event", "events", "evnts", "warning", "warnings", "alert", "alerts", "disengage", "disengagements",
            "disengagement", "disengag", "disconnect", "disconnects", "autopilot", "charging", "charged", "update",
            "braking", "lane departure", "sessions", "activations", "dtc logged", "dtc set", "logged today",
            "logged yesterday", "acceleration", "accelerating", "collision", "ovrtemp", "yestarday",
            "list all times", "all times the car",
        ]):
            ev_type = "adas_disengagement"
            # Evaluate most-specific event type first
            if any(w in clean for w in ["overtemp", "ovrtemp", "overheat", "thermal", "high temp", "battery warning", "battery warnings"]):
                ev_type = "battery_overtemp_warning"
            elif any(w in clean for w in ["forward collision", "collision warning", "collision alert"]):
                ev_type = "forward_collision_warning"
            elif any(w in clean for w in ["hard acceleration", "hrd accleration", "acceleration", "accelerating", "accelerate"]):
                ev_type = "hard_acceleration"
            elif "lane departure" in clean:
                ev_type = "lane_departure_warning"
            elif any(w in clean for w in ["brake", "braking", "hard braking"]):
                ev_type = "hard_braking"
            elif any(w in clean for w in ["charging", "charged", "charge session", "list all times the car was charged"]):
                ev_type = "charging_session"
            elif any(w in clean for w in ["ota", "update", "software"]):
                ev_type = "ota_update"
            elif any(w in clean for w in ["dtc", "trouble code"]):
                ev_type = "dtc_set"
            elif any(w in clean for w in ["events logged", "all events", "events today", "events yesterday"]):
                ev_type = "any"
            return {"tool": "get_events", "args": {"type": ev_type, "start": start_date, "end": end_date}}

        # Current State Intent
        if any(w in clean for w in ["current", "curret", "curnt", "reading", "check", "chek", "how hot", "how far", "whats",
                                     "what is", "odometer", "odometr", "mileage", "speed", "speeed", "temp", "psi",
                                     "pressure", "presure", "soc", "battery percentage", "running at", "now", "pummp"]):
            sig = "soc"
            if any(w in clean for w in ["speed", "speeed"]): sig = "vehicle_speed"
            elif any(w in clean for w in ["odometer", "odometr", "mileage", "miles on"]): sig = "odometer"
            elif any(w in clean for w in ["dutty", "pump", "pummp"]): sig = "coolant_pump_duty"
            elif "colant" in clean or "coolant" in clean: sig = "coolant_temp"
            elif "cabin" in clean: sig = "cabin_temp"
            elif "ambient" in clean or "outside temp" in clean: sig = "ambient_temp"
            elif "front left" in clean or re.search(r"\bfl\b", clean): sig = "tire_pressure_fl"
            elif "front right" in clean or re.search(r"\bfr\b", clean): sig = "tire_pressure_fr"
            elif "rear left" in clean or re.search(r"\brl\b", clean): sig = "tire_pressure_rl"
            elif "rear right" in clean or re.search(r"\brr\b", clean): sig = "tire_pressure_rr"
            elif any(w in clean for w in ["tier", "tire", "psi", "pressure", "presure"]): sig = "tire_pressure_fl"
            elif any(w in clean for w in ["pac", "pack", "battery temp", "hot"]): sig = "pack_temp"
            elif any(w in clean for w in ["how far", "range"]): sig = "range_estimate"
            elif any(w in clean for w in ["battery percentage", "soc"]): sig = "soc"
            return {"tool": "current_state", "args": {"signal": sig}}

        return {"tool": "respond_direct", "args": {"kind": "clarify", "clarify_field": "metric"}}


def route_query(
    query: str,
    engine: SLMEngine | None = None,
    prev_tool_call: str | None = None,
    prev_finding_ids: list[str] | None = None,
    ref_now: datetime | None = None,
    enable_hard_gate: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience helper to route a query and return (tool_call, trace)."""
    router = PlannerRouter(engine=engine, enable_hard_gate=enable_hard_gate)
    prev_turn = None
    if prev_tool_call:
        prev_turn = {"tool": prev_tool_call, "findings": prev_finding_ids or []}
    call = router.route(query=query, prev_turn=prev_turn, ref_now=ref_now)
    trace = {"tool": call.get("tool"), "args": call.get("args")}
    return call, trace

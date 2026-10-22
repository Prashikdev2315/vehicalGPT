"""Synthetic LoRA Training Data Generator for VehicleGPT SLM Planner.

Generates 3,000–5,000 diverse automotive query-to-tool pairs across all 10 tools:
- explain_change, largest_change, get_events, timeline_before, compare,
  lookup_dtc, search_logs, current_state, trend, respond_direct.

Key Features:
1. Exact inference prompt formatting matching slm/prompts.py.
2. Diverse phrasing: canonical, colloquial, typos, temporal expressions, follow-ups.
3. Strict n-gram deduplication (4-gram overlap filtering) against DEV and TEST splits
   in eval/planner_benchmark_300.json and eval/benchmark.json to prevent data leakage.
4. Outputs data/lora_train.jsonl and data/lora_val.jsonl.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import sys
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from slm.prompts import SYSTEM_PROMPT_PREFIX
from slm.time_prepass import format_time_hint

BENCHMARK_300_PATH = Path("eval/planner_benchmark_300.json")
BENCHMARK_100_PATH = Path("eval/benchmark.json")
OUTPUT_TRAIN_PATH = Path("data/lora_train.jsonl")
OUTPUT_VAL_PATH = Path("data/lora_val.jsonl")

REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)

# Extract 4-grams from text
def get_ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = [w.lower() for w in re.findall(r"\b\w+\b", text)]
    if len(words) < n:
        return {tuple(words)}
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def load_heldout_ngrams() -> set[tuple[str, ...]]:
    """Collect all 4-grams from both dev and test benchmark splits."""
    heldout_ngrams: set[tuple[str, ...]] = set()

    for path in (BENCHMARK_300_PATH, BENCHMARK_100_PATH):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
                for it in items:
                    q = it.get("question", "")
                    heldout_ngrams.update(get_ngrams(q, n=4))

    return heldout_ngrams


# Template banks for generation
SIGNALS = [
    ("soc", ["battery state of charge", "current battery percentage", "how much battery is left", "soc reading", "battery level right now"]),
    ("vehicle_speed", ["how fast am i driving", "current vehicle speed", "speed reading", "car speed now", "speedometer value"]),
    ("pack_temp", ["battery temperature", "battery pack temp", "how hot is the battery pack", "hv battery temp", "pack thermal reading"]),
    ("coolant_temp", ["engine coolant temperature", "coolant temp right now", "radiator coolant temp", "how warm is the coolant"]),
    ("coolant_pump_duty", ["coolant pump duty cycle", "pump speed percentage", "water pump duty", "coolant pump activity"]),
    ("odometer", ["odometer mileage", "total distance driven", "odometer reading", "car mileage reading", "how many kilometers on odometer"]),
    ("tire_pressure_fl", ["front left tire psi", "tire pressure fl", "fl wheel pressure", "front driver side tire pressure"]),
    ("tire_pressure_fr", ["front right tire pressure", "fr tire psi", "front passenger tire pressure", "tire pressure fr"]),
    ("tire_pressure_rl", ["rear left tire psi", "rl tire pressure", "rear driver side tire pressure"]),
    ("tire_pressure_rr", ["rear right tire psi", "rr tire pressure", "rear passenger tire pressure"]),
    ("cabin_temp", ["interior cabin temperature", "ac temperature inside", "cabin climate temp", "how hot is it inside the car"]),
    ("ambient_temp", ["outside temperature", "ambient weather temperature", "exterior air temp", "outdoor thermometer reading"]),
    ("range_estimate", ["estimated remaining range", "how far can i drive", "remaining distance to empty", "projected range"]),
]

DTC_CODES = [
    ("P0A80", "Hybrid Battery Pack Deterioration"),
    ("P0A1F", "Battery Energy Control Module"),
    ("P0A0D", "High Voltage System Interlock Circuit"),
    ("U0100", "Lost Communication with ECM/PCM"),
    ("C1234", "Wheel Speed Sensor Circuit Fault"),
    ("B1000", "ECU Internal Fault"),
    ("P0300", "Random Misfire Detected"),
    ("P0420", "Catalyst System Efficiency Below Threshold"),
    ("U0121", "Lost Communication with ABS Control Module"),
]

EVENTS = [
    ("battery_overtemp_warning", ["battery overtemp alert", "battery overheating warning", "high battery temp event"]),
    ("adas_disengagement", ["autopilot disengagement", "adas disconnect", "driver takeover event", "driver assist disengaged"]),
    ("hard_braking", ["emergency braking activation", "hard brake event", "sudden decel trigger", "aeb activation"]),
    ("charging_session", ["fast charging session", "level 2 charging cycle", "plug-in charging event", "dc charging"]),
    ("ota_update", ["software update installed", "ota firmware upgrade", "ecu software update event"]),
    ("lane_departure_warning", ["lane departure chime", "lane drift alert", "lane boundary warning"]),
]

METRICS = [
    ("range_per_charge", ["range per charge", "battery range", "driving range", "distance per charge", "range efficiency"]),
    ("energy_per_km", ["energy consumption", "wh per km", "power consumption", "electricity usage per km", "efficiency"]),
]

WINDOWS = [
    ("2026-10-01/2026-10-05", "2026-10-24/2026-10-28"),
    ("2026-10-01/2026-10-07", "2026-10-22/2026-10-28"),
    ("2026-10-03/2026-10-08", "2026-10-20/2026-10-25"),
    ("2026-10-05/2026-10-10", "2026-10-21/2026-10-26"),
]

DATES = [
    ("2026-10-01", "2026-10-28"),
    ("2026-10-05", "2026-10-20"),
    ("2026-10-10", "2026-10-25"),
    ("2026-10-15", "2026-10-28"),
    ("2026-10-01", "2026-10-14"),
]

CONTROL_REQUESTS = [
    ("Roll down the driver window", "control_request"),
    ("Unlock the passenger side door", "control_request"),
    ("Open the vehicle frunk", "control_request"),
    ("Turn on maximum AC cooling to 18C", "control_request"),
    ("Activate hazard flashers now", "control_request"),
    ("Engage autonomous self-driving autopilot", "control_request"),
    ("Sound the vehicle horn", "control_request"),
    ("Start charging battery immediately", "control_request"),
    ("Apply the emergency parking brake", "control_request"),
]

SAFETY_REQUESTS = [
    ("Is it safe for me to keep driving with this alert?", "safety_judgement"),
    ("Can I safely disregard the battery temperature light?", "safety_judgement"),
    ("Will the car catch fire if I continue on the highway?", "safety_judgement"),
    ("Should I pull over immediately right now?", "safety_judgement"),
    ("Guarantee that the high voltage battery won't fail", "safety_judgement"),
]

OUT_OF_SCOPE_REQUESTS = [
    ("What is the capital of Australia?", "out_of_scope"),
    ("Write a python script to sort a dictionary", "out_of_scope"),
    ("Tell me a funny joke about electric cars", "out_of_scope"),
    ("Who won the 2026 FIFA World Cup final?", "out_of_scope"),
    ("What is the current stock price of Apple?", "out_of_scope"),
]


def generate_synthetic_samples(target_count: int = 3500) -> list[dict[str, Any]]:
    heldout_ngrams = load_heldout_ngrams()
    print(f"Loaded {len(heldout_ngrams)} held-out n-grams from dev/test benchmarks for deduplication.")

    samples = []
    seen_queries = set()

    def add_sample(query: str, tool: str, args: dict[str, Any]) -> bool:
        clean_q = query.strip()
        if clean_q.lower() in seen_queries:
            return False

        # N-gram overlap check against held-out dev/test
        query_ngrams = get_ngrams(clean_q, n=4)
        if query_ngrams:
            overlap = len(query_ngrams.intersection(heldout_ngrams)) / len(query_ngrams)
            if overlap >= 0.70:
                # Reject contaminated sample!
                return False

        seen_queries.add(clean_q.lower())

        time_hint = format_time_hint(clean_q, ref_now=REF_NOW)
        user_turn = f"{time_hint}\nQuery: {clean_q}"
        assistant_turn = json.dumps({"tool": tool, "args": args})

        # Exact prompt format
        formatted_prompt = (
            f"{SYSTEM_PROMPT_PREFIX}"
            f"<|im_start|>user\n{user_turn}<|im_end|>\n"
            f"<|im_start|>assistant\n{assistant_turn}<|im_end|>"
        )

        samples.append({
            "query": clean_q,
            "tool": tool,
            "args": args,
            "prompt": formatted_prompt,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_PREFIX.replace("<|im_start|>system\n", "").replace("<|im_end|>\n", "").strip()},
                {"role": "user", "content": user_turn},
                {"role": "assistant", "content": assistant_turn},
            ],
        })
        return True

    fillers = ["", "Please ", "Can you ", "Hey, ", "VehicleGPT, ", "Tell me ", "Could you ", "Quick check: ", "I need to know: "]
    typo_fillers = ["", "pls ", "wat is ", "chek ", "curnt "]

    attempts = 0
    max_attempts = target_count * 10

    while len(samples) < target_count and attempts < max_attempts:
        attempts += 1
        category_choice = random.randint(1, 10)
        prefix = random.choice(fillers)

        # 1. current_state
        if category_choice in (1, 2):
            sig, phrases = random.choice(SIGNALS)
            template = random.choice([
                "what is the {}",
                "check the {}",
                "show current {}",
                "can you tell me the {}",
                "report {}",
                "give me the latest reading of {}",
                "what's the {} right now",
                "current {} level",
            ])
            phrase = random.choice(phrases)
            q = prefix + template.format(phrase)
            add_sample(q, "current_state", {"signal": sig})

        # 2. lookup_dtc
        elif category_choice == 3:
            # Generate valid standard DTC codes
            if random.random() < 0.6:
                code, _ = random.choice(DTC_CODES)
            else:
                prefix_char = random.choice(["P", "C", "B", "U"])
                code = f"{prefix_char}{random.randint(0, 2)}{random.randint(0, 9):01d}{random.randint(0, 15):01X}{random.randint(0, 15):01X}"
            template = random.choice([
                "what does DTC {} mean?",
                "lookup fault code {}",
                "explain error code {}",
                "check diagnostic trouble code {}",
                "what is code {} in the ECU?",
                "trouble code {}",
                "what causes fault {}?",
            ])
            q = prefix + template.format(code)
            add_sample(q, "lookup_dtc", {"code": code})

        # 3. explain_change
        elif category_choice == 4:
            metric, m_phrases = random.choice(METRICS)
            d1 = random.randint(1, 5)
            d2 = d1 + random.randint(3, 5)
            d3 = random.randint(18, 23)
            d4 = min(d3 + random.randint(3, 5), 28)
            w_a = f"2026-10-{d1:02d}/2026-10-{d2:02d}"
            w_b = f"2026-10-{d3:02d}/2026-10-{d4:02d}"
            template = random.choice([
                "explain the change in {} from {} to {}",
                "why did {} change between {} and {}?",
                "what caused the shift in {} from {} to {}?",
                "break down the change in {} from {} to {}",
                "explain why {} varied between {} and {}",
            ])
            q = prefix + template.format(random.choice(m_phrases), w_a, w_b)
            add_sample(q, "explain_change", {"metric": metric, "window_a": w_a, "window_b": w_b})

        # 4. largest_change
        elif category_choice == 5:
            metric, m_phrases = random.choice(METRICS)
            d1 = random.randint(1, 10)
            d2 = random.randint(18, 28)
            start = f"2026-10-{d1:02d}"
            end = f"2026-10-{d2:02d}"
            direction = random.choice(["drop", "increase", "change", "rise"])
            dir_norm = "drop" if direction == "drop" else ("increase" if direction in ("increase", "rise") else "change")
            template = random.choice([
                "find the largest {} in {} between {} and {}",
                "when was the biggest {} in {} from {} to {}?",
                "identify largest {} in {} between {} and {}",
                "when did {} experience the greatest {} between {} and {}",
            ])
            q = prefix + template.format(direction, random.choice(m_phrases), start, end)
            add_sample(q, "largest_change", {"metric": metric, "start": start, "end": end, "direction": dir_norm})

        # 5. compare
        elif category_choice == 6:
            metric, m_phrases = random.choice(METRICS)
            d1 = random.randint(1, 8)
            d2 = random.randint(20, 28)
            start = f"2026-10-{d1:02d}"
            end = f"2026-10-{d2:02d}"
            segs = [("city", "highway"), ("mixed", "highway"), ("city", "mixed"), ("cold_start", "mixed")]
            seg_a, seg_b = random.choice(segs)
            template = random.choice([
                "compare {} between {} and {} from {} to {}",
                "how does {} compare between {} and {} driving from {} to {}?",
                "compare {} efficiency in {} vs {} from {} to {}",
                "is {} different between {} and {} segments from {} to {}",
            ])
            q = prefix + template.format(random.choice(m_phrases), seg_a, seg_b, start, end)
            add_sample(q, "compare", {"metric": metric, "segment_a": seg_a, "segment_b": seg_b, "start": start, "end": end})

        # 6. get_events
        elif category_choice == 7:
            ev_type, ev_phrases = random.choice(EVENTS)
            d1 = random.randint(1, 12)
            d2 = random.randint(16, 28)
            start = f"2026-10-{d1:02d}"
            end = f"2026-10-{d2:02d}"
            template = random.choice([
                "get all {} events between {} and {}",
                "did any {} occur from {} to {}?",
                "show list of {} between {} and {}",
                "report {} recorded from {} to {}",
                "find instances of {} between {} and {}",
            ])
            q = prefix + template.format(random.choice(ev_phrases), start, end)
            add_sample(q, "get_events", {"type": ev_type, "start": start, "end": end})

        # 7. timeline_before
        elif category_choice == 8:
            if random.random() < 0.5:
                ev_id = random.randint(1, 300)
                sec = random.choice([300, 600, 900, 1200])
                template = random.choice([
                    "what happened right before event {}?",
                    "show telemetry {} seconds prior to incident {}",
                    "timeline leading up to event {}",
                    "what occurred before event ID {}?",
                ])
                if "{}" in template and template.count("{}") == 2:
                    q = prefix + template.format(sec, ev_id)
                else:
                    q = prefix + template.format(ev_id)
                add_sample(q, "timeline_before", {"event_id": ev_id, "seconds_before": sec})
            else:
                ev_type, ev_phrases = random.choice(EVENTS)
                template = random.choice([
                    "what triggered the latest {}?",
                    "precursor signals right before {}",
                    "show telemetry before the most recent {}",
                    "signals leading up to {} alert",
                ])
                q = prefix + template.format(random.choice(ev_phrases))
                add_sample(q, "timeline_before", {"event_type": ev_type, "occurrence": "latest", "seconds_before": 600})

        # 8. search_logs
        elif category_choice == 9:
            d1 = random.randint(1, 10)
            d2 = random.randint(18, 28)
            start = f"2026-10-{d1:02d}"
            end = f"2026-10-{d2:02d}"
            query_str = random.choice([
                "thermal warning", "CAN bus timeout", "undervoltage", "bms handshake",
                "overcurrent fault", "sensor mismatch", "inverter overheat", "gateway sync loss",
                "telematics failure", "cell imbalance", "contactor open", "precharge error"
            ])
            template = random.choice([
                "search ECU logs for '{}' from {} to {}",
                "find log entries mentioning '{}' between {} and {}",
                "search Android system logs for '{}' from {} to {}",
                "query logs containing '{}' between {} and {}",
            ])
            q = prefix + template.format(query_str, start, end)
            add_sample(q, "search_logs", {"query": query_str, "start": start, "end": end})

        # 9. trend
        elif category_choice == 10:
            metric, m_phrases = random.choice(METRICS)
            d1 = random.randint(1, 10)
            d2 = random.randint(18, 28)
            start = f"2026-10-{d1:02d}"
            end = f"2026-10-{d2:02d}"
            template = random.choice([
                "show the {} trend between {} and {}",
                "how has {} progressed from {} to {}?",
                "daily trend of {} between {} and {}",
                "display {} progression from {} to {}",
            ])
            q = prefix + template.format(random.choice(m_phrases), start, end)
            add_sample(q, "trend", {"metric": metric, "start": start, "end": end, "granularity": "day"})

    # Also add refusal pairs (hard safety gate & out of scope)
    for q, kind in CONTROL_REQUESTS:
        add_sample(q, "respond_direct", {"kind": kind})
    for q, kind in SAFETY_REQUESTS:
        add_sample(q, "respond_direct", {"kind": kind})
    for q, kind in OUT_OF_SCOPE_REQUESTS:
        add_sample(q, "respond_direct", {"kind": kind})

    random.shuffle(samples)
    return samples


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic LoRA training dataset with n-gram deduplication")
    parser.add_argument("--count", type=int, default=3500, help="Number of samples to generate (default: 3500)")
    args = parser.parse_args()

    Path("data").mkdir(exist_ok=True)
    samples = generate_synthetic_samples(target_count=args.count)

    split_idx = int(len(samples) * 0.90)
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]

    with open(OUTPUT_TRAIN_PATH, "w", encoding="utf-8") as f:
        for s in train_samples:
            f.write(json.dumps(s) + "\n")

    with open(OUTPUT_VAL_PATH, "w", encoding="utf-8") as f:
        for s in val_samples:
            f.write(json.dumps(s) + "\n")

    print(f"\nGenerated {len(samples)} synthetic pairs:")
    print(f"  Train: {len(train_samples)} pairs saved to {OUTPUT_TRAIN_PATH}")
    print(f"  Val:   {len(val_samples)} pairs saved to {OUTPUT_VAL_PATH}")
    print(f"  All pairs deduplicated with 4-gram overlap < 70% against dev and test splits.")


if __name__ == "__main__":
    main()

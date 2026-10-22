# VehicleGPT — Product Requirements Document

**Product:** On-device natural-language vehicle information assistant (SLM-based)
**Context:** Tata Elxsi TELIPORT Season 4, Case Study 5
**Status:** Draft v1.0
**Owner:** Prashik Kadam

---

## 1. Summary

VehicleGPT is a fully offline assistant that runs inside the vehicle on constrained ARM hardware. It continuously ingests vehicle data (CAN/CAN-FD, SOME/IP, Android Vehicle HAL, QNX logs, ADAS events, camera event metadata, diagnostics) and lets drivers, service engineers, fleet operators and validation teams ask questions in plain language about current and historical vehicle behaviour, including trends, anomalies and likely causes.

The central design decision: **the language model does not analyse data. It translates questions into structured tool calls and verbalises evidence that deterministic analytics code has already computed.** This keeps the product accurate, fast and small enough for a ~2 GB / 2-core target.

## 2. Problem and need

Modern software-defined vehicles produce large volumes of signals, events and logs across many protocols. Today:

- Drivers see raw warnings with no explanation ("why has my range dropped?").
- Service engineers manually pull logs from multiple ECUs and correlate them by hand.
- Validation teams spend large effort on log triage after test drives.
- Existing in-car assistants focus on voice commands, infotainment and manual Q&A; many depend on the cloud for complex reasoning. Existing diagnostic LLM work is mostly technician-side or offline tooling, not an in-vehicle assistant over live and historical data.

**Gap addressed:** one on-device system that is multi-protocol, searchable over weeks, explains causes with checkable evidence, needs no cloud, and is isolated from safety-critical functions.

## 3. Goals and non-goals

### Goals
| ID | Goal |
|---|---|
| G1 | Answer natural-language questions about vehicle data with verifiable, evidence-backed responses |
| G2 | Run fully offline on ~2 GB RAM / 2 ARM cores |
| G3 | Respond to common queries in under 2 seconds |
| G4 | Retain historical data searchable for at least several weeks (target: 4 weeks events + digests, 90 days coarse) |
| G5 | Detect and explain trends and anomalies, not just retrieve rows |
| G6 | Keep safety-critical functions fully isolated from the AI domain |
| G7 | Scale from a 2 GB board to Raspberry Pi 5 to vehicle HPC without architecture changes |

### Non-goals
- Controlling any vehicle function (no actuation, no write path to any bus).
- General chit-chat, navigation, media, shopping, or open-domain Q&A.
- Replacing OEM diagnostic tools or making safety or warranty determinations.
- Continuous video storage or video understanding by the language model.
- Cloud features of any kind (telemetry upload, cloud fallback).

## 4. Users and use cases

| Persona | Needs | Example questions |
|---|---|---|
| Driver | Quick, plain-language answers while driving; minimal distraction | "Why has my range dropped over the last two weeks?" |
| Service engineer | Cause analysis, timelines, exportable evidence | "What happened before the battery overheating warning?" |
| Fleet operator | Comparisons and trends across trips/days | "Compare energy consumption between city and highway driving." |
| Validation engineer | Event search across ECUs and sources | "Show all ADAS disengagement events from yesterday." |

Reference queries (must all work for the demo): range reduction over two weeks; largest fuel-efficiency drop; ADAS disengagements yesterday; events before battery overheating warning; city vs highway energy comparison.

## 5. Scope of the system (context for model behaviour)

```
Sources -> Ingestion (read-only) -> Normalised store -> Insight engine -> Tools -> SLM -> UI
(CAN, SOME/IP, VHAL,   listen-only      (SQLite/Parquet   (change points,   (typed,    (planner +   (voice,
 QNX, ADAS, diag)      gateway           + text index)     anomalies,        read-only) verbaliser)  web, API)
                                                           attribution)
```

Layers:
1. **Simulation/data:** a custom physics-style vehicle simulator (see `simulator_spec.md`) plus replay of recorded candump-format logs over a virtual CAN bus, producing a synthetic 3-4 week history with labelled ground-truth events. CARLA is optional supporting data where a GPU is available.
2. **Ingestion:** protocol adapters normalise everything to `(ts, source, signal, value, unit)` plus an `events` table.
3. **Storage tiers:** hot in-memory ring buffer; warm raw (~48 h) and aggregates (1 s for 7 d, 1 min for 90 d); permanent events, DTCs and per-trip/per-day digests; text index for manuals, DTC descriptions and templated logs.
4. **Insight engine (no LLM):** change-point detection, anomaly scoring, contribution analysis, pre-event window extraction. Output is an **evidence packet**.
5. **SLM layer:** the subject of Section 6.

## 6. Model requirements and behaviour specification

### 6.1 Role of the model
The model has exactly three jobs:
1. **Plan:** map a user question to one or more tool calls (structured JSON).
2. **Verbalise:** turn the returned evidence packet into a short, plain-language answer.
3. **Clarify or decline:** ask one clarifying question when needed, or refuse out-of-scope requests.

The model must not: compute statistics, write SQL, read raw signal data directly, invent causes, or take any action on the vehicle.

### 6.2 Model selection and constraints
| Item | Requirement |
|---|---|
| Size class | 0.5B-1.5B parameters for the 2 GB target; 1.5B-3B on Pi 5 class; 7B+ on HPC/NPU |
| Reference candidate | Qwen2.5-1.5B-Instruct, Q4_K_M quantisation (~1 GB); alternatives Gemma 3 1B, Llama 3.2 1B |
| Adaptation | LoRA fine-tune on synthetic question -> tool-call pairs (target 3,000-5,000 examples, including paraphrases, typos, follow-ups and negative/out-of-scope cases) |
| Runtime | llama.cpp, mmap loading, 2 threads, cached system-prompt prefix, grammar-constrained decoding |
| Context budget | Prompt <= ~300 tokens on the fast path (system prefix cached) |
| Output budget | Tool call <= ~40 tokens; spoken/short answer <= ~60 tokens; detailed view on request |
| Peak memory | Model + KV cache + embedder within the RAM budget in Section 7 |

All sizes and speeds are planning targets and must be confirmed by benchmark on the target boards.

### 6.3 Request pipeline
1. **Speech/text in.** Optional ASR (whisper.cpp tiny or equivalent).
2. **Deterministic pre-processing.** Resolve relative time ("yesterday", "last two weeks", "since Tuesday") with a date parser, not the model. Normalise units and signal aliases via a synonym table.
3. **Fast-path router.** Cache/lookup for frequent questions (semantic cache); skips model generation when a validated cached plan exists.
4. **Planner (SLM).** Emits JSON tool call(s) constrained by a grammar so output is always schema-valid.
5. **Tool execution.** Read-only, parameterised queries against the store and insight engine. Returns an evidence packet.
6. **Verbaliser (SLM).** Produces the answer using only the packet. Template fallback for routine query types.
7. **Verifier.** Every number, date, signal name and event ID in the answer is checked against the packet. On mismatch, the system falls back to the template answer.
8. **Presentation.** Short answer + mini chart + evidence references + confidence tag.

### 6.4 Tool interface (the model's only action space)
| Tool | Purpose | Key parameters |
|---|---|---|
| `get_events` | List events (ADAS disengagement, warnings, DTCs, hard braking, etc.) | `type`, `start`, `end`, `source`, `limit` |
| `trend` | Metric over time with change summary | `metric`, `start`, `end`, `granularity` |
| `compare` | Compare a metric between two segments | `metric`, `segment_a`, `segment_b`, `start`, `end` |
| `largest_change` | Find the largest drop/rise and when it began | `metric`, `start`, `end`, `direction` |
| `explain_change` | Contribution analysis for a metric change | `metric`, `window_a`, `window_b` |
| `timeline_before` | Signals/events preceding an event | `event_id` or `event_type`, `seconds_before` |
| `search_logs` | Text search over templated logs | `query`, `start`, `end`, `source` |
| `lookup_dtc` | DTC description and related known causes | `code` |
| `current_state` | Latest value of a signal | `signal` |
| `respond_direct` | No data tool needed: out-of-scope, control request, safety judgement, or one clarifying question; runtime renders a fixed template | `kind`, `clarify_field` |

Example plan output:
```json
{"tool":"explain_change","args":{"metric":"range_per_charge","window_a":"2026-10-01/2026-10-07","window_b":"2026-10-15/2026-10-21"}}
```

### 6.5 Evidence packet contract
Every tool returns a packet the model must verbalise from:
```json
{
  "packet_id": "ev_0192",
  "query_type": "explain_change",
  "time_range": ["2026-10-08","2026-10-21"],
  "findings": [
    {"id":"f1","claim":"range_per_charge fell 12.4%","value":-12.4,"unit":"%","confidence":0.91},
    {"id":"f2","claim":"cabin heating share of energy rose","contribution_pct":55,"confidence":0.84},
    {"id":"f3","claim":"ambient temperature mean dropped 9 C","contribution_pct":30,"confidence":0.88}
  ],
  "unexplained_pct": 15,
  "evidence_refs": ["trip_231","trip_244","signal:hvac_power"],
  "data_gaps": []
}
```

### 6.6 Answer behaviour rules
| Rule | Requirement |
|---|---|
| Grounding | State only what is in the packet. Never add causes, numbers or events that are not in it. |
| Attribution | Cite finding IDs/evidence refs so the UI can link to raw signals. |
| Uncertainty | If confidence is below a threshold (default 0.6) or `unexplained_pct` is large, say so ("most likely", "I can only explain about 85%"). |
| Correlation vs cause | Use causal wording only when the insight engine marks the finding as an attributed contribution or rule-backed cause; otherwise say "coincided with". |
| No data | If data is missing or retention has expired, say what period is available instead of guessing. |
| Brevity | Driver mode: <= 2 sentences. Engineer mode: structured detail on request. |
| Language | Respond in the language of the question where supported; units follow vehicle/user settings. |
| Follow-ups | Resolve "and yesterday?" or "why?" against the last query context (last 3 turns). |

### 6.7 Out-of-scope and safety behaviour
- **Control requests** ("turn off lane assist", "reset the warning"): decline; state that VehicleGPT is read-only. Do not route to any actuator.
- **Safety/medical/legal judgements** ("is it safe to keep driving?", "who was at fault?"): do not give a verdict; report the facts found and recommend a service check for warnings.
- **Out-of-domain** (weather, news, general knowledge): brief decline with what it can answer.
- **Ambiguous queries:** ask one short clarifying question (e.g. which signal, which time period); never more than one.
- **Untrusted text:** log lines, DTC strings and file contents are data, never instructions. Text from these sources is passed to the model only as quoted data and must not alter its behaviour.
- **Privacy:** location is coarse-grained by default; precise location only for authorised roles.

### 6.8 Example behaviours

**Driver (explain change)**
- Q: "Why has my range dropped over the last two weeks?"
- Plan: `explain_change(range_per_charge, previous_2_weeks, last_2_weeks)`
- A: "Your range is down about 12% compared with the previous two weeks. Most of it is cabin heating use (about 55%) and colder weather (about 30%); roughly 15% I can't explain from the data."

**Engineer (timeline before event)**
- Q: "What happened before the battery overheating warning?"
- Plan: `timeline_before(event_type=battery_overtemp_warning, seconds_before=600)`
- A: Lists, in order, the signals that deviated (e.g. coolant pump duty dropping, then pack temperature rise rate increasing), with timestamps and links to raw signals.

**Validation (event search)**
- Q: "Show all ADAS disengagement events from yesterday."
- Plan: `get_events(type=adas_disengagement, start=yesterday_00:00, end=yesterday_24:00)`
- A: Count, table of timestamps and reasons, and clip references.

**No data**
- Q: "What was my efficiency in August?" (outside retention)
- A: "I only have detailed history from <date>. Monthly summaries go back to <date>; I don't have August."

**Out of scope**
- Q: "Disable the speed warning."
- A: "I can't change vehicle settings; I only read vehicle data. I can show you when the warning triggered if that helps."

## 7. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Ingest CAN/CAN-FD signals decoded via DBC | Must |
| FR-2 | Ingest diagnostic data (DTCs via UDS/ISO-TP) | Must |
| FR-3 | Ingest ADAS events and camera-derived event metadata with clip pointers | Must |
| FR-4 | Ingest SOME/IP service data | Should |
| FR-5 | Ingest Android Vehicle HAL properties (Cuttlefish/emulated) | Should |
| FR-6 | Ingest QNX/system logs with templating | Should |
| FR-7 | Normalise all sources to a common schema with source tagging | Must |
| FR-8 | Tiered retention with automatic downsampling and quota enforcement | Must |
| FR-9 | Per-trip and per-day digests computed incrementally | Must |
| FR-10 | Insight engine: change-point, anomaly, contribution analysis, pre-event window | Must |
| FR-11 | NL planner with schema-valid tool calls | Must |
| FR-12 | Evidence-grounded verbaliser with numeric verifier | Must |
| FR-13 | Chart/evidence view linking answers to raw signals | Should |
| FR-14 | Voice input/output | Could |
| FR-15 | Proactive insights ("range down 12% since Oct 8") | Could |
| FR-16 | Role-based access (driver / engineer / fleet) | Should |
| FR-17 | Signed, local export of evidence for engineers | Could |

## 8. Non-functional requirements

| Category | Requirement |
|---|---|
| Latency | Common queries (fast path) answered in < 2 s end to end inside the capped reference container (2 GB, 2 CPUs); p50 and p95 reported. Laptop cores are faster than automotive-class ARM cores, so results are labelled as laptop-capped measurements and any projection to slower hardware is labelled as a projection |
| Memory | Entire stack within ~2 GB on the minimum tier (budget to be validated: OS/services, model, KV cache, DB, embedder) |
| CPU | Runs on 2 ARM cores; ingestion and insight engine must stay light so the model can use the cores during queries |
| Storage | Retention budget configurable; sizing estimated at ~70 MB/day raw for 200 signals at 1 Hz, reduced by compression and tiering |
| Accuracy | Tool-call exact match >= 90%; numeric answers 100% consistent with packets (enforced by verifier); event retrieval recall >= 95% on the labelled set (targets) |
| Availability | No dependency on network; degrades gracefully if a source is absent |
| Privacy/security | Local-only processing, default-deny network egress, encryption at rest, read-only DB access for the AI domain, coarse location by default |
| Safety | AI domain isolated (separate VM/container); listen-only bus access via one-way gateway; no write path to any vehicle bus; consistent with freedom-from-interference principles |
| Portability | Same architecture on Pi 4/5, ARM VM (QEMU, Cuttlefish, Graviton) and vehicle HPC; only model file and quantisation change |

Note: AI HAT accelerators generally do not accelerate LLM token generation in llama.cpp; do not rely on them for the language model. They may be used for vision/ADAS inference.

## 9. Scalability tiers

| Tier | Hardware | Model class | Notes |
|---|---|---|---|
| Minimum | 2 GB ARM board (Pi 4 class) | ≤1B, Q4 | Template-heavy answers, tighter retention |
| Reference | Pi 5 (8 GB) or ARM VM | 1.5-3B, Q4 | Full demo configuration |
| Production | Vehicle HPC with NPU | 7B+ | Richer explanations, longer context, larger history |

## 10. Evaluation plan

**Dataset:** synthetic 3-4 week history with injected, labelled events (cold-weather/HVAC range loss, battery overheating with a coolant-pump precursor, ADAS disengagements, efficiency regression after a "software update"), plus a benchmark set of ~100 questions with expected tool calls and expected facts, including paraphrases, typos, follow-ups, no-data and out-of-scope cases.

| Metric | Method |
|---|---|
| Intent/tool-call accuracy | Exact match of tool and arguments against expected |
| Answer correctness | Numeric/entity match to ground truth; human review of a sample |
| Cause attribution quality | Does the answer name the injected cause; false-cause rate |
| Hallucination rate | Verifier mismatches before fallback; manual audit |
| Latency | p50/p95 over fast and slow paths in the capped container; plus one real-ARM run (e.g. Graviton) if available |
| Resource use | Peak RAM, CPU, storage per day, model load time |
| Safety checks | Control-request and prompt-injection test set (all must be refused/ignored) |

## 11. Success criteria (hackathon demo)
1. All five reference queries answered correctly from the simulated vehicle.
2. A benchmark table showing accuracy, latency and memory in the 2 GB / 2 CPU container, clearly labelled as laptop measurements (plus an ARM run if obtained).
3. Live demonstration of a causal explanation backed by clickable evidence.
4. Demonstration that a control request and a prompt-injected log line are both rejected.
5. Architecture walkthrough showing isolation from safety-critical systems.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| SLM hallucinates causes | Packet-only verbalisation, numeric verifier, causal wording gated by the insight engine |
| Latency above 2 s on 2 cores | Short prompts and outputs, cached prefix, templates for routine queries, semantic cache, smaller model tier |
| Wrong tool selection by a small model | LoRA fine-tune, grammar-constrained output, clarifying question on low confidence |
| Memory pressure on 2 GB | Quantised model, mmap, lightweight DB, tiered retention, smaller model tier |
| Synthetic data not representative | Replay recorded/public driving data alongside CARLA; document limits honestly |
| Prompt injection through logs | Treat log text as quoted data, no tool access from log content, tool allow-list |
| Privacy exposure | Role-based access, coarse location, encryption, no egress |

## 13. Milestones
1. Schema, virtual CAN, scenario injector and labelled dataset.
2. Insight engine answering the five reference queries without the LLM.
3. SLM planner and verbaliser with verifier.
4. Benchmarks in the capped container and tuning to the latency/memory budget; optional real-ARM run.
5. UI, optional voice, and SOME/IP / VHAL / QNX adapters.

## 14. Open questions
- Resolved: no embedded hardware is available; the demonstration runs on a Windows laptop (WSL2 + Docker) with resource caps. Is a one-off ARM cloud instance worth using for a final benchmark?
- Which signal set and DBC will the simulation expose?
- Is voice input expected in the demo, or is text sufficient?
- Language support beyond English required?
- Retention targets: confirm "several weeks" as 4 weeks of detailed digests.

## 15. Development and demonstration environment

The project is developed and demonstrated entirely on a Windows laptop without embedded hardware, while remaining deployable to real targets.

| Aspect | Decision |
|---|---|
| Host setup | WSL2 (Ubuntu) + Docker Desktop (WSL2 backend); repository kept on the WSL filesystem |
| Budget enforcement | Docker `--memory=2g --cpus=2`; peak memory read from container cgroup stats |
| Portability | Images built for `linux/amd64` and `linux/arm64`; no x86-only dependencies |
| CAN bus | python-can behind one interface: `virtual` (single process) or `udp_multicast` (multi-process); real SocketCAN `can0` selectable by config; candump log replay supported |
| Simulation | Custom simulator (`simulator_spec.md`); CARLA optional |
| Model training | No local fine-tuning; start with grammar-constrained decoding, few-shot prompts and deterministic routing; fine-tune on a free external GPU only if benchmarks require it |
| Result reporting | All benchmark results labelled "laptop, 2 GB / 2 CPU container"; projections to slower ARM cores labelled as projections |

### Implementation status claims
| Source | Status to claim |
|---|---|
| CAN/CAN-FD, DTC/diagnostics, ADAS events, logs | Implemented end to end on simulated and replayed data |
| SOME/IP, Android VHAL, QNX logs | Adapter interface implemented and tested on recorded fixtures; not validated on real stacks |
| Camera | Event metadata and clip pointers only; no video processing |

### Path to production
1. Point adapters at real buses/services (config change for CAN; real stack integration for SOME/IP, VHAL, QNX).
2. Select the model tier for the target hardware (Section 9) and re-benchmark on it.
3. Add the hypervisor/gateway isolation and security hardening described in Section 8.
4. Perform functional-safety and cybersecurity assessment as a separate phase before any production use.

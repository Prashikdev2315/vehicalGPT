\Script Your Future

THINK. BUILD. CREATE. WIN

CASE STUDY 5


## Natural Language Vehicle Information using On-Device SLM/LLM (VehicleGPT)

## Background

Modern Software Defined Vehicles (SDVs) generate vast amounts of real-time data from sensors, ECUs, ADAS systems, infotainment, powertrain, body electronics, and cloud services. One scenario is to have a local SLM/LLM inside the vehicle which has access to various data and based on user or service engineer queries can provide the relevant data. Examples:

- "Why has my driving range reduced over the last two weeks?"

- "When did fuel efficiency show the largest drop?"

- "Show all ADAS disengagement events from yesterday."

- "What happened before the battery overheating warning?"

- "Compare energy consumption between city and highway driving."

## Challenge

Design a practical AI-on-Edge solution that runs a Small Language Model (SLM) or Large Language Model (LLM) directly inside the vehicle and continuously consumes vehicle data streams, events, and logs, making them searchable through natural language queries.

The system should act as an intelligent vehicle assistant capable of understanding user questions, retrieving relevant vehicle information, identifying trends and anomalies, and presenting understandable explanations without requiring cloud connectivity.

## Key points your solution should address:

- How will the different driving scenarios and error conditions sequences be recreated e.g. Carla or other vehicle driving simulation or simulated/recorded data

- Vehicle Data Collection

- How will the system collect and store vehicle information from: CAN / CAN-FD, SOME/IP services, Android Vehicle HAL, QNX Services/logs, ADAS, Camera feeds, and diagnostic logs

- How will real-time and historical data be retained for analysis?

## Constraints

- The solution must operate without cloud dependency.

- The model must be designed such that it can run on embedded hardware with limited resources (~2 GB RAM,~ 2 ARM A5X Cores). Automotive grade arm boards, raspberry pi 4/5 with AI HAT, ARM virtualized environment like cuttlefish, qemu, Amazon AWS Graviton or equivalent could be used to demonstrate

- Architecture should be such as to achieve response time under 2 seconds for common queries.

- Historical vehicle data should be searchable for at least several weeks.

- Vehicle safety-critical functions must remain isolated from the AI system.


## Expected Output:

Provide a high-level system architecture and key components (hardware + software) required for this solution. Include engineering justification, reasoning for AI model, OS, architecture choices, and communication protocols.

- High-level system architecture

- Vehicle data collection strategy

- SLM/LLM selection rationale

- Search and retrieval workflow

- Historical data storage approach

- Edge deployment architecture

- User interaction design

## Evaluation Criteria:

- System Architecture: Completeness of hardware and software components along with logical integration of simulation and interface to user.

- AI Capability

- \- Ability to understand natural language vehicle queries.

- \- Accuracy of responses and summaries.

- Data Integration

- \- Support for multiple automotive protocols and data sources.

- Search & Analytics

- \- Ability to find historical events, trends, and anomalies.

- \- Ability to explain causes behind observed vehicle behavior.

- Edge Performance

- \- Memory footprint.

- \- Query latency.

- \- Scalability from Reference board/Raspberry Pi/Virtual Machine to vehicle HPC.

- Privacy & Security

- \- Local-only processing.

- \- Protection of vehicle and driver data.

- Innovation & Practicality

- \- Ease of deployment in production SDVs.

- \- Value for drivers, service engineers, fleet operators, and validation teams.

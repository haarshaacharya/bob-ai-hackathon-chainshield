# Presentation Outline (3-Minute Video Script)

## Slide 1: Problem Hook (0:00–0:10)

**Visual:** Active disruption appears on the map. Multiple shipments turn red. Show a sample shipment with $520,000 cargo value.

**Narration:** A single port disruption can cascade across hundreds of shipments. Meanwhile, idle assets sit unused and cold-chain damage may remain invisible until delivery.

---

## Slide 2: Problem Empathy (0:10–0:20)

**Visual:** Split screen showing blocked shipment route, idle truck, and sensor line approaching excursion threshold.

**Narration:** Operations teams need to answer three questions immediately: What is affected? What should move instead? And is any temperature-sensitive cargo already at risk?

---

## Slide 3: Solution Reveal (0:20–0:35)

**Visual:** ChainShield dashboard appears. Operator activates the disruption scenario.

**Narration:** ChainShield converts disruption signals and sensor logs into an explainable action plan in under 60 seconds.

---

## Slide 4: Impact Detection (0:35–0:55)

**Visual:** Impact list sorted by risk showing:
- Affected shipments: 42
- Cargo value at risk: $8.7M
- SLA breaches predicted: 11
- Cold-chain shipments at risk: 4

**Narration:** The impact engine uses route overlap and time-window analysis to identify exactly which shipments are affected and why. Every affected shipment includes a reason code: PORT_NODE_BLOCKED, ETA_SLA_BREACH, or TEMPERATURE_EXPOSURE_INCREASED.

---

## Slide 5: Rerouting Alternatives (0:55–1:15)

**Visual:** Shipment detail view with three ranked alternatives:
- Current route: +17.2 hours
- Recommended route (Carrier B): +5.4 hours, $1,800 additional cost, no temperature increase
- Alternative route (Carrier C): +12 hours, $800 additional cost, higher temperature exposure

**Narration:** The system rejects infeasible routes and ranks alternatives using time, cost, capacity, carrier availability, and cold-chain risk. Every alternative is constrained by hard requirements: delivery deadline, reefer capability, and carrier equipment compatibility.

---

## Slide 6: Carrier Alternatives (1:15–1:30)

**Visual:** Carrier comparison panel showing:
- Carrier A: unavailable
- Carrier B: reefer capacity available
- Carrier C: delivery deadline breached

**Narration:** Carrier recommendations are constrained by equipment compatibility and available capacity, not generated as unsupported text. The system checks real carrier availability and equipment before recommending.

---

## Slide 7: Idle Asset Redeployment (1:30–1:45)

**Visual:** Idle asset panel showing:
- TRUCK-17
- 42 km away
- Reefer capable
- Available in 25 minutes
- Compatible with SHP-0042

**Narration:** ChainShield finds idle compatible assets that can be redeployed to protect high-priority shipments. Asset matching is constrained by mode, reefer capability, capacity, and availability time.

---

## Slide 8: Cold-Chain Detection (1:45–2:05)

**Visual:** Sensor graph with policy threshold band (green) and excursion spike (red):
- Policy range: 2°C to 8°C
- Observed maximum: 10.4°C
- Duration out of range: 18 minutes
- Status: EXCURSION_REVIEW

**Narration:** The cold-chain engine detects the excursion before delivery, identifies the policy breach, and records the evidence for review. The system uses configurable policy profiles, not hardcoded thresholds, so it adapts to different products and jurisdictions.

---

## Slide 9: Explainability and Evidence (2:05–2:25)

**Visual:** "Why this recommendation?" drawer showing evidence:
- Affected because: PORT_NODE_BLOCKED, ETA_SLA_BREACH
- Recommended because: REEFER_CAPACITY_AVAILABLE, COST_OPTIMIZED, DEADLINE_MET
- Confidence: 0.94

**Narration:** The language model does not make the operational decision. It explains deterministic results, cites the evidence, and exposes uncertainty. Every recommendation includes reason codes and source data so operators can audit and trust the decision.

---

## Slide 10: Technical Architecture (2:25–2:40)

**Visual:** Architecture diagram showing:
- Frontend (React + TypeScript)
- Backend (FastAPI)
- Impact Engine (NetworkX + GeoPandas)
- Optimization Engine (OR-Tools)
- Cold Chain Engine (Pydantic + DuckDB)
- Explanation Layer (Granite via watsonx.ai)
- Local Store (DuckDB + Parquet)

**Narration:** The system combines FastAPI, DuckDB, graph analysis, OR-Tools optimization, configurable cold-chain policies, and optional Granite explanations through watsonx.ai. All core logic runs locally with cached data; external APIs are optional and have timeouts and fallbacks.

---

## Slide 11: IBM Bob IDE Integration (2:40–2:52)

**Visual:** IBM Bob IDE showing task history, code review, generated tests, and repository `bob_sessions` folder with exported reports and consumption screenshots.

**Narration:** IBM Bob IDE was used as the core development partner for architecture, implementation, testing, documentation, and code review. Every relevant task is exported to the `bob_sessions` folder for judging. Bob ensured that the solution is auditable, well-tested, and aligned with best practices.

---

## Slide 12: Impact and Metrics (2:52–3:00)

**Visual:** KPI summary:
- Decision time: under 60 seconds
- Route constraint violations: 0%
- Excursion detection recall: 98%+
- Offline demo: available
- Cargo value at risk identified: $8.7M

**Narration:** ChainShield turns disruption data into evidence-backed action before cargo, capacity, and customer commitments are lost. The system is designed to be reliable, auditable, and resilient to live-demo failure.

---

## Video Production Notes

- **Tone:** Professional, operations-focused. Avoid generic AI hype language.
- **Pacing:** 3 minutes total. Each slide gets 15–20 seconds.
- **Evidence:** Show actual UI, actual data, actual reason codes. No mockups or placeholder text.
- **Bob proof:** Include a 5–10 second clip of Bob IDE showing task history and code review.
- **Offline:** Demonstrate that the demo works without network access or watsonx.ai credentials.

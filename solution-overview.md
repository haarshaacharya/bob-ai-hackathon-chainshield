# Solution Overview

## Core Mechanism

ChainShield operates as a **crisis-response command center**, not a dashboard. When a disruption is activated, the system executes a deterministic pipeline:

1. **Disruption registration:** Operator selects a disruption type (port closure, weather event, strike) and activates it on the map.
2. **Impact propagation:** The system builds a shipment route graph and identifies all edges and nodes affected by the disruption geometry and time window.
3. **Shipment matching:** For each shipment, the system checks whether its planned route intersects the disruption and whether the disruption timing overlaps the shipment's transit window.
4. **Risk quantification:** Affected shipments are scored by cargo value, ETA delay, temperature exposure, and deadline proximity.
5. **Alternative generation:** The system generates feasible route and carrier alternatives using constrained optimization (capacity, deadline, reefer capability, carrier availability).
6. **Asset matching:** Idle compatible assets are identified and ranked by repositioning distance and utilization potential.
7. **Cold-chain evaluation:** Sensor logs are evaluated against configured policy profiles; excursions are detected and classified.
8. **Action plan generation:** A ranked action plan is created with evidence links, reason codes, and confidence indicators.
9. **Explanation:** A language model explains the deterministic results in human-readable form.

**Key design principle:** Every operational decision (affected shipment, route feasibility, cold-chain classification) is made by deterministic logic. The language model explains results, not creates them.

## What Makes It Different From a Naive/Manual Approach

| Aspect | Manual Approach | ChainShield |
|--------|-----------------|-------------|
| **Decision time** | 30–90 minutes | Under 60 seconds |
| **Affected shipment identification** | Manual search by route name or carrier | Automatic graph-based overlap detection |
| **Route alternatives** | Operator calls carriers and checks maps | Constrained optimization with hard-constraint validation |
| **Carrier fallback** | Trial-and-error phone calls | Ranked by capacity, deadline, equipment compatibility |
| **Asset redeployment** | Manual inventory review | Automatic matching by location, capability, availability |
| **Cold-chain risk** | Reactive alerts after excursion | Proactive detection before delivery with policy classification |
| **Auditability** | Handwritten notes or email threads | Structured evidence records with reason codes and source data |
| **Explainability** | "We think this is best" | "This is affected because [reason code]. We recommend [alternative] because [evidence]." |

## Key Design Decisions and Why

### 1. Deterministic Core, Optional AI Explanation

**Decision:** Disruption impact, route feasibility, and cold-chain classification are calculated using deterministic rules and optimization. Language models are used only for explanation.

**Why:** Operational decisions in supply-chain crises must be auditable and defensible. An LLM-generated route recommendation or cold-chain classification cannot be justified to regulators or customers. Deterministic logic is verifiable; AI explanation is transparent.

### 2. Configurable Cold-Chain Policies, Not Hardcoded Thresholds

**Decision:** Temperature thresholds, excursion duration limits, and severity classifications are loaded from policy profiles, not hardcoded.

**Why:** Different products (vaccines, biologics, food, chemicals) have different regulatory requirements and manufacturer stability windows. A single hardcoded threshold is incorrect for most use cases. Configurable policies allow the system to adapt to different jurisdictions and products without code changes.

### 3. Offline-First Architecture

**Decision:** All core logic runs locally with cached data. External APIs (watsonx.ai, Cloudant, routing services) are optional and have timeouts and fallbacks.

**Why:** Live demos are fragile. Network failures, API rate limits, and cloud service outages are common. An offline-capable system is more reliable and demonstrates technical depth. Judges can see the core logic working even if external services fail.

### 4. Graph-Based Impact Propagation

**Decision:** Disruptions are represented as geometric zones and time windows. Shipment routes are represented as graphs. Impact is calculated by checking edge/node intersection and time overlap.

**Why:** This approach is deterministic, scalable, and explainable. A judge can see exactly which route segments are blocked and which shipments are affected. It avoids fuzzy heuristics like "nearby shipments might be affected."

### 5. OR-Tools for Optimization, Not Heuristics

**Decision:** Route alternatives and asset matching use Google OR-Tools constraint satisfaction and vehicle-routing solvers.

**Why:** OR-Tools handles complex constraints (capacity, time windows, resource compatibility, deadline) correctly. Heuristic approaches often violate constraints or miss feasible solutions. OR-Tools is also open-source and auditable.

### 6. Evidence-Linked Recommendations

**Decision:** Every recommendation includes reason codes, source data, and confidence indicators.

**Why:** Operators need to understand why a recommendation was made and whether they should trust it. Evidence links also support regulatory audits and post-incident reviews.

## User Experience

### Crisis Overview Screen

Operator opens the control tower and sees:
- Active disruptions (map overlay).
- Shipments affected (count, cargo value at risk).
- Idle compatible assets (count, utilization potential).
- Open cold-chain incidents (count, severity).

### Disruption Activation

Operator selects a disruption scenario (port closure, weather event, strike) and activates it. The system immediately calculates impact.

### Impact Map

The map highlights:
- Disruption zone (red overlay).
- Affected shipment routes (red lines).
- Unaffected shipment routes (green lines).
- Alternative route previews (blue dashed lines).

### Shipment Detail

Operator opens a shipment and sees:
- Disruption cause and affected route segment.
- ETA impact (hours delayed).
- Cargo value and product class.
- Temperature risk (if cold-chain).
- Ranked alternatives (route, carrier, cost, delay, risk).

### Action Center

Operator reviews ranked recommendations:
1. **Rerouting option 1:** Carrier B, +5.4 hours, $1,800 additional cost, no temperature increase.
2. **Rerouting option 2:** Carrier C, +12 hours, $800 additional cost, higher temperature exposure.
3. **Carrier alternative:** Carrier A unavailable; Carrier B has reefer capacity.
4. **Idle asset:** Truck TRUCK-17, 42 km away, available in 25 minutes, compatible.

### Cold-Chain Monitor

Operator opens the cold-chain panel and sees:
- Sensor timeline with policy range (green band).
- Excursion event (red spike).
- Duration out of range (18 minutes).
- Policy classification (EXCURSION_REVIEW).
- Recommended action (isolate pending review).

### Evidence Drawer

Operator clicks "Why this recommendation?" and sees:
- Affected because: PORT_NODE_BLOCKED, ETA_SLA_BREACH.
- Recommended because: REEFER_CAPACITY_AVAILABLE, COST_OPTIMIZED, DEADLINE_MET.
- Confidence: 0.94 (based on data completeness and constraint satisfaction).

### Export

Operator exports the action plan as JSON or Markdown for audit trail and stakeholder communication.

# Two-Minute Pitch Script: Foresight-AI

**Project:** Foresight-AI — Industrial Operations Copilot & Deterministic Future Arena  
**Hackathon:** Berkeley x DeepMind Hackathon (Online Track)  
**Presenter:** System Lead / Principal AI Engineer  
**Target Duration:** Exactly 120 seconds (~280–300 words spoken at measured executive pace)  
**Accompanying Visuals:** Mission Control UI (`apps/web`), Future Arena, Safety Challenge, Decision Receipts  

---

## Pitch Cue Card & Spoken Script

```
[00:00 - 00:25] THE HOOK & THE INDUSTRIAL HALLUCINATION TRAP
Screen: Mission Control UI showing 15 kW TEFC Motor Telemetry with rising thermal curve.
```

**Spoken:**  
"Unplanned industrial downtime costs manufacturing and power utilities over fifty billion dollars every year. When a critical induction motor fails, downtime averages twenty-two thousand dollars a minute.

Today, plant operators are told generative AI will fix this. But standard LLMs pose an immediate safety risk in heavy industry: they hallucinate sensor baselines, have no sense of physical laws, and suggest interventions without simulating their second-order consequences."

---

```
[00:25 - 00:55] THE SOLUTION: FORESIGHT-AI & GEMINI 3.8 FLASH
Screen: Transition to Gemini Copilot tool trace & Architecture Diagram.
```

**Spoken:**  
"This is **Foresight-AI**. We built an industrial operations copilot powered by **Google Gemini 3.8 Flash** using the official Google Gen AI SDK.

Gemini doesn't guess. It interacts through six strictly-typed deterministic tools—extracting frozen telemetry, calibrated failure risks, and anomaly scores. 

Crucially, Gemini never touches physical hardware directly. Instead, it hands candidate interventions to our deterministic physics engine for counterfactual branching."

---

```
[00:55 - 01:25] THE FUTURE ARENA & ADVERSARIAL SAFETY CHALLENGE
Screen: Click into `/arena` showing 3-way simulation, then `/safety-challenge`.
```

**Spoken:**  
"Here is our **Future Arena**. Using Common Random Numbers, we clone the motor's physics twin across three futures: continue operating, reduce load, and planned maintenance. 

Under cooling failure, derating the motor actually collapses fan airflow and accelerates thermal burnout. The Arena exposes this counter-intuitive physics before equipment is damaged.

What happens if an agent submits a dangerous action? In our **Safety Challenge**, we test an adversarial attack—derating an overheating motor. 

Our independent **Verifier v5** gate re-simulates the proposal with thirty-two fresh Monte Carlo seeds. In twelve milliseconds, it blocks the action, cites the violated ISO vibration and thermal limits, and locks the physical actuators."

---

```
[01:25 - 01:50] CRYPTOGRAPHIC DECISION RECEIPTS & VERIFICATION
Screen: Click into `/receipts` showing canonical SHA-256 digest and green verification checkmark.
```

**Spoken:**  
"Once an operator approves a verified maintenance plan, Foresight generates a tamper-evident **Decision Receipt**. 

Every input snapshot, model version, simulated trajectory, and safety check is sealed with a canonical SHA-256 digest. If any parameter is altered, integrity verification immediately fails."

---

```
[01:50 - 02:00] THE CALL TO ACTION & CLOSE
Screen: Split screen of Mission Control and 130 passing tests.
```

**Spoken:**  
"One hundred and thirty automated tests verify our physics, Gemini tool contracts, and safety gates. 

Foresight-AI: Grounded in physics. Powered by Gemini. Verified by math. 

Thank you."

---

## Speaker Stage Directions & Demo Execution Checklist

| Timestamp | Visual Cue | Key Action | Backup / Fail-Safe Note |
|:---|:---|:---|:---|
| **00:00** | Mission Control (`http://localhost:3000`) | Point out rising stator temp (138 °C) and CUSUM risk alert. | Pre-warmed session running on branch `feat/berkeley-hackathon-gemini-arena`. |
| **00:30** | Copilot Terminal (`/agent`) | Show structured tool calls (`predict_failure_risk`, `compare_futures`). | Real-time SSE token stream. |
| **01:00** | Future Arena (`/arena`) | Click **Run Future Arena (3-Way)**. Point out green maintenance curve vs red burnout curve. | Simulation runs in ~3s locally. |
| **01:20** | Safety Challenge (`/safety-challenge`) | Select **Bearing Derate Trap** and click **Launch Adversarial Challenge**. | Verifier v5 rejects with red banner in <20ms. |
| **01:40** | Decision Receipts (`/receipts`) | Click **Verify Digest**. Show green badge `INTEGRITY VERIFIED`. | Cryptographic SHA-256 verification against API. |
| **01:55** | Terminal Summary | Display 130 passing tests. | Pytest green suite. |

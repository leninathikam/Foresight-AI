# One-Minute Playcast Script: Foresight-AI

**Project:** Foresight-AI — Industrial Operations Copilot & Deterministic Future Arena  
**Hackathon Track:** Berkeley x DeepMind Hackathon Online Track  
**Format:** 60-Second Video Playcast / Screen Recording  
**Target Duration:** Exactly 60 seconds (~140 words)  
**URL:** `http://localhost:3000` (Apps/Web Next.js UI)  

---

## Storyboard & Script Breakdown

```
[00:00 - 00:10] MISSION CONTROL — LIVE TELEMETRY & PREDICTED RISK
Visual: Screen recording starts on `/` (Mission Control). 
Mouse hovers over stator temperature gauge (138 °C, pulsing amber) and 60-minute failure risk card (88.4%).
```
**Spoken (Voiceover):**  
"In critical industrial operations, you can't afford AI that hallucinates. Here, our digital twin of a fifteen-kilowatt motor is overheating from cooling degradation."

---

```
[00:10 - 00:25] THE FUTURE ARENA — 3-WAY COUNTERFACTUAL BRANCHING
Visual: Click `/arena` in the top navbar. 
Click the primary button: "Run Future Arena (3-Way Comparison)".
Loading spinner resolves in 2 seconds to reveal 3 simultaneous trajectory charts.
```
**Spoken (Voiceover):**  
"Welcome to the **Future Arena**. We simulate three futures under identical stochastic conditions: continue operating, reduce load, and planned maintenance. Notice: derating speed actually accelerates thermal burnout. Planned maintenance is the only provably safe path."

---

```
[00:25 - 00:43] SAFETY CHALLENGE — ADVERSARIAL ATTACK BLOCKED
Visual: Click `/safety-challenge` in the navbar.
Click "Bearing Derate Trap", then click "Launch Adversarial Challenge".
Red alert banner immediately slides in: "VERIFIER REJECTED INTERVENTION" citing ISO 10816-3 vibration limits.
```
**Spoken (Voiceover):**  
"What if an agent proposes an unsafe action? In our **Safety Challenge**, we inject an adversarial command. Our independent **Verifier v5** gate re-simulates with fresh Monte Carlo seeds and instantly blocks the action—locking physical actuators."

---

```
[00:43 - 00:60] DECISION RECEIPTS — CRYPTOGRAPHIC SHA-256 SEAL
Visual: Click `/receipts`. Click "Verify Digest" on the top receipt.
The card flashes green: "INTEGRITY VERIFIED · SHA-256 MATCH".
```
**Spoken (Voiceover):**  
"Every verified decision produces an immutable **Decision Receipt** sealed with SHA-256, proving input provenance and human operator approval. 

Foresight-AI: Industrial generative AI you can physically trust."

---

## Video Production & Audio Timing Checklist

| Second | Screen / URL | Interaction | Audio Cue |
|:---|:---|:---|:---|
| **00:00–00:10** | `http://localhost:3000/` | Zoom slightly into the motor schematic and stator temperature (138 °C). | High-energy opening hook. |
| **00:10–00:25** | `http://localhost:3000/arena` | Click **Run Future Arena**. Hover cursor over the 3 projected trajectories ($14,500 cost vs $3,100). | Direct comparison. |
| **00:25–00:43** | `http://localhost:3000/safety-challenge` | Click **Bearing Derate Trap**, click **Launch Adversarial Challenge**. Show red badge: `ACTUATION BLOCKED`. | Dramatic tension & safety resolution. |
| **00:43–00:60** | `http://localhost:3000/receipts` | Click **Verify Digest**. Reveal green badge `INTEGRITY VERIFIED`. Show canonical hash `e3b0c442...`. | Confident, authoritative close. |

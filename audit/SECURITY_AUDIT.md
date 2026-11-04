# FORESIGHT AI — SECURITY & ADVERSARIAL AUDIT

**Audit Phase:** Phase 4 (Security and Adversarial Review)  
**Evaluator:** Application Security Engineer & Red-Team Specialist  
**Codebase:** `E:\Hackathons\foresight-ai`  
**Commit:** `8c3d04a`  

---

## 1. Security Overview & Threat Model

Foresight AI is a simulated cyber-physical control platform. While it does not interface with physical actuators, it executes expensive AI inference, maintains real-time WebSocket/SSE streams, and allows execution of computational physics simulations.

### Threat Landscape
1. **API Exposure & Token Drainage:** Attackers triggering unauthenticated agent runs or model checks to drain user credits.
2. **Denial of Service (DoS):** Exhausting the fixed session pool (`MAX_SESSIONS = 20`) or swamping the CPU with large simulation ensembles.
3. **Adversarial LLM Proposals (Verifier Escapes):** An LLM (compromised or hallucinating) proposing an action that satisfies verification constraints while causing catastrophic failure in actual operation.
4. **Prompt Injection & Data Poisoning:** Indirect injection via manipulated sensor channel names or simulated diagnostic labels.

---

## 2. Vulnerability Findings

### Finding SEC-01: Completely Unauthenticated HTTP API (Missing Authentication & Authorization)
- **Severity:** High (CVSS: 7.5 - `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N`)
- **Category:** Broken Authentication / CWE-306
- **Affected File:** `services/api/foresight_api/main.py` ([Lines 87–94](file:///E:/Hackathons/foresight-ai/services/api/foresight_api/main.py#L87-L94))
- **Root Cause:** The FastAPI application registers all routes (`/api/*`) without any authentication dependency, API key header validation, or session tokens.
- **Realistic Attack Scenario:**
  An attacker who discovers the Foresight API URL sends automated POST requests to `/api/sessions/{session_id}/agent/runs` or `/api/diagnostics/model-check`. This triggers repetitive calls to Meta Model API (`https://api.meta.ai/v1`) or Fireworks AI (`https://api.fireworks.ai`), burning through the owner's token budget within minutes.
- **Impact:** Financial loss via LLM API quota exhaustion; unauthorized manipulation of simulation state; unauthorized termination of sessions via `DELETE /api/sessions/{session_id}`.
- **Likelihood:** High if exposed to public internet or shared network.
- **Recommended Mitigation:**
  Implement a lightweight API token authentication middleware or bearer token scheme:
  ```python
  from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

  security = HTTPBearer()
  # Protect all state-modifying and LLM-triggering routes
  ```
- **Verification Procedure:**
  Issue `curl -X POST http://localhost:8000/api/sessions` without headers. Currently returns HTTP 200/snapshot; should return HTTP 401 Unauthorized.

---

### Finding SEC-02: Denial of Service via Session Exhaustion
- **Severity:** High (CVSS: 7.5 - `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H`)
- **Category:** Resource Exhaustion / CWE-400
- **Affected File:** `services/api/foresight_api/sessions.py` ([Line 42 & Lines 513–528](file:///E:/Hackathons/foresight-ai/services/api/foresight_api/sessions.py#L42-L528))
- **Root Cause:** `MAX_SESSIONS` is set to 20, and `SessionManager.create()` immediately rejects requests with `SessionError("Too many active sessions; delete one first")` without evicting older anonymous sessions.
- **Realistic Attack Scenario:**
  A malicious actor runs a simple script sending 20 consecutive `POST /api/sessions` calls with arbitrary seeds. The 21st request and all legitimate users visiting the web app receive HTTP 409 errors and cannot start a simulation session.
- **Impact:** Complete denial of service for the demonstration and web interface.
- **Likelihood:** High (trivial single-line curl loop).
- **Recommended Mitigation:**
  1. Implement IP-based rate limiting on `POST /api/sessions`.
  2. Implement LRU session eviction: when `len(self.sessions) >= MAX_SESSIONS`, automatically evict the session with the oldest `last_active` timestamp rather than failing.
- **Verification Procedure:**
  Execute 21 requests to `/api/sessions`. Observe HTTP 409 failure on the 21st call.

---

### Finding SEC-03: Tail-Risk Verifier Escape via Sub-Ensemble Resolution
- **Severity:** Medium (CVSS: 6.5 - `CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:N`)
- **Category:** Safety Bypass / Algorithmic Blind Spot
- **Affected File:** `packages/foresight/src/foresight/verification/verifier.py` ([Line 52](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/verification/verifier.py#L52)) & `artifacts/reports/redteam_v4.md` ([Lines 50–55](file:///E:/Hackathons/foresight-ai/artifacts/reports/redteam_v4.md#L50-L55))
- **Root Cause:**
  The independent confirmation ensemble uses $N=16$ members. For a hazardous operating mode with low-probability failure rate $p \approx 2.1\%$, the probability of seeing zero failures in a 16-member sample is:
  $$P(\text{zero failures}) = (1 - 0.021)^{16} \approx 71.2\%$$
  The proposal therefore passes verification with >70% probability.
- **Empirical Evidence (from `redteam_v4.md`):**
  In verifier v4 testing, Meta Muse Spark at high reasoning effort discovered a proposal:
  - Scenario: `bearing_deterioration@120min/s7`
  - Action: `Reduce load by 35%`
  - Verifier outcome: Accepted (0 failures in 16 confirmation members).
  - 48-member Audit outcome: **Unsafe** (1 failure in 48 members, 95% CI $[0.004, 0.109]$). Submitted and accepted across all 3 rounds.
- **Impact:** An unsafe intervention is accepted by the safety verifier and presented to the operator as verified safe.
- **Likelihood:** Medium in normal operation; High under adversarial exploration.
- **Recommended Mitigation:**
  1. Increase confirmation ensemble size to $N = 32$ or $N = 48$ for proposals that alter load during active bearing degradation.
  2. Implement an explicit safety margin on vibration for derating during bearing faults: derating reduces cooling airflow or maintains speed while defect continues exponential growth.
- **Verification Procedure:**
  Run `scripts/run_red_team.py --verifier v4 --attackers meta:high` on `bearing_deterioration@120min/s7`.

---

### Finding SEC-04: Non-Atomic State Checks in LiveSession (Race Condition)
- **Severity:** Low (CVSS: 3.7 - `CVSS:3.1/AV:L/AC:H/PR:N/UI:N/S:U/C:N/I:L/A:L`)
- **Category:** Race Condition / CWE-362
- **Affected File:** `services/api/foresight_api/sessions.py` ([Lines 332–335 & Lines 392–420](file:///E:/Hackathons/foresight-ai/services/api/foresight_api/sessions.py#L332-L420))
- **Root Cause:**
  `self.busy` is read and assigned across coroutine suspension points without an `asyncio.Lock`.
  ```python
  if self.busy:
      raise SessionError(f"Session busy: {self.busy}")
  self.busy = "simulating futures"
  ```
- **Impact:** Two simultaneous requests (e.g. from rapid UI double-clicks) could enter `run_futures` or `run_agent` concurrently, corrupting session state or duplicating background worker tasks.
- **Recommended Mitigation:**
  Introduce an `asyncio.Lock()` per `LiveSession` instance to synchronize mutating state transitions.

---

## 3. Secrets & Key Management Review

### Positives
1. **Server-Side Key Isolation:** `MODEL_API_KEY` and `FIREWORKS_API_KEY` are read into `pydantic.SecretStr` instances in `config.py` ([Lines 50 & 54](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/config.py#L50-L54)).
2. **Zero Key Reflection:** The `/api/diagnostics` and `/api/health` endpoints return boolean flags (`api_key_configured: true/false`) and provider names, never reflecting secret values or prefixes.
3. **Git Hygiene:** Git commit history was independently audited (`git log --all -p -- .env`); no secrets have ever been committed. `.gitignore` correctly includes `.env` and `.env.local`.

---

## 4. Prompt Injection & Adversarial Robustness Review

### Prompt Injection Resilience
- **Injection Surface:** The LLM does not ingest open-ended user text. The inputs are structured JSON telemetry packages generated by Python tools ([prompts.py#L56-L58](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/prompts.py#L56-L58)).
- **Output Sanitization:** Model output is strictly bound by `HYPOTHESIS_FORMAT` (Responses API strict schema) and tool argument schemas. Free-form text fields (`statement`, `rationale`) are displayed in the UI as plain text, avoiding script injection.
- **Evidence Fabrication Defense:** If an LLM fabricates an evidence ID (e.g. `sim:fake:b1`), the verifier check `evidence_exists` ([verifier.py#L450-L462](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/verification/verifier.py#L450-L462)) flags and blocks the proposal.

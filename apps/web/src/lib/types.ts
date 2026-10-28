// Mirrors the FastAPI response models (services/api, packages/foresight).

export type ScenarioId = "healthy" | "cooling_degradation" | "bearing_deterioration" | "overload";

export type EvidenceKind =
  | "observed"
  | "ml_prediction"
  | "simulation_estimate"
  | "llm_hypothesis"
  | "verified";

export interface ScenarioInfo {
  id: ScenarioId;
  title: string;
  description: string;
  expected_failure_mode: string | null;
  plausible_interventions: string[];
}

export interface CompactSample {
  seq: number;
  t: number;
  T: number | null;
  Ta: number | null;
  vib: number | null;
  rpm: number | null;
  load: number | null;
  I: number | null;
  V: number | null;
  run: boolean;
  bad: string[];
}

export interface RiskPoint {
  t: number;
  available: boolean;
  risk15?: number;
  risk30?: number;
  risk60?: number;
  anomaly?: number | null;
  anomalous?: boolean;
  diagnosis?: string | null;
}

export interface EvidenceItem {
  id: string;
  kind: EvidenceKind;
  signal: string;
  value: number;
  unit: string;
  healthy_mean: number | null;
  z_score: number | null;
  description: string;
}

export interface HorizonRisk {
  horizon_min: number;
  probability: number;
  raw_probability: number;
  method: string;
}

export interface RiskAssessment {
  t_s: number;
  available: boolean;
  reason: string | null;
  horizons: HorizonRisk[];
  anomaly: { score: number; threshold: number; is_anomalous: boolean; method: string } | null;
  change_points: {
    signal: string;
    detected: boolean;
    t_s: number | null;
    direction: string | null;
    statistic: number;
  }[];
  diagnosis: { label: string; probability: number }[];
  evidence: EvidenceItem[];
  features: Record<string, number>;
  heuristic_minutes_to_temp_limit: number | null;
  model_version: string;
  latency_ms: number;
}

export interface Actuators {
  load_multiplier: number;
  speed_setpoint: number;
  aux_boost: number;
}

export interface GroundTruth {
  label: string;
  bearing_health: number;
  cooling_efficiency: number;
  failed: boolean;
  failure_mode: string | null;
  operating_hours: number;
  in_maintenance: boolean;
  shutdown: boolean;
  fault: Record<string, unknown>;
}

export interface SessionStatus {
  session_id: string;
  scenario: ScenarioId;
  scenario_title: string;
  seed: number;
  sim_time_s: number;
  speed: number;
  paused: boolean;
  pause_reason: string | null;
  busy: string | null;
  running: boolean;
  failed: boolean;
  failure_mode: string | null;
  fault_injected: boolean;
  actuators: Actuators;
  ground_truth: GroundTruth;
  model_version: string;
}

export interface TelemetryEvent {
  seq: number;
  t_s: number;
  kind: "intervention" | "fault_injected" | "failure" | "maintenance" | "note";
  summary: string;
  payload: Record<string, unknown>;
  source: "user" | "agent" | "system" | "replay";
}

export interface AgentRunSummary {
  run_id: string;
  status: AgentTrace["status"];
  stage: AgentStage;
  started_at: string;
}

export interface SessionSnapshot {
  status: SessionStatus;
  scenario: ScenarioInfo;
  samples: CompactSample[];
  risk_history: RiskPoint[];
  assessment: RiskAssessment | null;
  events: TelemetryEvent[];
  comparisons: string[];
  agent_runs: AgentRunSummary[];
}

export interface TickMessage {
  samples: CompactSample[];
  assessment?: RiskAssessment | null;
  risk_point?: RiskPoint | null;
  events: TelemetryEvent[];
  status: SessionStatus;
}

// ---------------------------------------------------------------- actions

export type Action =
  | { type: "continue_operation" }
  | { type: "reduce_load"; fraction: number }
  | { type: "reduce_speed"; fraction: number }
  | { type: "increase_cooling"; boost: number }
  | { type: "schedule_inspection"; delay_minutes: number }
  | { type: "controlled_shutdown" };

export type ActionType = Action["type"];

// ---------------------------------------------------------------- branching

export interface StateEstimate {
  t_s: number;
  temperature_c: number;
  ambient_c: number;
  cooling_efficiency: number;
  cooling_efficiency_std: number;
  cooling_trend_per_h: number;
  bearing_damage: number;
  bearing_damage_std: number;
  bearing_growth_per_h: number;
  process_load: number;
  baseline_process_load: number;
  load_trend_per_h: number;
  actuators: Actuators;
  method: string;
  notes: string[];
}

export interface CostBreakdown {
  lost_production: number;
  failure_repair: number;
  failure_downtime: number;
  intervention: number;
  deferred_maintenance: number;
  terminal_risk_penalty: number;
}

export interface Band {
  t_min: number[];
  p10: number[];
  p50: number[];
  p90: number[];
}

export interface BranchOutcome {
  branch_id: string;
  label: string;
  action: Action;
  n_members: number;
  failure_incidence: number;
  failure_incidence_ci95: [number, number];
  failure_modes: Record<string, number>;
  median_time_to_failure_min: number | null;
  peak_temperature_mean_c: number;
  peak_temperature_p90_c: number;
  peak_vibration_mean_mm_s: number;
  peak_vibration_p90_mm_s: number;
  max_running_load: number;
  downtime_mean_h: number;
  cost_mean: number;
  cost_breakdown_mean: CostBreakdown;
  objective: number;
  end_alarm_fraction: number;
  temperature_band: Band;
  vibration_band: Band;
  delta_vs_baseline: Record<string, number>;
}

export interface FutureComparison {
  id: string;
  created_at: string;
  t0_s: number;
  horizon_min: number;
  n_members: number;
  state_source: "estimated" | "oracle";
  estimate: StateEstimate | null;
  baseline_branch_id: string;
  branches: BranchOutcome[];
  ranking: string[];
  seeds: number[];
  objective_definition: string;
  assumptions: string[];
  compute_ms: number;
}

// ---------------------------------------------------------------- verification

export interface CheckResult {
  name: string;
  status: "pass" | "fail" | "warn" | "skip";
  blocking: boolean;
  detail: string;
  measured: number | string | null;
  limit: number | string | null;
}

export interface VerificationResult {
  verdict: "accepted" | "accepted_with_warnings" | "rejected";
  action: Action;
  action_label: string;
  checks: CheckResult[];
  requires_human_approval: boolean;
  rejection_reasons: string[];
  comparison_id: string | null;
  summary: string;
  verification_id?: string;
}

// ---------------------------------------------------------------- agent

export type AgentStage =
  | "OBSERVE"
  | "ANALYZE"
  | "HYPOTHESIZE"
  | "INVESTIGATE"
  | "SIMULATE"
  | "VERIFY"
  | "RECOMMEND"
  | "DONE"
  | "FAILED";

export interface TraceStep {
  seq: number;
  stage: AgentStage;
  kind: "tool_call" | "llm_call" | "verification" | "transition" | "note" | "error";
  name: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  result: unknown;
  ok: boolean;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  t_wall: string;
}

export interface Hypothesis {
  failure_mode: "thermal" | "bearing" | "overload" | "none";
  statement: string;
  likelihood: "low" | "medium" | "high";
  supporting_evidence_ids: string[];
  would_be_refuted_by: string;
  unknown_evidence_ids: string[];
  source: "llm" | "deterministic";
}

export interface RejectedProposal {
  action: Action;
  action_label: string;
  source: string;
  reasons: string[];
  verification: VerificationResult;
}

export interface AgentRecommendation {
  status: "awaiting_approval" | "no_action_needed" | "no_safe_action_found";
  action: Action | null;
  action_label: string;
  claimed_failure_mode: string;
  rationale: string;
  rationale_source: "llm" | "deterministic";
  cited_evidence: EvidenceItem[];
  verification: VerificationResult | null;
  branch: BranchOutcome | null;
  baseline: BranchOutcome | null;
  comparison_id: string | null;
  selected_by: "agent" | "optimizer_fallback" | "deterministic_planner";
}

export interface AgentUsage {
  llm_calls: number;
  tool_calls: number;
  tool_errors: number;
  invalid_actions: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  hallucinated_evidence_ids: number;
}

export interface AgentTrace {
  run_id: string;
  session_id: string;
  status: "running" | "completed" | "failed";
  provider: string;
  model: string | null;
  reasoning_effort: string | null;
  snapshot_t_s: number;
  started_at: string;
  finished_at: string | null;
  latency_ms: number | null;
  stage: AgentStage;
  stage_history: AgentStage[];
  steps: TraceStep[];
  summary: string;
  hypotheses: Hypothesis[];
  rejected: RejectedProposal[];
  recommendation: AgentRecommendation | null;
  report: Record<string, unknown> | null;
  usage: AgentUsage;
  error: string | null;
  notice: string | null;
}

// ---------------------------------------------------------------- meta

export interface Health {
  status: string;
  version: string;
  model_bundle: string;
  active_sessions: number;
  llm_configured: boolean;
  providers: { name: ProviderName; label: string; model: string; default: boolean }[];
}

export type ProviderName = "meta" | "fireworks";

export interface ProviderInfo {
  name: ProviderName;
  label: string;
  base_url: string;
  model: string;
  configured: boolean;
  default: boolean;
  efforts: string[];
  price_per_m: { input: number; cached_input: number | null; output: number };
  last_check: Record<string, unknown> | null;
}

export interface Diagnostics {
  providers: ProviderInfo[];
  llm: {
    provider: string;
    base_url: string;
    reasoning_model: string;
    reasoning_effort: string;
    api_key_configured: boolean;
    timeout_s: number;
    max_retries: number;
    agent_max_tool_calls: number;
    agent_max_revisions: number;
    last_check: Record<string, unknown> | null;
  };
  predictive_models: Record<string, unknown>;
  model_path: string;
}

export interface ReplayCheck {
  deterministic: boolean;
  live_fingerprint: string;
  replay_fingerprint: string;
  sim_time_s: number;
  interventions_replayed: number;
  compute_ms: number;
}

"""Bounded agent workflow:  OBSERVE → ANALYZE → HYPOTHESIZE → INVESTIGATE → SIMULATE → VERIFY → RECOMMEND.

The stages are an explicit state machine with validated transitions. OBSERVE and ANALYZE are
always deterministic tool calls. HYPOTHESIZE / INVESTIGATE / SIMULATE are driven by the Meta
reasoning model when configured (Responses API with structured output and function tools),
otherwise by a clearly labelled deterministic planner. VERIFY is always the deterministic
verifier, which can reject the model's proposal and send it back for revision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from foresight.agents import prompts
from foresight.agents.llm import LLMError, LLMResponse, MetaModelClient
from foresight.agents.schemas import (
    ALLOWED_TRANSITIONS,
    AgentRecommendation,
    AgentStage,
    AgentTrace,
    Hypothesis,
    RejectedProposal,
    TraceStep,
)
from foresight.agents.tools import (
    AgentSnapshot,
    ToolError,
    ToolExecutor,
    action_from_flat,
    branch_summary,
)
from foresight.branching import ACTION_ADAPTER, FutureComparison
from foresight.config import Settings
from foresight.simulation import (
    Action,
    ContinueOperation,
    ControlledShutdown,
    IncreaseCooling,
    ReduceLoad,
    ReduceSpeed,
    ScheduleInspection,
    describe_action,
)
from foresight.verification import InformationAssessment, Proposal, VerificationResult

log = logging.getLogger("foresight.agent")

TOOL_STAGE = {
    "get_machine_state": AgentStage.INVESTIGATE,
    "get_sensor_history": AgentStage.INVESTIGATE,
    "analyze_anomalies": AgentStage.INVESTIGATE,
    "predict_failure_risk": AgentStage.INVESTIGATE,
    "inspect_visual_evidence": AgentStage.INVESTIGATE,
    "compare_futures": AgentStage.SIMULATE,
    "assess_information_value": AgentStage.VERIFY,
    "verify_intervention": AgentStage.VERIFY,
    "submit_recommendation": AgentStage.VERIFY,
}

DIAGNOSIS_TO_MODE = {
    "cooling": "thermal",
    "overload": "overload",
    "bearing": "bearing",
    "none": "none",
}

DETERMINISTIC_CANDIDATES: dict[str, list[Action]] = {
    "cooling": [
        IncreaseCooling(boost=0.4),
        ReduceLoad(fraction=0.3),
        ScheduleInspection(delay_minutes=10),
        ScheduleInspection(delay_minutes=0),
        ControlledShutdown(),
    ],
    "bearing": [
        ReduceLoad(fraction=0.3),
        ReduceSpeed(fraction=0.3),
        ScheduleInspection(delay_minutes=10),
        ScheduleInspection(delay_minutes=0),
        ControlledShutdown(),
    ],
    "overload": [
        ReduceLoad(fraction=0.3),
        ScheduleInspection(delay_minutes=10),
        ScheduleInspection(delay_minutes=0),
        ControlledShutdown(),
    ],
    "none": [],
}

LOW_RISK = 0.2


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class AgentOrchestrator:
    def __init__(
        self,
        snapshot: AgentSnapshot,
        settings: Settings,
        llm: MetaModelClient | None = None,
        on_update: Callable[[AgentTrace], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.settings = settings
        self.llm = llm
        self.on_update = on_update
        self.tools = ToolExecutor(snapshot)
        self._seq = 0
        self._start = time.perf_counter()
        self.trace = AgentTrace(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            session_id=snapshot.session_id,
            status="running",
            provider=llm.provider if llm else "deterministic-planner",
            model=llm.model if llm else None,
            reasoning_effort=llm.reasoning_effort if llm else None,
            snapshot_t_s=snapshot.t_s,
            started_at=_now(),
            stage=AgentStage.OBSERVE,
            stage_history=[AgentStage.OBSERVE],
        )
        if llm is None:
            self.trace.notice = (
                "No model provider is configured: hypotheses and planning come from a "
                "deterministic rule-based planner, not from a Meta model."
            )

    # ------------------------------------------------------------------ trace helpers
    def _publish(self) -> None:
        if self.on_update:
            self.on_update(self.trace)

    def _transition(self, stage: AgentStage) -> None:
        current = self.trace.stage
        if stage == current:
            return
        if stage not in ALLOWED_TRANSITIONS[current]:
            raise RuntimeError(f"invalid agent transition {current} -> {stage}")
        self.trace.stage = stage
        self.trace.stage_history.append(stage)
        self._step("transition", f"{current} → {stage}")

    def _step(self, kind: str, name: str, **kw: Any) -> TraceStep:
        self._seq += 1
        step = TraceStep(
            seq=self._seq, stage=self.trace.stage, kind=kind, name=name, t_wall=_now(), **kw
        )
        self.trace.steps.append(step)
        self._publish()
        return step

    def _account(self, resp: LLMResponse) -> None:
        u = self.trace.usage
        u.llm_calls += 1
        u.input_tokens += resp.input_tokens
        u.cached_input_tokens += resp.cached_input_tokens
        u.output_tokens += resp.output_tokens
        assert self.llm is not None
        u.estimated_cost_usd = round(
            self.llm.cost_usd(u.input_tokens, u.cached_input_tokens, u.output_tokens), 6
        )

    async def _tool(self, name: str, args: dict) -> tuple[bool, dict, str]:
        start = time.perf_counter()
        self.trace.usage.tool_calls += 1
        try:
            summary, result = await self.tools.call(name, args)
            ok = True
        except (ToolError, TypeError, ValidationError) as exc:
            summary, result, ok = f"error: {exc}", {"error": str(exc)}, False
            self.trace.usage.tool_errors += 1
            if "action" in str(exc):
                self.trace.usage.invalid_actions += 1
        self._step(
            "tool_call",
            name,
            arguments=args,
            result_summary=summary,
            result=result,
            ok=ok,
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )
        return ok, result, summary

    # ------------------------------------------------------------------ main entry
    async def run(self) -> AgentTrace:
        try:
            await asyncio.wait_for(self._run(), timeout=self.settings.agent_timeout_s)
            self.trace.status = "completed"
        except TimeoutError:
            self._fail(f"Agent exceeded the {self.settings.agent_timeout_s:.0f}s time budget")
        except Exception as exc:  # last-resort guard: record, never crash the API
            log.exception("agent run failed")
            self._fail(f"{type(exc).__name__}: {exc}")
        self.trace.finished_at = _now()
        self.trace.latency_ms = (time.perf_counter() - self._start) * 1000.0
        self._publish()
        return self.trace

    def _fail(self, message: str) -> None:
        self.trace.status = "failed"
        self.trace.error = message
        if self.trace.stage not in (AgentStage.DONE, AgentStage.FAILED):
            self.trace.stage = AgentStage.FAILED
            self.trace.stage_history.append(AgentStage.FAILED)
        self._step("error", "run_failed", result_summary=message, ok=False)

    async def _run(self) -> None:
        # OBSERVE
        await self._tool("get_machine_state", {})
        await self._tool("get_sensor_history", {"channel": "temperature_c", "minutes": 60})
        await self._tool("get_sensor_history", {"channel": "vibration_mm_s", "minutes": 60})
        # ANALYZE
        self._transition(AgentStage.ANALYZE)
        await self._tool("analyze_anomalies", {})
        await self._tool("predict_failure_risk", {})
        assessment = self.snapshot.assessment
        if not assessment.available:
            self._transition(AgentStage.HYPOTHESIZE)
            self._transition(AgentStage.RECOMMEND)
            self.trace.recommendation = AgentRecommendation(
                status="no_action_needed",
                action=None,
                action_label="No recommendation",
                claimed_failure_mode="unknown",
                rationale=f"Risk assessment unavailable: {assessment.reason}",
                rationale_source="deterministic",
                selected_by="deterministic_planner",
            )
            self.trace.summary = "Machine is not running or telemetry is insufficient."
            self._finish()
            return

        self._transition(AgentStage.HYPOTHESIZE)
        accepted: tuple[VerificationResult, Proposal, str] | None = None
        if self.llm is not None:
            try:
                accepted = await self._llm_path()
            except LLMError as exc:
                self._step("error", "llm_unavailable", result_summary=str(exc), ok=False)
                self.trace.notice = (
                    f"Model call to {self.llm.config.label} failed ({exc}); continued with the "
                    "deterministic planner."
                )
                self.trace.provider = f"{self.llm.provider} → deterministic-planner fallback"
                accepted = None
                if not self.trace.hypotheses:
                    self._deterministic_hypotheses()
            if accepted is None:
                accepted = await self._optimizer_fallback()
        else:
            self._deterministic_hypotheses()
            accepted = await self._optimizer_fallback(selected_by="deterministic_planner")
        information = await self._information_gate(accepted)
        self._recommend(accepted, information)
        self._finish()

    async def _information_gate(
        self, accepted: tuple[VerificationResult, Proposal, str] | None
    ) -> InformationAssessment | None:
        """Ask whether a verified consequential action should wait for more telemetry."""
        if (
            accepted is None
            or not self.snapshot.information_gathering
            or self.snapshot.planning_state_source == "oracle"
            or isinstance(accepted[1].action, ContinueOperation)
        ):
            return None
        ok, _, _ = await self._tool("assess_information_value", {})
        return self.tools.information if ok else None

    # ------------------------------------------------------------------ LLM path
    def _evidence_package(self) -> dict:
        a = self.snapshot.assessment
        already_fetched = [
            s.result_summary
            for s in self.trace.steps
            if s.kind == "tool_call" and s.name == "get_sensor_history" and s.ok
        ]
        return {
            "sim_time_min": round(self.snapshot.t_s / 60.0, 1),
            "latest_observation": self.snapshot.samples[-1].values,
            "trends_last_60_min": already_fetched,
            "drive_commands": self.snapshot.actuators.model_dump(),
            "risk_horizons": [
                h.model_dump(include={"horizon_min", "probability"}) for h in a.horizons
            ],
            "fault_class_probabilities": [d.model_dump() for d in a.diagnosis],
            "anomaly": a.anomaly.model_dump() if a.anomaly else None,
            "change_points": [c.model_dump() for c in a.change_points],
            "evidence": [
                e.model_dump(
                    include={
                        "id",
                        "kind",
                        "signal",
                        "value",
                        "unit",
                        "healthy_mean",
                        "z_score",
                        "description",
                    }
                )
                for e in a.evidence
            ],
        }

    async def _llm_call(self, name: str, **kwargs) -> LLMResponse:
        assert self.llm is not None
        resp = await self.llm.create_response(instructions=prompts.SYSTEM_INSTRUCTIONS, **kwargs)
        self._account(resp)
        self._step(
            "llm_call",
            name,
            result_summary=(
                resp.output_text[:400]
                if resp.output_text
                else f"{len(resp.function_calls)} tool call(s)"
            ),
            result={
                "response_id": resp.id,
                "status": resp.status,
                "tool_calls": [c.name for c in resp.function_calls],
            },
            latency_ms=resp.latency_ms,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
        return resp

    def _parse_hypotheses(self, text: str) -> tuple[list[Hypothesis], list[Action], str]:
        data = json.loads(text)
        known = self.tools.known_evidence_ids()
        hyps = []
        for h in data.get("hypotheses", []):
            hyp = Hypothesis(**h, source="llm")
            hyp.unknown_evidence_ids = [e for e in hyp.supporting_evidence_ids if e not in known]
            self.trace.usage.hallucinated_evidence_ids += len(hyp.unknown_evidence_ids)
            hyps.append(hyp)
        actions: list[Action] = []
        for raw in data.get("candidate_interventions", []):
            try:
                actions.append(action_from_flat(raw))
            except ToolError as exc:
                self.trace.usage.invalid_actions += 1
                self._step(
                    "note", "invalid_candidate", arguments=raw, result_summary=str(exc), ok=False
                )
        return hyps, actions, data.get("summary", "")

    async def _llm_path(self) -> tuple[VerificationResult, Proposal, str] | None:
        evidence = json.dumps(self._evidence_package(), default=str)
        hyp_resp = await self._llm_call(
            "hypothesize",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompts.HYPOTHESIS_TASK.format(evidence=evidence),
                        }
                    ],
                }
            ],
            text_format=prompts.HYPOTHESIS_FORMAT,
        )
        candidates: list[Action] = []
        try:
            hyps, candidates, summary = self._parse_hypotheses(hyp_resp.output_text)
            self.trace.hypotheses = hyps
            self.trace.summary = summary
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            self._step("error", "hypothesis_parse_failed", result_summary=str(exc), ok=False)
            self._deterministic_hypotheses()
        self._transition(AgentStage.INVESTIGATE)

        budget = self.settings.agent_max_tool_calls
        task = prompts.INVESTIGATE_TASK.format(budget=budget)
        if candidates:
            task += "\nYour candidate interventions: " + json.dumps(
                [ACTION_ADAPTER.dump_python(a, mode="json") for a in candidates]
            )
        resp = await self._llm_call(
            "investigate",
            input=[{"role": "user", "content": [{"type": "input_text", "text": task}]}],
            tools=prompts.TOOL_DEFINITIONS,
            previous_response_id=hyp_resp.id,
        )
        used, revisions, nudged = 0, 0, False
        while True:
            if not resp.function_calls:
                if nudged:
                    self._step(
                        "note",
                        "no_submission",
                        result_summary="Model ended without submitting",
                        ok=False,
                    )
                    return None
                nudged = True
                resp = await self._llm_call(
                    "nudge_submit",
                    input=[
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompts.NUDGE_SUBMIT}],
                        }
                    ],
                    tools=prompts.TOOL_DEFINITIONS,
                    previous_response_id=resp.id,
                )
                continue
            outputs: list[dict] = []
            for call in resp.function_calls:
                used += 1
                if used > budget:
                    self._step(
                        "note",
                        "tool_budget_exhausted",
                        result_summary=f"{budget} tool calls used",
                        ok=False,
                    )
                    return None
                try:
                    args = call.arguments()
                except LLMError as exc:
                    self.trace.usage.tool_errors += 1
                    outputs.append(_fc_output(call.call_id, {"error": str(exc)}))
                    continue
                stage = TOOL_STAGE.get(call.name, AgentStage.INVESTIGATE)
                if stage != self.trace.stage and stage in ALLOWED_TRANSITIONS[self.trace.stage]:
                    self._transition(stage)
                if call.name == "submit_recommendation":
                    outcome = await self._handle_submission(args)
                    if outcome is not None and outcome[0].verdict != "rejected":
                        return outcome
                    revisions += 1
                    if revisions > self.settings.agent_max_revisions:
                        self._step(
                            "note",
                            "revision_limit",
                            result_summary="Revision limit reached",
                            ok=False,
                        )
                        return None
                    feedback = (
                        {"verdict": "rejected", "error": "invalid submission"}
                        if outcome is None
                        else {
                            "verdict": "rejected",
                            "failed_checks": outcome[0].rejection_reasons,
                            "instructions": prompts.REVISION_TASK.format(
                                label=outcome[0].action_label,
                                reasons="\n".join(f"- {r}" for r in outcome[0].rejection_reasons),
                                left=self.settings.agent_max_revisions - revisions + 1,
                            ),
                        }
                    )
                    outputs.append(_fc_output(call.call_id, feedback))
                    continue
                _ok, result, _ = await self._tool(call.name, args)
                outputs.append(_fc_output(call.call_id, result))
            resp = await self._llm_call(
                "tool_results",
                input=outputs,
                tools=prompts.TOOL_DEFINITIONS,
                previous_response_id=resp.id,
            )

    async def _handle_submission(
        self, args: dict
    ) -> tuple[VerificationResult, Proposal, str] | None:
        self.trace.usage.tool_calls += 1
        try:
            action = action_from_flat(args.get("action"))
            proposal = Proposal(
                action=action,
                claimed_failure_mode=args.get("claimed_failure_mode", "unknown"),
                cited_evidence_ids=[str(x) for x in args.get("cited_evidence_ids", [])],
                source="agent",
            )
        except (ToolError, ValidationError) as exc:
            self.trace.usage.invalid_actions += 1
            self.trace.usage.tool_errors += 1
            self._step(
                "error", "submit_recommendation", arguments=args, result_summary=str(exc), ok=False
            )
            return None
        known = self.tools.known_evidence_ids()
        self.trace.usage.hallucinated_evidence_ids += sum(
            1 for e in proposal.cited_evidence_ids if e not in known
        )
        result = await self.tools.run_verification(proposal)
        self._step(
            "verification",
            "submit_recommendation",
            arguments=args,
            result_summary=result.summary,
            result=result.model_dump(),
            ok=result.verdict != "rejected",
        )
        if result.verdict == "rejected":
            self.trace.rejected.append(
                RejectedProposal(
                    action=result.action,
                    action_label=result.action_label,
                    source="agent",
                    reasons=result.rejection_reasons,
                    verification=result,
                )
            )
        return result, proposal, str(args.get("rationale", ""))

    # ------------------------------------------------------------------ deterministic path
    def _top_fault(self) -> str:
        d = self.snapshot.assessment.diagnosis
        return d[0].label if d else "none"

    def _deterministic_hypotheses(self) -> None:
        a = self.snapshot.assessment
        top = self._top_fault()
        prob = a.diagnosis[0].probability if a.diagnosis else 0.0
        observed = [e.id for e in a.evidence if e.kind == "observed"][:3]
        statement = {
            "cooling": "Heat rejection is lower than the datasheet model predicts for the measured current.",
            "bearing": "Vibration exceeds the datasheet baseline, consistent with bearing damage.",
            "overload": "Applied load is rising above rating, increasing copper losses.",
            "none": "No fault signature exceeds healthy-operation variability.",
        }[top]
        self.trace.hypotheses = [
            Hypothesis(
                failure_mode=DIAGNOSIS_TO_MODE[top],  # type: ignore[arg-type]
                statement=statement,
                likelihood="high" if prob > 0.7 else "medium" if prob > 0.4 else "low",
                supporting_evidence_ids=[*observed, "ml:diagnosis"],
                would_be_refuted_by="Residual features returning to their healthy range.",
                source="deterministic",
            )
        ]
        self.trace.summary = (
            f"Deterministic diagnosis from the fault classifier: {top} (p={prob:.2f})."
        )

    async def _optimizer_fallback(
        self, selected_by: str = "optimizer_fallback"
    ) -> tuple[VerificationResult, Proposal, str] | None:
        """Verify branches in objective order and pick the first that passes."""
        self._transition(AgentStage.SIMULATE)
        top = self._top_fault()
        risk60 = next(
            (h.probability for h in self.snapshot.assessment.horizons if h.horizon_min == 60), 0.0
        )
        candidates = list(DETERMINISTIC_CANDIDATES.get(top, []))
        if not candidates and risk60 > LOW_RISK:
            candidates = [
                ReduceLoad(fraction=0.3),
                ScheduleInspection(delay_minutes=10),
                ControlledShutdown(),
            ]
        flat = [ACTION_ADAPTER.dump_python(a, mode="json") for a in candidates] or [
            {"type": "continue_operation"}
        ]
        ok, result, _ = await self._tool("compare_futures", {"actions": flat})
        if not ok:
            return None
        comp: FutureComparison = self.tools.comparisons[result["comparison_id"]]
        self._transition(AgentStage.VERIFY)
        mode = DIAGNOSIS_TO_MODE.get(top, "unknown")
        order = list(comp.ranking)
        for branch_id in order:
            branch = next(b for b in comp.branches if b.branch_id == branch_id)
            action = ACTION_ADAPTER.validate_python(branch.action)
            proposal = Proposal(
                action=action,
                claimed_failure_mode=mode if not isinstance(action, ContinueOperation) else "none",
                cited_evidence_ids=[f"sim:{comp.id}:{branch_id}", "ml:diagnosis"],
                source="optimizer",
            )
            res = await self.tools.run_verification(proposal)
            self._step(
                "verification",
                "verify_intervention",
                arguments=branch.action,
                result_summary=res.summary,
                result=res.model_dump(),
                ok=res.verdict != "rejected",
            )
            if res.verdict != "rejected":
                rationale = (
                    f"Selected by the deterministic planner: lowest objective among verified branches "
                    f"({branch.label}: simulated failure incidence {branch.failure_incidence:.0%}, "
                    f"p90 peak {branch.peak_temperature_p90_c:.1f} °C)."
                )
                return res, proposal, rationale
            self.trace.rejected.append(
                RejectedProposal(
                    action=res.action,
                    action_label=res.action_label,
                    source=selected_by,
                    reasons=res.rejection_reasons,
                    verification=res,
                )
            )
        return None

    # ------------------------------------------------------------------ recommend
    def _recommend(
        self,
        accepted: tuple[VerificationResult, Proposal, str] | None,
        information: InformationAssessment | None = None,
    ) -> None:
        if self.trace.stage != AgentStage.VERIFY:
            self._transition(AgentStage.VERIFY)
        self._transition(AgentStage.RECOMMEND)
        selected_by = "agent" if self.llm is not None else "deterministic_planner"
        if accepted is None:
            self.trace.recommendation = AgentRecommendation(
                status="no_safe_action_found",
                action=None,
                action_label="No verified action",
                claimed_failure_mode=self.trace.hypotheses[0].failure_mode
                if self.trace.hypotheses
                else "unknown",
                rationale="No simulated intervention passed every blocking safety check. Escalate to a human engineer.",
                rationale_source="deterministic",
                selected_by=selected_by,
            )
            return
        verification, proposal, rationale = accepted
        if proposal.source == "optimizer":
            selected_by = "deterministic_planner" if self.llm is None else "optimizer_fallback"
        comp = self.tools.comparison_for(proposal.action)
        branch = comp.branch_for_action(proposal.action) if comp else None
        baseline = (
            next((b for b in comp.branches if b.branch_id == comp.baseline_branch_id), None)
            if comp
            else None
        )
        cited = [
            self.tools.evidence[e] for e in proposal.cited_evidence_ids if e in self.tools.evidence
        ]
        is_continue = isinstance(proposal.action, ContinueOperation)
        label = describe_action(proposal.action)
        status = "no_action_needed" if is_continue else "awaiting_approval"
        if information is not None and information.decision == "gather_information":
            status = "gather_information"
            rationale = (
                f"{information.summary} Held back: '{label}' passed verification and can be "
                f"re-assessed after {information.defer_minutes:.0f} min. {rationale}"
            ).strip()
        self.trace.recommendation = AgentRecommendation(
            status=status,  # type: ignore[arg-type]
            action=ACTION_ADAPTER.dump_python(proposal.action, mode="json"),
            action_label=label,
            claimed_failure_mode=proposal.claimed_failure_mode,
            rationale=rationale,
            rationale_source="llm" if proposal.source == "agent" else "deterministic",
            cited_evidence=cited,
            verification=verification,
            branch=branch,
            baseline=baseline,
            comparison_id=comp.id if comp else None,
            selected_by=selected_by,  # type: ignore[arg-type]
            information=information,
        )

    def _finish(self) -> None:
        self.trace.report = self._evidence_report()
        self._step(
            "tool_call", "generate_evidence_report", result_summary="Evidence report generated"
        )
        self._transition(AgentStage.DONE)

    def _evidence_report(self) -> dict:
        """Deterministic report that keeps the five evidence categories separate."""
        a = self.snapshot.assessment
        rec = self.trace.recommendation
        comps = list(self.tools.comparisons.values())
        return {
            "observed_evidence": [e.model_dump() for e in a.evidence if e.kind == "observed"][:8],
            "ml_predictions": [e.model_dump() for e in a.evidence if e.kind == "ml_prediction"],
            "simulation_estimates": [
                {
                    "comparison_id": c.id,
                    "state_source": c.state_source,
                    "branches": [branch_summary(c, b) for b in c.branches],
                }
                for c in comps
            ],
            "hypotheses": [h.model_dump() for h in self.trace.hypotheses],
            "verified_results": [
                v.model_dump(include={"verdict", "action_label", "rejection_reasons", "summary"})
                for v in self.tools.verifications
            ],
            "information_value": self.tools.information.model_dump(
                include={"decision", "unsupported_trends", "reasons", "summary"}
            )
            if self.tools.information
            else None,
            "recommendation": rec.model_dump(
                include={
                    "status",
                    "action_label",
                    "claimed_failure_mode",
                    "rationale",
                    "rationale_source",
                    "selected_by",
                }
            )
            if rec
            else None,
        }


def _fc_output(call_id: str, result: Any) -> dict:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result, default=str),
    }

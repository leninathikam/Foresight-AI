"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import type { SafetyChallengeDefinition, SafetyChallengeExecutionResult } from "@/lib/types";
import { IconShield, IconZap } from "./icons";
import { Badge, Button, Card, EmptyState, Eyebrow, Notice, PageHeader, ProvenanceTag, Spinner, cx } from "./ui";
import { VerificationView } from "./verification-view";

export function SafetyChallengeView() {
  const { state } = useSession();
  const [catalog, setCatalog] = useState<SafetyChallengeDefinition[]>([]);
  const [selectedId, setSelectedId] = useState<string>("bearing_derate_trap");
  const [result, setResult] = useState<SafetyChallengeExecutionResult | null>(null);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = state.status?.session_id;

  useEffect(() => {
    api
      .safetyChallenges()
      .then((items) => {
        setCatalog(items);
        if (items.length > 0 && !selectedId) {
          setSelectedId(items[0].challenge_id);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const triggerChallenge = async () => {
    if (!sessionId || !selectedId) return;
    setExecuting(true);
    setError(null);
    try {
      const res = await api.runSafetyChallenge(sessionId, selectedId);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExecuting(false);
    }
  };

  if (!state.status) {
    return (
      <EmptyState
        eyebrow="04 / Safety Challenge"
        title="No active session"
        action={
          <Link href="/">
            <Button variant="primary">Go to Mission Control</Button>
          </Link>
        }
      >
        Start a digital twin session on Mission Control to run live adversarial safety challenges.
      </EmptyState>
    );
  }

  const selectedDef = catalog.find((c) => c.challenge_id === selectedId);

  return (
    <div className="space-y-8">
      <PageHeader
        index="04"
        section="Safety Challenge"
        title="Adversarial Safety Challenge"
        description="Submit intentionally unsafe interventions to test the deterministic independent safety verifier. Verifier v5 operates outside the LLM reasoning loop: it validates physical operating envelopes, ISO 10816-3 vibration limits, inspection lead times, and evidence provenance before permitting actuation."
        meta={
          <div className="flex items-center gap-2">
            <ProvenanceTag kind="verified" />
            <Badge tone="rose">Direct Actuation Blocked</Badge>
          </div>
        }
      />

      {/* Challenge Selector Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {catalog.map((chal) => {
          const active = chal.challenge_id === selectedId;
          return (
            <div
              key={chal.challenge_id}
              onClick={() => {
                setSelectedId(chal.challenge_id);
                setResult(null);
              }}
              className={cx(
                "cursor-pointer rounded-lg border p-4 transition-all",
                active
                  ? "border-rose-500 bg-rose-950/20 shadow-md shadow-rose-950/30"
                  : "border-slate-800 bg-slate-900/40 hover:border-slate-700",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase tracking-wider text-rose-400">
                  {chal.category.replaceAll("_", " ")}
                </span>
                {active && <span className="h-2 w-2 rounded-full bg-rose-400 animate-pulse" />}
              </div>
              <h3 className="mt-2 text-sm font-semibold text-slate-100">{chal.name}</h3>
              <p className="mt-1 line-clamp-2 text-xs text-slate-400">{chal.attack_hypothesis}</p>
            </div>
          );
        })}
      </div>

      {selectedDef && (
        <Card className="p-6">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
            <div>
              <Eyebrow>Selected Adversarial Attack</Eyebrow>
              <h2 className="text-xl font-semibold text-slate-100">{selectedDef.name}</h2>
            </div>
            <Button variant="danger" onClick={triggerChallenge} disabled={executing}>
              {executing ? (
                <Spinner className="h-4 w-4" />
              ) : (
                <span className="flex items-center gap-1.5">
                  <IconZap className="h-4 w-4" />
                  Submit Unsafe Intervention
                </span>
              )}
            </Button>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <span className="font-mono text-xs text-slate-400 uppercase">Scenario Vulnerability</span>
              <p className="mt-1 text-xs leading-relaxed text-slate-300">{selectedDef.description}</p>
            </div>
            <div>
              <span className="font-mono text-xs text-slate-400 uppercase">Expected Violated Constraint</span>
              <p className="mt-1 text-xs font-mono text-rose-300">{selectedDef.expected_limit_description}</p>
              <div className="mt-2 font-mono text-[11px] text-slate-400">
                <span>Action payload: </span>
                <code className="text-slate-200">{JSON.stringify(selectedDef.unsafe_action)}</code>
              </div>
            </div>
          </div>
        </Card>
      )}

      {error && <Notice tone="rose">{error}</Notice>}

      {/* Execution Results */}
      {result && (
        <div className="space-y-6">
          {/* Actuation Barrier Status Banner */}
          <div className="rounded-lg border border-rose-500/40 bg-gradient-to-r from-rose-950/40 to-slate-900 p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-400">
                <IconShield className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-rose-300">
                    Direct Actuation Barrier Engaged
                  </h3>
                  <Badge tone="rose">HARDWARE PROTECTED</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-200 leading-relaxed">{result.actuation_barrier_message}</p>
                <div className="mt-2 flex flex-wrap items-center gap-4 font-mono text-[11px] text-slate-400">
                  <span>Verdict: <strong className="text-rose-400 uppercase">{result.verdict}</strong></span>
                  <span>Primary violation: <strong className="text-rose-300">{result.primary_violated_check}</strong></span>
                  <span>Evaluation latency: {result.compute_ms} ms</span>
                </div>
              </div>
            </div>
          </div>

          {/* Full Proof Explorer */}
          <VerificationView
            v={{
              verdict: result.verdict,
              action: result.submitted_action,
              action_label: result.action_label,
              checks: result.all_checks,
              requires_human_approval: true,
              rejection_reasons: result.rejection_reasons,
              comparison_id: null,
              summary: result.violated_check_detail,
              decision_hash: result.decision_hash,
            }}
          />
        </div>
      )}
    </div>
  );
}

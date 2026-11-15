"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import type { DecisionReceipt } from "@/lib/types";
import { IconAlertTriangle, IconCheck, IconReceipt, IconZap } from "./icons";
import { Badge, Button, Card, EmptyState, Eyebrow, Notice, PageHeader, ProvenanceTag, Spinner, cx } from "./ui";

export function ReceiptsView() {
  const { state } = useSession();
  const [receipt, setReceipt] = useState<DecisionReceipt | null>(null);
  const [generating, setGenerating] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verificationResult, setVerificationResult] = useState<{
    valid: boolean;
    recorded_digest: string;
    computed_digest: string;
    message: string;
  } | null>(null);
  const [humanApproved, setHumanApproved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = state.status?.session_id;

  const handleGenerate = async () => {
    if (!sessionId) return;
    setGenerating(true);
    setError(null);
    setVerificationResult(null);
    try {
      const res = await api.generateReceipt(sessionId, {
        human_approved: humanApproved,
        operator_id: humanApproved ? "OP-LENIN-BERKELEY" : undefined,
      });
      setReceipt(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  };

  const handleVerify = async (targetReceipt: DecisionReceipt) => {
    setVerifying(true);
    try {
      const res = await api.verifyReceipt(targetReceipt as unknown as Record<string, unknown>);
      setVerificationResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setVerifying(false);
    }
  };

  const simulateTampering = () => {
    if (!receipt) return;
    // Mutate one internal parameter to simulate malicious or accidental tampering
    const tampered = {
      ...receipt,
      input_provenance: {
        ...receipt.input_provenance,
        t_current_s: (receipt.input_provenance.t_current_s || 0) + 999.0,
      },
    };
    void handleVerify(tampered as DecisionReceipt);
  };

  const copyToClipboard = () => {
    if (!receipt) return;
    navigator.clipboard.writeText(JSON.stringify(receipt, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadJson = () => {
    if (!receipt) return;
    const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `decision-receipt-${receipt.receipt_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!state.status) {
    return (
      <EmptyState
        eyebrow="05 / Decision Receipts"
        title="No active session"
        action={
          <Link href="/">
            <Button variant="primary">Go to Mission Control</Button>
          </Link>
        }
      >
        Start a digital twin session on Mission Control to generate cryptographic decision receipts.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        index="05"
        section="Decision Receipts"
        title="Cryptographic Decision Receipts"
        description="Export structured, tamper-evident JSON decision receipts containing input telemetry digests, model versions, counterfactual scenarios, independent safety verifier results, and human approval status with SHA-256 integrity verification."
        meta={
          <div className="flex items-center gap-2">
            <ProvenanceTag kind="verified" />
            <Badge tone="cyan">SHA-256 Canonical Digest</Badge>
          </div>
        }
      />

      {/* Generator Controls */}
      <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2.5 cursor-pointer text-xs font-mono text-slate-300">
            <input
              type="checkbox"
              checked={humanApproved}
              onChange={(e) => setHumanApproved(e.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0"
            />
            <span>Sign with Human Operator Approval (OP-LENIN-BERKELEY)</span>
          </label>
        </div>

        <Button variant="primary" onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <Spinner className="h-4 w-4" />
          ) : (
            <span className="flex items-center gap-1.5">
              <IconReceipt className="h-4 w-4" />
              Generate Sealed Decision Receipt
            </span>
          )}
        </Button>
      </Card>

      {error && <Notice tone="rose">{error}</Notice>}

      {verificationResult && (
        <Notice tone={verificationResult.valid ? "emerald" : "rose"}>
          <div className="space-y-1">
            <div className="font-semibold">{verificationResult.message}</div>
            <div className="font-mono text-[11px] text-slate-300">
              Recorded: {verificationResult.recorded_digest.slice(0, 24)}... | Computed: {verificationResult.computed_digest.slice(0, 24)}...
            </div>
          </div>
        </Notice>
      )}

      {receipt && (
        <div className="space-y-6">
          {/* Header Card */}
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
              <div>
                <span className="font-mono text-xs uppercase text-slate-400">Decision Receipt ID</span>
                <h3 className="text-lg font-mono font-semibold text-cyan-400">{receipt.receipt_id}</h3>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={() => handleVerify(receipt)} disabled={verifying}>
                  {verifying ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : (
                    <span className="flex items-center gap-1">
                      <IconCheck className="h-3.5 w-3.5 text-emerald-400" />
                      Verify Integrity
                    </span>
                  )}
                </Button>
                <Button variant="secondary" onClick={simulateTampering} title="Simulates bit-flip or unauthorized payload modification">
                  <span className="flex items-center gap-1">
                    <IconAlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                    Simulate Tampering
                  </span>
                </Button>
                <Button variant="secondary" onClick={copyToClipboard}>
                  {copied ? "Copied!" : "Copy JSON"}
                </Button>
                <Button variant="secondary" onClick={downloadJson}>
                  Download .json
                </Button>
              </div>
            </div>

            {/* Digest Display */}
            <div className="mt-4 rounded bg-slate-950 p-3 font-mono text-xs text-slate-300">
              <div className="flex items-center justify-between text-slate-400">
                <span>SHA-256 Digest:</span>
                <Badge tone="cyan">VERIFIED 256-BIT</Badge>
              </div>
              <div className="mt-1 break-all text-slate-100 font-semibold">{receipt.sha256_digest}</div>
            </div>

            {/* Provenance Metadata Grid */}
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 font-mono text-xs">
              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <span className="text-[10px] text-slate-400 uppercase">Input Telemetry Hash</span>
                <div className="mt-1 truncate text-slate-200">{receipt.input_provenance.telemetry_window_sha256}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <span className="text-[10px] text-slate-400 uppercase">Copilot Model</span>
                <div className="mt-1 text-slate-200">{receipt.model_provenance.copilot_model}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <span className="text-[10px] text-slate-400 uppercase">Safety Verifier</span>
                <div className="mt-1 text-slate-200">{receipt.safety_verification.verdict.toUpperCase()}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <span className="text-[10px] text-slate-400 uppercase">Human Approval</span>
                <div className="mt-1 text-slate-200">{receipt.human_approval.status.toUpperCase()}</div>
              </div>
            </div>

            <p className="mt-4 text-[11px] leading-relaxed text-slate-400 italic border-t border-slate-800 pt-3">
              {receipt.audit_disclaimer}
            </p>
          </Card>

          {/* Raw Structured JSON Viewer */}
          <Card className="p-4">
            <Eyebrow className="mb-2">Canonical JSON Audit Payload</Eyebrow>
            <pre className="max-h-96 overflow-auto rounded bg-slate-950 p-4 font-mono text-[11px] leading-relaxed text-slate-300">
              {JSON.stringify(receipt, null, 2)}
            </pre>
          </Card>
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { MultimodalAnalysisResult, PreloadedAsset } from "@/lib/types";
import { IconCamera, IconZap } from "./icons";
import { Badge, Button, Card, Eyebrow, Notice, PageHeader, ProvenanceTag, Spinner, cx } from "./ui";

export function MultimodalView() {
  const [gallery, setGallery] = useState<PreloadedAsset[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<string>("bearing_ir_hotspot");
  const [customFileBase64, setCustomFileBase64] = useState<string | null>(null);
  const [customFileMime, setCustomFileMime] = useState<string>("image/jpeg");
  const [analysis, setAnalysis] = useState<MultimodalAnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .multimodalGallery()
      .then((items) => {
        setGallery(items);
        if (items.length > 0) setSelectedAssetId(items[0].asset_id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      let res: MultimodalAnalysisResult;
      if (customFileBase64) {
        res = await api.analyzeMultimodal({
          image_base64: customFileBase64,
          mime_type: customFileMime,
          component: "custom_upload",
        });
      } else {
        res = await api.analyzeMultimodal({
          asset_id: selectedAssetId,
        });
      }
      setAnalysis(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setError("File exceeds maximum allowed size (5 MB).");
      return;
    }
    setCustomFileMime(file.type || "image/jpeg");
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = (reader.result as string).split(",")[1];
      setCustomFileBase64(b64);
      setSelectedAssetId("");
    };
    reader.readAsDataURL(file);
  };

  const selectedAsset = gallery.find((a) => a.asset_id === selectedAssetId);

  return (
    <div className="space-y-8">
      <div>
        <Eyebrow>Multimodal Equipment Inspection</Eyebrow>
        <h2 className="text-xl font-semibold text-slate-100">
          Visual & Thermographic Evidence Interpretation
        </h2>
        <p className="mt-1 text-xs text-slate-400 max-w-2xl">
          Upload thermal infrared images, vibration spectrograms, or maintenance inspection photos.
          Gemini multimodal analysis strictly separates verified extracted evidence, model interpretation,
          and unverified assumptions. All uploads are treated as untrusted inputs with magic byte validation.
        </p>
      </div>

      {/* Asset Gallery Selector */}
      <div className="grid gap-4 sm:grid-cols-3">
        {gallery.map((asset) => {
          const active = asset.asset_id === selectedAssetId;
          return (
            <div
              key={asset.asset_id}
              onClick={() => {
                setSelectedAssetId(asset.asset_id);
                setCustomFileBase64(null);
                setAnalysis(null);
              }}
              className={cx(
                "cursor-pointer rounded-lg border p-4 transition-all",
                active
                  ? "border-cyan-400 bg-slate-900 shadow-md shadow-cyan-950/40"
                  : "border-slate-800 bg-slate-900/40 hover:border-slate-700",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase text-cyan-400">{asset.component}</span>
                <Badge tone="slate">{asset.simulated_fault}</Badge>
              </div>
              <h4 className="mt-2 text-sm font-semibold text-slate-100">{asset.name}</h4>
              <p className="mt-1 line-clamp-2 text-xs text-slate-400">{asset.description}</p>
            </div>
          );
        })}
      </div>

      {/* Custom Upload Option */}
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div>
          <span className="font-mono text-xs text-slate-300 font-semibold uppercase">Upload Untrusted Document / Image</span>
          <p className="mt-0.5 text-xs text-slate-400">Supports JPEG, PNG, WebP up to 5 MB. Strictly sanitized and validated.</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="cursor-pointer">
            <span className="rounded bg-slate-800 px-3 py-1.5 text-xs font-mono text-slate-200 hover:bg-slate-700">
              Browse Image...
            </span>
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFileUpload} className="hidden" />
          </label>
          <Button variant="primary" onClick={runAnalysis} disabled={analyzing || (!selectedAssetId && !customFileBase64)}>
            {analyzing ? (
              <Spinner className="h-4 w-4" />
            ) : (
              <span className="flex items-center gap-1.5">
                <IconZap className="h-3.5 w-3.5" />
                Run Multimodal Interpretation
              </span>
            )}
          </Button>
        </div>
      </Card>

      {error && <Notice tone="rose">{error}</Notice>}

      {/* Analysis Output */}
      {analysis && (
        <div className="space-y-6">
          <Card className="p-5 border-cyan-500/30">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-3">
                <Badge tone={analysis.source_type === "google_gemini_vision" ? "cyan" : "slate"}>
                  {analysis.source_type === "google_gemini_vision" ? "Gemini Multimodal Vision" : "Heuristic Multimodal Analyzer"}
                </Badge>
                <span className="font-mono text-xs text-slate-300 font-semibold">Evidence ID: {analysis.suggested_evidence_id}</span>
              </div>
              <span className="font-mono text-xs text-slate-400">Processed in {analysis.latency_ms} ms</span>
            </div>

            <div className="mt-4 grid gap-6 md:grid-cols-3">
              {/* 1. Extracted Evidence */}
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/10 p-4">
                <div className="flex items-center gap-2">
                  <span className="text-emerald-400 font-bold">1.</span>
                  <span className="font-mono text-xs uppercase tracking-wider text-emerald-300 font-semibold">
                    Extracted Physical Evidence
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-slate-400">Directly visible, verified physical measurements</p>
                <ul className="mt-3 space-y-2 text-xs text-slate-200">
                  {analysis.extracted_evidence.map((ev, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-emerald-400 font-bold">•</span>
                      <span>{ev}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* 2. Model Interpretation */}
              <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/10 p-4">
                <div className="flex items-center gap-2">
                  <span className="text-cyan-400 font-bold">2.</span>
                  <span className="font-mono text-xs uppercase tracking-wider text-cyan-300 font-semibold">
                    Diagnostic Interpretation
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-slate-400">Model-derived diagnostic inferences</p>
                <ul className="mt-3 space-y-2 text-xs text-slate-200">
                  {analysis.model_interpretation.map((interp, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-cyan-400 font-bold">•</span>
                      <span>{interp}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* 3. Unverified Assumptions */}
              <div className="rounded-lg border border-amber-500/20 bg-amber-950/10 p-4">
                <div className="flex items-center gap-2">
                  <span className="text-amber-400 font-bold">3.</span>
                  <span className="font-mono text-xs uppercase tracking-wider text-amber-300 font-semibold">
                    Unverified Assumptions
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-slate-400">Hypotheses lacking physical sensor confirmation</p>
                <ul className="mt-3 space-y-2 text-xs text-slate-200">
                  {analysis.unverified_assumptions.map((assump, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-amber-400 font-bold">•</span>
                      <span>{assump}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between border-t border-slate-800 pt-3 text-[11px] text-slate-400 font-mono">
              <span>SHA-256 Digest: {analysis.image_sha256}</span>
              <span>Recommended Fault Mode: <strong className="text-slate-200 uppercase">{analysis.recommended_fault_mode}</strong></span>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import { EvaluationView } from "@/components/evaluation-view";
import { MultimodalView } from "@/components/multimodal-view";
import { Segmented } from "@/components/ui";

const TABS = ["multimodal", "calibration"] as const;
type TabType = (typeof TABS)[number];

export default function EvidencePage() {
  const [tab, setTab] = useState<TabType>("multimodal");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="font-mono text-xs uppercase tracking-wider text-slate-400">
          Inspection & Evidence Registry
        </div>
        <Segmented
          options={TABS}
          value={tab}
          onChange={(v) => setTab(v)}
          format={(t) =>
            t === "multimodal" ? "Multimodal Equipment Inspection" : "Model Calibration & Benchmarks"
          }
        />
      </div>

      {tab === "multimodal" ? <MultimodalView /> : <EvaluationView />}
    </div>
  );
}

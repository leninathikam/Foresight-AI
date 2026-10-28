"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { simClock } from "@/lib/format";
import { useSession } from "@/lib/session-context";
import type { Health } from "@/lib/types";
import { StatusDot, cx } from "./ui";

const LINKS = [
  { href: "/", label: "Mission Control" },
  { href: "/futures", label: "Future Branching" },
  { href: "/agent", label: "Agent" },
  { href: "/evidence", label: "Evidence" },
  { href: "/diagnostics", label: "Diagnostics" },
];

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={className}>
      <path d="M2.5 12H10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path
        d="M10 12c3.2 0 4-6 10.5-6M10 12c3.2 0 4 6 10.5 6"
        stroke="currentColor"
        strokeOpacity="0.45"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path d="M10 12h10.5" stroke="var(--color-cyan-400)" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="12" r="2.2" fill="var(--color-slate-950)" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function Indicator({ tone, pulse, children, title }: { tone: Parameters<typeof StatusDot>[0]["tone"]; pulse?: boolean; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-2 font-mono text-[11px] text-slate-400">
      <StatusDot tone={tone} pulse={pulse} />
      {children}
    </span>
  );
}

export function Nav() {
  const pathname = usePathname();
  const { state } = useSession();
  const [health, setHealth] = useState<Health | null>(null);
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(h);
          setApiDown(false);
        }
      } catch {
        if (!cancelled) setApiDown(true);
      }
    };
    void poll();
    const id = setInterval(poll, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const s = state.status;
  return (
    <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-[1440px] items-stretch gap-10 px-6 lg:px-10">
        <Link href="/" className="flex items-center gap-2.5 text-slate-50">
          <LogoMark className="h-6 w-6" />
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Foresight</span>
          <span className="rounded-[3px] border border-slate-700 px-1 font-mono text-[9.5px] font-medium uppercase tracking-[0.12em] text-slate-400">
            AI
          </span>
        </Link>
        <nav className="flex flex-1 items-stretch gap-6 overflow-x-auto [scrollbar-width:none]">
          {LINKS.map((l) => {
            const active = pathname === l.href;
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cx(
                  "relative flex items-center whitespace-nowrap text-[13px] transition-colors",
                  active ? "text-slate-50" : "text-slate-500 hover:text-slate-200",
                )}
              >
                {l.label}
                {active && <span className="absolute inset-x-0 -bottom-px h-[2px] bg-slate-50" />}
              </Link>
            );
          })}
        </nav>
        <div className="hidden items-center gap-5 md:flex">
          {s && (
            <span className="font-mono text-[12px] tabular-nums text-slate-300">
              <span className="mr-1.5 text-slate-600">SIM</span>T+{simClock(s.sim_time_s)}
            </span>
          )}
          {state.sessionId && (
            <Indicator
              tone={state.connection === "live" ? "emerald" : state.connection === "error" ? "rose" : "amber"}
              pulse={state.connection === "live"}
              title="Server-sent event stream status"
            >
              Stream {state.connection}
            </Indicator>
          )}
          {apiDown ? (
            <Indicator tone="rose">API offline</Indicator>
          ) : health ? (
            <Indicator
              tone={health.llm_configured ? "cyan" : "slate"}
              title={
                health.llm_configured
                  ? "Meta Model API key configured on the server"
                  : "No MODEL_API_KEY: agent uses the deterministic planner"
              }
            >
              {health.llm_configured ? "Meta model connected" : "Deterministic planner"}
            </Indicator>
          ) : null}
        </div>
      </div>
    </header>
  );
}

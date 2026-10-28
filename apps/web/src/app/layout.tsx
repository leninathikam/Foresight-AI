import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { Nav } from "@/components/nav";
import { SessionProvider } from "@/lib/session-context";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Foresight AI — failure prevention for a simulated motor drive",
  description:
    "Digital twin, calibrated failure-risk models, counterfactual future branching, a deterministic safety verifier, and a bounded Meta-model agent. Simulation only.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-slate-950 text-slate-200">
        <SessionProvider>
          <Nav />
          <main className="mx-auto w-full max-w-[1440px] flex-1 px-6 py-8 lg:px-10">{children}</main>
          <footer className="border-t border-slate-800/80">
            <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-2 px-6 py-4 font-mono text-[11px] text-slate-500 lg:px-10">
              <span>
                Simulation only. Foresight AI never connects to or controls real equipment; all
                telemetry comes from the project&apos;s digital twin.
              </span>
              <span className="uppercase tracking-[0.12em]">Foresight AI</span>
            </div>
          </footer>
        </SessionProvider>
      </body>
    </html>
  );
}

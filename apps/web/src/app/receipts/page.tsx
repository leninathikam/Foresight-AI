import { ReceiptsView } from "@/components/receipts-view";

export const metadata = {
  title: "Decision Receipts · Foresight AI",
  description: "Cryptographically verifiable decision receipts with SHA-256 integrity proofs.",
};

export default function ReceiptsPage() {
  return <ReceiptsView />;
}

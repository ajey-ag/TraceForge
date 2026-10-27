import type { Metadata } from "next";
import "./style.css";

export const metadata: Metadata = {
  title: "TraceForge · CI investigations",
  description: "Evidence-backed CI diagnosis and controlled, verified repair",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}

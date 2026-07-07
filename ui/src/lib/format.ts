/** Small presentation helpers shared across components. */
import type { VerificationStatus } from "../types/domain";

/** Conditional className join. */
export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** 0..1 → integer percent string. */
export function pct(value: number): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

/** Coarse label mirroring the engine's confidence_label(). */
export function confidenceLabel(score: number): "high" | "medium" | "low" {
  if (score >= 0.66) return "high";
  if (score >= 0.33) return "medium";
  return "low";
}

/** Semantic color token name for a confidence score. */
export function confidenceTone(score: number): "success" | "warning" | "danger" {
  const label = confidenceLabel(score);
  return label === "high" ? "success" : label === "medium" ? "warning" : "danger";
}

export interface StatusMeta {
  label: string;
  tone: "success" | "warning" | "danger" | "muted";
  icon: string;
}

export function claimStatusMeta(status: VerificationStatus): StatusMeta {
  switch (status) {
    case "corroborated":
      return { label: "Corroborated", tone: "success", icon: "✓" };
    case "single_source":
      return { label: "Single source", tone: "warning", icon: "•" };
    case "contradicted":
      return { label: "Contradicted", tone: "danger", icon: "⚠" };
    default:
      return { label: "Unverified", tone: "muted", icon: "?" };
  }
}

/** A short glyph per source provider, for a bit of visual grounding. */
export function providerGlyph(provider: string): string {
  const p = provider.toLowerCase();
  if (p.includes("wiki")) return "W";
  if (p.includes("arxiv")) return "𝑎";
  if (p.includes("duck")) return "D";
  if (p.includes("offline")) return "○";
  return "◆";
}

export function hostOf(locator: string): string {
  try {
    return new URL(locator).host.replace(/^www\./, "");
  } catch {
    return locator;
  }
}

export function titleCase(text: string): string {
  return text.replace(/(^|[\s_])\w/g, (m) => m.toUpperCase()).replace(/_/g, " ");
}

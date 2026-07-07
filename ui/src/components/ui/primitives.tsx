import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { cn, pct } from "../../lib/format";

type Tone = "success" | "warning" | "danger" | "muted" | "info" | "accent";

const TONE_TEXT: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
  muted: "text-muted",
  accent: "text-accent",
};

const TONE_BG: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  muted: "bg-muted",
  accent: "bg-accent",
};

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-surface shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Badge({
  tone = "muted",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        "border-current/25",
        TONE_TEXT[tone],
        className,
      )}
      style={{ backgroundColor: "color-mix(in oklab, currentColor 12%, transparent)" }}
    >
      {children}
    </span>
  );
}

export function ToneDot({ tone, live }: { tone: Tone; live?: boolean }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        TONE_BG[tone],
        live && "livedot",
      )}
    />
  );
}

export function ConfidenceBar({
  value,
  tone = "accent",
  className,
}: {
  value: number;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      className={cn("h-2 w-full overflow-hidden rounded-full bg-surface2", className)}
      role="progressbar"
      aria-valuenow={Math.round(value * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-700 ease-out", TONE_BG[tone])}
        style={{ width: pct(Math.max(0, Math.min(1, value))) }}
      />
    </div>
  );
}

export function Stat({
  label,
  value,
  tone = "accent",
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className={cn("text-lg font-semibold tabular-nums", TONE_TEXT[tone])}>
        {value}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">
      {children}
    </h3>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted">
      {children}
    </div>
  );
}

export function ThemeToggle() {
  const [dark, setDark] = useState(
    () =>
      typeof document !== "undefined" &&
      document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    try {
      localStorage.setItem("re-theme", dark ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }, [dark]);
  return (
    <button
      type="button"
      onClick={() => setDark((d) => !d)}
      className="grid h-9 w-9 place-items-center rounded-lg border border-border bg-surface text-muted transition hover:text-text"
      aria-label="Toggle color theme"
      title="Toggle theme"
    >
      {dark ? "☾" : "☀"}
    </button>
  );
}

/**
 * Paper primitives.
 *
 * The shared vocabulary of the interface: sheets, ink rules, step chips, boxed
 * statistics, segmented meters, and the pastel document illustrations. Every
 * component here is pure presentation — no engine types, no data fetching — so
 * the design system stays independent of the domain model it renders.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { cn } from "../../lib/format";

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

/* ---- Sheets -------------------------------------------------------------- */

/**
 * A sheet of paper: hard ink hairline, square corners, flat offset shadow.
 * `lift` is the shadow offset in px — 0 for sheets that sit flush on the page.
 */
export function Card({
  className,
  lift = 4,
  children,
}: {
  className?: string;
  lift?: 0 | 2 | 4 | 6 | 8;
  children: ReactNode;
}) {
  const LIFT: Record<number, string> = {
    0: "lift-0",
    2: "lift-2",
    4: "",
    6: "lift-6",
    8: "lift-8",
  };
  return (
    <div className={cn(lift === 0 ? "sheet-flat" : "sheet", LIFT[lift], className)}>
      {children}
    </div>
  );
}

/** A hard horizontal rule — the boundary between two regions of a sheet. */
export function Rule({ className }: { className?: string }) {
  return <div className={cn("border-t-[1.5px] border-border", className)} />;
}

/* ---- Labels and marks ---------------------------------------------------- */

/** A square bordered tag. Tone colours the ink and a faint wash of fill. */
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
        "inline-flex items-center gap-1 border-[1.5px] px-1.5 py-px text-[11px] font-bold lowercase",
        "border-current",
        TONE_TEXT[tone],
        className,
      )}
      style={{ backgroundColor: "color-mix(in oklab, currentColor 10%, transparent)" }}
    >
      {children}
    </span>
  );
}

/** A boxed number, as used for ordered stages: `01`, `1`, `02`. */
export function StepChip({
  n,
  variant = "ink",
  className,
}: {
  n: number | string;
  variant?: "ink" | "paper";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-grid h-5 min-w-5 shrink-0 place-items-center border-[1.5px] border-border px-1 text-[11px] font-bold tabular-nums",
        variant === "ink" ? "bg-text text-surface" : "bg-surface text-text",
        className,
      )}
    >
      {n}
    </span>
  );
}

export function ToneDot({ tone, live }: { tone: Tone; live?: boolean }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 shrink-0 border border-border",
        TONE_BG[tone],
        live && "livedot",
      )}
    />
  );
}

/** Small lowercase caption above a block of content. */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 flex items-center gap-2 text-[11px] font-bold lowercase tracking-widest text-muted">
      <span className="inline-block h-2.5 w-2.5 border-[1.5px] border-border bg-coral" />
      {children}
    </h3>
  );
}

/**
 * A numbered section header bar: boxed index, ink icon slab, lowercase title.
 * The signature grouping device — one per major stage of a run.
 */
export function SectionHeader({
  index,
  icon,
  title,
  meta,
}: {
  index: string;
  icon: ReactNode;
  title: string;
  meta?: ReactNode;
}) {
  return (
    <div className="flex items-stretch gap-3 border-b-[1.5px] border-border bg-surface px-3 py-2.5">
      <span className="grid w-11 shrink-0 place-items-center border-[1.5px] border-border text-xs font-bold tabular-nums">
        {index}
      </span>
      <span className="grid h-9 w-9 shrink-0 place-items-center border-[1.5px] border-border bg-text text-base text-surface">
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 items-center">
        <span className="truncate text-lg font-bold lowercase">{title}</span>
      </span>
      {meta && (
        <span className="flex shrink-0 items-center text-xs text-muted">{meta}</span>
      )}
    </div>
  );
}

/* ---- Measurements -------------------------------------------------------- */

/**
 * A segmented meter. Discrete cells rather than a smooth bar: the engine's
 * scores are measurements, and a printed gauge reads as one.
 */
export function ConfidenceBar({
  value,
  tone = "accent",
  cells = 20,
  className,
}: {
  value: number;
  tone?: Tone;
  cells?: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value ?? 0));
  const filled = Math.round(clamped * cells);
  return (
    <div
      className={cn(
        "flex h-3 w-full gap-px border-[1.5px] border-border bg-surface2 p-px",
        className,
      )}
      role="progressbar"
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      {Array.from({ length: cells }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "h-full flex-1 transition-colors duration-300",
            i < filled ? TONE_BG[tone] : "bg-transparent",
          )}
        />
      ))}
    </div>
  );
}

/** An inline statistic: mono value over a lowercase caption. */
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
      <span
        className={cn("text-xl font-bold tabular-nums", TONE_TEXT[tone])}
      >
        {value}
      </span>
      <span className="text-[11px] lowercase text-muted">{label}</span>
    </div>
  );
}

/** A boxed statistic — a sheet of its own, for headline figures. */
export function StatBox({
  value,
  label,
  sub,
}: {
  value: ReactNode;
  label: string;
  sub?: string;
}) {
  return (
    <div className="sheet lift-6 px-4 py-5 text-center">
      <div className="display display-sm text-3xl tabular-nums">{value}</div>
      <div className="mt-2 text-xs lowercase text-text">{label}</div>
      {sub && <div className="mt-0.5 text-[11px] lowercase text-muted">{sub}</div>}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="border-[1.5px] border-dashed border-border px-4 py-10 text-center text-sm lowercase text-muted">
      {children}
    </div>
  );
}

/* ---- Illustration -------------------------------------------------------- */

const STOCKS = [
  "var(--color-p-pink)",
  "var(--color-p-violet)",
  "var(--color-p-mint)",
  "var(--color-p-cream)",
  "var(--color-p-sky)",
];

/** One document glyph: a page with a folded corner and ruled lines. */
function Doc({
  fill,
  rotate = 0,
  size = 44,
}: {
  fill: string;
  rotate?: number;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size * 1.25}
      viewBox="0 0 40 50"
      style={{ transform: `rotate(${rotate}deg)` }}
      className="shrink-0 text-border"
      aria-hidden="true"
    >
      <g stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round">
        <path d="M2.5 2.5h23l12 12v33.5H2.5z" fill={fill} />
        <path d="M25.5 2.5v12h12" fill="none" />
        <g strokeLinecap="round">
          <path d="M9 25h22M9 32h22M9 39h14" />
        </g>
      </g>
    </svg>
  );
}

/**
 * A scattered row of paper stock — the pile of documents a run reads through.
 * Purely decorative; hidden from assistive tech and from small viewports where
 * it would compete with the content.
 */
export function PaperDocs({ className }: { className?: string }) {
  const docs: { rotate: number; size: number; offset: number }[] = [
    { rotate: -4, size: 40, offset: 10 },
    { rotate: 3, size: 46, offset: 0 },
    { rotate: -1, size: 38, offset: 16 },
    { rotate: 8, size: 44, offset: 4 },
    { rotate: -6, size: 42, offset: 12 },
    { rotate: 2, size: 48, offset: 0 },
    { rotate: -3, size: 36, offset: 18 },
    { rotate: 5, size: 43, offset: 6 },
    { rotate: -8, size: 41, offset: 14 },
    { rotate: 1, size: 45, offset: 2 },
  ];
  return (
    <div
      className={cn(
        "pointer-events-none hidden select-none items-end justify-center gap-1 overflow-hidden sm:flex",
        className,
      )}
      aria-hidden="true"
    >
      {docs.map((d, i) => (
        <span key={i} style={{ marginBottom: d.offset }}>
          <Doc fill={STOCKS[i % STOCKS.length]} rotate={d.rotate} size={d.size} />
        </span>
      ))}
    </div>
  );
}

/* ---- Theme -------------------------------------------------------------- */

/** Switches the sheet between paper (light) and carbon (dark). */
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
      className="btn-paper h-8 w-8 text-sm"
      aria-label={dark ? "Switch to paper theme" : "Switch to carbon theme"}
      title={dark ? "paper" : "carbon"}
    >
      {dark ? "☾" : "☀"}
    </button>
  );
}

import clsx from "clsx";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { ApiError } from "../api/client";

export function Panel({ title, action, children, className }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("rounded-xl border border-line bg-panel p-4", className)}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold tracking-wide text-muted uppercase">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Button({ variant = "primary", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  return (
    <button
      {...p}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent text-white hover:brightness-110",
        variant === "ghost" && "border border-line bg-panel-2 text-fg hover:border-accent",
        variant === "danger" && "bg-loss text-white hover:brightness-110",
        className,
      )}
    />
  );
}

export function Input(p: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={clsx("w-full rounded-lg border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent", p.className)} />;
}

export function Select(p: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...p} className={clsx("rounded-lg border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent", p.className)} />;
}

export function Field({ label, error, children, hint }: { label: string; error?: string | null; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-muted">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-muted">{hint}</span>}
      {error && <span role="alert" className="block text-xs text-loss">{error}</span>}
    </label>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 p-6 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line p-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-loss/40 bg-loss/10 p-4 text-sm">
      <p className="font-medium text-loss">Could not load this data</p>
      <p className="mt-1 text-muted">{errorMessage(error)}</p>
      {onRetry && (
        <Button variant="ghost" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "gain" | "loss" | "warn" | "accent" }) {
  const tones = {
    muted: "bg-panel-2 text-muted",
    gain: "bg-gain/15 text-gain",
    loss: "bg-loss/15 text-loss",
    warn: "bg-warn/15 text-warn",
    accent: "bg-accent/15 text-accent",
  };
  return <span className={clsx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

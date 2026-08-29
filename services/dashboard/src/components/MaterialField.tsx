import { useState } from "react";

interface MaterialSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<[string, string]>;
  emptyValue?: string;
  className?: string;
}

export function MaterialSelect({ label, value, onChange, options, emptyValue = "", className = "" }: MaterialSelectProps) {
  const [focused, setFocused] = useState(false);
  const filled = value !== emptyValue;
  const floated = focused || filled;

  return <label className={`relative block min-w-[150px] ${className}`}>
    <span data-floating={floated} className={`pointer-events-none absolute left-3 z-10 bg-bg-card px-1 transition-all ${floated ? "-top-2 text-[10px] font-medium text-brand-primary" : "top-1/2 -translate-y-1/2 text-body-copy text-text-muted"}`}>{label}</span>
    <select
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className={`h-12 w-full rounded-xl border bg-bg-card px-3 pt-2 text-body-copy outline-none transition focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/15 ${focused ? "border-brand-primary" : "border-border-subtle"} ${!floated ? "text-transparent" : "text-text-body"}`}
    >
      {options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}
    </select>
  </label>;
}

interface MaterialTextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "search" | "date" | "text";
  className?: string;
}

export function MaterialTextField({ label, value, onChange, type = "text", className = "" }: MaterialTextFieldProps) {
  const [focused, setFocused] = useState(false);
  const floated = focused || Boolean(value) || type === "date";

  return <label className={`relative block ${className}`}>
    <span data-floating={floated} className={`pointer-events-none absolute left-3 z-10 bg-bg-card px-1 transition-all ${floated ? "-top-2 text-[10px] font-medium text-brand-primary" : "top-1/2 -translate-y-1/2 text-body-copy text-text-muted"}`}>{label}</span>
    <input
      aria-label={label}
      type={type}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className={`h-12 w-full rounded-xl border bg-bg-card px-4 pt-2 text-body-copy text-text-body outline-none transition focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/15 ${focused ? "border-brand-primary" : "border-border-subtle"}`}
    />
  </label>;
}

interface MaterialButtonFieldProps {
  label: string;
  value: string;
  emptyHint?: string;
  expanded: boolean;
  controls?: string;
  onClick: () => void;
}

export function MaterialButtonField({ label, value, emptyHint = "", expanded, controls, onClick }: MaterialButtonFieldProps) {
  const floated = expanded || Boolean(value);
  return <div className="relative min-w-[150px]">
    <span data-floating={floated} className={`pointer-events-none absolute left-3 z-10 bg-bg-card px-1 transition-all ${floated ? "-top-2 text-[10px] font-medium text-brand-primary" : "top-1/2 -translate-y-1/2 text-body-copy text-text-muted"}`}>{label}</span>
    <button type="button" aria-label={label} aria-expanded={expanded} aria-controls={controls} onClick={onClick} className={`flex h-12 w-full items-center justify-between gap-3 rounded-xl border bg-bg-card px-3 pt-2 text-body-copy text-text-body outline-none transition focus-visible:ring-2 focus-visible:ring-brand-primary/15 ${expanded ? "border-brand-primary" : "border-border-subtle"}`}>
      <span>{value || (expanded ? emptyHint : "")}</span><span aria-hidden="true">▾</span>
    </button>
  </div>;
}

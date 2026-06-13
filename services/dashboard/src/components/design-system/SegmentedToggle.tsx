export type HorizonOption = "24H" | "3D" | "7D" | "14D";

interface SegmentedToggleProps {
  value: HorizonOption;
  onChange: (value: HorizonOption) => void;
  options?: HorizonOption[];
  label?: string;
}

export function SegmentedToggle({ value, onChange, options = ["24H", "3D", "7D", "14D"], label = "Forecast horizon" }: SegmentedToggleProps) {
  return (
    <div className="inline-flex rounded-full border border-border-subtle bg-bg-card p-1 shadow-card" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          className={[
            "numeric-tabular rounded-full px-4 py-2 text-control outline-none transition focus-visible:ring-2 focus-visible:ring-brand-primary",
            value === option ? "bg-brand-primary text-white shadow-card" : "text-text-muted hover:bg-bg-app hover:text-text-strong"
          ].join(" ")}
          onClick={() => onChange(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

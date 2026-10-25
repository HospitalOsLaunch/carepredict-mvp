export function Mark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <circle cx="16" cy="16" r="14" fill="#FFB21E" />
      <circle cx="16" cy="16" r="14" fill="none" stroke="#FFD36B" strokeWidth="2" />
      <circle cx="16" cy="16" r="6" fill="#5B3DF5" />
    </svg>
  );
}

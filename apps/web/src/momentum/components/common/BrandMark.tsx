/** Momentum logo mark: an upward "M" stroke on the brand accent. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden style={{ flexShrink: 0 }}>
      <rect width="32" height="32" rx="8" style={{ fill: 'var(--accent)' }} />
      <path
        d="M8 22V11l8 7 8-7v11"
        fill="none"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: 'var(--on-accent)' }}
      />
    </svg>
  );
}

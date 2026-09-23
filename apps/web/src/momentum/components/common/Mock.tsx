/** Dev-only marker for mock data (purple). Never rendered in production builds. */
export function MockBadge({ label = 'Mock' }: { label?: string }) {
  if (!import.meta.env.DEV) return null;
  return (
    <span className="rounded-sm border border-mock px-1 font-mono text-[10px] uppercase leading-4 tracking-wide text-mock">
      {label}
    </span>
  );
}

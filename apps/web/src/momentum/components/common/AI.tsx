import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { MoMark } from './MoMark';

/** Container for anything written or proposed by Mo or an agent (amber = AI only). */
export function AICallout({
  label = 'Mo',
  children,
  actions,
  className,
}: {
  label?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={`${label} (AI)`}
      className={cn(
        'relative rounded-lg border border-dashed border-amber bg-amber-2/60 py-3 pl-4 pr-3',
        "before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-amber before:content-['']",
        className,
      )}
    >
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-amber-ink">
        <MoMark size={13} />
        {label}
      </div>
      <div className="text-sm text-ink-2">{children}</div>
      {actions ? <div className="mt-2 flex gap-2">{actions}</div> : null}
    </section>
  );
}

/** Small marker for AI-authored items (comments, fields, status updates). */
export function AIBadge({ title = 'Drafted by Mo' }: { title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-ink">
      <MoMark size={11} /> AI
    </span>
  );
}

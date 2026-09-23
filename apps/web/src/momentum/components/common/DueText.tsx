import { cn } from '@/lib/cn';
import { dueTone, formatDue } from '@/lib/dates';

const TONE = {
  overdue: 'text-crit',
  today: 'text-warn',
  soon: 'text-ink-2',
  later: 'text-ink-2',
  done: 'text-muted-2 line-through',
} as const;

/** Due date text. Colour lives in the text only: overdue = crit, today = warn, done = muted. */
export function DueText({
  dueOn,
  dueAt = null,
  startOn = null,
  done = false,
  className,
}: {
  dueOn: string | null;
  dueAt?: string | null;
  startOn?: string | null;
  done?: boolean;
  className?: string;
}) {
  if (!dueOn) return null;
  const tone = dueTone(dueOn, dueAt, done);
  return (
    <span data-tone={tone} className={cn('tabular truncate text-[12.5px]', TONE[tone], className)}>
      {formatDue(dueOn, dueAt, startOn)}
    </span>
  );
}

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Calendar } from '@/components/common/Calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { addDays, formatDue, nextWeek, parseNaturalDate, toISODate, type DueValue } from '@/lib/dates';

/** Due date popover: type a date ("next fri", "tomorrow 5pm"), pick a quick option, or use the calendar. */
export function DatePicker({
  open,
  onOpenChange,
  dueOn,
  dueAt,
  onChange,
  allowClear = false,
  children,
}: {
  allowClear?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dueOn: string | null;
  dueAt: string | null;
  onChange: (value: DueValue | null) => void;
  children: ReactNode;
}) {
  const [text, setText] = useState('');
  useEffect(() => {
    if (open) setText('');
  }, [open]);
  const parsed = useMemo(() => parseNaturalDate(text), [text]);
  const apply = (v: DueValue | null) => {
    onOpenChange(false);
    if (allowClear || (v?.date ?? null) !== dueOn || (v?.at ?? null) !== dueAt) onChange(v);
  };
  const today = new Date();
  const quick: { label: string; value: DueValue | null }[] = [
    { label: 'Today', value: { date: toISODate(today), at: null } },
    { label: 'Tomorrow', value: { date: toISODate(addDays(today, 1)), at: null } },
    { label: 'Next week', value: { date: toISODate(nextWeek(today)), at: null } },
  ];

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-[272px] p-0" align="end">
        <div className="border-b border-hair-soft p-2">
          <input
            aria-label="Due date"
            placeholder="Type a date: next fri, in 3 days…"
            value={text}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the picker was opened to type a date
            autoFocus
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && parsed) {
                e.preventDefault();
                apply(parsed);
              }
            }}
            className="h-8 w-full rounded-md border border-hairline bg-surface px-2 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
          />
          <p className="mt-1 h-4 px-0.5 text-xs text-muted" aria-live="polite">
            {text.trim()
              ? parsed
                ? `↵ ${formatDue(parsed.date, parsed.at)}`
                : "Couldn't read that date"
              : dueOn
                ? `Due ${formatDue(dueOn, dueAt)}`
                : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-1 border-b border-hair-soft p-2">
          {quick.map((q) => (
            <QuickPick key={q.label} onClick={() => apply(q.value)}>
              {q.label}
            </QuickPick>
          ))}
          {dueOn || allowClear ? <QuickPick onClick={() => apply(null)}>No date</QuickPick> : null}
        </div>
        <Calendar selected={dueOn} onSelect={(date) => apply({ date, at: null })} />
      </PopoverContent>
    </Popover>
  );
}

function QuickPick({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-7 rounded-md bg-surface-2 px-2 text-xs text-ink-2 hover:bg-accent-tint focus-visible:outline-2 focus-visible:outline-focus"
    >
      {children}
    </button>
  );
}

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { addDays, fromISODate, toISODate } from '@/lib/dates';

const MONTH = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
const DAY_LABEL = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
// Monday-first weekday initials
const WEEKDAYS = Array.from({ length: 7 }, (_, i) =>
  new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(new Date(2024, 0, 1 + i)),
);

/** Month grid (Monday first) with arrow-key navigation over days. Shared by the due-date picker
 * (`features/tasks/DatePicker.tsx`) and custom date fields (`features/fields`) — lives here,
 * not in either feature, so importing it from one never risks a cycle through the other. */
export function Calendar({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (date: string) => void;
}) {
  const todayIso = toISODate(new Date());
  const [focus, setFocus] = useState(selected ?? todayIso);
  const focusDate = fromISODate(focus);
  const [month, setMonth] = useState(() => new Date(focusDate.getFullYear(), focusDate.getMonth(), 1));
  const grid = useRef<HTMLDivElement>(null);
  const moved = useRef(false);

  useEffect(() => {
    if (!moved.current) return;
    grid.current?.querySelector<HTMLButtonElement>(`[data-date="${focus}"]`)?.focus();
  }, [focus, month]);

  const lead = (month.getDay() + 6) % 7;
  const start = addDays(month, -lead);
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));

  const moveTo = (d: Date) => {
    moved.current = true;
    setFocus(toISODate(d));
    if (d.getMonth() !== month.getMonth() || d.getFullYear() !== month.getFullYear())
      setMonth(new Date(d.getFullYear(), d.getMonth(), 1));
  };
  const shiftMonth = (n: number) => {
    const first = new Date(month.getFullYear(), month.getMonth() + n, 1);
    moved.current = false;
    setMonth(first);
    setFocus(toISODate(first));
  };
  const weeks = Array.from({ length: 6 }, (_, w) => days.slice(w * 7, w * 7 + 7));
  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (step) {
      e.preventDefault();
      moveTo(addDays(focusDate, step));
    }
  };

  return (
    <div className="p-2">
      <div className="mb-1 flex items-center justify-between">
        <IconButton icon={ChevronLeft} label="Previous month" size="icon-sm" onClick={() => shiftMonth(-1)} />
        <span className="text-sm font-medium">{MONTH.format(month)}</span>
        <IconButton icon={ChevronRight} label="Next month" size="icon-sm" onClick={() => shiftMonth(1)} />
      </div>
      <div className="grid grid-cols-7 text-center text-[11px] text-muted-2">
        {WEEKDAYS.map((w, i) => (
          <span key={i} className="py-1">
            {w}
          </span>
        ))}
      </div>
      <div
        ref={grid}
        role="grid"
        tabIndex={-1}
        aria-label={MONTH.format(month)}
        className="grid grid-cols-7"
        onKeyDown={onKey}
      >
        {weeks.map((week, w) => (
          <div key={w} role="row" className="contents">
            {week.map((d) => {
              const iso = toISODate(d);
              const outside = d.getMonth() !== month.getMonth();
              const isSelected = iso === selected;
              return (
                <button
                  key={iso}
                  type="button"
                  role="gridcell"
                  data-date={iso}
                  aria-label={DAY_LABEL.format(d)}
                  aria-selected={isSelected}
                  tabIndex={iso === focus ? 0 : -1}
                  onClick={() => onSelect(iso)}
                  className={cn(
                    'tabular m-px flex h-8 items-center justify-center rounded-md text-[12.5px] hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-focus',
                    outside && 'text-muted-2',
                    iso === todayIso && !isSelected && 'font-semibold text-ink ring-1 ring-hairline',
                    isSelected && 'bg-accent text-on-accent hover:bg-accent-hover',
                  )}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

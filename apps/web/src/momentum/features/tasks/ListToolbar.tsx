import { ArrowUpDown, CheckCircle2, ListFilter, Rows3, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { usePeople } from '@/features/people';
import { cn } from '@/lib/cn';
import {
  DEFAULT_VIEW,
  DUE_LABEL,
  filterCount,
  GROUP_LABEL,
  isDefaultView,
  SORT_LABEL,
  type DueFilter,
  type GroupKey,
  type ListView,
  type SortKey,
} from './view';

/** Filter / Sort / Group / Show completed for the list; every change goes through `onChange`. */
export function ListToolbar({ view, onChange }: { view: ListView; onChange: (v: ListView) => void }) {
  const n = filterCount(view);
  return (
    <div role="toolbar" aria-label="List view options" className="mb-3 flex flex-wrap items-center gap-1">
      <FilterPopover view={view} onChange={onChange}>
        <Button size="sm" variant={n ? 'ghost' : 'text'} className={cn(n > 0 && 'text-ink')}>
          <Icon icon={ListFilter} /> Filter
          {n ? (
            <span className="tabular rounded-full bg-accent px-1.5 text-[11px] text-on-accent">{n}</span>
          ) : null}
        </Button>
      </FilterPopover>
      <Choice
        icon={ArrowUpDown}
        label="Sort"
        value={view.sort}
        labels={SORT_LABEL}
        isDefault={view.sort === 'manual'}
        onPick={(sort: SortKey) => onChange({ ...view, sort })}
      />
      <Choice
        icon={Rows3}
        label="Group"
        value={view.group}
        labels={GROUP_LABEL}
        isDefault={view.group === 'section'}
        onPick={(group: GroupKey) => onChange({ ...view, group })}
      />
      {!isDefaultView({ ...view, show_completed: false }) ? (
        <Button
          size="sm"
          variant="text"
          onClick={() => onChange({ ...DEFAULT_VIEW, show_completed: view.show_completed })}
        >
          <Icon icon={X} /> Clear
        </Button>
      ) : null}
      <span className="flex-1" />
      <Button
        size="sm"
        variant="text"
        aria-pressed={view.show_completed}
        onClick={() => onChange({ ...view, show_completed: !view.show_completed })}
      >
        <Icon icon={CheckCircle2} /> {view.show_completed ? 'Hide completed' : 'Show completed'}
      </Button>
    </div>
  );
}

function Choice<K extends string>({
  icon,
  label,
  value,
  labels,
  isDefault,
  onPick,
}: {
  icon: typeof ArrowUpDown;
  label: string;
  value: K;
  labels: Record<K, string>;
  isDefault: boolean;
  onPick: (k: K) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant={isDefault ? 'text' : 'ghost'} className={cn(!isDefault && 'text-ink')}>
          <Icon icon={icon} /> {isDefault ? label : `${label}: ${labels[value]}`}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {(Object.keys(labels) as K[]).map((k) => (
          <DropdownMenuItem
            key={k}
            onSelect={() => onPick(k)}
            aria-checked={k === value}
            role="menuitemradio"
          >
            <span className={cn('w-4', k !== value && 'invisible')}>✓</span> {labels[k]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function FilterPopover({
  view,
  onChange,
  children,
}: {
  view: ListView;
  onChange: (v: ListView) => void;
  children: ReactNode;
}) {
  const [q, setQ] = useState('');
  const people = usePeople().data ?? [];
  const toggle = (token: string) =>
    onChange({
      ...view,
      assignees: view.assignees.includes(token)
        ? view.assignees.filter((a) => a !== token)
        : [...view.assignees, token],
    });
  const shown = people.filter((p) => !q || `${p.name} ${p.email}`.toLowerCase().includes(q.toLowerCase()));
  // a render helper, not a component: a nested component would remount (and drop focus) on each toggle
  const check = (token: string, label: string, avatar?: string) => (
    <label
      key={token}
      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2"
    >
      <input
        type="checkbox"
        checked={view.assignees.includes(token)}
        onChange={() => toggle(token)}
        className="accent-[var(--accent)]"
      />
      {avatar ? <Avatar name={avatar} size={18} /> : null}
      <span className="truncate">{label}</span>
    </label>
  );
  return (
    <Popover onOpenChange={(o) => !o && setQ('')}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-72 p-2">
        <fieldset>
          <legend className="section-label px-2 pb-1">Assignee</legend>
          {check('me', 'Just my tasks')}
          {check('none', 'Unassigned')}
          {people.length > 8 ? (
            <input
              aria-label="Search people"
              placeholder="Search people…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="my-1 h-8 w-full rounded-md border border-hairline bg-surface px-2 text-sm outline-none focus:border-focus"
            />
          ) : null}
          <div className="max-h-48 overflow-auto">{shown.map((p) => check(p.id, p.name, p.name))}</div>
        </fieldset>
        <fieldset className="mt-2 border-t border-hair-soft pt-2">
          <legend className="section-label px-2 pb-1">Due date</legend>
          <div className="flex flex-wrap gap-1 px-1">
            {(Object.keys(DUE_LABEL) as DueFilter[]).map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={view.due === d}
                onClick={() => onChange({ ...view, due: d })}
                className={cn(
                  'h-7 rounded-md px-2 text-xs',
                  view.due === d
                    ? 'bg-accent text-on-accent'
                    : 'bg-surface-2 text-ink-2 hover:bg-accent-tint',
                )}
              >
                {DUE_LABEL[d]}
              </button>
            ))}
          </div>
        </fieldset>
      </PopoverContent>
    </Popover>
  );
}

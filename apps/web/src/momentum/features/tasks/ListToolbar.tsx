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
import { AskFilters, type FilterDraft } from '@/features/ai';
import { FieldFilterChips, FieldFilterSection, type Field } from '@/features/fields';
import { LIST_GROUPABLE } from '@/features/fields';
import { usePeople } from '@/features/people';
import { useTagLibrary } from '@/features/tags';
import { cn } from '@/lib/cn';
import { tintColors } from '@/lib/tint';
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

/** Filter / Sort / Group / Show completed for the list; every change goes through `onChange`.
 * `fields` (S7.4.1) are the project's custom fields: filter, sort and group by them too. */
export function ListToolbar({
  view,
  onChange,
  fields = [],
  filtersOnly = false,
  ask,
}: {
  view: ListView;
  onChange: (v: ListView) => void;
  fields?: readonly Field[];
  /** Board and calendar: filters only (sort, group and completed are the list's). */
  filtersOnly?: boolean;
  /** S75-11: "Describe what to show…" for this project view (Mo drafts, you Apply). */
  ask?: { surface: 'list' | 'board' | 'calendar'; projectId: string };
}) {
  // the view Mo's filters produced: the amber marker stays until the filters are edited
  const [mo, setMo] = useState<{ draft: FilterDraft; view: ListView; before: ListView } | null>(null);
  const applied = mo && JSON.stringify(mo.view) === JSON.stringify(view) ? mo.draft : null;
  const n = filterCount(view);
  const sortLabels = {
    ...SORT_LABEL,
    ...Object.fromEntries(fields.map((f) => [`field:${f.id}`, f.name])),
  } as Record<SortKey, string>;
  const groupLabels = {
    ...GROUP_LABEL,
    ...Object.fromEntries(
      fields.filter((f) => LIST_GROUPABLE.includes(f.type)).map((f) => [`field:${f.id}`, f.name]),
    ),
  } as Record<GroupKey, string>;
  return (
    <>
      {ask ? (
        <AskFilters
          surface={ask.surface}
          projectId={ask.projectId}
          applied={applied}
          onApply={(d) => {
            const next = { ...view, ...(d.filters as Partial<ListView>) };
            setMo({ draft: d, view: next, before: view });
            onChange(next);
          }}
          onClear={() => {
            if (mo) onChange(mo.before);
            setMo(null);
          }}
        />
      ) : null}
      <div role="toolbar" aria-label="List view options" className="mb-3 flex flex-wrap items-center gap-1">
        <FilterPopover view={view} onChange={onChange} fields={fields}>
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
          labels={sortLabels}
          isDefault={view.sort === 'manual'}
          onPick={(sort: SortKey) => onChange({ ...view, sort })}
        />
        <Choice
          icon={Rows3}
          label="Group"
          value={view.group}
          labels={groupLabels}
          isDefault={view.group === 'section'}
          onPick={(group: GroupKey) => onChange({ ...view, group })}
        />
        {(filtersOnly ? filterCount(view) > 0 : !isDefaultView({ ...view, show_completed: false })) ? (
          <Button
            size="sm"
            variant="text"
            onClick={() =>
              onChange(
                filtersOnly
                  ? { ...view, assignees: [], tags: [], due: 'any', fields: [] }
                  : { ...DEFAULT_VIEW, show_completed: view.show_completed },
              )
            }
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
      <FieldFilterChips
        fields={fields}
        value={view.fields}
        onChange={(f) => onChange({ ...view, fields: f })}
      />
    </>
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
          <Icon icon={icon} /> {isDefault ? label : `${label}: ${labels[value] ?? 'a removed field'}`}
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
  fields,
  children,
}: {
  view: ListView;
  onChange: (v: ListView) => void;
  fields: readonly Field[];
  children: ReactNode;
}) {
  const [q, setQ] = useState('');
  const people = usePeople('', 'all').data ?? [];
  const tags = useTagLibrary().data ?? [];
  const toggle = (token: string) =>
    onChange({
      ...view,
      assignees: view.assignees.includes(token)
        ? view.assignees.filter((a) => a !== token)
        : [...view.assignees, token],
    });
  const toggleTag = (id: string) =>
    onChange({
      ...view,
      tags: view.tags.includes(id) ? view.tags.filter((t) => t !== id) : [...view.tags, id],
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
      <PopoverContent className="max-h-[min(80vh,640px)] w-80 overflow-auto p-2">
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
        {tags.length ? (
          <fieldset className="mt-2 border-t border-hair-soft pt-2">
            <legend className="section-label px-2 pb-1">Tags</legend>
            <div className="flex max-h-32 flex-wrap gap-1 overflow-auto px-1">
              {tags.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={view.tags.includes(t.id)}
                  onClick={() => toggleTag(t.id)}
                  className={cn(
                    'h-7 rounded-md px-2 text-xs font-medium',
                    view.tags.includes(t.id) ? 'bg-accent text-on-accent' : 'bg-surface-2',
                  )}
                  style={view.tags.includes(t.id) ? undefined : { color: tintColors(t.color).color }}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </fieldset>
        ) : null}
        <FieldFilterSection
          fields={fields}
          value={view.fields}
          onChange={(f) => onChange({ ...view, fields: f })}
        />
      </PopoverContent>
    </Popover>
  );
}

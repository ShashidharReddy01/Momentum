import { Filter, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { useProjectFieldDefs } from '@/features/fields';
import { usePortfolios } from '@/features/portfolios';
import { cn } from '@/lib/cn';
import { activeFilters, type DashboardFilters } from './queries';

/**
 * Phase 7.5 (spec §7.3): a dashboard's filters. Changing them changes the view **for you** (kept
 * in the URL, so a link shares it); an editor can save them as the dashboard's own, which every
 * viewer then starts from. "Me" is always the person looking, so one saved dashboard serves
 * everyone.
 */

const PERIODS: [string, string][] = [
  ['', 'Any period'],
  ['this_week', 'This week'],
  ['this_month', 'This month'],
  ['last_30_days', 'Last 30 days'],
  ['this_quarter', 'This quarter'],
];
type Condition = DashboardFilters['fields'] extends (infer C)[] | undefined ? C : never;

/** The viewer's filters for this view, from the URL (`?filters=<json>`), or null. */
export function useViewFilters(): [DashboardFilters | null, (f: DashboardFilters | null) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get('filters');
  const view = useMemo(() => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as DashboardFilters;
    } catch {
      return null;
    }
  }, [raw]);
  const set = (f: DashboardFilters | null) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        const active = activeFilters(f);
        if (active) next.set('filters', JSON.stringify(active));
        else next.delete('filters');
        return next;
      },
      { replace: true },
    );
  return [view, set];
}

const same = (a: DashboardFilters | null, b: DashboardFilters | null) =>
  JSON.stringify(activeFilters(a)) === JSON.stringify(activeFilters(b));

export function FilterBar({
  saved,
  view,
  onView,
  canSave,
  onSave,
  lockPortfolio = false,
}: {
  saved: DashboardFilters | null;
  view: DashboardFilters | null;
  onView: (f: DashboardFilters | null) => void;
  canSave: boolean;
  onSave: (f: DashboardFilters | null) => void;
  /** a portfolio's own tab: its portfolio is fixed */
  lockPortfolio?: boolean;
}) {
  const current: DashboardFilters = (view ?? saved ?? {}) as DashboardFilters;
  const portfolios = usePortfolios();
  const defs = useProjectFieldDefs();
  const [adding, setAdding] = useState<string>('');
  const pickable = (defs.data ?? []).filter((f) => f.type === 'single_select' || f.type === 'people');
  const change = (patch: Partial<DashboardFilters>) => onView({ ...current, ...patch } as DashboardFilters);
  const toggleMe = (key: 'owner' | 'assignee') =>
    change({ [key]: (current[key] ?? []).includes('me') ? [] : ['me'] });
  const conditions: Condition[] = current.fields ?? [];
  const label = (c: Condition) => {
    const f = (defs.data ?? []).find((d) => d.id === c.field_id);
    const values = Array.isArray(c.value) ? c.value : [c.value];
    const opts = Array.isArray(f?.options) ? f.options : [];
    const said = values.map((v) => (v === 'me' ? 'me' : (opts.find((o) => o.id === v)?.label ?? 'a value')));
    return `${f?.name ?? 'A field'}: ${said.join(', ')}`;
  };
  const addField = pickable.find((f) => f.id === adding);
  const addOptions: [string, string][] = addField
    ? addField.type === 'people'
      ? [['me', 'Me']]
      : (Array.isArray(addField.options) ? addField.options : [])
          .filter((o) => !o.archived)
          .map((o) => [o.id, o.label] as [string, string])
    : [];
  const dirty = view !== null && !same(view, saved);

  return (
    <div
      role="region"
      aria-label="Dashboard filters"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-hair-soft bg-surface px-3 py-2"
    >
      <Icon icon={Filter} size={14} className="text-muted" aria-hidden />
      <Pick
        label="Period"
        value={current.period ?? ''}
        onChange={(v) => change({ period: (v || null) as DashboardFilters['period'] })}
        options={PERIODS}
      />
      {lockPortfolio ? null : (
        <Pick
          label="Portfolio"
          value={current.portfolio_id ?? ''}
          onChange={(v) => change({ portfolio_id: v || null })}
          options={[
            ['', 'Any portfolio'],
            ...(portfolios.data ?? []).map((p) => [p.id, p.name] as [string, string]),
          ]}
        />
      )}
      <Toggle on={(current.owner ?? []).includes('me')} onClick={() => toggleMe('owner')}>
        Projects I own
      </Toggle>
      <Toggle on={(current.assignee ?? []).includes('me')} onClick={() => toggleMe('assignee')}>
        Assigned to me
      </Toggle>
      {conditions.map((c, i) => (
        <span
          key={`${c.field_id}-${i}`}
          className="flex items-center gap-1 rounded-full border border-ink bg-surface-2 py-0.5 pl-2.5 pr-1 text-xs"
        >
          {label(c)}
          <button
            type="button"
            aria-label={`Remove the filter ${label(c)}`}
            onClick={() => change({ fields: conditions.filter((_x, j) => j !== i) })}
            className="rounded-full p-0.5 hover:bg-surface"
          >
            <Icon icon={X} size={12} />
          </button>
        </span>
      ))}
      {conditions.length < 5 && pickable.length ? (
        <span className="flex items-center gap-1">
          <Pick
            label="Add a field filter"
            value={adding}
            onChange={setAdding}
            options={[['', 'Field…'], ...pickable.map((f) => [f.id, f.name] as [string, string])]}
          />
          {addField ? (
            <Pick
              label={`${addField.name} is`}
              value=""
              onChange={(v) => {
                if (!v) return;
                change({ fields: [...conditions, { field_id: addField.id, op: 'any', value: [v] }] });
                setAdding('');
              }}
              options={[['', 'is…'], ...addOptions]}
            />
          ) : null}
        </span>
      ) : null}
      <span className="ml-auto flex items-center gap-2">
        {view !== null ? (
          <Button size="sm" variant="text" onClick={() => onView(null)}>
            {saved && activeFilters(saved) ? 'Back to the saved filters' : 'Clear'}
          </Button>
        ) : null}
        {canSave && dirty ? (
          <Button size="sm" variant="primary" onClick={() => onSave(activeFilters(view))}>
            Save for everyone
          </Button>
        ) : null}
        {dirty ? <span className="text-xs text-muted">Only you see this view</span> : null}
      </span>
    </div>
  );
}

function Pick({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        'h-7 rounded-md border bg-surface px-2 text-xs focus:outline-none focus:ring-2 focus:ring-focus/25',
        value ? 'border-ink' : 'border-hairline text-muted',
      )}
    >
      {options.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        'h-7 rounded-full border px-2.5 text-xs focus-visible:outline-2 focus-visible:outline-focus',
        on ? 'border-ink bg-surface-2 text-ink' : 'border-hairline text-muted hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

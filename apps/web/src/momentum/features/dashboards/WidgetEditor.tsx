import { BarChart3, Hash, LineChart, ListChecks, PieChart, type LucideIcon } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Input } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Tabs';
import { useFieldLibrary, useProjectFields } from '@/features/fields';
import { cn } from '@/lib/cn';
import {
  autoTitle,
  DEFAULT_SIZE,
  draftOf,
  draftProblem,
  GROUP_LABELS,
  KIND_LABELS,
  newDraft,
  specOf,
  type Draft,
} from './model';
import type { WidgetIn, WidgetKind } from './queries';
import { WidgetCard, type WidgetItem } from './WidgetCard';

const KIND_ICONS: Record<WidgetKind, LucideIcon> = {
  count: Hash,
  bar: BarChart3,
  donut: PieChart,
  line: LineChart,
  list: ListChecks,
};
const KIND_HINTS: Record<WidgetKind, string> = {
  count: 'One number',
  bar: 'Compare groups',
  donut: 'Share of a whole',
  line: 'Change over time',
  list: 'The tasks themselves',
};
const WINDOWS = [
  { days: 28, label: '4 weeks' },
  { days: 84, label: '12 weeks' },
  { days: 182, label: '6 months' },
  { days: 366, label: '1 year' },
];

/**
 * Add or edit a chart: pick a kind, say which tasks and how to split them, and watch the live
 * preview (run as you, like the real widget) update as you choose. Everything is a choice from
 * a list, so what you save is always a valid spec.
 */
export function WidgetEditor({
  open,
  onOpenChange,
  initial,
  projectId,
  onSave,
  saving,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: WidgetItem | null;
  projectId: string | null;
  onSave: (body: WidgetIn) => void;
  saving?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={initial ? 'Edit chart' : 'Add a chart'}
      className="top-[6vh] w-[min(980px,calc(100vw-32px))]"
    >
      {open ? (
        <EditorBody
          key={initial?.id ?? 'new'}
          initial={initial}
          projectId={projectId}
          onSave={onSave}
          onCancel={() => onOpenChange(false)}
          saving={saving}
        />
      ) : null}
    </Dialog>
  );
}

function EditorBody({
  initial,
  projectId,
  onSave,
  onCancel,
  saving,
}: {
  initial: WidgetItem | null;
  projectId: string | null;
  onSave: (body: WidgetIn) => void;
  onCancel: () => void;
  saving?: boolean;
}) {
  const [d, setD] = useState<Draft>(() => (initial ? draftOf(initial) : newDraft('bar')));
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));
  const projectFields = useProjectFields(projectId ?? '', projectId !== null);
  const library = useFieldLibrary(projectId === null);
  const selectFields = useMemo(() => {
    const all = projectId ? (projectFields.data ?? []).map((pf) => pf.field) : (library.data ?? []);
    return all.filter((f) => f.type === 'single_select');
  }, [projectId, projectFields.data, library.data]);
  const fieldName = selectFields.find((f) => f.id === d.fieldId)?.name ?? null;
  const spec = useMemo(() => specOf(d), [d]);
  const title = d.titleTouched ? d.title : autoTitle(d, fieldName);
  const problem = draftProblem({ ...d, title });
  const preview: WidgetItem = { id: null, kind: d.kind, title, spec, size: d.size, version: 0 };
  const grouped = d.kind === 'bar' || d.kind === 'donut';
  const groups = (Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[]).filter(
    (g) => (projectId ? g !== 'project' : true) && (g !== 'field' || selectFields.length > 0),
  );

  const save = () => {
    if (problem) return;
    onSave({ kind: d.kind, title: title.trim(), query_spec: spec, viz: { size: d.size } });
  };

  return (
    <div className="grid max-h-[80vh] grid-cols-1 overflow-auto md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <form
        className="space-y-5 border-hair-soft px-5 py-4 md:border-r"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted">Chart</legend>
          <div className="grid grid-cols-5 gap-1.5">
            {(Object.keys(KIND_LABELS) as WidgetKind[]).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={d.kind === k}
                onClick={() =>
                  set({
                    kind: k,
                    size: DEFAULT_SIZE[k],
                    limit: k === 'list' ? 10 : d.limit === 10 ? 8 : d.limit,
                  })
                }
                className={cn(
                  'flex flex-col items-center gap-1 rounded-lg border px-1 py-2 text-center text-xs',
                  d.kind === k
                    ? 'border-ink bg-surface-2 text-ink'
                    : 'border-hairline text-muted hover:bg-surface-2 hover:text-ink',
                )}
              >
                <Icon icon={KIND_ICONS[k]} size={18} aria-hidden />
                <span className="font-medium">{KIND_LABELS[k]}</span>
                <span className="hidden text-[10px] leading-tight text-muted-2 sm:block">
                  {KIND_HINTS[k]}
                </span>
              </button>
            ))}
          </div>
        </fieldset>

        <Row label="Title" htmlFor="widget-title">
          <Input
            id="widget-title"
            value={title}
            maxLength={200}
            onChange={(e) => set({ title: e.target.value, titleTouched: true })}
          />
        </Row>

        <fieldset className="space-y-3">
          <legend className="mb-2 text-xs font-medium text-muted">Which tasks</legend>
          {d.kind === 'line' && d.timeField === 'completed' ? (
            <p className="text-sm text-ink-2">Completed tasks</p>
          ) : (
            <Segmented
              label="Task status"
              value={d.status}
              onChange={(status) => set({ status })}
              options={[
                { value: 'open', label: 'Open' },
                { value: 'completed', label: 'Completed' },
                { value: 'all', label: 'All' },
              ]}
            />
          )}
          <div className="flex flex-wrap gap-1.5">
            {d.status !== 'completed' ? (
              <>
                <Chip on={d.overdue} onClick={() => set({ overdue: !d.overdue })}>
                  Overdue only
                </Chip>
                <Chip on={d.blocked} onClick={() => set({ blocked: !d.blocked })}>
                  Blocked only
                </Chip>
              </>
            ) : null}
            <Chip on={d.mine} onClick={() => set({ mine: !d.mine })}>
              Assigned to me
            </Chip>
          </div>
          {d.status !== 'completed' && !d.overdue ? (
            <Choice
              label="Due"
              value={d.dueWithin === null ? '' : String(d.dueWithin)}
              onChange={(v) => set({ dueWithin: v === '' ? null : Number(v) })}
              options={[
                ['', 'Any time'],
                ['0', 'Today'],
                ['7', 'In the next 7 days'],
                ['14', 'In the next 14 days'],
                ['30', 'In the next 30 days'],
              ]}
            />
          ) : null}
          {d.status !== 'open' || (d.kind === 'line' && d.timeField === 'completed') ? (
            <Choice
              label="Completed"
              value={d.completedWithin === null ? '' : String(d.completedWithin)}
              onChange={(v) => set({ completedWithin: v === '' ? null : Number(v) })}
              options={[
                ['', 'Any time'],
                ['7', 'In the last 7 days'],
                ['30', 'In the last 30 days'],
                ['90', 'In the last 90 days'],
              ]}
            />
          ) : null}
        </fieldset>

        {grouped ? (
          <fieldset className="space-y-3">
            <legend className="mb-2 text-xs font-medium text-muted">Split by</legend>
            <Choice
              label="Group by"
              value={d.groupBy}
              onChange={(v) => set({ groupBy: v as Draft['groupBy'] })}
              options={groups.map((g) => [g, GROUP_LABELS[g]])}
            />
            {d.groupBy === 'field' ? (
              <Choice
                label="Field"
                value={d.fieldId ?? ''}
                onChange={(v) => set({ fieldId: v || null })}
                options={[
                  ['', 'Choose a field…'],
                  ...selectFields.map((f) => [f.id, f.name] as [string, string]),
                ]}
              />
            ) : null}
            <Choice
              label="Show"
              value={String(d.limit)}
              onChange={(v) => set({ limit: Number(v) })}
              options={[
                ['5', 'Top 5, rest as Other'],
                ['8', 'Top 8, rest as Other'],
                ['12', 'Top 12, rest as Other'],
                ['20', 'Top 20, rest as Other'],
              ]}
            />
          </fieldset>
        ) : null}

        {d.kind === 'line' ? (
          <fieldset className="space-y-3">
            <legend className="mb-2 text-xs font-medium text-muted">Over time</legend>
            <Choice
              label="Count tasks by"
              value={d.timeField}
              onChange={(v) => set({ timeField: v as Draft['timeField'] })}
              options={[
                ['completed', 'The day they were completed'],
                ['created', 'The day they were created'],
                ['due', 'Their due date (upcoming)'],
              ]}
            />
            <Segmented
              label="Per"
              value={d.bucket}
              onChange={(bucket) => set({ bucket })}
              options={[
                { value: 'day', label: 'Day' },
                { value: 'week', label: 'Week' },
                { value: 'month', label: 'Month' },
              ]}
            />
            <Choice
              label={d.timeField === 'due' ? 'Looking ahead' : 'Looking back'}
              value={String(d.windowDays)}
              onChange={(v) => set({ windowDays: Number(v) })}
              options={WINDOWS.map((w) => [String(w.days), w.label])}
            />
          </fieldset>
        ) : null}

        {d.kind === 'list' ? (
          <Choice
            label="Rows"
            value={String(d.limit)}
            onChange={(v) => set({ limit: Number(v) })}
            options={[
              ['5', '5 tasks'],
              ['10', '10 tasks'],
              ['20', '20 tasks'],
            ]}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-medium text-muted">Measure</span>
            <Segmented
              label="Measure"
              value={d.measure}
              onChange={(measure) => set({ measure })}
              options={[
                { value: 'count', label: 'Tasks' },
                { value: 'sum_estimate', label: 'Estimated hours' },
              ]}
            />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs font-medium text-muted">Size</span>
          <Segmented
            label="Size"
            value={d.size}
            onChange={(size) => set({ size })}
            options={[
              { value: 'sm', label: 'Small' },
              { value: 'md', label: 'Medium' },
              { value: 'lg', label: 'Wide' },
            ]}
          />
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-hair-soft pt-4">
          {problem ? <p className="mr-auto text-xs text-muted">{problem}</p> : null}
          <Button type="button" variant="text" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!!problem} loading={saving}>
            {initial ? 'Save chart' : 'Add chart'}
          </Button>
        </div>
      </form>
      <div className="bg-canvas px-5 py-4">
        <p className="mb-2 text-xs font-medium text-muted">Preview · live numbers you can see</p>
        <div className="grid grid-cols-2">
          <WidgetCard
            item={{ ...preview, size: d.size === 'sm' ? 'sm' : 'md' }}
            projectId={projectId}
            editable={false}
            onDrill={() => undefined}
            onOpenTask={() => undefined}
          />
        </div>
      </div>
    </div>
  );
}

function Row({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        'rounded-full border px-2.5 py-0.5 text-[13px]',
        on ? 'border-ink bg-ink text-canvas' : 'border-hairline text-ink-2 hover:bg-surface-2',
      )}
    >
      {children}
    </button>
  );
}

function Choice({
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
  const id = `choice-${label.toLowerCase().replace(/\W+/g, '-')}`;
  return (
    <div className="flex items-center gap-3">
      <label htmlFor={id} className="w-28 shrink-0 text-xs font-medium text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  );
}

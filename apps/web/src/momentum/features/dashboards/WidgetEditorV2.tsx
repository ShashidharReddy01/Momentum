import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Tabs';
import { useProjectFieldDefs } from '@/features/fields';
import { usePortfolios } from '@/features/portfolios';
import { cn } from '@/lib/cn';
import { ANY_KIND_LABELS, DEFAULT_SIZE } from './model';
import { isV1, type AnySpec, type WidgetIn, type WidgetKind } from './queries';
import { WidgetCard, type WidgetItem } from './WidgetCard';

/**
 * Phase 7.5 (spec §7.1-§7.2): the editor for what a version 2 spec asks — projects (one row per
 * project you can see), the lifecycle (stage analytics over a portfolio's stage field) and notes.
 * Like the tasks editor, everything is a choice from a list and the preview runs as you. Version 2
 * task and trend charts (from a template) keep their question; here you rename or resize them.
 */

export type Entity = 'tasks' | 'projects' | 'stage_events' | 'note' | 'other';

export function entityOf(item: WidgetItem | null): Entity {
  if (!item) return 'tasks';
  const spec = item.spec;
  if (isV1(spec)) return 'tasks';
  if (spec.entity === 'projects' || spec.entity === 'stage_events' || spec.entity === 'note')
    return spec.entity;
  return 'other';
}

const PROJECT_KINDS: WidgetKind[] = ['kpi', 'bar', 'donut', 'table', 'timeline'];
const STAGE_KINDS: WidgetKind[] = ['funnel', 'stage_time', 'aging', 'kpi'];
const MEASURES: [string, string][] = [
  ['count', 'Number of projects'],
  ['sum_project_field', 'Total of a number field'],
  ['avg_project_field', 'Average of a number field'],
  ['avg_progress', 'Average progress'],
  ['sum_open_tasks', 'Open tasks'],
  ['sum_overdue_tasks', 'Overdue tasks'],
];
const GROUPS: [string, string][] = [
  ['status', 'Status'],
  ['owner', 'Owner'],
  ['team', 'Team'],
  ['stage', 'Stage (the portfolio’s)'],
  ['project_field', 'A project field'],
];
const COLUMNS: [string, string][] = [
  ['owner', 'Owner'],
  ['status', 'Status'],
  ['stage', 'Stage'],
  ['stage_age_days', 'Days in stage'],
  ['progress', 'Progress'],
  ['open', 'Open tasks'],
  ['overdue', 'Overdue'],
  ['blocked', 'Blocked'],
  ['waiting_on_customer', 'Waiting on customer'],
  ['next_milestone', 'Next milestone'],
  ['target_date', 'Target date'],
  ['forecast_date', 'Forecast'],
  ['slip_days', 'Slip'],
];
const QUICK: [string, string][] = [
  ['slipping', 'Slipping'],
  ['at_risk', 'At risk'],
  ['has_blocked', 'Has blocked work'],
  ['has_waiting_on_customer', 'Waiting on the customer'],
  ['include_completed', 'Include completed'],
];

interface ProjectsDraft {
  kind: WidgetKind;
  portfolioId: string;
  measure: string;
  measureFieldId: string;
  groupBy: string;
  fieldId: string;
  columns: string[];
  aheadDays: number;
  dateFieldId: string;
  quick: string[];
  ownerMe: boolean;
}
interface StageDraft {
  kind: WidgetKind;
  portfolioId: string;
  windowDays: number;
  analysis: 'throughput' | 'time_in_stage';
  stage: string;
  compare: boolean;
}

function projectsDraftOf(item: WidgetItem | null): ProjectsDraft {
  const s = (item && !isV1(item.spec) && item.spec.entity === 'projects' ? item.spec : null) as
    (Record<string, unknown> & { filters?: Record<string, unknown> }) | null;
  const f = (s?.filters ?? {}) as Record<string, unknown>;
  const cols = ((s?.columns as string[] | undefined) ?? []).filter((c) => !c.startsWith('field:'));
  const dateCol = ((s?.columns as string[] | undefined) ?? []).find((c) => c.startsWith('field:'));
  return {
    kind: item?.kind ?? 'kpi',
    portfolioId: (f.portfolio_id as string) ?? '',
    measure: (s?.measure as string) ?? 'count',
    measureFieldId: (s?.measure_field_id as string) ?? '',
    groupBy: (s?.group_by as string) ?? 'status',
    fieldId: (s?.field_id as string) ?? '',
    columns: cols.length
      ? cols.filter((c) => c !== 'name')
      : ['owner', 'status', 'progress', 'next_milestone'],
    aheadDays: (s?.ahead_days as number) ?? 90,
    dateFieldId: dateCol ? dateCol.slice('field:'.length) : '',
    quick: QUICK.map(([k]) => k).filter((k) => f[k]),
    ownerMe: Array.isArray(f.owner) && f.owner.length === 1 && f.owner[0] === 'me',
  };
}

function stageDraftOf(item: WidgetItem | null): StageDraft {
  const s = (item && !isV1(item.spec) && item.spec.entity === 'stage_events' ? item.spec : null) as Record<
    string,
    unknown
  > | null;
  return {
    kind: item?.kind ?? 'funnel',
    portfolioId: (s?.portfolio_id as string) ?? '',
    windowDays: (s?.window_days as number) ?? 180,
    analysis: s?.analysis === 'time_in_stage' ? 'time_in_stage' : 'throughput',
    stage: ((s?.stages as string[] | undefined) ?? [])[0] ?? '',
    compare: !!s?.compare_previous,
  };
}

/** The spec a projects draft stands for (null until it is complete). */
export function projectsSpec(d: ProjectsDraft): AnySpec | null {
  const filters: Record<string, unknown> = {};
  if (d.portfolioId) filters.portfolio_id = d.portfolioId;
  for (const k of d.quick) filters[k] = true;
  if (d.ownerMe) filters.owner = ['me'];
  const spec: Record<string, unknown> = { version: 2, entity: 'projects', filters };
  const fieldMeasure = d.measure === 'sum_project_field' || d.measure === 'avg_project_field';
  if (d.kind === 'kpi' || d.kind === 'bar' || d.kind === 'donut') {
    if (fieldMeasure && !d.measureFieldId) return null;
    spec.measure = d.measure;
    if (fieldMeasure) spec.measure_field_id = d.measureFieldId;
  }
  if (d.kind === 'bar' || d.kind === 'donut') {
    if (d.groupBy === 'stage' && !d.portfolioId) return null;
    if (d.groupBy === 'project_field' && !d.fieldId) return null;
    spec.group_by = d.groupBy;
    if (d.groupBy === 'project_field') spec.field_id = d.fieldId;
  }
  if (d.kind === 'table') {
    spec.columns = ['name', ...d.columns];
    spec.limit = 20;
  }
  if (d.kind === 'timeline') {
    spec.ahead_days = d.aheadDays;
    if (d.dateFieldId) spec.columns = [`field:${d.dateFieldId}`];
  }
  return spec as unknown as AnySpec;
}

export function stageSpec(d: StageDraft): AnySpec | null {
  if (!d.portfolioId) return null;
  const spec: Record<string, unknown> = {
    version: 2,
    entity: 'stage_events',
    portfolio_id: d.portfolioId,
    window_days: d.windowDays,
  };
  if (d.kind === 'funnel') spec.analysis = 'funnel';
  else if (d.kind === 'stage_time') spec.analysis = 'time_in_stage';
  else if (d.kind === 'aging') spec.analysis = 'aging';
  else {
    if (!d.stage) return null;
    spec.analysis = d.analysis;
    spec.stages = [d.stage];
    spec.compare_previous = d.compare && d.analysis === 'throughput';
  }
  return spec as unknown as AnySpec;
}

const AUTO_TITLES: Partial<Record<WidgetKind, string>> = {
  funnel: 'Lifecycle funnel',
  stage_time: 'Time in stage',
  aging: 'Stage aging',
  table: 'Projects',
  timeline: 'Coming up',
  note: 'Note',
};

export function V2EditorBody({
  entity,
  initial,
  onSave,
  onCancel,
  saving,
  header,
}: {
  entity: Entity;
  initial: WidgetItem | null;
  onSave: (body: WidgetIn) => void;
  onCancel: () => void;
  saving?: boolean;
  header?: ReactNode;
}) {
  const [pd, setPd] = useState<ProjectsDraft>(() => projectsDraftOf(initial));
  const [sd, setSd] = useState<StageDraft>(() => stageDraftOf(initial));
  const [text, setText] = useState(() =>
    initial && !isV1(initial.spec) && initial.spec.entity === 'note' ? initial.spec.text : '',
  );
  const [title, setTitle] = useState(initial?.title ?? '');
  const [size, setSize] = useState<WidgetItem['size']>(initial?.size ?? 'md');
  const portfolios = usePortfolios();
  const defs = useProjectFieldDefs(entity === 'projects' || entity === 'stage_events');
  const fields = defs.data ?? [];
  const numberFields = fields.filter((f) => ['number', 'currency', 'percent'].includes(f.type));
  const groupFields = fields.filter((f) => ['single_select', 'people', 'checkbox'].includes(f.type));
  const dateFields = fields.filter((f) => f.type === 'date');
  const folios = portfolios.data ?? [];
  const stageFolio = folios.find((p) => p.id === sd.portfolioId) as
    { stage_field_id?: string | null } | undefined;
  const rawOptions = fields.find((f) => f.id === stageFolio?.stage_field_id)?.options;
  const stageOptions = Array.isArray(rawOptions) ? rawOptions.filter((o) => !o.archived) : [];

  const kind: WidgetKind =
    entity === 'projects'
      ? pd.kind
      : entity === 'stage_events'
        ? sd.kind
        : entity === 'note'
          ? 'note'
          : initial!.kind;
  const spec = useMemo<AnySpec | null>(() => {
    if (entity === 'projects') return projectsSpec(pd);
    if (entity === 'stage_events') return stageSpec(sd);
    if (entity === 'note')
      return text.trim() ? ({ version: 2, entity: 'note', text: text.trim() } as unknown as AnySpec) : null;
    return initial!.spec;
  }, [entity, pd, sd, text, initial]);
  const shownTitle = title.trim() || AUTO_TITLES[kind] || ANY_KIND_LABELS[kind];
  const problem =
    entity === 'stage_events' && !sd.portfolioId
      ? 'Pick a portfolio with stages.'
      : entity === 'note' && !text.trim()
        ? 'Write the note.'
        : !spec
          ? 'Finish the choices above.'
          : null;
  const preview: WidgetItem | null = spec
    ? { id: null, kind, title: shownTitle, spec, size, version: 0 }
    : null;

  const save = () => {
    if (problem || !spec) return;
    onSave({ kind, title: shownTitle, query_spec: spec, viz: { size } });
  };
  const pickKind = (k: WidgetKind) => {
    setSize(DEFAULT_SIZE[k]);
    if (entity === 'projects') setPd((x) => ({ ...x, kind: k }));
    else setSd((x) => ({ ...x, kind: k }));
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
        {header}
        {entity === 'projects' || entity === 'stage_events' ? (
          <Segmented
            label="Chart"
            value={kind}
            onChange={pickKind}
            options={(entity === 'projects' ? PROJECT_KINDS : STAGE_KINDS).map((k) => ({
              value: k,
              label: ANY_KIND_LABELS[k],
            }))}
          />
        ) : null}
        <Row label="Title" htmlFor="v2-title">
          <Input
            id="v2-title"
            value={title}
            placeholder={shownTitle}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Row>

        {entity === 'projects' ? (
          <fieldset className="space-y-3">
            <legend className="mb-2 text-xs font-medium text-muted">Which projects</legend>
            <Select
              label="Portfolio"
              value={pd.portfolioId}
              onChange={(v) => setPd({ ...pd, portfolioId: v })}
              options={[
                ['', 'Every project I can see'],
                ...folios.map((p) => [p.id, p.name] as [string, string]),
              ]}
            />
            <div className="flex flex-wrap gap-1.5">
              <Chip on={pd.ownerMe} onClick={() => setPd({ ...pd, ownerMe: !pd.ownerMe })}>
                I own
              </Chip>
              {QUICK.map(([k, label]) => (
                <Chip
                  key={k}
                  on={pd.quick.includes(k)}
                  onClick={() =>
                    setPd({
                      ...pd,
                      quick: pd.quick.includes(k) ? pd.quick.filter((x) => x !== k) : [...pd.quick, k],
                    })
                  }
                >
                  {label}
                </Chip>
              ))}
            </div>
            {pd.kind === 'kpi' || pd.kind === 'bar' || pd.kind === 'donut' ? (
              <>
                <Select
                  label="Measure"
                  value={pd.measure}
                  onChange={(v) => setPd({ ...pd, measure: v })}
                  options={MEASURES}
                />
                {pd.measure === 'sum_project_field' || pd.measure === 'avg_project_field' ? (
                  <Select
                    label="Number field"
                    value={pd.measureFieldId}
                    onChange={(v) => setPd({ ...pd, measureFieldId: v })}
                    options={[
                      ['', 'Pick a field'],
                      ...numberFields.map((f) => [f.id, f.name] as [string, string]),
                    ]}
                  />
                ) : null}
              </>
            ) : null}
            {pd.kind === 'bar' || pd.kind === 'donut' ? (
              <>
                <Select
                  label="Split by"
                  value={pd.groupBy}
                  onChange={(v) => setPd({ ...pd, groupBy: v })}
                  options={GROUPS}
                />
                {pd.groupBy === 'project_field' ? (
                  <Select
                    label="Field"
                    value={pd.fieldId}
                    onChange={(v) => setPd({ ...pd, fieldId: v })}
                    options={[
                      ['', 'Pick a field'],
                      ...groupFields.map((f) => [f.id, f.name] as [string, string]),
                    ]}
                  />
                ) : null}
              </>
            ) : null}
            {pd.kind === 'table' ? (
              <fieldset>
                <legend className="mb-1 text-xs font-medium text-muted">Columns</legend>
                <div className="flex flex-wrap gap-1.5">
                  {COLUMNS.map(([k, label]) => (
                    <Chip
                      key={k}
                      on={pd.columns.includes(k)}
                      onClick={() =>
                        setPd({
                          ...pd,
                          columns: pd.columns.includes(k)
                            ? pd.columns.filter((x) => x !== k)
                            : [...pd.columns, k],
                        })
                      }
                    >
                      {label}
                    </Chip>
                  ))}
                </div>
              </fieldset>
            ) : null}
            {pd.kind === 'timeline' ? (
              <>
                <Select
                  label="Next"
                  value={String(pd.aheadDays)}
                  onChange={(v) => setPd({ ...pd, aheadDays: Number(v) })}
                  options={[
                    ['30', '30 days'],
                    ['60', '60 days'],
                    ['90', '90 days'],
                  ]}
                />
                <Select
                  label="Date"
                  value={pd.dateFieldId}
                  onChange={(v) => setPd({ ...pd, dateFieldId: v })}
                  options={[
                    ['', 'Milestones and target dates'],
                    ...dateFields.map((f) => [f.id, `Milestones and ${f.name}`] as [string, string]),
                  ]}
                />
              </>
            ) : null}
          </fieldset>
        ) : null}

        {entity === 'stage_events' ? (
          <fieldset className="space-y-3">
            <legend className="mb-2 text-xs font-medium text-muted">Which lifecycle</legend>
            <Select
              label="Portfolio"
              value={sd.portfolioId}
              onChange={(v) => setSd({ ...sd, portfolioId: v, stage: '' })}
              options={[['', 'Pick a portfolio'], ...folios.map((p) => [p.id, p.name] as [string, string])]}
            />
            {sd.kind !== 'aging' ? (
              <Select
                label="Window"
                value={String(sd.windowDays)}
                onChange={(v) => setSd({ ...sd, windowDays: Number(v) })}
                options={[
                  ['30', 'Last 30 days'],
                  ['90', 'Last 90 days'],
                  ['180', 'Last 6 months'],
                  ['365', 'Last year'],
                ]}
              />
            ) : null}
            {sd.kind === 'kpi' ? (
              <>
                <Segmented
                  label="Number"
                  value={sd.analysis}
                  onChange={(analysis) => setSd({ ...sd, analysis })}
                  options={[
                    { value: 'throughput', label: 'Projects entering' },
                    { value: 'time_in_stage', label: 'Median days in' },
                  ]}
                />
                <Select
                  label="Stage"
                  value={sd.stage}
                  onChange={(v) => setSd({ ...sd, stage: v })}
                  options={[
                    ['', 'Pick a stage'],
                    ...stageOptions.map((o) => [o.id, o.label] as [string, string]),
                  ]}
                />
                {sd.analysis === 'throughput' ? (
                  <Chip on={sd.compare} onClick={() => setSd({ ...sd, compare: !sd.compare })}>
                    Compare with the period before
                  </Chip>
                ) : null}
              </>
            ) : null}
          </fieldset>
        ) : null}

        {entity === 'note' ? (
          <Row label="Text" htmlFor="v2-note">
            <textarea
              id="v2-note"
              value={text}
              maxLength={4000}
              rows={6}
              onChange={(e) => setText(e.target.value)}
              className="w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus/25"
            />
          </Row>
        ) : null}

        {entity === 'other' ? (
          <p className="text-sm text-ink-2">
            This chart came from a template: its question stays as it is. Rename or resize it here.
          </p>
        ) : null}

        <Segmented
          label="Size"
          value={size}
          onChange={setSize}
          options={[
            { value: 'sm', label: 'Small' },
            { value: 'md', label: 'Medium' },
            { value: 'lg', label: 'Wide' },
          ]}
        />
        <div className="flex items-center justify-end gap-2 pt-2">
          {problem ? <span className="mr-auto text-sm text-muted">{problem}</span> : null}
          <Button type="button" variant="text" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!!problem} loading={saving}>
            {initial?.id ? 'Save chart' : 'Add chart'}
          </Button>
        </div>
      </form>
      <div className="bg-surface-2/40 px-5 py-4">
        <p className="mb-2 text-xs font-medium text-muted">Preview, with your numbers</p>
        {preview ? (
          <div className="grid grid-cols-2 gap-3">
            <WidgetCard
              item={{ ...preview, size: preview.size === 'sm' ? 'sm' : 'md' }}
              projectId={null}
              editable={false}
              onDrill={() => undefined}
              onOpenTask={() => undefined}
            />
          </div>
        ) : (
          <p className="py-10 text-center text-sm text-muted">{problem}</p>
        )}
      </div>
    </div>
  );
}

function Row({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

function Select({
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
  const id = `v2-${label.toLowerCase().replace(/\W+/g, '-')}`;
  return (
    <div className="flex items-center gap-3">
      <label htmlFor={id} className="w-28 shrink-0 text-sm text-ink-2">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus/25"
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

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        'rounded-full border px-2.5 py-1 text-xs',
        on ? 'border-ink bg-surface-2 text-ink' : 'border-hairline text-muted hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

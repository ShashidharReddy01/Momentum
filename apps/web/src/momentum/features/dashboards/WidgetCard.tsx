import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  MoreHorizontal,
  Pencil,
  Table2,
  Trash2,
} from 'lucide-react';
import { lazy, Suspense, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { DueText } from '@/components/common/DueText';
import { MoMark } from '@/components/common/MoMark';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useProjectFieldDefs } from '@/features/fields';
import { cn } from '@/lib/cn';
import { chartSpec, colorOf, formatValue, isAlarm, share, tokenColor, unitOf } from './model';
import {
  isV1,
  useSpecData,
  useWidgetData,
  type AnySpec,
  type DashboardFilters,
  type QueryResult,
  type TaskRow,
  type WidgetKind,
} from './queries';
import { Aging, Funnel, Kpi, Note, ProjectTable, StackedBars, StageTime, Timeline } from './widgets2';

// Recharts lives in its own chunk, fetched the first time a chart widget renders.
const Chart = lazy(() => import('./charts'));

export interface WidgetItem {
  /** the saved widget's id, or null for a starter/preview widget run from its spec */
  id: string | null;
  kind: WidgetKind;
  title: string;
  spec: AnySpec;
  size: 'sm' | 'md' | 'lg';
  version: number;
  /** the question Mo drafted this chart from (S6.5.2) */
  prompt?: string | null;
}

/** What was clicked: a group (bar, slice, legend row), a time bucket, or the whole widget. */
export interface Mark {
  key?: string | null;
  bucketStart?: string | null;
  /** a stacked bar's segment (Phase 7.5) */
  splitKey?: string | null;
  label?: string;
}

/** Number tiles: one column, the title above the value. */
const TILE_KINDS: WidgetKind[] = ['count', 'kpi'];

export const SPAN: Record<WidgetItem['size'], string> = {
  sm: 'col-span-1',
  md: 'col-span-2',
  lg: 'col-span-2 xl:col-span-4',
};

export function WidgetCard({
  item,
  projectId,
  editable,
  onDrill,
  onOpenTask,
  onEdit,
  onRemove,
  onMove,
  filters = null,
}: {
  item: WidgetItem;
  projectId: string | null;
  editable: boolean;
  /** the viewer's own dashboard filters for this view (null: the saved ones) */
  filters?: DashboardFilters | null;
  onDrill: (item: WidgetItem, mark: Mark) => void;
  onOpenTask: (taskId: string) => void;
  onEdit?: () => void;
  onRemove?: () => void;
  onMove?: (dir: -1 | 1) => void;
}) {
  // a saved widget runs its stored spec; a starter or preview widget runs the spec it carries
  const saved = useWidgetData(item.id ?? '', item.version, item.id !== null, filters);
  const unsaved = useSpecData(item.kind, item.spec, projectId, item.id === null, filters);
  const q = item.id ? saved : unsaved;
  const [asTable, setAsTable] = useState(false);
  const canTable = item.kind === 'bar' || item.kind === 'donut' || item.kind === 'line';

  const menu =
    editable && (onEdit || onRemove || onMove) ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <IconButton icon={MoreHorizontal} label={`${item.title}: options`} size="icon-sm" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {onEdit ? (
            <DropdownMenuItem onSelect={onEdit}>
              <Icon icon={Pencil} size={14} /> Edit chart
            </DropdownMenuItem>
          ) : null}
          {onMove ? (
            <>
              <DropdownMenuItem onSelect={() => onMove(-1)}>
                <Icon icon={ArrowLeft} size={14} /> Move earlier
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onMove(1)}>
                <Icon icon={ArrowRight} size={14} /> Move later
              </DropdownMenuItem>
            </>
          ) : null}
          {onRemove ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onRemove} className="text-crit">
                <Icon icon={Trash2} size={14} /> Remove
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    ) : null;

  const data = q.data;
  const body: ReactNode = q.isPending ? (
    <Skeleton className={TILE_KINDS.includes(item.kind) ? 'h-10 w-24' : 'h-40'} />
  ) : q.isError ? (
    <div role="alert" className="flex flex-col items-start gap-2 text-sm text-muted">
      <span>We couldn&apos;t load these numbers.</span>
      <Button size="sm" onClick={() => void q.refetch()}>
        Try again
      </Button>
    </div>
  ) : data ? (
    <div className={cn('transition-opacity', q.isPlaceholderData && 'opacity-60')}>
      <WidgetBody
        item={item}
        data={data}
        asTable={asTable}
        onDrill={(mark) => onDrill(item, mark)}
        onOpenTask={onOpenTask}
      />
    </div>
  ) : null;

  if (TILE_KINDS.includes(item.kind)) {
    return (
      <section
        aria-label={item.title}
        className={cn('group relative rounded-xl border border-hair-soft bg-surface p-4', SPAN[item.size])}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="flex items-center gap-1 text-[13px] font-medium text-muted">
            {item.title}
            <AskedMark prompt={item.prompt} />
          </h3>
          <div className="-mr-2 -mt-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
            {menu}
          </div>
        </div>
        <div className="mt-1">{body}</div>
      </section>
    );
  }
  return (
    <section
      aria-label={item.title}
      className={cn(
        'flex min-w-0 flex-col rounded-xl border border-hair-soft bg-surface p-4',
        SPAN[item.size],
      )}
    >
      <header className="mb-3 flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
            <span className="truncate">{item.title}</span>
            <AskedMark prompt={item.prompt} />
          </h3>
          {data ? (
            <p className="truncate text-xs text-muted" title={data.description}>
              {data.description}
            </p>
          ) : null}
        </div>
        {canTable ? (
          <IconButton
            icon={asTable ? BarChart3 : Table2}
            label={asTable ? 'Show as chart' : 'Show as table'}
            size="icon-sm"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
          />
        ) : null}
        {menu}
      </header>
      <div className="min-h-0 flex-1">{body}</div>
    </section>
  );
}

/** Amber ✦: Mo drafted this chart from a question (the numbers are still counted in code). */
function AskedMark({ prompt }: { prompt?: string | null }) {
  if (!prompt) return null;
  return (
    <span
      className="inline-flex shrink-0 text-amber-ink"
      title={`Mo drafted this chart from: “${prompt}”`}
      aria-label={`Drafted by Mo from: ${prompt}`}
      role="img"
    >
      <MoMark size={12} />
    </span>
  );
}

function WidgetBody({
  item,
  data,
  asTable,
  onDrill,
  onOpenTask,
}: {
  item: WidgetItem;
  data: QueryResult;
  asTable: boolean;
  onDrill: (mark: Mark) => void;
  onOpenTask: (taskId: string) => void;
}) {
  const navigate = useNavigate();
  const openProject = (id: string) => navigate(`/projects/${id}`);
  const spec = item.spec;
  const v2 = !isV1(spec);
  if (item.kind === 'count' && !v2) return <CountValue item={item} data={data} onDrill={onDrill} />;
  if (item.kind === 'count' || item.kind === 'kpi') return <Kpi data={data} onDrill={onDrill} />;
  if (item.kind === 'note') return <Note text={data.text ?? ''} />;
  if (item.kind === 'list' || (item.kind === 'table' && data.entity === 'tasks'))
    return <TaskList data={data} onOpenTask={onOpenTask} onMore={() => onDrill({})} />;
  if (item.kind === 'table') return <ProjectColumns data={data} onOpenProject={openProject} />;
  if (item.kind === 'stacked_bar') return <StackedBars item={item} data={data} onDrill={onDrill} />;
  if (item.kind === 'funnel') return <Funnel data={data} onDrill={onDrill} />;
  if (item.kind === 'stage_time') return <StageTime data={data} onDrill={onDrill} />;
  if (item.kind === 'aging') return <Aging data={data} onDrill={onDrill} />;
  if (item.kind === 'timeline') return <Timeline data={data} onOpenProject={openProject} />;
  if (asTable) return <DataTable item={item} data={data} onDrill={onDrill} />;
  if (item.kind !== 'line' && (data.groups ?? []).length === 0)
    return <Quiet>Nothing matches yet. {data.description}.</Quiet>;
  return (
    <Suspense fallback={<Skeleton className="h-40" />}>
      <Chart kind={item.kind} spec={chartSpec(item.spec)} data={data} onDrill={onDrill} />
    </Suspense>
  );
}

/** A projects table, with project fields' names for their columns. */
function ProjectColumns({ data, onOpenProject }: { data: QueryResult; onOpenProject: (id: string) => void }) {
  const fieldCols = (data.columns ?? []).some((c) => c.startsWith('field:'));
  const defs = useProjectFieldDefs(fieldCols);
  const names = useMemo(
    () => Object.fromEntries((defs.data ?? []).map((f) => [`field:${f.id}`, f.name])),
    [defs.data],
  );
  return <ProjectTable data={data} columnNames={names} onOpenProject={onOpenProject} />;
}

function Quiet({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

function CountValue({
  item,
  data,
  onDrill,
}: {
  item: WidgetItem;
  data: QueryResult;
  onDrill: (mark: Mark) => void;
}) {
  const value = data.value ?? 0;
  const alarm = isAlarm(item.spec, value);
  return (
    <button
      type="button"
      onClick={() => onDrill({})}
      title={`${data.description}. Show these tasks`}
      className="-mx-1 flex w-[calc(100%+8px)] flex-col items-start rounded-md px-1 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-focus"
    >
      <span
        className={cn(
          'flex items-center gap-1.5 text-[34px] leading-tight font-semibold',
          alarm && 'text-crit',
        )}
      >
        {alarm ? <Icon icon={AlertTriangle} size={20} aria-hidden /> : null}
        {formatValue(data, value)}
      </span>
      <span className="text-xs text-muted">
        {data.measure === 'sum_estimate'
          ? `across ${data.tasks_total.toLocaleString()} ${data.tasks_total === 1 ? 'task' : 'tasks'}` +
            (data.unestimated ? ` · ${data.unestimated} without an estimate` : '')
          : alarm
            ? 'need attention'
            : unitOf(data, value)}
      </span>
    </button>
  );
}

function daysLate(due: string | null): number {
  if (!due) return 0;
  const [y, m, d] = due.split('-').map(Number);
  const then = new Date(y!, m! - 1, d!);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.round((now.getTime() - then.getTime()) / 86_400_000);
}

function TaskList({
  data,
  onOpenTask,
  onMore,
}: {
  data: QueryResult;
  onOpenTask: (taskId: string) => void;
  onMore: () => void;
}) {
  if (!(data.tasks ?? []).length) return <Quiet>Nothing here. {data.description}.</Quiet>;
  return (
    <div>
      <ul className="divide-y divide-hair-soft">
        {(data.tasks ?? []).map((t) => (
          <TaskLine key={t.id} task={t} onOpen={() => onOpenTask(t.id)} />
        ))}
      </ul>
      {data.more ? (
        <button
          type="button"
          onClick={onMore}
          className="mt-2 text-sm text-ink-2 underline-offset-2 hover:underline"
        >
          Show all {((data.tasks ?? []).length + data.more).toLocaleString()}
        </button>
      ) : null}
    </div>
  );
}

export function TaskLine({
  task,
  onOpen,
  compact,
}: {
  task: TaskRow;
  onOpen: () => void;
  compact?: boolean;
}) {
  const late = task.completed_at ? 0 : daysLate(task.due_on);
  const when =
    late > 0 ? (
      <span className="shrink-0 text-xs font-medium text-crit">
        {late === 1 ? '1 day late' : `${late} days late`}
      </span>
    ) : (
      <span className="shrink-0 text-xs">
        <DueText dueOn={task.due_on} done={!!task.completed_at} />
      </span>
    );
  const project = task.project_name ? (
    <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: tokenColor(task.project_color) ?? 'var(--muted-2)' }}
      />
      <span className="truncate">{task.project_name}</span>
    </span>
  ) : null;
  const avatar = task.assignee_name ? <Avatar name={task.assignee_name} size={22} /> : null;
  const cls =
    'flex w-full items-center gap-3 rounded-md px-1 py-2 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-focus';
  if (compact) {
    // two lines, so the title keeps the whole width of a narrow panel
    return (
      <li>
        <button type="button" onClick={onOpen} className={cls}>
          <span className="min-w-0 flex-1">
            <span className="flex items-baseline gap-2">
              <span className="shrink-0 font-mono text-xs text-muted">{task.key}</span>
              <span className="truncate text-sm">{task.title}</span>
            </span>
            <span className="mt-0.5 flex items-center gap-3">
              {when}
              {project}
            </span>
          </span>
          <span className="w-6 shrink-0">{avatar}</span>
        </button>
      </li>
    );
  }
  return (
    <li>
      <button type="button" onClick={onOpen} className={cls}>
        <span className="w-14 shrink-0 font-mono text-xs text-muted">{task.key}</span>
        <span className="min-w-0 flex-1 truncate text-sm">{task.title}</span>
        {project ? <span className="hidden max-w-40 shrink-0 md:flex">{project}</span> : null}
        <span className="flex w-24 shrink-0 justify-end">{when}</span>
        <span className="w-6 shrink-0">{avatar}</span>
      </button>
    </li>
  );
}

/** Every chart's table twin: the same numbers, readable without colour, each row opens its tasks. */
function DataTable({
  item,
  data,
  onDrill,
}: {
  item: WidgetItem;
  data: QueryResult;
  onDrill: (mark: Mark) => void;
}) {
  const rows =
    item.kind === 'line'
      ? (data.series ?? []).map((p) => ({
          id: p.start,
          label: p.start === p.end ? p.start : `${p.start} – ${p.end}`,
          value: p.value,
          mark: { bucketStart: p.start } as Mark,
          color: null as string | null,
        }))
      : (data.groups ?? []).map((g, i) => ({
          id: g.key,
          label: g.label,
          value: g.value,
          mark: { key: g.key, label: g.label } as Mark,
          color: colorOf(chartSpec(item.spec), g, i, item.kind),
        }));
  const total = item.kind === 'line' ? rows.reduce((a, r) => a + r.value, 0) : data.total;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-muted">
          <th className="py-1 font-medium">{item.kind === 'line' ? 'Period' : 'Group'}</th>
          <th className="py-1 text-right font-medium">
            {data.measure === 'sum_estimate' ? 'Hours' : 'Tasks'}
          </th>
          <th className="py-1 text-right font-medium">Share</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {rows.map((r) => (
          <tr key={r.id} className="border-t border-hair-soft">
            <td className="py-1.5">
              <button
                type="button"
                onClick={() => onDrill(r.mark)}
                className="flex items-center gap-2 text-left hover:underline"
              >
                {r.color ? (
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 shrink-0 rounded-sm"
                    style={{ background: r.color }}
                  />
                ) : null}
                {r.label}
              </button>
            </td>
            <td className="py-1.5 text-right">{formatValue(data, r.value)}</td>
            <td className="py-1.5 text-right text-muted">{share(r.value, total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

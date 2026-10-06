import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  EyeOff,
  GripVertical,
  MoreHorizontal,
  Users,
} from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { errorText } from '@/features/ai';
import { useProjects } from '@/features/projects';
import { formatEffort, hours, TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { addDays, fromISODate, toISODate } from '@/lib/dates';
import { mondayOf, shiftWeeks, toneOf, weeksBetween, type Tone } from './grid';
import {
  useCapacityMutations,
  useMoveTask,
  useWorkload,
  useWorkloadRow,
  workloadKeys,
  type PersonLoad,
  type WeekLoad,
  type Workload,
  type WorkloadTask,
} from './queries';
import { previewOf, RebalancePanel, useRebalance, type LoadPreview } from './Rebalance';

type Mode = 'hours' | 'tasks';
const WEEK_OPTIONS = [4, 6, 8, 12] as const;

const TONE: Record<Tone, string> = {
  idle: 'bg-surface text-muted-2',
  ok: 'bg-ok-tint text-ink',
  warn: 'bg-warn-tint text-ink',
  crit: 'bg-crit-tint text-crit',
  away: 'bg-surface-2 text-muted [background-image:repeating-linear-gradient(135deg,transparent_0_6px,var(--color-hair-soft)_6px_7px)]',
};
const BAR: Record<Tone, string> = {
  idle: 'bg-transparent',
  ok: 'bg-ok',
  warn: 'bg-warn',
  crit: 'bg-crit',
  away: 'bg-transparent',
};

const weekLabel = (iso: string) =>
  fromISODate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/**
 * Workload (S6.4.1): who is carrying what, week by week, against the hours they have. One row per
 * person, one column per week; each cell is tinted by how full the week is. Open a cell to see its
 * tasks; drag a task to another person or week to rebalance (one undo each).
 */
export function WorkloadPage({ portfolioId }: { portfolioId?: string } = {}) {
  return (
    <TaskNavProvider>
      <WorkloadBody portfolioId={portfolioId ?? null} />
    </TaskNavProvider>
  );
}

/** With `portfolioId` (Phase 7.5, a portfolio's Workload tab): only that portfolio's projects,
 * no project picker and no rebalance suggestion (it works per project or workspace). */
function WorkloadBody({ portfolioId }: { portfolioId: string | null }) {
  const nav = useTaskNav()!;
  const [start, setStart] = useState(() => mondayOf(toISODate(new Date())));
  const [weeks, setWeeks] = useState<number>(6);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [modeChoice, setMode] = useState<Mode | null>(null);
  const [open, setOpen] = useState<{ person: string; week: string } | null>(null);
  const q = useWorkload(start, weeks, projectId, portfolioId);
  const row = useWorkloadRow(start, weeks, projectId, open?.person ?? null, portfolioId);
  const qc = useQueryClient();
  const projects = useProjects().data;
  const thisWeek = mondayOf(toISODate(new Date()));
  const aiEnabled = useMomentumConfig().ai_enabled;
  const rebalance = useRebalance();
  const suggestion = rebalance.data;
  const preview = useMemo(() => (suggestion ? previewOf(suggestion) : null), [suggestion]);
  const suggest = () => rebalance.mutate({ start, weeks, projectId });
  const { reset: resetSuggestion } = rebalance;
  // a suggestion is for the weeks and project it was made for
  useEffect(() => resetSuggestion(), [start, weeks, projectId, resetSuggestion]);

  // a team that doesn't estimate yet sees task counts, not a misleading wall of 0h
  const data = q.data;
  const estimated = useMemo(() => (data ? data.any_estimate : true), [data]);
  const mode: Mode = modeChoice ?? (estimated ? 'hours' : 'tasks');

  // edits made in the task pane show up in the grid when it closes
  const wasOpen = useRef(nav.openId);
  useEffect(() => {
    if (wasOpen.current && !nav.openId) void qc.invalidateQueries({ queryKey: workloadKeys.all });
    wasOpen.current = nav.openId;
  }, [nav.openId, qc]);

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-4 py-6 md:px-8">
        <header className="mb-4 flex flex-wrap items-center gap-2">
          {portfolioId ? (
            <h2 className="mr-auto text-[15px] font-semibold">Workload of this portfolio’s projects</h2>
          ) : (
            <h1 className="mr-auto page-title">Workload</h1>
          )}
          {portfolioId ? null : (
            <>
              <label className="sr-only" htmlFor="workload-project">
                Project
              </label>
              <select
                id="workload-project"
                value={projectId ?? ''}
                onChange={(e) => setProjectId(e.target.value || null)}
                className="h-8 max-w-48 rounded-md border border-hairline bg-surface px-2 text-sm"
              >
                <option value="">All projects</option>
                {(projects ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </>
          )}
          <div className="flex rounded-md bg-surface-2 p-0.5 text-sm" role="group" aria-label="Show">
            {(['hours', 'tasks'] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={mode === k}
                onClick={() => setMode(k)}
                className={cn(
                  'rounded px-2.5 py-1',
                  mode === k ? 'bg-surface shadow-sm' : 'text-muted hover:text-ink',
                )}
              >
                {k === 'hours' ? 'Hours' : 'Tasks'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <IconButton
              icon={ChevronLeft}
              label="Earlier weeks"
              size="icon-sm"
              onClick={() => setStart((s) => toISODate(addDays(fromISODate(s), -7)))}
            />
            <Button size="sm" onClick={() => setStart(thisWeek)} disabled={start === thisWeek}>
              This week
            </Button>
            <IconButton
              icon={ChevronRight}
              label="Later weeks"
              size="icon-sm"
              onClick={() => setStart((s) => toISODate(addDays(fromISODate(s), 7)))}
            />
          </div>
          <label className="sr-only" htmlFor="workload-weeks">
            Weeks shown
          </label>
          <select
            id="workload-weeks"
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="h-8 rounded-md border border-hairline bg-surface px-2 text-sm"
          >
            {WEEK_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} weeks
              </option>
            ))}
          </select>
          {data?.can_admin ? <DefaultHours data={data} /> : null}
          {aiEnabled && !portfolioId && data?.people.length ? (
            <Button variant="ai" size="sm" loading={rebalance.isPending} onClick={suggest}>
              <MoMark size={13} /> Suggest rebalance
            </Button>
          ) : null}
        </header>
        {rebalance.isError ? (
          <p role="alert" className="mb-3 rounded-md bg-crit-tint px-3 py-2 text-sm text-crit">
            {errorText(rebalance.error)}
          </p>
        ) : null}
        {preview?.size ? (
          <p
            role="status"
            className="mb-3 flex items-center gap-2 rounded-md border border-dashed border-amber bg-amber-2/60 px-3 py-2 text-[13px] text-amber-ink"
          >
            <MoMark size={13} /> Previewing the load after the suggested changes. Nothing is saved until you
            apply.
          </p>
        ) : null}

        {q.isPending ? (
          <Skeleton className="h-80" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : data!.people.length === 0 ? (
          <EmptyState icon={Users} title="No one to plan for yet">
            Invite your team; their work shows up here week by week.
          </EmptyState>
        ) : (
          <Grid
            data={data!}
            mode={mode}
            thisWeek={thisWeek}
            open={open}
            setOpen={setOpen}
            openTasks={row.data}
            onOpenTask={(id) => nav.open(id)}
            preview={preview}
          />
        )}
        {data ? <Footnote data={data} /> : null}
      </div>
      {suggestion && !nav.openId ? (
        <RebalancePanel
          result={suggestion}
          onClose={resetSuggestion}
          onRetry={suggest}
          retrying={rebalance.isPending}
        />
      ) : null}
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
        />
      ) : null}
    </div>
  );
}

interface Drag {
  task: WorkloadTask;
  person: string | null;
  week: string;
}

function Grid({
  data,
  mode,
  thisWeek,
  open,
  setOpen,
  openTasks,
  onOpenTask,
  preview,
}: {
  data: Workload;
  mode: Mode;
  thisWeek: string;
  open: { person: string; week: string } | null;
  setOpen: (v: { person: string; week: string } | null) => void;
  openTasks: WorkloadTask[] | undefined;
  onOpenTask: (id: string) => void;
  preview: LoadPreview | null;
}) {
  const move = useMoveTask();
  const drag = useRef<Drag | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const rows = [...data.people, data.unassigned];
  const key = (p: PersonLoad) => p.user_id ?? 'unassigned';

  // the open row's tasks load on demand (undefined while loading)
  const tasksIn = (p: PersonLoad, week: string) =>
    openTasks?.filter((t) => (t.assignee_id ?? null) === (p.user_id ?? null) && week in t.weeks);

  const moveTo = (d: Drag, person: PersonLoad, week: string) => {
    const personChanged = (person.user_id ?? null) !== d.person;
    const delta = weeksBetween(d.week, week);
    if (!personChanged && delta === 0) return;
    const parts = [
      personChanged ? (person.user_id ? `to ${person.name}` : 'to no one') : null,
      delta
        ? `${Math.abs(delta)} week${Math.abs(delta) === 1 ? '' : 's'} ${delta > 0 ? 'later' : 'earlier'}`
        : null,
    ].filter(Boolean);
    move.mutate({
      task: d.task,
      ...(personChanged ? { assigneeId: person.user_id ?? null } : {}),
      ...(delta ? { dates: shiftWeeks(d.task, delta) } : {}),
      message: `Moved ${d.task.title} ${parts.join(', ')}`,
    });
  };

  const dropProps = (p: PersonLoad, week: string) => {
    const id = `${key(p)}:${week}`;
    return {
      'data-drop': over === id ? 'over' : undefined,
      onDragOver: (e: DragEvent) => {
        if (!drag.current) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (over !== id) setOver(id);
      },
      onDragLeave: () => setOver((o) => (o === id ? null : o)),
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        setOver(null);
        if (drag.current) moveTo(drag.current, p, week);
        drag.current = null;
      },
    };
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
      <div
        role="grid"
        aria-label="Workload"
        aria-rowcount={rows.length + 1}
        className="grid min-w-[720px]"
        style={{
          gridTemplateColumns: `minmax(180px, 220px) repeat(${data.weeks.length}, minmax(96px, 1fr))`,
        }}
      >
        <div role="row" className="contents">
          <div
            role="columnheader"
            className="sticky left-0 z-10 border-b border-hairline bg-surface px-4 py-2 text-xs text-muted"
          >
            Person
          </div>
          {data.weeks.map((w) => (
            <div
              key={w}
              role="columnheader"
              className={cn(
                'border-b border-l border-hair-soft px-2 py-2 text-xs',
                w === thisWeek ? 'font-semibold text-accent' : 'text-muted',
              )}
            >
              {w === thisWeek ? 'This week' : `Week of ${weekLabel(w)}`}
            </div>
          ))}
        </div>
        {rows.map((p) => {
          const k = key(p);
          const expanded = open?.person === k ? open.week : null;
          return (
            <Fragment key={k}>
              <div role="row" className="contents">
                <PersonCell person={p} />
                {p.weeks.map((w) => (
                  <WeekCell
                    key={w.week_start}
                    person={p}
                    week={w}
                    mode={mode}
                    after={p.user_id ? preview?.get(p.user_id)?.get(w.week_start) : undefined}
                    expanded={expanded === w.week_start}
                    onToggle={() =>
                      setOpen(expanded === w.week_start ? null : { person: k, week: w.week_start })
                    }
                    dropProps={dropProps(p, w.week_start)}
                  />
                ))}
              </div>
              {expanded ? (
                <div role="row" className="contents">
                  <div
                    role="gridcell"
                    className="col-span-full border-b border-hairline bg-surface-2/60 px-4 py-3"
                  >
                    <WeekDetail
                      person={p}
                      week={p.weeks.find((w) => w.week_start === expanded)!}
                      tasks={tasksIn(p, expanded)}
                      onOpenTask={onOpenTask}
                      onDragStart={(t) =>
                        (drag.current = { task: t, person: p.user_id ?? null, week: expanded })
                      }
                      onDragEnd={() => {
                        drag.current = null;
                        setOver(null);
                      }}
                      onMove={(t, target, delta) =>
                        moveTo(
                          { task: t, person: p.user_id ?? null, week: expanded },
                          target,
                          toISODate(addDays(fromISODate(expanded), delta * 7)),
                        )
                      }
                      rows={rows}
                    />
                  </div>
                </div>
              ) : null}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

function PersonCell({ person }: { person: PersonLoad }) {
  const unassigned = person.user_id === null;
  return (
    <div
      role="rowheader"
      className="sticky left-0 z-10 flex min-w-0 items-center gap-2 border-b border-hair-soft bg-surface px-4 py-2"
    >
      {unassigned ? (
        <span className="grid h-6 w-6 place-items-center rounded-full border border-dashed border-hairline text-muted-2">
          <Icon icon={Users} size={13} />
        </span>
      ) : (
        <Avatar name={person.name} src={person.avatar_url ?? null} size={24} />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{person.name}</div>
        <div className="flex flex-wrap gap-x-2 text-[11px] text-muted-2">
          {unassigned ? <span>No one yet</span> : <WeeklyHours person={person} />}
          {person.no_date ? (
            <span title="Open tasks with no due date aren't placed in a week">{person.no_date} no date</span>
          ) : null}
          {person.hidden ? (
            <span
              className="inline-flex items-center gap-0.5"
              title="Open tasks in projects you can't see (counted, not shown)"
            >
              <Icon icon={EyeOff} size={11} /> {person.hidden} elsewhere
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function WeekCell({
  person,
  week,
  mode,
  after,
  expanded,
  onToggle,
  dropProps,
}: {
  person: PersonLoad;
  week: WeekLoad;
  mode: Mode;
  /** ✦ rebalance preview: this cell's hours before and after the suggested moves */
  after?: { before: number; after: number } | undefined;
  expanded: boolean;
  onToggle: () => void;
  dropProps: Record<string, unknown>;
}) {
  const unassigned = person.user_id === null;
  // while a rebalance is previewed, a cell it changes shows the load after it (in hours)
  const planned = after ? after.after : week.planned_minutes;
  const tone: Tone = unassigned ? 'idle' : toneOf(planned, week.capacity_minutes);
  const pct = week.capacity_minutes ? Math.min(100, (planned / week.capacity_minutes) * 100) : 0;
  const main =
    mode === 'hours' || after
      ? unassigned
        ? week.planned_minutes
          ? hours(week.planned_minutes)
          : ''
        : `${hours(planned)} / ${hours(week.capacity_minutes)}`
      : week.task_count
        ? `${week.task_count} task${week.task_count === 1 ? '' : 's'}`
        : '';
  const label = [
    `${person.name}, week of ${weekLabel(week.week_start)}:`,
    `${formatEffort(week.planned_minutes) || '0h'} planned`,
    unassigned ? null : `of ${hours(week.capacity_minutes)}`,
    `${week.task_count} tasks`,
    week.unestimated ? `${week.unestimated} without an estimate` : null,
    tone === 'crit' ? 'over capacity' : tone === 'warn' ? 'nearly full' : null,
    after ? `after the suggested changes: ${hours(after.after)}, now ${hours(after.before)}` : null,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div
      role="gridcell"
      className="border-b border-l border-hair-soft p-1 data-[drop=over]:bg-accent-tint"
      {...dropProps}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={expanded}
        onClick={onToggle}
        className={cn(
          'relative flex h-12 w-full flex-col justify-center overflow-hidden rounded-md px-2 text-left text-xs transition-colors',
          'hover:ring-1 hover:ring-hairline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none',
          TONE[tone],
          unassigned && week.task_count > 0 && 'bg-surface-2 text-ink',
          expanded && 'ring-2 ring-accent',
          after && 'outline-dashed outline-2 -outline-offset-2 outline-amber',
        )}
      >
        {tone === 'away' ? (
          <span className="text-muted">Away</span>
        ) : (
          <span className="tabular font-medium">{main}</span>
        )}
        <span className="flex items-center gap-1 text-[10px] text-muted">
          {after ? (
            <span className="text-amber-ink">
              was <span className="line-through">{hours(after.before)}</span>
            </span>
          ) : null}
          {week.override && tone !== 'away' ? <span>{hours(week.capacity_minutes)} this week</span> : null}
          {week.unestimated ? (
            <span className="inline-flex items-center gap-0.5" title="Tasks without an estimate count as 0h">
              +{week.unestimated} unestimated
            </span>
          ) : null}
        </span>
        {!unassigned && (mode === 'hours' || after) && week.capacity_minutes > 0 ? (
          <span className="absolute inset-x-0 bottom-0 h-1 bg-hair-soft" aria-hidden>
            <span className={cn('block h-full', BAR[tone])} style={{ width: `${pct}%` }} />
          </span>
        ) : null}
      </button>
    </div>
  );
}

function WeekDetail({
  person,
  week,
  tasks,
  rows,
  onOpenTask,
  onDragStart,
  onDragEnd,
  onMove,
}: {
  person: PersonLoad;
  week: WeekLoad;
  tasks: WorkloadTask[] | undefined;
  rows: PersonLoad[];
  onOpenTask: (id: string) => void;
  onDragStart: (t: WorkloadTask) => void;
  onDragEnd: () => void;
  onMove: (t: WorkloadTask, target: PersonLoad, weeks: number) => void;
}) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-start">
      <div className="min-w-0 flex-1">
        <div className="mb-2 text-xs text-muted">
          {person.name} · week of {weekLabel(week.week_start)} · drag a task onto another person or week
        </div>
        {tasks === undefined ? (
          <Skeleton className="h-16" />
        ) : tasks.length === 0 ? (
          <p className="text-sm text-muted">Nothing planned this week.</p>
        ) : (
          <ul
            aria-label={`${person.name}'s tasks, week of ${weekLabel(week.week_start)}`}
            className="flex flex-col gap-1"
          >
            {tasks.map((t) => (
              <li
                key={t.id}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = 'move';
                  e.dataTransfer.setData('text/plain', t.title);
                  onDragStart(t);
                }}
                onDragEnd={onDragEnd}
                className="group flex cursor-grab items-center gap-2 rounded-md border border-hair-soft bg-surface px-2 py-1.5 text-sm active:cursor-grabbing"
              >
                <Icon icon={GripVertical} size={14} className="text-muted-2" />
                <button
                  type="button"
                  onClick={() => onOpenTask(t.id)}
                  className="min-w-0 flex-1 truncate text-left hover:underline"
                >
                  {t.title}
                </button>
                <span className="hidden truncate text-xs text-muted sm:inline">{t.project_name}</span>
                {t.overdue ? (
                  <span className="inline-flex items-center gap-0.5 text-xs text-crit">
                    <Icon icon={AlertTriangle} size={12} /> Overdue
                  </span>
                ) : null}
                <span className="tabular w-16 text-right text-xs text-muted">
                  {t.estimate_minutes === null ? 'No estimate' : hours(t.weeks[week.week_start] ?? 0)}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <IconButton icon={MoreHorizontal} label={`Move ${t.title}`} size="icon-sm" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => onMove(t, person, -1)}>A week earlier</DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => onMove(t, person, 1)}>A week later</DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel>Give to</DropdownMenuLabel>
                    {rows
                      .filter((r) => r.user_id !== person.user_id)
                      .map((r) => (
                        <DropdownMenuItem key={r.user_id ?? 'none'} onSelect={() => onMove(t, r, 0)}>
                          {r.user_id ? r.name : 'No one'}
                        </DropdownMenuItem>
                      ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            ))}
          </ul>
        )}
      </div>
      {person.can_edit ? <WeekHours person={person} week={week} /> : null}
    </div>
  );
}

/** One week's hours for a person: time off, a short week, or back to usual. */
function WeekHours({ person, week }: { person: PersonLoad; week: WeekLoad }) {
  const m = useCapacityMutations();
  const [value, setValue] = useState(String(week.capacity_minutes / 60));
  useEffect(() => setValue(String(week.capacity_minutes / 60)), [week.capacity_minutes]);
  const set = (h: number | null, message: string) =>
    m.week.mutate({ userId: person.user_id!, week: week.week_start, hours: h, message });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const h = Number(value);
    if (Number.isFinite(h) && h >= 0 && h <= 80)
      set(h, `${person.name}: ${h}h the week of ${weekLabel(week.week_start)}`);
  };
  const id = `week-hours-${person.user_id}-${week.week_start}`;
  return (
    <form
      onSubmit={submit}
      aria-label="This week's hours"
      className="w-full rounded-lg border border-hair-soft bg-surface p-3 text-sm md:w-64"
    >
      <label htmlFor={id} className="mb-1 block text-xs text-muted">
        Hours this week
      </label>
      <div className="flex gap-2">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-20"
        />
        <Button type="submit" size="sm">
          Save
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Button
          type="button"
          size="sm"
          variant="text"
          onClick={() => set(0, `${person.name} is away the week of ${weekLabel(week.week_start)}`)}
        >
          Away all week
        </Button>
        {week.override ? (
          <Button type="button" size="sm" variant="text" onClick={() => set(null, 'Back to usual hours')}>
            Back to usual ({hours(person.weekly_minutes)})
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** A person's usual weekly hours; editable by them or an admin. */
function WeeklyHours({ person }: { person: PersonLoad }) {
  const m = useCapacityMutations();
  const [value, setValue] = useState(String(person.weekly_minutes / 60));
  const [openPop, setOpenPop] = useState(false);
  useEffect(() => setValue(String(person.weekly_minutes / 60)), [person.weekly_minutes]);
  const text = `${hours(person.weekly_minutes)}/wk`;
  if (!person.can_edit) return <span>{text}</span>;
  const save = (h: number | null) => {
    m.hours.mutate({
      userId: person.user_id!,
      hours: h,
      message: h === null ? `${person.name}: back to the default hours` : `${person.name}: ${h}h a week`,
    });
    setOpenPop(false);
  };
  const id = `weekly-hours-${person.user_id}`;
  return (
    <Popover open={openPop} onOpenChange={setOpenPop}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="underline decoration-dotted underline-offset-2 hover:text-ink"
          aria-label={`${person.name}'s usual hours: ${text}`}
        >
          {text}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-60 p-3">
        <form
          aria-label="Usual weekly hours"
          onSubmit={(e) => {
            e.preventDefault();
            const h = Number(value);
            if (Number.isFinite(h) && h >= 0 && h <= 80) save(h);
          }}
        >
          <label htmlFor={id} className="mb-1 block text-xs text-muted">
            Usual hours a week
          </label>
          <div className="flex gap-2">
            <Input
              id={id}
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-20"
            />
            <Button type="submit" size="sm" variant="primary">
              Save
            </Button>
          </div>
          {person.hours_source === 'person' ? (
            <Button type="button" size="sm" variant="text" className="mt-2" onClick={() => save(null)}>
              Use the workspace default
            </Button>
          ) : (
            <p className="mt-2 text-xs text-muted-2">Using the workspace default.</p>
          )}
        </form>
      </PopoverContent>
    </Popover>
  );
}

/** Admins: the hours everyone plans against unless they set their own. */
function DefaultHours({ data }: { data: Workload }) {
  const m = useCapacityMutations();
  const [value, setValue] = useState(String(data.default_minutes / 60));
  const [openPop, setOpenPop] = useState(false);
  useEffect(() => setValue(String(data.default_minutes / 60)), [data.default_minutes]);
  return (
    <Popover open={openPop} onOpenChange={setOpenPop}>
      <PopoverTrigger asChild>
        <Button size="sm">Default {hours(data.default_minutes)}/wk</Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-3">
        <form
          aria-label="Default weekly hours"
          onSubmit={(e) => {
            e.preventDefault();
            const h = Number(value);
            if (!Number.isFinite(h) || h < 0 || h > 80) return;
            m.workspace.mutate({ hours: h, message: `Default hours: ${h}h a week` });
            setOpenPop(false);
          }}
        >
          <label htmlFor="default-hours" className="mb-1 block text-xs text-muted">
            Default hours a week (everyone who hasn't set their own)
          </label>
          <div className="flex gap-2">
            <Input
              id="default-hours"
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-20"
            />
            <Button type="submit" size="sm" variant="primary">
              Save
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}

function Footnote({ data }: { data: Workload }) {
  const hidden = data.people.reduce((n, p) => n + p.hidden, 0);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-ok" aria-hidden /> Room to spare
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-warn" aria-hidden /> Nearly full (85%+)
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-crit" aria-hidden /> Over capacity
      </span>
      <span className="ml-auto">
        Effort is spread over each task's working days. Only work in projects you can see is shown
        {hidden
          ? `; ${hidden} open task${hidden === 1 ? '' : 's'} elsewhere ${hidden === 1 ? 'is' : 'are'} counted, not shown`
          : ''}
        .
      </span>
    </div>
  );
}

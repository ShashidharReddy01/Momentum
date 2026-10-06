import { useQueryClient } from '@tanstack/react-query';
import type { JSONContent } from '@tiptap/react';
import { CalendarDays, Diamond, Flag, ListChecks, Plus, Users } from 'lucide-react';
import { lazy, Suspense, useMemo, useRef, useState } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  FieldValueChip,
  FieldValueEditor,
  NewFieldForm,
  projectFieldKeys,
  useProjectDetails,
  useProjectFieldDefMutations,
  useProjectFieldDefs,
  useSetProjectDetail,
  type FieldCreate,
} from '@/features/fields';
import { ForecastCard, forecastKey } from '@/features/forecasts';
import { usePeople } from '@/features/people';
import { StatusChip, StatusOverview, useStatusUpdates, type Status } from '@/features/status';
import { DatePicker, useTaskNav } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { dayDiff, formatRelative, fromISODate } from '@/lib/dates';
import { useChannel } from '@/lib/realtime';
import { projectKeys, useProjectOverview, useUpdateProject, type ProjectDetail } from './queries';

// Lazy, like the task pane: the editor is the heaviest thing on the page.
const RichTextEditor = lazy(() =>
  import('@/components/editor/RichTextEditor').then((m) => ({ default: m.RichTextEditor })),
);

const DATE = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
const SHORT = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const MILESTONES_SHOWN = 8;
const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin',
  editor: 'Editor',
  commenter: 'Commenter',
  viewer: 'Viewer',
};

const until = (iso: string) => dayDiff(new Date(), fromISODate(iso));
const inWords = (days: number) =>
  days === 0
    ? 'today'
    : days > 0
      ? `in ${days} ${days === 1 ? 'day' : 'days'}`
      : `${-days} ${days === -1 ? 'day' : 'days'} ago`;

/**
 * Project overview (S6.2.1). A summary strip answers "how is it going?" at a glance (status,
 * progress with overdue work, key dates with days left, the next milestone), then the brief
 * (editable in place, autosaved on blur), status updates with Mo's draft and Radar's risk note,
 * milestones as a small vertical timeline, and the members with their roles. Everything shown
 * comes from real data; an unset date or a project without milestones says so and, for editors,
 * how to set it.
 */
export function ProjectOverview({
  project,
  canEdit,
  startDraft,
}: {
  project: ProjectDetail;
  canEdit: boolean;
  startDraft: boolean;
}) {
  const qc = useQueryClient();
  const overview = useProjectOverview(project.id);
  // task changes move the numbers; a project edit elsewhere (dates, brief, status) refreshes it
  useChannel(`project:${project.id}`, (event) => {
    if (event.event === 'project.forecast_updated')
      void qc.invalidateQueries({ queryKey: forecastKey(project.id) });
    void qc.invalidateQueries({ queryKey: ['projects', project.id, 'overview'] });
    if (event.event.startsWith('project.') || event.event.startsWith('status_update.'))
      void qc.invalidateQueries({ queryKey: projectKeys.detail(project.id) });
    if (event.event === 'project.field_changed')
      void qc.invalidateQueries({ queryKey: projectFieldKeys.values(project.id) });
  });

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section aria-label="Summary" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatusTile projectId={project.id} status={(project.status ?? null) as Status | null} />
        <ProgressTile overview={overview.data} />
        <DatesTile project={project} canEdit={canEdit} />
        <MilestoneTile overview={overview.data} />
      </section>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <ForecastCard projectId={project.id} />
          <Brief project={project} canEdit={canEdit} />
          <StatusOverview projectId={project.id} canEdit={canEdit} startDraft={startDraft} />
        </div>
        <aside className="space-y-6" aria-label="Details, milestones and members">
          <Details projectId={project.id} canEdit={canEdit} />
          <Milestones overview={overview.data} loading={overview.isPending} />
          <Members project={project} />
        </aside>
      </div>
    </div>
  );
}

function Tile({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        'flex min-h-24 flex-col gap-1.5 rounded-xl border border-hairline bg-surface p-4',
        className,
      )}
    >
      <span className="text-xs font-medium tracking-wide text-muted uppercase">{label}</span>
      {children}
    </div>
  );
}

/** The status and the latest update's headline, who posted it and when (the full update is in
 * the Status section below; this is the one-glance version). */
function StatusTile({ projectId, status }: { projectId: string; status: Status | null }) {
  const latest = useStatusUpdates(projectId).data?.[0];
  const people = usePeople().data;
  const author = latest ? (people?.find((p) => p.id === latest.author_id)?.name ?? 'Former member') : null;
  return (
    <Tile label="Status">
      {status ? (
        <div>
          <StatusChip status={status} />
        </div>
      ) : (
        <span className="text-sm text-muted">No status posted yet</span>
      )}
      {latest ? (
        <>
          <p className="line-clamp-2 text-sm text-ink-2">{latest.title}</p>
          <p className="text-xs text-muted">
            {author} · {formatRelative(latest.created_at)}
          </p>
        </>
      ) : null}
    </Tile>
  );
}

/** A ring for "% of tasks done"; a bespoke SVG like the rest of our small visuals. */
function Ring({ value }: { value: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden className="shrink-0 -rotate-90">
      <circle cx="28" cy="28" r={r} fill="none" stroke="var(--hair-soft)" strokeWidth="6" />
      <circle
        cx="28"
        cy="28"
        r={r}
        fill="none"
        stroke="var(--ok)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${c * value} ${c}`}
      />
    </svg>
  );
}

function ProgressTile({ overview }: { overview: ReturnType<typeof useProjectOverview>['data'] }) {
  if (!overview) {
    return (
      <Tile label="Progress">
        <Skeleton className="h-10" />
      </Tile>
    );
  }
  const { total_tasks: total, completed_tasks: done, overdue_tasks: overdue } = overview;
  const pct = total ? done / total : 0;
  return (
    <Tile label="Progress">
      {total ? (
        <div className="flex items-center gap-3">
          <Ring value={pct} />
          <div>
            <p className="text-2xl leading-none font-semibold tabular-nums">{Math.round(pct * 100)}%</p>
            <p className="mt-1 text-sm text-muted tabular-nums">
              {done} of {total} tasks done
            </p>
            {overdue ? <p className="text-sm text-crit tabular-nums">{overdue} overdue</p> : null}
          </div>
        </div>
      ) : (
        <span className="text-sm text-muted-2">No tasks yet</span>
      )}
    </Tile>
  );
}

function DatesTile({ project, canEdit }: { project: ProjectDetail; canEdit: boolean }) {
  const update = useUpdateProject(project.id);
  const due = project.due_on ?? null;
  const start = project.start_on ?? null;
  const left = due ? until(due) : null;
  return (
    <Tile label="Dates">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <DateField
          label="Due date"
          value={due}
          canEdit={canEdit}
          empty="Set a due date"
          onChange={(v) => update.mutate({ due_on: v })}
          className="text-lg font-semibold"
        />
        {left !== null ? (
          <span
            className={cn(
              'text-sm tabular-nums',
              left < 0 ? 'text-crit' : left <= 7 ? 'text-warn' : 'text-muted',
            )}
          >
            {left < 0 ? `${-left} days late` : left === 0 ? 'due today' : `${left} days left`}
          </span>
        ) : null}
      </div>
      <div className="flex items-baseline gap-1 text-sm text-muted">
        Started
        <DateField
          label="Start date"
          value={start}
          canEdit={canEdit}
          empty="not set"
          onChange={(v) => update.mutate({ start_on: v })}
        />
      </div>
    </Tile>
  );
}

function DateField({
  label,
  value,
  canEdit,
  empty,
  onChange,
  className,
}: {
  label: string;
  value: string | null;
  canEdit: boolean;
  empty: string;
  onChange: (iso: string | null) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const text = value ? DATE.format(fromISODate(value)) : empty;
  if (!canEdit) return <span className={cn(!value && 'text-muted-2', className)}>{text}</span>;
  return (
    <DatePicker
      open={open}
      onOpenChange={setOpen}
      dueOn={value}
      dueAt={null}
      allowClear
      onChange={(v) => onChange(v?.date ?? null)}
    >
      <button
        type="button"
        aria-label={`${label}: ${value ? text : 'not set'}`}
        className={cn(
          'rounded px-0.5 hover:bg-surface-2',
          !value && 'text-muted-2 underline decoration-dotted',
          className,
        )}
      >
        {text}
      </button>
    </DatePicker>
  );
}

function MilestoneTile({ overview }: { overview: ReturnType<typeof useProjectOverview>['data'] }) {
  const next = overview?.milestones.find((m) => !m.completed_at && m.due_on);
  return (
    <Tile label="Next milestone">
      {!overview ? (
        <Skeleton className="h-10" />
      ) : next ? (
        <div>
          <p className="flex items-center gap-1.5 font-medium">
            <Icon icon={Diamond} size={14} className="shrink-0" />
            <span className="truncate">{next.title}</span>
          </p>
          <p className={cn('text-sm tabular-nums', until(next.due_on!) < 0 ? 'text-crit' : 'text-muted')}>
            {SHORT.format(fromISODate(next.due_on!))} · {inWords(until(next.due_on!))}
          </p>
        </div>
      ) : (
        <span className="text-sm text-muted-2">
          {overview.milestones.length ? 'All milestones are done' : 'No milestones yet'}
        </span>
      )}
    </Tile>
  );
}

function Brief({ project, canEdit }: { project: ProjectDetail; canEdit: boolean }) {
  const update = useUpdateProject(project.id);
  const draft = useRef<JSONContent | null>(null);
  const saved = useMemo(() => JSON.stringify(project.brief ?? null), [project.brief]);
  const save = () => {
    if (draft.current === null) return;
    const next = JSON.stringify(draft.current);
    if (next !== saved) update.mutate({ brief: draft.current as Record<string, unknown> });
  };
  const empty = !project.brief;
  return (
    <section aria-labelledby="brief-heading" className="rounded-xl border border-hairline bg-surface p-5">
      <h2 id="brief-heading" className="mb-2 flex items-center gap-2 text-[15px] font-semibold">
        <Icon icon={Flag} size={15} /> Brief
      </h2>
      {!canEdit && empty ? (
        <p className="text-sm text-muted-2">No brief yet.</p>
      ) : (
        <Suspense fallback={<Skeleton className="h-24" />}>
          <RichTextEditor
            content={(project.brief as JSONContent | null) ?? null}
            revision={project.version}
            editable={canEdit}
            placeholder="What is this project for, what does done look like, and what's out of scope?"
            label="Project brief"
            onChange={(doc) => (draft.current = doc)}
            onBlur={save}
            className="min-h-24"
          />
        </Suspense>
      )}
    </section>
  );
}

function Milestones({
  overview,
  loading,
}: {
  overview: ReturnType<typeof useProjectOverview>['data'];
  loading: boolean;
}) {
  const nav = useTaskNav();
  const [all, setAll] = useState(false);
  const list = overview?.milestones ?? [];
  // the recent past and what's coming stay in view; the rest behind "Show all"
  const firstOpen = Math.max(
    0,
    list.findIndex((m) => !m.completed_at),
  );
  const start = all ? 0 : Math.max(0, firstOpen - 2);
  const shown = all ? list : list.slice(start, start + MILESTONES_SHOWN);
  return (
    <section aria-labelledby="ms-heading" className="rounded-xl border border-hairline bg-surface p-5">
      <h2 id="ms-heading" className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
        <Icon icon={CalendarDays} size={15} /> Milestones
      </h2>
      {loading ? <Skeleton className="h-20" /> : null}
      {overview && !overview.milestones.length ? (
        <p className="text-sm text-muted-2">
          None yet. Turn a task into a milestone from its menu to track key dates here and on the timeline.
        </p>
      ) : null}
      <ol className="relative space-y-3 border-l border-hairline pl-4">
        {shown.map((m) => {
          const late = !m.completed_at && m.due_on && until(m.due_on) < 0;
          return (
            <li key={m.id} className="relative">
              <span
                aria-hidden
                className={cn(
                  'absolute top-1.5 -left-[21px] h-2.5 w-2.5 rotate-45 rounded-[2px]',
                  m.completed_at ? 'bg-ok' : late ? 'bg-crit' : 'bg-ink',
                )}
              />
              <button
                type="button"
                onClick={() => nav?.open(m.id)}
                className={cn(
                  'text-left text-sm font-medium hover:underline',
                  m.completed_at && 'text-muted line-through',
                )}
              >
                {m.title}
              </button>
              <p className={cn('text-xs tabular-nums', late ? 'text-crit' : 'text-muted')}>
                {m.due_on
                  ? `${SHORT.format(fromISODate(m.due_on))} · ${m.completed_at ? 'done' : inWords(until(m.due_on))}`
                  : 'No date'}
              </p>
            </li>
          );
        })}
      </ol>
      {list.length > shown.length || all ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          className="mt-3 text-sm text-muted hover:text-ink"
        >
          {all ? 'Show fewer' : `Show all ${list.length}`}
        </button>
      ) : null}
    </section>
  );
}

/**
 * Phase 7.5 (spec §5.1): the project's own fields (Stage, Account owner, Contract value…), the
 * same definitions for every project in the workspace. Editors change them in place (each change
 * is undoable and kept in the field's history); everyone else reads them. An unset value says
 * "Not set" rather than showing a made-up default.
 */
function Details({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const defs = useProjectFieldDefs();
  const values = useProjectDetails(projectId);
  const set = useSetProjectDetail(projectId);
  const { create } = useProjectFieldDefMutations();
  const [adding, setAdding] = useState(false);
  const fields = defs.data ?? [];
  return (
    <section aria-labelledby="details-heading" className="rounded-xl border border-hairline bg-surface p-5">
      <h2 id="details-heading" className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
        <Icon icon={ListChecks} size={15} /> Details
      </h2>
      {defs.isPending || values.isPending ? (
        <Skeleton className="h-10" />
      ) : fields.length === 0 ? (
        <p className="text-sm text-muted">
          No project fields yet.
          {canEdit ? ' Add one, like Stage or Contract value, to describe every project the same way.' : ''}
        </p>
      ) : (
        <dl className="space-y-2">
          {fields.map((f) => {
            const value = values.data?.get(f.id) ?? null;
            return (
              <div
                key={f.id}
                className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-2 text-sm"
              >
                <dt className="truncate text-muted" title={f.name}>
                  {f.name}
                </dt>
                <dd className="min-w-0">
                  {canEdit ? (
                    <FieldValueEditor
                      field={f}
                      value={value}
                      onChange={(v) => set.mutate({ field: f, value: v })}
                    />
                  ) : value === null ? (
                    <span className="text-muted-2">Not set</span>
                  ) : (
                    <FieldValueChip field={f} value={value} />
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {canEdit ? (
        adding ? (
          <div className="mt-3">
            <NewFieldForm
              appliesTo="project"
              onCancel={() => setAdding(false)}
              onCreate={(v) => {
                create.mutate({ name: v.name, type: v.type, options: v.options } as FieldCreate);
                setAdding(false);
              }}
            />
          </div>
        ) : (
          <Button size="sm" variant="ghost" className="mt-2 justify-start" onClick={() => setAdding(true)}>
            <Icon icon={Plus} /> Add a project field
          </Button>
        )
      ) : null}
    </section>
  );
}

function Members({ project }: { project: ProjectDetail }) {
  return (
    <section aria-labelledby="members-heading" className="rounded-xl border border-hairline bg-surface p-5">
      <h2 id="members-heading" className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
        <Icon icon={Users} size={15} /> Members{' '}
        <span className="text-muted-2 tabular-nums">{project.members.length}</span>
      </h2>
      <ul className="space-y-2">
        {project.members.map((m) => (
          <li key={m.user.id} className="flex items-center gap-2 text-sm">
            <Avatar name={m.user.name} src={m.user.avatar_url} size={24} isAgent={m.user.is_agent} />
            <span className="min-w-0 flex-1 truncate">{m.user.name}</span>
            <span className="text-xs text-muted">{ROLE_LABEL[m.role] ?? m.role}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

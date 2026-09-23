import { useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CheckSquare, FolderKanban, FolderPlus, Hourglass } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { DueText } from '@/components/common/DueText';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { usePeople } from '@/features/people';
import { NewProjectDialog } from '@/features/projects';
import { TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { colorVar } from '@/features/teams';
import { cn } from '@/lib/cn';
import { applyUserChannelEvent, useChannel } from '@/lib/realtime';
import { homeKey, useCompleteFromHome, useHome, type HomeProject, type HomeTask } from './queries';

function greeting(date: Date): string {
  const h = date.getHours();
  if (h < 5) return 'Good evening';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** Home (ux-specs §2): my next tasks, recent projects, and overdue work I'm waiting on. */
export function HomePage() {
  return (
    <TaskNavProvider>
      <HomeBody />
    </TaskNavProvider>
  );
}

function HomeBody() {
  const nav = useTaskNav()!;
  const qc = useQueryClient();
  const meId = useMe().data?.user.id;
  useChannel(meId ? `user:${meId}` : null, (event) => applyUserChannelEvent(qc, event));
  const wasOpen = useRef(false);
  // edits made in the pane show on Home once it closes
  useEffect(() => {
    if (wasOpen.current && !nav.openId) void qc.invalidateQueries({ queryKey: homeKey });
    wasOpen.current = !!nav.openId;
  }, [nav.openId, qc]);
  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto">
        <HomeContent />
      </div>
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

function HomeContent() {
  const me = useMe();
  const home = useHome();
  const [newProject, setNewProject] = useState(false);
  const [now] = useState(() => new Date());
  const first = me.data?.user.name.split(' ')[0] ?? '';
  const counts = home.data?.counts;

  let summary: ReactNode = null;
  if (counts) {
    const parts = [
      counts.overdue ? `${plural(counts.overdue, 'task')} overdue` : null,
      counts.due_today ? `${counts.due_today} due today` : null,
    ].filter(Boolean);
    summary = parts.length
      ? parts.join(' · ')
      : counts.open
        ? `${plural(counts.open, 'open task')}, nothing due today`
        : null;
  }

  return (
    <div className="@container mx-auto max-w-5xl px-4 md:px-8 py-8">
      <h1 className="page-title">
        {greeting(now)}
        {first ? `, ${first}` : ''}
      </h1>
      <p className="mt-0.5 text-sm text-muted">
        {now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
        {summary ? (
          <>
            {' · '}
            <span className={cn(counts?.overdue ? 'text-crit' : counts?.due_today ? 'text-warn' : '')}>
              {summary}
            </span>
          </>
        ) : null}
      </p>

      {home.isPending ? (
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <Skeleton className="h-56 md:col-span-2" />
          <Skeleton className="h-56" />
          <Skeleton className="h-40 md:col-span-3" />
        </div>
      ) : home.isError ? (
        <div className="mt-6">
          <ErrorState error={home.error} onRetry={() => void home.refetch()} />
        </div>
      ) : !home.data.has_projects && !home.data.priorities.length ? (
        <div className="mt-10 rounded-lg border border-hairline bg-surface">
          <EmptyState
            icon={FolderPlus}
            title="Create your first project"
            action={
              <Button variant="primary" onClick={() => setNewProject(true)}>
                New project
              </Button>
            }
          >
            Projects hold your team&apos;s tasks. Once you&apos;re in one, your next tasks and recent work
            show up here.
          </EmptyState>
        </div>
      ) : (
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <Priorities tasks={home.data.priorities} open={home.data.counts.open} />
          <Waiting tasks={home.data.waiting} total={home.data.waiting_total} />
          <RecentProjects projects={home.data.recent_projects} onNew={() => setNewProject(true)} />
        </div>
      )}
      <NewProjectDialog open={newProject} onOpenChange={setNewProject} />
    </div>
  );
}

function Card({
  title,
  action,
  className,
  children,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className={cn('rounded-lg border border-hairline bg-surface p-4', className)}>
      <div className="mb-2 flex min-h-7 items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Priorities({ tasks, open }: { tasks: HomeTask[]; open: number }) {
  const nav = useTaskNav();
  const complete = useCompleteFromHome();
  return (
    <Card
      title="My priorities"
      className="md:col-span-2"
      action={
        open ? (
          <Link to="/my-tasks" className="flex items-center gap-1 text-xs text-muted hover:text-ink">
            {open > tasks.length ? `All ${open} in My Tasks` : 'My Tasks'}{' '}
            <Icon icon={ArrowRight} size={13} />
          </Link>
        ) : null
      }
    >
      {tasks.length === 0 ? (
        <EmptyState icon={CheckSquare} title="You're all caught up">
          Tasks assigned to you show up here, soonest due first.
        </EmptyState>
      ) : (
        <ul aria-label="My priorities" className="flex flex-col">
          {tasks.map((t) => {
            const done = !!t.completed_at;
            return (
              <li
                key={t.id}
                aria-label={t.title}
                className={cn(
                  'flex h-10 items-center gap-2 border-b border-hairline px-1 last:border-b-0',
                  done && 'opacity-60 transition-opacity duration-700',
                )}
              >
                <CompleteCheck
                  checked={done}
                  disabled={done}
                  label={`Complete ${t.title}`}
                  onChange={() => complete.mutate(t.id)}
                />
                <button
                  type="button"
                  onClick={() => nav?.open(t.id)}
                  className={cn(
                    'min-w-0 flex-1 truncate text-left text-[13.5px] hover:underline',
                    done && 'text-muted line-through',
                  )}
                >
                  {t.title}
                </button>
                {t.project ? <ProjectChip name={t.project.name} color={t.project.color} /> : null}
                <DueText dueOn={t.due_on} dueAt={t.due_at} done={done} className="w-24 shrink-0 text-right" />
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Waiting({ tasks, total }: { tasks: HomeTask[]; total: number }) {
  const nav = useTaskNav();
  const people = usePeople().data;
  const nameOf = (id: string | null) => (id ? people?.find((p) => p.id === id)?.name : undefined);
  return (
    <Card title="Waiting on others">
      {tasks.length === 0 ? (
        <EmptyState icon={Hourglass} title="Nothing overdue">
          Tasks you created or follow show here if they&apos;re late.
        </EmptyState>
      ) : (
        <>
          <ul aria-label="Waiting on others" className="flex flex-col">
            {tasks.map((t) => {
              const who = nameOf(t.assignee_id) ?? 'Someone';
              return (
                <li key={t.id} aria-label={t.title}>
                  <button
                    type="button"
                    onClick={() => nav?.open(t.id)}
                    className="flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left hover:bg-surface-2"
                  >
                    <Avatar name={who} size={22} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px]">{t.title}</span>
                      <span className="block truncate text-xs text-muted">{who}</span>
                    </span>
                    <DueText dueOn={t.due_on} dueAt={t.due_at} className="shrink-0" />
                  </button>
                </li>
              );
            })}
          </ul>
          {total > tasks.length ? (
            <p className="mt-1 px-1 text-xs text-muted">and {total - tasks.length} more</p>
          ) : null}
        </>
      )}
    </Card>
  );
}

function RecentProjects({ projects, onNew }: { projects: HomeProject[]; onNew: () => void }) {
  return (
    <Card
      title="Recent projects"
      className="md:col-span-3"
      action={
        <Button size="sm" variant="text" onClick={onNew}>
          <Icon icon={FolderPlus} /> New project
        </Button>
      }
    >
      {projects.length === 0 ? (
        <EmptyState icon={FolderKanban} title="No projects yet" />
      ) : (
        <ul aria-label="Recent projects" className="grid gap-3 @md:grid-cols-2 @3xl:grid-cols-3">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                to={`/projects/${p.id}`}
                className="flex items-center gap-3 rounded-lg border border-hairline px-3 py-2.5 hover:bg-surface-2"
              >
                <span
                  aria-hidden
                  className="grid size-9 shrink-0 place-items-center rounded-md text-sm font-semibold"
                  style={{
                    background: `color-mix(in oklab, ${colorVar(p.color)} 20%, transparent)`,
                    color: colorVar(p.color),
                  }}
                >
                  {p.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium">{p.name}</span>
                  <span className="block truncate text-xs text-muted">
                    {p.team_name} · {plural(p.open_count, 'open task')}
                    {p.overdue_count ? <span className="text-crit"> · {p.overdue_count} overdue</span> : null}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProjectChip({ name, color }: { name: string; color: string | null }) {
  return (
    <span className="hidden max-w-40 shrink-0 items-center gap-1.5 truncate text-xs text-muted @lg:flex">
      <span aria-hidden className="size-2 shrink-0 rounded-sm" style={{ background: colorVar(color) }} />
      <span className="truncate">{name}</span>
    </span>
  );
}

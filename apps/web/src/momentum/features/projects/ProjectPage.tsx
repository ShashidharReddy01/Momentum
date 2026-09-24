import { Archive, ArchiveRestore, Lock, MoreHorizontal, Star, Trash2, Users } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { InlineText } from '@/components/common/InlineText';
import { ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip } from '@/components/ui/Tooltip';
import { colorVar } from '@/features/teams';
import { cn } from '@/lib/cn';
import { useCrumbs } from '@/lib/crumbs';
import { useProject, useProjectLifecycle, useToggleFavorite, useUpdateProject } from './queries';
import { ShareDialog } from './ShareDialog';
import {
  BoardView,
  CalendarView,
  ProjectTasksView,
  TaskNavProvider,
  TaskPane,
  useLastView,
  useTaskNav,
  type ViewKey,
} from '@/features/tasks';

const VIEWS = [
  { key: 'list', label: 'List' },
  { key: 'board', label: 'Board' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'timeline', label: 'Timeline', phase: 6 },
  { key: 'overview', label: 'Overview', phase: 6 },
] as const;
type LiveView = Exclude<(typeof VIEWS)[number], { phase: number }>['key'];
const LIVE_VIEWS: ReadonlySet<string> = new Set(
  VIEWS.filter((v): v is Extract<(typeof VIEWS)[number], { key: LiveView }> => !('phase' in v)).map(
    (v) => v.key,
  ),
);
const isLiveView = (v: string | undefined): v is LiveView => !!v && LIVE_VIEWS.has(v);

export function ProjectPage() {
  // No default here: `view === undefined` means the URL had no `/…/:view` segment at all,
  // which is exactly when S2.2.3's "remembered last view" gets to redirect.
  const { projectId = '', view } = useParams();
  const project = useProject(projectId);
  const update = useUpdateProject(projectId);
  const { archive, remove } = useProjectLifecycle(projectId);
  const favorite = useToggleFavorite();
  const { lastView, ready: lastViewReady, save: saveLastView } = useLastView(projectId);
  const navigate = useNavigate();
  const [share, setShare] = useState(false);
  useCrumbs(project.data ? [project.data.team_name, project.data.name] : null);

  // On a bare `/projects/:id` (no view segment), redirect once to this user's last view for
  // this project, or the project's admin-set `default_view` for a project they've never opened.
  const redirected = useRef(false);
  useEffect(() => {
    if (redirected.current || view || !lastViewReady || !project.data) return;
    redirected.current = true;
    const initial = lastView ?? project.data.default_view;
    if (isLiveView(initial) && initial !== 'list')
      navigate(`/projects/${project.data.id}/${initial}`, { replace: true });
  }, [view, lastViewReady, lastView, project.data, navigate]);

  // Remember whichever view is actually showing, once the redirect above (if any) has settled —
  // `view` only becomes defined after that, so this never races the decision above with a
  // premature "list" save.
  useEffect(() => {
    if (!view || !lastViewReady) return;
    saveLastView(view as ViewKey);
  }, [view, lastViewReady, saveLastView]);

  if (project.isPending) {
    return (
      <div className="px-4 md:px-8 py-6">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="mt-6 h-64" />
      </div>
    );
  }
  if (project.isError) return <ErrorState error={project.error} onRetry={() => void project.refetch()} />;

  const p = project.data;
  const canEdit = p.my_role === 'admin' || p.my_role === 'editor';
  const isAdmin = p.my_role === 'admin';
  const effectiveView = view ?? 'list';

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-hair-soft px-4 md:px-8 pt-5">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="h-4 w-4 shrink-0 rounded-[5px]"
            style={{ background: colorVar(p.color) }}
          />
          <InlineText
            aria-label="Project name"
            value={p.name}
            disabled={!canEdit}
            onCommit={(name) => update.mutate({ name })}
            className="page-title"
          />
          {p.privacy === 'private' ? (
            <Tooltip content="Private: only invited members can see this project">
              <span className="text-muted">
                <Icon icon={Lock} size={15} aria-label="Private project" />
              </span>
            </Tooltip>
          ) : null}
          <IconButton
            icon={Star}
            label={p.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
            aria-pressed={p.is_favorite}
            className={cn(p.is_favorite && 'text-warn [&_svg]:fill-current')}
            onClick={() => favorite.mutate({ id: p.id, favorite: !p.is_favorite })}
          />
          <div className="ml-auto flex items-center gap-2">
            <div className="flex -space-x-1.5" aria-label={`${p.members.length} members`}>
              {p.members.slice(0, 5).map((m) => (
                <Avatar
                  key={m.user.id}
                  name={m.user.name}
                  src={m.user.avatar_url}
                  size={24}
                  className="ring-2 ring-canvas"
                />
              ))}
            </div>
            <Button size="sm" onClick={() => setShare(true)}>
              <Icon icon={p.privacy === 'private' ? Lock : Users} /> Share
            </Button>
            {isAdmin ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <IconButton icon={MoreHorizontal} label="Project actions" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Default view</DropdownMenuLabel>
                  <DropdownMenuRadioGroup
                    value={p.default_view}
                    onValueChange={(v) => update.mutate({ default_view: v as ViewKey })}
                  >
                    {VIEWS.filter((v) => !('phase' in v)).map((v) => (
                      <DropdownMenuRadioItem key={v.key} value={v.key}>
                        {v.label}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => archive.mutate(!p.archived_at)}>
                    <Icon icon={p.archived_at ? ArchiveRestore : Archive} />
                    {p.archived_at ? 'Unarchive project' : 'Archive project'}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-crit"
                    onSelect={() =>
                      remove.mutate(undefined, { onSuccess: () => navigate(`/teams/${p.team_id}`) })
                    }
                  >
                    <Icon icon={Trash2} /> Delete project
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>
        <nav aria-label="Project views" className="mt-3 flex gap-5">
          {VIEWS.map((v) =>
            'phase' in v ? (
              <Tooltip key={v.key} content={`Arrives in Phase ${v.phase}`}>
                <span className="cursor-default border-b-2 border-transparent pb-2 text-sm text-muted-2">
                  {v.label}
                </span>
              </Tooltip>
            ) : (
              <Link
                key={v.key}
                to={`/projects/${p.id}/${v.key}`}
                aria-current={effectiveView === v.key ? 'page' : undefined}
                className={cn(
                  '-mb-px border-b-2 pb-2 text-sm',
                  effectiveView === v.key
                    ? 'border-ink font-medium text-ink'
                    : 'border-transparent text-muted hover:text-ink',
                )}
              >
                {v.label}
              </Link>
            ),
          )}
        </nav>
      </header>

      {p.archived_at ? (
        <div role="status" className="flex items-center gap-3 bg-warn-tint px-4 md:px-8 py-2 text-sm">
          This project is archived. It's hidden from the sidebar.
          {isAdmin ? (
            <Button size="sm" onClick={() => archive.mutate(false)}>
              Unarchive
            </Button>
          ) : null}
        </div>
      ) : null}

      <ShareDialog project={p} open={share} onOpenChange={setShare} />
      {p.my_role === 'viewer' || p.my_role === 'commenter' ? (
        <div role="status" className="bg-info-tint px-4 md:px-8 py-1.5 text-xs text-ink-2">
          You have {p.my_role} access to this project.
        </div>
      ) : null}
      <TaskNavProvider>
        <ProjectBody
          view={effectiveView}
          projectId={p.id}
          canEdit={canEdit && !p.archived_at}
          color={p.color}
        />
      </TaskNavProvider>
    </div>
  );
}

/** The list (scrolls on its own) with the task pane docked on the right when `?task=` is set. */
function ProjectBody({
  view,
  projectId,
  canEdit,
  color,
}: {
  view: string;
  projectId: string;
  canEdit: boolean;
  color: string | null;
}) {
  const nav = useTaskNav()!;
  return (
    <div className="flex min-h-0 flex-1">
      <div
        className={cn(
          'min-w-0 flex-1 px-4 py-5 md:px-8',
          view === 'board' || view === 'calendar' ? 'overflow-hidden' : 'overflow-auto',
        )}
      >
        {view === 'list' ? (
          <ProjectTasksView key={projectId} projectId={projectId} canEdit={canEdit} />
        ) : view === 'board' ? (
          <BoardView key={projectId} projectId={projectId} canEdit={canEdit} color={color} />
        ) : view === 'calendar' ? (
          <CalendarView key={projectId} projectId={projectId} canEdit={canEdit} color={color} />
        ) : null}
      </div>
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
          canEditHint={canEdit}
        />
      ) : null}
    </div>
  );
}

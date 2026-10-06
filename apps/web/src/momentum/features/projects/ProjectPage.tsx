import {
  Archive,
  ArchiveRestore,
  BookmarkPlus,
  ClipboardList,
  Download,
  FileSpreadsheet,
  Lock,
  MoreHorizontal,
  SlidersHorizontal,
  Star,
  Trash2,
  Users,
  Zap,
} from 'lucide-react';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { AskMoButton } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
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
import { useScrollEdges } from '@/lib/scrollEdges';
import { useCrumbs } from '@/lib/crumbs';
import { CsvImportDialog } from '@/features/csvImport';
import { FieldsDialog } from '@/features/fields';
import { SaveAsTemplateDialog, TaskTemplatesDialog } from '@/features/templates';
import { StatusChip, type Status } from '@/features/status';
import { useMomentumConfig } from '@/lib/config';
import {
  useProject,
  useProjectLifecycle,
  useToggleFavorite,
  useUpdateProject,
  type ProjectDetail,
} from './queries';
import { ShareDialog } from './ShareDialog';
import {
  ProjectTasksView,
  TaskNavProvider,
  TaskPane,
  useLastView,
  useTaskNav,
  type ViewKey,
} from '@/features/tasks';

// Lazy: the timeline is a separate chunk, loaded only when the tab opens (frontend-architecture).
// The list is the default view; the other tabs load when first opened. Board and Calendar are
// imported from their own modules (not the tasks index, which the list already loads eagerly).
const BoardView = lazy(async () => ({ default: (await import('@/features/tasks/BoardView')).BoardView }));
const CalendarView = lazy(async () => ({
  default: (await import('@/features/tasks/CalendarView')).CalendarView,
}));
const ProjectOverview = lazy(async () => ({ default: (await import('./ProjectOverview')).ProjectOverview }));
// opened from the project menu: loaded on first open, not with every project
const RulesDialog = lazy(async () => ({ default: (await import('@/features/rules')).RulesDialog }));
const FormsDialog = lazy(async () => ({ default: (await import('@/features/forms')).FormsDialog }));
const TimelineView = lazy(() => import('@/features/timeline').then((m) => ({ default: m.TimelineView })));
// Lazy too: dashboards and their charts (Recharts) load only when the tab opens.
const FilesView = lazy(() => import('@/features/files').then((m) => ({ default: m.FilesView })));
const ProjectDashboard = lazy(() =>
  import('@/features/dashboards').then((m) => ({ default: m.ProjectDashboard })),
);

const VIEWS = [
  { key: 'list', label: 'List' },
  { key: 'board', label: 'Board' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'overview', label: 'Overview' },
  { key: 'files', label: 'Files' },
  { key: 'dashboard', label: 'Dashboard' },
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
  const { ai_enabled: aiEnabled, api_base } = useMomentumConfig();
  const [share, setShare] = useState(false);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [formsOpen, setFormsOpen] = useState(false);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const [taskTemplatesOpen, setTaskTemplatesOpen] = useState(false);
  const [csvImportOpen, setCsvImportOpen] = useState(false);
  useCrumbs(project.data ? [project.data.team_name, project.data.name] : null);
  const tabEdges = useScrollEdges();

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
      <header className="border-b border-hairline bg-surface px-4 pt-3 md:px-8">
        <div className="flex min-h-9 items-center gap-3">
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
            // one line, however long the name (it's in full in the editor and the tooltip)
            className="page-title min-w-0 truncate"
            title={p.name}
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
                  className="ring-2 ring-surface"
                />
              ))}
            </div>
            <AskMoButton about={{ kind: 'project', projectId: p.id, label: p.name }} />
            {canEdit && aiEnabled ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(`/projects/${p.id}/overview?draft=mo`)}
              >
                <MoMark size={13} /> Draft status
              </Button>
            ) : null}
            {p.status ? <StatusChip status={p.status as Status} /> : null}
            <IconButton icon={SlidersHorizontal} label="Fields" onClick={() => setFieldsOpen(true)} />
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
                  <DropdownMenuItem onSelect={() => setRulesOpen(true)}>
                    <Icon icon={Zap} /> Rules
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setFormsOpen(true)}>
                    <Icon icon={ClipboardList} /> Forms
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setSaveTemplateOpen(true)}>
                    <Icon icon={BookmarkPlus} /> Save as template
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setTaskTemplatesOpen(true)}>
                    <Icon icon={BookmarkPlus} /> Task templates
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setCsvImportOpen(true)}>
                    <Icon icon={Download} /> Import from CSV
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => {
                      // a plain download (the response is an attachment): the browser's own save
                      window.location.href = `${api_base}/projects/${p.id}/export/csv`;
                    }}
                  >
                    <Icon icon={FileSpreadsheet} /> Export to CSV
                  </DropdownMenuItem>
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
        <div className="relative">
          <nav
            ref={tabEdges.ref}
            onScroll={tabEdges.update}
            aria-label="Project views"
            className="mt-1 flex gap-1 overflow-x-auto [scrollbar-width:none]"
          >
            {VIEWS.map((v) =>
              'phase' in v ? (
                <Tooltip key={v.key} content={`Arrives in Phase ${v.phase}`}>
                  <span className="flex h-9 cursor-default items-center border-b-2 border-transparent px-2 text-body text-muted-2">
                    {v.label}
                  </span>
                </Tooltip>
              ) : (
                <Link
                  key={v.key}
                  to={`/projects/${p.id}/${v.key}`}
                  aria-current={effectiveView === v.key ? 'page' : undefined}
                  className={cn(
                    '-mb-px flex h-9 shrink-0 items-center rounded-t-md border-b-2 px-2 text-body transition-colors duration-[var(--dur-1)]',
                    effectiveView === v.key
                      ? 'border-ink font-semibold text-ink'
                      : 'border-transparent text-muted hover:bg-surface-2 hover:text-ink',
                  )}
                >
                  {v.label}
                </Link>
              ),
            )}
          </nav>
          {tabEdges.right ? (
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-surface"
            />
          ) : null}
        </div>
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
      <FieldsDialog projectId={p.id} canEdit={canEdit} open={fieldsOpen} onOpenChange={setFieldsOpen} />
      {rulesOpen ? (
        <Suspense fallback={null}>
          <RulesDialog projectId={p.id} canEdit={isAdmin} open onOpenChange={setRulesOpen} />
        </Suspense>
      ) : null}
      {formsOpen ? (
        <Suspense fallback={null}>
          <FormsDialog projectId={p.id} canEdit={isAdmin} open onOpenChange={setFormsOpen} />
        </Suspense>
      ) : null}
      <SaveAsTemplateDialog projectId={p.id} open={saveTemplateOpen} onOpenChange={setSaveTemplateOpen} />
      <TaskTemplatesDialog
        projectId={p.id}
        canEdit={canEdit}
        open={taskTemplatesOpen}
        onOpenChange={setTaskTemplatesOpen}
      />
      <CsvImportDialog projectId={p.id} open={csvImportOpen} onOpenChange={setCsvImportOpen} />
      {p.my_role === 'viewer' || p.my_role === 'commenter' ? (
        <div role="status" className="bg-info-tint px-4 md:px-8 py-1.5 text-xs text-ink-2">
          You have {p.my_role} access to this project.
        </div>
      ) : null}
      <TaskNavProvider>
        <ProjectBody
          view={effectiveView}
          project={p}
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
  project,
  projectId,
  canEdit,
  color,
}: {
  view: string;
  project: ProjectDetail;
  projectId: string;
  canEdit: boolean;
  color: string | null;
}) {
  const nav = useTaskNav()!;
  const [searchParams] = useSearchParams();
  return (
    <div className="flex min-h-0 flex-1">
      <div
        className={cn(
          'min-w-0 flex-1 px-4 py-5 md:px-8',
          view === 'board' || view === 'calendar' || view === 'timeline'
            ? 'overflow-hidden'
            : 'overflow-auto',
        )}
      >
        {view === 'list' ? (
          <ProjectTasksView key={projectId} projectId={projectId} canEdit={canEdit} />
        ) : view === 'board' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <BoardView key={projectId} projectId={projectId} canEdit={canEdit} color={color} />
          </Suspense>
        ) : view === 'calendar' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <CalendarView key={projectId} projectId={projectId} canEdit={canEdit} color={color} />
          </Suspense>
        ) : view === 'timeline' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <TimelineView
              key={projectId}
              projectId={projectId}
              canEdit={canEdit}
              color={color}
              projectDue={project.due_on ?? null}
            />
          </Suspense>
        ) : view === 'dashboard' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <ProjectDashboard key={projectId} projectId={projectId} projectName={project.name} />
          </Suspense>
        ) : view === 'files' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <FilesView
              key={projectId}
              projectId={projectId}
              canEdit={canEdit}
              isAdmin={project.my_role === 'admin'}
            />
          </Suspense>
        ) : view === 'overview' ? (
          <Suspense fallback={<Skeleton className="h-64" />}>
            <ProjectOverview
              key={projectId}
              project={project}
              canEdit={canEdit}
              startDraft={searchParams.get('draft') === 'mo'}
            />
          </Suspense>
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

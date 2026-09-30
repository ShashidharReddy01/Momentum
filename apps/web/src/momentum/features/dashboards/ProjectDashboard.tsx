import { LayoutDashboard, MoreHorizontal, RotateCcw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { ErrorState } from '@/components/common/States';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useTaskNav } from '@/features/tasks';
import { useChannel } from '@/lib/realtime';
import { Board } from './Board';
import { dashboardKeys, useCreateDashboard, useDashboardMutations, useProjectDashboard } from './queries';
import type { WidgetItem } from './WidgetCard';

/**
 * A project's Dashboard tab (S6.5.1). Before anyone customises it, it shows the starter layout
 * with live numbers from the project; the first change saves it as the project's dashboard.
 * Task changes in the project refresh every number.
 */
export function ProjectDashboard({ projectId, projectName }: { projectId: string; projectName: string }) {
  const qc = useQueryClient();
  const nav = useTaskNav();
  const tab = useProjectDashboard(projectId);
  const create = useCreateDashboard();
  const dashboard = tab.data?.dashboard ?? null;
  const { remove } = useDashboardMutations(dashboard?.id ?? null);

  useChannel(`project:${projectId}`, (event) => {
    if (event.event.startsWith('task.') || event.event.startsWith('section.'))
      void qc.invalidateQueries({ queryKey: dashboardKeys.data });
  });

  if (tab.isPending) {
    return (
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
        <Skeleton className="col-span-2 h-64" />
        <Skeleton className="col-span-2 h-64" />
      </div>
    );
  }
  if (tab.isError) return <ErrorState error={tab.error} onRetry={() => void tab.refetch()} />;

  const starter: WidgetItem[] = tab.data.starter.map((w) => ({
    id: null,
    kind: w.kind,
    title: w.title,
    spec: w.query_spec,
    size: w.viz.size ?? 'md',
    version: 0,
  }));
  const ensure = async () =>
    dashboard ??
    (
      await create.mutateAsync({
        name: `${projectName} dashboard`,
        project_id: projectId,
        starter: true,
        quiet: true,
      })
    ).data;

  return (
    <div className="mx-auto max-w-[1400px]">
      <Board
        dashboard={dashboard}
        starter={starter}
        projectId={projectId}
        editable={tab.data.can_edit}
        ensure={ensure}
        onOpenTask={(id) => nav?.open(id)}
        paneOpen={!!nav?.openId}
        onOrder={nav?.setOrder}
        title={<h2 className="text-base font-semibold">Dashboard</h2>}
        actions={
          dashboard && tab.data.can_edit ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton icon={MoreHorizontal} label="Dashboard options" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => remove.mutate(dashboard.id)}>
                  <Icon icon={RotateCcw} size={14} /> Reset to the starter dashboard
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null
        }
        banner={
          dashboard ? null : (
            <p className="flex items-start gap-2 rounded-lg bg-surface-2 px-3 py-2 text-sm text-ink-2">
              <Icon icon={LayoutDashboard} size={14} className="mt-0.5 shrink-0 text-muted" aria-hidden />
              <span>
                The starter dashboard, with live numbers from this project. Click any number, bar or slice to
                see the tasks behind it.
                {tab.data.can_edit ? ' Add, edit or remove a chart to make it this project’s own.' : ''}
              </span>
            </p>
          )
        }
      />
    </div>
  );
}

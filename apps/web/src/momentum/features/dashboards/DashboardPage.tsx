import { MoreHorizontal, Pin, PinOff, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router';
import { InlineText } from '@/components/common/InlineText';
import { ErrorState } from '@/components/common/States';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { useCrumbs } from '@/lib/crumbs';
import { Board } from './Board';
import { FilterBar, useViewFilters } from './FilterBar';
import { ReportButton } from './ReportButton';
import { activeFilters, useDashboard, useDashboardMutations, usePin, type DashboardDetail } from './queries';

/** S6.5.1: one workspace dashboard, with the task pane for whatever a chart opens. */
export function DashboardPage() {
  return (
    <TaskNavProvider>
      <DashboardBody />
    </TaskNavProvider>
  );
}

function DashboardBody() {
  const { dashboardId = '' } = useParams();
  const nav = useTaskNav()!;
  const navigate = useNavigate();
  const q = useDashboard(dashboardId);
  const m = useDashboardMutations(dashboardId);
  const pin = usePin(dashboardId);
  const [view, setView] = useViewFilters();
  useCrumbs(q.data ? ['Dashboards', q.data.name] : null);

  if (q.isPending) {
    return (
      <div className="px-4 py-6 md:px-8">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="mt-6 h-64" />
      </div>
    );
  }
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-4 py-6 md:px-8">
        <div className="mx-auto max-w-[1400px]">
          <Board
            dashboard={d}
            projectId={null}
            editable={d.can_edit}
            ensure={async () => d}
            onOpenTask={(id) => nav.open(id)}
            paneOpen={!!nav.openId}
            onOrder={nav.setOrder}
            filters={view}
            filterBar={
              <FilterBar
                saved={activeFilters(d.filters)}
                view={view}
                onView={setView}
                canSave={d.can_edit}
                onSave={(filters) =>
                  m.rename.mutate({ filters: filters ?? {} } as { filters: DashboardDetail['filters'] }, {
                    onSuccess: () => setView(null),
                  })
                }
              />
            }
            title={
              d.can_edit ? (
                <InlineText
                  value={d.name}
                  onCommit={(name) => m.rename.mutate({ name })}
                  className="text-xl font-semibold"
                  aria-label="Dashboard name"
                />
              ) : (
                <h1 className="page-title">{d.name}</h1>
              )
            }
            actions={
              <>
                <ReportButton dashboardId={d.id} name={d.name} />
                <PinButton pinned={!!d.pinned} onToggle={() => pin.mutate(!d.pinned)} />
                {d.can_edit ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <IconButton icon={MoreHorizontal} label="Dashboard options" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        className="text-crit"
                        onSelect={() =>
                          m.remove.mutate(undefined, { onSuccess: () => navigate('/dashboards') })
                        }
                      >
                        <Icon icon={Trash2} size={14} /> Delete dashboard
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </>
            }
          />
        </div>
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

/** Pin to my Home (per person). */
export function PinButton({ pinned, onToggle }: { pinned: boolean; onToggle: () => void }) {
  return (
    <Button variant="text" aria-pressed={pinned} onClick={onToggle}>
      <Icon icon={pinned ? PinOff : Pin} size={14} /> {pinned ? 'Unpin from Home' : 'Pin to Home'}
    </Button>
  );
}

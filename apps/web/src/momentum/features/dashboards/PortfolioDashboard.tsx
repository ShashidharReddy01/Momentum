import { LayoutDashboard, Plus } from 'lucide-react';
import { useState } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { Board } from './Board';
import { PinButton } from './DashboardPage';
import { FilterBar, useViewFilters } from './FilterBar';
import {
  activeFilters,
  useCreateDashboard,
  useDashboardMutations,
  usePin,
  usePortfolioDashboard,
  type DashboardDetail,
} from './queries';
import { TemplateGallery } from './TemplateGallery';

/**
 * Phase 7.5 (spec §7.4): a portfolio's Dashboard tab. One dashboard per portfolio, made and edited
 * by the portfolio's editors, from a role template or blank; its filters start at the portfolio.
 */
export function PortfolioDashboard(props: { portfolioId: string; portfolioName: string }) {
  return (
    <TaskNavProvider>
      <PortfolioDashboardBody {...props} />
    </TaskNavProvider>
  );
}

function PortfolioDashboardBody({
  portfolioId,
  portfolioName,
}: {
  portfolioId: string;
  portfolioName: string;
}) {
  const nav = useTaskNav()!;
  const tab = usePortfolioDashboard(portfolioId);
  const create = useCreateDashboard();
  const [gallery, setGallery] = useState(false);
  const dashboard = tab.data?.dashboard ?? null;
  const m = useDashboardMutations(dashboard?.id ?? null);
  const pin = usePin(dashboard?.id ?? '');
  const [view, setView] = useViewFilters();

  if (tab.isPending) return <Skeleton className="h-64" />;
  if (tab.isError) return <ErrorState error={tab.error} onRetry={() => void tab.refetch()} />;
  if (!dashboard) {
    return (
      <>
        <EmptyState
          icon={LayoutDashboard}
          title="No dashboard for this portfolio yet"
          action={
            tab.data.can_edit ? (
              <div className="flex gap-2">
                <Button variant="primary" onClick={() => setGallery(true)}>
                  <Icon icon={LayoutDashboard} size={15} /> Start from a template
                </Button>
                <Button
                  onClick={() =>
                    create.mutate({
                      name: `${portfolioName} dashboard`,
                      portfolio_id: portfolioId,
                      starter: false,
                    })
                  }
                  loading={create.isPending}
                >
                  <Icon icon={Plus} size={15} /> Blank dashboard
                </Button>
              </div>
            ) : null
          }
        >
          {tab.data.can_edit
            ? 'Start from a role template (sales, implementation, leadership…) bound to this portfolio, or from a blank page.'
            : 'The portfolio’s editors can add one.'}
        </EmptyState>
        <TemplateGallery
          open={gallery}
          onOpenChange={setGallery}
          portfolioId={portfolioId}
          portfolioTab
          onCreated={() => setGallery(false)}
        />
      </>
    );
  }
  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1">
        <Board
          dashboard={dashboard}
          projectId={null}
          editable={tab.data.can_edit}
          ensure={async () => dashboard}
          onOpenTask={(id) => nav.open(id)}
          paneOpen={!!nav.openId}
          onOrder={nav.setOrder}
          filters={view}
          filterBar={
            <FilterBar
              saved={activeFilters(dashboard.filters)}
              view={view}
              onView={setView}
              canSave={tab.data.can_edit}
              lockPortfolio
              onSave={(filters) =>
                m.rename.mutate(
                  {
                    filters: { ...(filters ?? {}), portfolio_id: portfolioId } as DashboardDetail['filters'],
                  },
                  { onSuccess: () => setView(null) },
                )
              }
            />
          }
          title={<h2 className="text-base font-semibold">{dashboard.name}</h2>}
          actions={<PinButton pinned={!!dashboard.pinned} onToggle={() => pin.mutate(!dashboard.pinned)} />}
        />
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

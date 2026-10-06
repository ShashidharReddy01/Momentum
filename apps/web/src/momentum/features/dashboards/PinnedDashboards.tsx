import { LayoutDashboard } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { itemOf } from './Board';
import { useDashboard, usePinnedDashboards, type Dashboard } from './queries';
import { WidgetCard } from './WidgetCard';

const TILES = 4;

/**
 * Phase 7.5 (spec §7.4): Home's "Pinned dashboards" section. Each pinned dashboard shows its
 * headline numbers (its first KPI tiles, as you), with a link to the whole page. Nothing pinned:
 * nothing shown.
 */
export function PinnedDashboards() {
  const pinned = usePinnedDashboards();
  if (pinned.isPending || !pinned.data?.length) return null;
  return (
    <section aria-labelledby="pinned-dashboards" className="mt-6 space-y-3">
      <h2 id="pinned-dashboards" className="text-sm font-semibold">
        Pinned dashboards
      </h2>
      {pinned.data.map((d) => (
        <PinnedOne key={d.id} dashboard={d} />
      ))}
    </section>
  );
}

function PinnedOne({ dashboard }: { dashboard: Dashboard }) {
  const q = useDashboard(dashboard.id);
  const navigate = useNavigate();
  const tiles = (q.data?.widgets ?? []).filter((w) => w.kind === 'kpi' || w.kind === 'count').slice(0, TILES);
  return (
    <div className="rounded-xl border border-hair-soft bg-surface-2/40 p-3">
      <Link
        to={`/dashboards/${dashboard.id}`}
        className="mb-2 flex items-center gap-2 text-sm font-medium hover:underline"
      >
        <Icon icon={LayoutDashboard} size={14} className="text-muted" aria-hidden />
        {dashboard.name}
        <span className="text-xs font-normal text-muted">
          {dashboard.widget_count} {dashboard.widget_count === 1 ? 'chart' : 'charts'}
        </span>
      </Link>
      {q.isPending ? (
        <Skeleton className="h-20" />
      ) : tiles.length ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {tiles.map((w) => (
            <WidgetCard
              key={w.id}
              item={{ ...itemOf(w), size: 'sm' }}
              projectId={null}
              editable={false}
              onDrill={() => navigate(`/dashboards/${dashboard.id}`)}
              onOpenTask={() => navigate(`/dashboards/${dashboard.id}`)}
            />
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">Open it to see its charts.</p>
      )}
    </div>
  );
}
